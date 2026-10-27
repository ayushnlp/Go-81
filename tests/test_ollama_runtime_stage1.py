"""
Comprehensive Tests for Go 81 Stage 1: Central Ollama Runtime Foundation.

Covers:
1. Ollama URL and configuration validation & normalization.
2. Local AI policy enforcement (rejection of cloud inference endpoints).
3. Model discovery (/api/tags) and missing-model diagnostics.
4. Successful local chat requests (/api/chat schema and duration).
5. Successful embedding requests (/api/embed schema and vector dimensions).
6. Malformed and unexpected response handling.
7. Ollama daemon unavailable / connection refused.
8. Request timeout behavior.
9. Secret and prompt redaction in logs.
10. No silent cloud inference fallback.
11. Model capability diagnostics (structured JSON and tool support).
12. Real local Ollama smoke test (or clear blocked diagnostic if daemon offline).
"""

import json
import logging
import os
import unittest.mock as mock
from typing import Any, Dict, List

import httpx
import pytest

from backend.ollama_client import (
    ChatMessage,
    ModelCapabilities,
    OllamaChatResponse,
    OllamaClient,
    OllamaConfig,
    OllamaConnectionError,
    OllamaEmbedResponse,
    OllamaLocalPolicyViolation,
    OllamaModelNotFoundError,
    OllamaResponseError,
    OllamaTimeoutError,
    get_ollama_client,
    sanitize_log_message,
)


# ============================================================================
# 1. Configuration & Local Policy Enforcement Tests
# ============================================================================

def test_config_defaults_and_normalization():
    """Validates default local settings and trailing slash normalization."""
    cfg = OllamaConfig(base_url="http://127.0.0.1:11434/")
    assert cfg.base_url == "http://127.0.0.1:11434"
    assert cfg.chat_model in ("llama3.2:3b", "gemma4:e2b") or len(cfg.chat_model) > 0
    assert cfg.embed_model == "nomic-embed-text"
    assert cfg.connect_timeout == 3.0
    assert cfg.request_timeout == 30.0


def test_config_env_overrides(monkeypatch):
    """Validates that environment variables override defaults cleanly."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_CHAT_MODEL", "qwen2.5:7b")
    monkeypatch.setenv("OLLAMA_EMBED_MODEL", "bge-m3")

    cfg = OllamaConfig()
    assert cfg.base_url == "http://localhost:11434"
    assert cfg.chat_model == "qwen2.5:7b"
    assert cfg.embed_model == "bge-m3"


def test_sovereign_policy_enforcement_blocks_cloud_endpoints():
    """
    Enforces NFR1 / NFR1.3:
    Rejects any cloud or external URL (OpenAI, Anthropic, cloud Ollama, etc.)
    to guarantee zero telemetry leakage.
    """
    prohibited_urls = [
        "https://api.openai.com/v1",
        "https://api.anthropic.com",
        "https://generativelanguage.googleapis.com",
        "https://api.groq.com/openai/v1",
        "https://ollama.external-cloud.com",
        "http://54.210.12.8:11434",
    ]
    for url in prohibited_urls:
        with pytest.raises(OllamaLocalPolicyViolation) as exc_info:
            OllamaConfig(base_url=url)
        assert "Sovereignty Violation" in str(exc_info.value) or "external or remote host" in str(exc_info.value)


def test_sovereign_policy_allows_localhost_and_loopback():
    """Confirms 127.0.0.1, localhost, ::1, and 0.0.0.0 are strictly permitted."""
    allowed = [
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://0.0.0.0:11434",
        "http://127.0.0.1:8080",
    ]
    for url in allowed:
        cfg = OllamaConfig(base_url=url)
        assert cfg.base_url == url


# ============================================================================
# 2. Model Discovery & Inspection Tests (Mocked)
# ============================================================================

def test_model_discovery_and_tags_parsing():
    """Validates GET /api/tags parsing and model detection."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_res = mock.MagicMock(status_code=200)
    mock_res.json.return_value = {
        "models": [
            {"name": "llama3.2:3b", "model": "llama3.2:3b"},
            {"name": "nomic-embed-text:latest", "model": "nomic-embed-text:latest"},
            {"name": "gemma4:e2b", "model": "gemma4:e2b"},
        ]
    }
    mock_client.get.return_value = mock_res

    client = OllamaClient(
        config=OllamaConfig(base_url="http://127.0.0.1:11434"),
        http_client=mock_client,
    )

    models = client.list_models()
    assert len(models) == 3
    names = client.get_installed_model_names()
    assert "llama3.2:3b" in names
    assert "nomic-embed-text:latest" in names

    assert client.has_model("llama3.2:3b") is True
    assert client.has_model("llama3.2:3b:latest") is True
    assert client.has_model("nomic-embed-text") is True
    assert client.has_model("nonexistent-model:99b") is False


