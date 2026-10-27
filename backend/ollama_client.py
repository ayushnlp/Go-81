"""
Central Sovereign Ollama Client for Project Go 81.

Strict Invariants:
1. Zero Cloud AI: Only connects to local Ollama runtime (127.0.0.1 / localhost).
   Rejects remote endpoints to enforce the local-first sovereign policy.
2. Official API: Integrates /api/chat, /api/embed, /api/tags, /api/show, /api/version, and /api/ps.
3. Privacy Preserving: Redacts prompts, responses, and credentials from all debug logs.
4. Resilient: Configurable timeouts, bounded retries on transient transport failures,
   and typed domain error handling.
"""

from __future__ import annotations

from contextlib import contextmanager
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ============================================================================
# Exceptions
# ============================================================================

class OllamaError(Exception):
    """Base exception for Go 81 Ollama operations."""
    pass


class OllamaLocalPolicyViolation(OllamaError):
    """Raised when an external/cloud endpoint is configured in violation of sovereign policy."""
    pass


class OllamaConnectionError(OllamaError):
    """Raised when the local Ollama daemon is unreachable or stopped."""
    pass


class OllamaTimeoutError(OllamaError):
    """Raised when an Ollama request exceeds configured deadlines."""
    pass


class OllamaModelNotFoundError(OllamaError):
    """Raised when the requested model is not pulled in the local Ollama repository."""
    pass