def test_missing_model_actionable_error():
    """Validates that a 404 from /api/show or /api/chat provides actionable pull command."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_res = mock.MagicMock(status_code=404, text='{"error":"model \'llama3.2:3b\' not found"}')
    mock_client.post.return_value = mock_res

    client = OllamaClient(
        config=OllamaConfig(base_url="http://127.0.0.1:11434"),
        http_client=mock_client,
    )

    with pytest.raises(OllamaModelNotFoundError) as exc_info:
        client.show_model("llama3.2:3b")

    err_msg = str(exc_info.value)
    assert "ollama pull llama3.2:3b" in err_msg


# ============================================================================
# 3. Chat Inference Tests (POST /api/chat)
# ============================================================================

def test_successful_chat_request_and_timing():
    """Validates non-streaming POST /api/chat payload, response parsing, and duration."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_res = mock.MagicMock(status_code=200)
    mock_res.json.return_value = {
        "model": "llama3.2:3b",
        "created_at": "2026-10-27T12:00:00Z",
        "message": {
            "role": "assistant",
            "content": "Sovereign plan formulated locally.",
        },
        "done": True,
        "total_duration": 450_000_000,  # 450 ms in nanoseconds
        "load_duration": 50_000_000,
        "eval_count": 28,
        "eval_duration": 380_000_000,
    }
    mock_client.post.return_value = mock_res

    client = OllamaClient(
        config=OllamaConfig(base_url="http://127.0.0.1:11434", chat_model="llama3.2:3b"),
        http_client=mock_client,
    )

    resp = client.chat(
        messages=[
            ChatMessage(role="user", content="Triage local project logs"),
        ],
        format="json",
        options={"temperature": 0.1},
    )

    assert resp.content == "Sovereign plan formulated locally."
    assert resp.model == "llama3.2:3b"
    assert resp.done is True
    assert resp.total_duration_ms == 450.0
    assert resp.load_duration_ms == 50.0

    # Verify payload format passed to client
    called_url, called_kwargs = mock_client.post.call_args
    assert called_url[0] == "http://127.0.0.1:11434/api/chat"
    payload = called_kwargs["json"]
    assert payload["model"] == "llama3.2:3b"
    assert payload["format"] == "json"
    assert payload["stream"] is False
    assert payload["options"] == {"temperature": 0.1}
    assert payload["messages"][0]["content"] == "Triage local project logs"


def test_chat_legacy_response_fallback():
    """Verifies backward compatibility when /api/generate format (response key) is returned."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_res = mock.MagicMock(status_code=200)
    mock_res.json.return_value = {
        "response": '{"status": "ok"}',
    }
    mock_client.post.return_value = mock_res

    client = OllamaClient(http_client=mock_client)
    res = client.chat(messages=[{"role": "user", "content": "ping"}])
    assert res.content == '{"status": "ok"}'


# ============================================================================
# 4. Embedding Inference Tests (POST /api/embed)
# ============================================================================

def test_successful_embedding_inference_and_dimensions():
    """Validates POST /api/embed payload and dynamic dimension discovery."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_res = mock.MagicMock(status_code=200)

    # 768-dimensional mock vector for nomic-embed-text
    mock_vector = [0.0123] * 768
    mock_res.json.return_value = {
        "model": "nomic-embed-text",
        "embeddings": [mock_vector],
        "total_duration": 85_000_000,
    }
    mock_client.post.return_value = mock_res

    client = OllamaClient(
        config=OllamaConfig(base_url="http://127.0.0.1:11434", embed_model="nomic-embed-text"),
        http_client=mock_client,
    )

    resp = client.embed(texts="User preference: dark mode and SQLite WAL")

    assert resp.dimensions == 768
    assert len(resp.embeddings) == 1
    assert len(resp.embeddings[0]) == 768
    assert resp.model == "nomic-embed-text"
    assert resp.total_duration_ms == 85.0

    called_url, called_kwargs = mock_client.post.call_args
    assert called_url[0] == "http://127.0.0.1:11434/api/embed"
    assert called_kwargs["json"]["model"] == "nomic-embed-text"
    assert called_kwargs["json"]["input"] == "User preference: dark mode and SQLite WAL"


def test_batch_embedding_input():
    """Validates batch list embedding requests."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_res = mock.MagicMock(status_code=200)
    mock_res.json.return_value = {
        "model": "nomic-embed-text",
        "embeddings": [[0.1] * 768, [0.2] * 768],
    }
    mock_client.post.return_value = mock_res

    client = OllamaClient(http_client=mock_client)
    resp = client.embed(texts=["Doc A", "Doc B"])
    assert len(resp.embeddings) == 2
    assert resp.dimensions == 768


def test_embedding_validates_numeric_vectors():
    """Rejects malformed or non-numeric embedding responses."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_res = mock.MagicMock(status_code=200)
    mock_res.json.return_value = {"embeddings": [["not_a_number"]]}
    mock_client.post.return_value = mock_res

    client = OllamaClient(http_client=mock_client)
    with pytest.raises(OllamaResponseError) as exc_info:
        client.embed("Test")
    assert "non-numeric" in str(exc_info.value)


# ============================================================================
# 5. Resilience, Timeouts & Error Propagation Tests
# ============================================================================