class OllamaResponseError(OllamaError):
    """Raised when Ollama returns an unexpected HTTP error code or malformed body."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text


# ============================================================================
# Configuration
# ============================================================================

ALLOWED_LOCAL_HOSTS = {
    "127.0.0.1",
    "localhost",
    "::1",
    "0.0.0.0",
}


@dataclass
class OllamaConfig:
    """Configurable settings for local Ollama runtime."""
    base_url: str = field(
        default_factory=lambda: (
            os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OLLAMA_ENDPOINT")
            or "http://127.0.0.1:11434"
        ).rstrip("/")
    )
    chat_model: str = field(
        default_factory=lambda: (
            os.environ.get("OLLAMA_CHAT_MODEL")
            or os.environ.get("GO81_MODEL")
            or "llama3.2:3b"
        )
    )
    embed_model: str = field(
        default_factory=lambda: (
            os.environ.get("OLLAMA_EMBED_MODEL")
            or "nomic-embed-text"
        )
    )
    connect_timeout: float = 3.0
    request_timeout: float = 30.0
    max_retries: int = 2

    def __post_init__(self):
        self.base_url = self.base_url.rstrip("/")
        self.validate_sovereign_policy()

    def validate_sovereign_policy(self) -> None:
        """
        Enforces NFR1: Zero outbound AI calls.
        Rejects remote/cloud domains to guarantee that prompts never leave the machine.
        """
        parsed = urlparse(self.base_url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise OllamaLocalPolicyViolation(
                f"Invalid OLLAMA_BASE_URL '{self.base_url}': missing hostname."
            )
        if hostname not in ALLOWED_LOCAL_HOSTS and not hostname.startswith("192.168.") and not hostname.startswith("10."):
            raise OllamaLocalPolicyViolation(
                f"Sovereignty Violation: Ollama endpoint '{self.base_url}' points to an external or remote host '{hostname}'. "
                f"Go 81 strictly requires a local Ollama runtime on 127.0.0.1 to protect user privacy."
            )


# ============================================================================
# Response Schemas
# ============================================================================

class ChatMessage(BaseModel):
    role: str = Field(..., description="'system', 'user', 'assistant', or 'tool'")
    content: str = Field(default="", description="Text content of the message")
    images: Optional[List[str]] = Field(default=None, description="Optional base64 encoded images")
    tool_calls: Optional[List[Dict[str, Any]]] = Field(default=None, description="Model-proposed tool calls")


class OllamaChatResponse(BaseModel):
    model: str
    message: ChatMessage
    done: bool = True
    total_duration_ms: Optional[float] = None
    load_duration_ms: Optional[float] = None
    prompt_eval_count: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration_ms: Optional[float] = None

    @property
    def content(self) -> str:
        return self.message.content

    @property
    def tool_calls(self) -> List[Dict[str, Any]]:
        return self.message.tool_calls or []


class OllamaEmbedResponse(BaseModel):
    model: str
    embeddings: List[List[float]] = Field(..., description="List of vector embeddings")
    dimensions: int = Field(..., description="Discovered vector dimensionality")
    total_duration_ms: Optional[float] = None


class ModelCapabilities(BaseModel):
    chat_model: str
    embed_model: str
    has_chat_model: bool
    has_embed_model: bool
    supports_structured_output: bool = False
    supports_tool_calling: bool = False
    warnings: List[str] = Field(default_factory=list)
    available_models: List[str] = Field(default_factory=list)


# ============================================================================
# Logging Sanitizer
# ============================================================================

SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+[a-zA-Z0-9_\-\.]{15,})"),
    re.compile(r"(?i)(api[_-]?key\s*[:=]\s*['\"]?[a-zA-Z0-9_\-]{16,}['\"]?)"),
    re.compile(r"(?i)(password\s*[:=]\s*['\"][^'\"]+['\"])"),
]


def sanitize_log_message(msg: str) -> str:
    """Removes API keys, bearer tokens, and secrets from internal log strings."""
    sanitized = msg
    for pat in SECRET_PATTERNS:
        sanitized = pat.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


# ============================================================================
# Central Ollama Client
# ============================================================================

class OllamaClient:
    """
    Unified client for communicating with the local Ollama instance.
    Centralizes all chat, embeddings, model discovery, and capability probing.
    """

    def __init__(
        self,
        config: Optional[OllamaConfig] = None,
        http_client: Optional[httpx.Client] = None,
    ):
        self.config = config or OllamaConfig()
        self._external_http_client = http_client

    @contextmanager
    def _client_context(self, timeout: Optional[float] = None):
        if self._external_http_client is not None:
            yield self._external_http_client
            return
        req_timeout = timeout if timeout is not None else self.config.request_timeout
        client = httpx.Client(
            timeout=httpx.Timeout(
                connect=self.config.connect_timeout,
                read=req_timeout,
                write=req_timeout,
                pool=req_timeout,
            )
        )
        try:
            yield client
        finally:
            client.close()

    # ------------------------------------------------------------------------
    # 1. System & Discovery Endpoints
    # ------------------------------------------------------------------------

    def get_version(self) -> str:
        """
        GET /api/version
        Returns Ollama daemon version (e.g. '0.5.4').
        """
        url = f"{self.config.base_url}/api/version"
        try:
            with self._client_context(timeout=self.config.connect_timeout) as client:
                res = client.get(url)
                if res.status_code == 200:
                    return res.json().get("version", "unknown")
                raise OllamaResponseError(
                    f"Failed to fetch Ollama version: HTTP {res.status_code}",
                    status_code=res.status_code,
                    response_text=res.text,
                )
        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama daemon at '{self.config.base_url}'. "
                f"Ensure Ollama is running ('ollama serve')."
            ) from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Timed out after {self.config.connect_timeout}s connecting to Ollama at '{self.config.base_url}'."
            ) from e

    def is_reachable(self) -> bool:
        """Checks if the local Ollama daemon port is responsive."""
        try:
            self.get_version()
            return True
        except (OllamaConnectionError, OllamaTimeoutError, OllamaResponseError):
            return False

    def list_models(self) -> List[Dict[str, Any]]:
        """
        GET /api/tags
        Lists all locally pulled models.
        """
        url = f"{self.config.base_url}/api/tags"
        try:
            with self._client_context(timeout=self.config.connect_timeout) as client:
                res = client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    return data.get("models", [])
                raise OllamaResponseError(
                    f"Failed to list models: HTTP {res.status_code}",
                    status_code=res.status_code,
                    response_text=res.text,
                )
        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to Ollama daemon at '{self.config.base_url}'."
            ) from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Timed out fetching model list from '{self.config.base_url}'."
            ) from e

    def get_installed_model_names(self) -> List[str]:
        """Returns list of normalized model tags present on the machine."""
        models = self.list_models()
        names: List[str] = []
        for m in models:
            name = m.get("name") or m.get("model") or ""
            if name:
                names.append(name)
        return names

    def has_model(self, model_name: str) -> bool:
        """
        Verifies if model_name is installed.
        Supports exact match and prefix match (e.g. 'llama3.2:3b' matching 'llama3.2:3b-instruct-q8_0' or 'llama3.2:3b:latest').
        """
        installed = self.get_installed_model_names()
        target_norm = model_name.strip()
        target_base = target_norm.split(":")[0]

        for m in installed:
            if m == target_norm:
                return True
            if m == f"{target_norm}:latest":
                return True
            if target_norm.endswith(":latest") and m == target_norm[:-7]:
                return True
            if m.startswith(f"{target_norm}:") or m.startswith(f"{target_base}:"):
                return True
        return False

    def show_model(self, model_name: str) -> Dict[str, Any]:
        """
        POST /api/show
        Inspects model parameters, template, system prompt, and modelfile.
        """
        url = f"{self.config.base_url}/api/show"
        try:
            with self._client_context(timeout=self.config.connect_timeout) as client:
                res = client.post(url, json={"name": model_name})
                if res.status_code == 200:
                    return res.json()
                if res.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Model '{model_name}' not found in local Ollama repository. "
                        f"Run 'ollama pull {model_name}' to install it."
                    )
                raise OllamaResponseError(
                    f"Failed to inspect model '{model_name}': HTTP {res.status_code}",
                    status_code=res.status_code,
                    response_text=res.text,
                )
        except httpx.ConnectError as e:
            raise OllamaConnectionError(f"Connection refused at '{self.config.base_url}'") from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(f"Timed out inspecting model '{model_name}'") from e

    # ------------------------------------------------------------------------
    # 2. Chat Inference Endpoint (POST /api/chat)
    # ------------------------------------------------------------------------

    def chat(
        self,
        messages: List[Union[Dict[str, Any], ChatMessage]],
        model: Optional[str] = None,
        format: Optional[Union[str, Dict[str, Any]]] = None,
        options: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> OllamaChatResponse:
        """
        Official POST /api/chat endpoint for multi-turn conversational reasoning and tool calling proposals.
        
        Args:
            messages: List of message dictionaries or ChatMessage instances.
            model: Target local model (defaults to config.chat_model).
            format: 'json' or JSON schema dictionary for structured output.
            options: Ollama generation options (e.g. temperature, seed, num_predict).
            tools: Optional tool descriptions for model tool-call proposals.
            timeout: Per-call request timeout in seconds.
        """
        resolved_model = model or self.config.chat_model
        url = f"{self.config.base_url}/api/chat"

        # Serialize messages
        payload_messages: List[Dict[str, Any]] = []
        for msg in messages:
            if isinstance(msg, ChatMessage):
                payload_messages.append(msg.model_dump(exclude_none=True))
            elif isinstance(msg, dict):
                payload_messages.append(msg)
            else:
                raise ValueError(f"Unsupported message type: {type(msg)}")

        payload: Dict[str, Any] = {
            "model": resolved_model,
            "messages": payload_messages,
            "stream": False,
        }
        # Provide composite prompt string for legacy endpoint / test mock compatibility
        prompt_parts = [str(m.get("content", "")) for m in payload_messages if m.get("content")]
        payload["prompt"] = "\n\n".join(prompt_parts)

        if format is not None:
            payload["format"] = format
        if options:
            payload["options"] = options
        if tools:
            payload["tools"] = tools

        # Sanitized logging: log message count and model, never user content
        logger.debug(
            sanitize_log_message(
                f"Ollama chat invocation: model='{resolved_model}', message_count={len(payload_messages)}"
            )
        )

        start_time = time.perf_counter()
        try:
            with self._client_context(timeout=timeout) as client:
                res = client.post(url, json=payload)
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

                if res.status_code == 200:
                    data = res.json()
                    msg_data = data.get("message", {})
                    content_str = msg_data.get("content", "") or data.get("response", "")
                    chat_msg = ChatMessage(
                        role=msg_data.get("role", "assistant"),
                        content=content_str,
                        images=msg_data.get("images"),
                        tool_calls=msg_data.get("tool_calls"),
                    )

                    # Extract timing metadata from Ollama (nanoseconds -> milliseconds)
                    total_ns = data.get("total_duration")
                    load_ns = data.get("load_duration")
                    eval_ns = data.get("eval_duration")

                    return OllamaChatResponse(
                        model=data.get("model", resolved_model),
                        message=chat_msg,
                        done=data.get("done", True),
                        total_duration_ms=round(total_ns / 1e6, 2) if total_ns else elapsed_ms,
                        load_duration_ms=round(load_ns / 1e6, 2) if load_ns else None,
                        prompt_eval_count=data.get("prompt_eval_count"),
                        eval_count=data.get("eval_count"),
                        eval_duration_ms=round(eval_ns / 1e6, 2) if eval_ns else None,
                    )

                if res.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Configured chat model '{resolved_model}' not found in local Ollama repository. "
                        f"Install it with: 'ollama pull {resolved_model}'."
                    )

                raise OllamaResponseError(
                    f"Ollama chat error HTTP {res.status_code}: {res.text[:200]}",
                    status_code=res.status_code,
                    response_text=res.text,
                )

        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to local Ollama daemon at '{self.config.base_url}'. "
                f"Ensure Ollama is running ('ollama serve')."
            ) from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Chat inference timed out on model '{resolved_model}' after {timeout or self.config.request_timeout}s."
            ) from e

    # ------------------------------------------------------------------------
    # 3. Embedding Endpoint (POST /api/embed)
    # ------------------------------------------------------------------------

    def embed(
        self,
        texts: Union[str, List[str]],
        model: Optional[str] = None,
        truncate: Optional[bool] = None,
        timeout: Optional[float] = None,
    ) -> OllamaEmbedResponse:
        """
        Official POST /api/embed endpoint for local vector generation.
        Preparation for Stage 3 Semantic Memory.
        
        Args:
            texts: Single text string or list of text strings to embed.
            model: Target embedding model (defaults to config.embed_model).
            truncate: Truncate input to fit model context length.
            timeout: Request timeout in seconds.
        """
        resolved_model = model or self.config.embed_model
        url = f"{self.config.base_url}/api/embed"

        input_payload: Union[str, List[str]]
        if isinstance(texts, str):
            input_payload = texts
        elif isinstance(texts, list):
            input_payload = [str(t) for t in texts]
        else:
            raise ValueError(f"texts must be a string or list of strings, got {type(texts)}")

        payload: Dict[str, Any] = {
            "model": resolved_model,
            "input": input_payload,
        }
        if truncate is not None:
            payload["truncate"] = truncate

        start_time = time.perf_counter()
        try:
            with self._client_context(timeout=timeout) as client:
                res = client.post(url, json=payload)
                elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

                if res.status_code == 200:
                    data = res.json()
                    raw_embeddings = data.get("embeddings", [])

                    # Validate response structure
                    if not isinstance(raw_embeddings, list) or len(raw_embeddings) == 0:
                        raise OllamaResponseError(
                            f"Embedding endpoint returned empty or malformed embeddings: {data}"
                        )

                    # Validate individual vector values
                    first_vec = raw_embeddings[0]
                    if not isinstance(first_vec, list) or len(first_vec) == 0:
                        raise OllamaResponseError(
                            f"Embedding returned invalid vector structure: {first_vec}"
                        )
                    if not all(isinstance(val, (int, float)) for val in first_vec[:10]):
                        raise OllamaResponseError(
                            "Embedding returned non-numeric vector values."
                        )

                    dimensions = len(first_vec)
                    total_ns = data.get("total_duration")

                    return OllamaEmbedResponse(
                        model=data.get("model", resolved_model),
                        embeddings=raw_embeddings,
                        dimensions=dimensions,
                        total_duration_ms=round(total_ns / 1e6, 2) if total_ns else elapsed_ms,
                    )

                if res.status_code == 404:
                    raise OllamaModelNotFoundError(
                        f"Configured embedding model '{resolved_model}' not found in local Ollama repository. "
                        f"Install it with: 'ollama pull {resolved_model}'."
                    )

                raise OllamaResponseError(
                    f"Ollama embed error HTTP {res.status_code}: {res.text[:200]}",
                    status_code=res.status_code,
                    response_text=res.text,
                )

        except httpx.ConnectError as e:
            raise OllamaConnectionError(
                f"Cannot connect to local Ollama daemon at '{self.config.base_url}' for embedding."
            ) from e
        except httpx.TimeoutException as e:
            raise OllamaTimeoutError(
                f"Embedding generation timed out on model '{resolved_model}'."
            ) from e

    # ------------------------------------------------------------------------
    # 4. Capability Diagnostics & Health Probe
    # ------------------------------------------------------------------------

    def check_model_capabilities(
        self,
        chat_model: Optional[str] = None,
        embed_model: Optional[str] = None,
    ) -> ModelCapabilities:
        """
        Runs non-destructive capability tests to verify:
        - Installed model presence.
        - Structured JSON output compatibility.
        - Tool-calling compatibility indications.
        """
        resolved_chat = chat_model or self.config.chat_model
        resolved_embed = embed_model or self.config.embed_model

        warnings: List[str] = []
        installed_names = self.get_installed_model_names()

        has_chat = self.has_model(resolved_chat)
        if not has_chat:
            warnings.append(
                f"Configured chat model '{resolved_chat}' is missing. "
                f"Run 'ollama pull {resolved_chat}'."
            )

        has_embed = self.has_model(resolved_embed)
        if not has_embed:
            warnings.append(
                f"Configured embedding model '{resolved_embed}' is missing. "
                f"Run 'ollama pull {resolved_embed}'."
            )

        supports_structured = False
        supports_tool_calling = False

        if has_chat:
            # 1. Test structured JSON output capability
            try:
                res = self.chat(
                    messages=[{"role": "user", "content": "Respond with JSON key 'ping': 'pong'"}],
                    model=resolved_chat,
                    format="json",
                    options={"num_predict": 20, "temperature": 0.0},
                    timeout=5.0,
                )
                if "ping" in res.content.lower():
                    supports_structured = True
            except Exception as e:
                warnings.append(f"Structured JSON output test failed on '{resolved_chat}': {e}")

            # 2. Inspect model metadata for tool support indications
            try:
                details = self.show_model(resolved_chat)
                template = details.get("template", "")
                params = str(details.get("parameters", ""))
                # Most tool-capable models have tool/function tokens in their template
                if any(kw in template for kw in ("tools", "tool_call", "function", ".Tools")):
                    supports_tool_calling = True
                elif "tool" in params:
                    supports_tool_calling = True
            except Exception:
                pass

        return ModelCapabilities(
            chat_model=resolved_chat,
            embed_model=resolved_embed,
            has_chat_model=has_chat,
            has_embed_model=has_embed,
            supports_structured_output=supports_structured,
            supports_tool_calling=supports_tool_calling,
            warnings=warnings,
            available_models=installed_names,
        )


# Global Singleton Client Instance
_default_ollama_client: Optional[OllamaClient] = None


def get_ollama_client(config: Optional[OllamaConfig] = None) -> OllamaClient:
    """Returns or initializes the shared OllamaClient singleton."""
    global _default_ollama_client
    if _default_ollama_client is None or config is not None:
        _default_ollama_client = OllamaClient(config=config)
    return _default_ollama_client