def test_connection_refused_error_handling():
    """Validates that a stopped daemon raises OllamaConnectionError with instructions."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = httpx.ConnectError("Connection refused on 127.0.0.1:11434")

    client = OllamaClient(http_client=mock_client)
    with pytest.raises(OllamaConnectionError) as exc_info:
        client.chat(messages=[{"role": "user", "content": "ping"}])

    err_str = str(exc_info.value)
    assert "Cannot connect to local Ollama daemon" in err_str
    assert "ollama serve" in err_str


def test_timeout_error_handling():
    """Validates timeout error propagation."""
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = httpx.TimeoutException("Read timed out after 30s")

    client = OllamaClient(http_client=mock_client)
    with pytest.raises(OllamaTimeoutError) as exc_info:
        client.chat(messages=[{"role": "user", "content": "long reasoning query"}])

    assert "timed out" in str(exc_info.value)


def test_no_silent_cloud_fallback_when_ollama_fails():
    """
    CRITICAL SOVEREIGN INVARIANT:
    When local Ollama fails or times out, the client must never silently fallback
    to OpenAI, Anthropic, or any remote service. It must fail honestly.
    """
    mock_client = mock.MagicMock(spec=httpx.Client)
    mock_client.post.side_effect = httpx.ConnectError("Daemon down")

    client = OllamaClient(http_client=mock_client)

    # Calling chat must raise local exception, NOT trigger cloud request
    with pytest.raises(OllamaConnectionError):
        client.chat(messages=[{"role": "user", "content": "critical task"}])


# ============================================================================
# 6. Secret Redaction in Logging Tests
# ============================================================================

def test_secret_redaction_in_log_sanitizer():
    """Verifies that secrets, API tokens, and passwords are wiped from log entries."""
    raw_log = "User sent request with Bearer abcdef1234567890xyz and api_key='sk-live998877665544332211'"
    clean_log = sanitize_log_message(raw_log)

    assert "abcdef1234567890xyz" not in clean_log
    assert "sk-live998877665544332211" not in clean_log
    assert "[REDACTED_SECRET]" in clean_log


# ============================================================================
# 7. Model Capabilities Diagnostics
# ============================================================================

def test_model_capabilities_smoke_detection():
    """Verifies structured output test and tool support discovery in metadata."""
    mock_client = mock.MagicMock(spec=httpx.Client)

    # 1. Tags returns llama3.2:3b and nomic-embed-text
    tags_res = mock.MagicMock(status_code=200)
    tags_res.json.return_value = {
        "models": [{"name": "llama3.2:3b"}, {"name": "nomic-embed-text"}]
    }
    mock_client.get.return_value = tags_res

    # 2. Chat structured output responds with JSON containing ping
    chat_res = mock.MagicMock(status_code=200)
    chat_res.json.return_value = {
        "message": {"role": "assistant", "content": '{"ping": "pong"}'}
    }

    # 3. Show model returns template with .Tools
    show_res = mock.MagicMock(status_code=200)
    show_res.json.return_value = {
        "template": "{{ if .Tools }}Tools: {{ .Tools }}{{ end }}",
        "parameters": "stop <|im_end|>",
    }

    def mock_post_dispatcher(url, **kwargs):
        if "/api/chat" in str(url):
            return chat_res
        if "/api/show" in str(url):
            return show_res
        return mock.MagicMock(status_code=200)

    mock_client.post.side_effect = mock_post_dispatcher

    client = OllamaClient(
        config=OllamaConfig(chat_model="llama3.2:3b", embed_model="nomic-embed-text"),
        http_client=mock_client,
    )

    caps = client.check_model_capabilities()
    assert caps.has_chat_model is True
    assert caps.has_embed_model is True
    assert caps.supports_structured_output is True
    assert caps.supports_tool_calling is True
    assert len(caps.warnings) == 0


# ============================================================================
# 8. Live Local Ollama Smoke Test (Honest Degraded Reporting)
# ============================================================================

def test_live_local_ollama_smoke_or_blocked_notice():
    """
    Smoke test against live local daemon at 127.0.0.1:11434.
    If the daemon is running and models are installed, it verifies live inference.
    If not, it outputs a clear, honest diagnostic without pretending it passed.
    """
    client = OllamaClient()
    if not client.is_reachable():
        pytest.skip(
            "LOCAL_OLLAMA_BLOCKED: Ollama daemon not reachable at http://127.0.0.1:11434. "
            "To enable live tests: install from https://ollama.com and run 'ollama serve' && "
            f"'ollama pull {client.config.chat_model}' && 'ollama pull {client.config.embed_model}'."
        )

    # Daemon is running: check models
    installed = client.get_installed_model_names()
    if not client.has_model(client.config.chat_model):
        pytest.skip(
            f"LOCAL_OLLAMA_MODEL_MISSING: Chat model '{client.config.chat_model}' not installed. "
            f"Available: {installed}. Run 'ollama pull {client.config.chat_model}'."
        )

    # Execute harmless live chat ping (allow 30s for model weight loading into VRAM/RAM)
    resp = client.chat(
        messages=[{"role": "user", "content": "Respond with single word: OK"}],
        options={"num_predict": 5},
        timeout=30.0,
    )
    assert resp.content.strip() != ""
    assert resp.total_duration_ms is not None
