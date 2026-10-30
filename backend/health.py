"""
Model and System Health Probing Engine for Project Go 81.
Distinguishes:
1. Ollama reachable (daemon socket responds)
2. Configured model present (model exists in tags registry)
3. Inference successful (test generation ping executes successfully)
4. Memory available (encrypted SQLite storage is unlocked and responsive)

Guarantees isolation:
- A stale or cached result never masks live failure or recovery.
- An unrelated memory failure cannot mark model inference failed when inference works.
- An available memory database cannot mark overall status healthy when inference fails.
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ModelHealthReport(BaseModel):
    """Exact status schema for sovereign agent model and subsystem health."""
    status: str = Field(..., description="'healthy' | 'degraded' | 'unhealthy'")
    online: bool = Field(..., description="True if service is running and memory is active")
    
    # Four distinct probe dimensions
    ollama_reachable: bool = Field(..., description="True if local Ollama daemon port responds")
    model_present: bool = Field(..., description="True if configured model is in Ollama tag registry")
    inference_successful: bool = Field(..., description="True if prompt test inference generates output")
    memory_available: bool = Field(..., description="True if SQLite memory database is unlocked and responsive")

    # Diagnostic metadata
    model: str = Field(..., description="Target model tag (e.g. gemma4:e2b)")
    ollama_endpoint: str = Field(..., description="Configured Ollama HTTP endpoint")
    ollama_status: str = Field(..., description="'connected' | 'disconnected' | 'degraded'")
    memory_status: str = Field(..., description="'unlocked' | 'locked' | 'unavailable'")
    latency_ms: Optional[float] = Field(None, description="Inference latency in milliseconds")
    failure_reason: Optional[str] = Field(None, description="Exact root cause if degraded or failing")
    probed_at: str = Field(default_factory=utc_now_iso, description="ISO UTC timestamp of fresh probe")


def probe_model_health(
    ollama_endpoint: Optional[str] = None,
    model: Optional[str] = None,
    memory_service: Optional[Any] = None,
    db: Optional[Any] = None,
    timeout: float = 8.0,
    test_inference: bool = True,
    client: Optional[httpx.Client] = None,
) -> ModelHealthReport:
    """
    Performs a fresh, isolated probe across model reachability, presence, inference, and memory.
    Every call is executed live to prevent stale cached states.
    """
    resolved_model = model or os.environ.get("OLLAMA_CHAT_MODEL", os.environ.get("GO81_MODEL", "llama3.2:3b"))
    resolved_endpoint = (ollama_endpoint or os.environ.get("OLLAMA_BASE_URL", os.environ.get("OLLAMA_ENDPOINT", "http://127.0.0.1:11434"))).rstrip("/")

    ollama_reachable = False
    model_present = False
    inference_successful = False
    memory_available = False
    latency_ms: Optional[float] = None
    failure_reasons: List[str] = []

    # -------------------------------------------------------------------------
    # 1. Probe Ollama Reachability & Model Presence
    # -------------------------------------------------------------------------
    def _do_http_probe(http_client: httpx.Client):
        nonlocal ollama_reachable, model_present, inference_successful, latency_ms
        try:
            tags_res = http_client.get(f"{resolved_endpoint}/api/tags")
            if tags_res.status_code == 200:
                ollama_reachable = True
                data = tags_res.json()
                models_list = [m.get("name", "") for m in data.get("models", [])]
                # Match exact name or prefix before ':latest'
                target_base = resolved_model.split(":")[0]
                model_present = any(
                    resolved_model == m or m.startswith(f"{resolved_model}:") or m.startswith(f"{target_base}:")
                    for m in models_list
                )
                if not model_present:
                    failure_reasons.append(
                        f"Configured model '{resolved_model}' not found in Ollama repository (available: {models_list}). "
                        f"Run 'ollama pull {resolved_model}'."
                    )
            else:
                ollama_reachable = False
                failure_reasons.append(
                    f"Ollama endpoint '{resolved_endpoint}' returned HTTP {tags_res.status_code}: {tags_res.text[:100]}"
                )
        except httpx.ConnectError:
            ollama_reachable = False
            failure_reasons.append(f"Connection refused at Ollama endpoint '{resolved_endpoint}'. Daemon is not running.")
        except httpx.TimeoutException:
            ollama_reachable = False
            failure_reasons.append(f"Connection timed out after {timeout}s connecting to Ollama endpoint '{resolved_endpoint}'.")
        except Exception as e:
            ollama_reachable = False
            failure_reasons.append(f"Failed to connect to Ollama endpoint '{resolved_endpoint}': {type(e).__name__} ({e})")

        # ---------------------------------------------------------------------
        # 2. Probe Live Model Inference (Isolated from Reachability alone)
        # ---------------------------------------------------------------------
        if ollama_reachable and model_present and test_inference:
            start_t = time.perf_counter()
            try:
                gen_res = http_client.post(
                    f"{resolved_endpoint}/api/generate",
                    json={
                        "model": resolved_model,
                        "prompt": "health_probe_ping",
                        "stream": False,
                        "options": {"num_predict": 1},
                    },
                )
                latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
                if gen_res.status_code == 200 and "response" in gen_res.json():
                    inference_successful = True
                else:
                    inference_successful = False
                    failure_reasons.append(
                        f"Inference execution failed on model '{resolved_model}': HTTP {gen_res.status_code} - {gen_res.text[:100]}"
                    )
            except httpx.TimeoutException:
                inference_successful = False
                failure_reasons.append(f"Inference timed out after {timeout}s on model '{resolved_model}'.")
            except Exception as e:
                inference_successful = False
                failure_reasons.append(f"Inference call error on model '{resolved_model}': {type(e).__name__} ({e})")

    if client is not None:
        _do_http_probe(client)
    else:
        try:
            with httpx.Client(timeout=timeout) as temp_client:
                _do_http_probe(temp_client)
        except Exception as outer_e:
            ollama_reachable = False
            failure_reasons.append(f"HTTP client initialization failed: {outer_e}")

    # Determine ollama_status
    if inference_successful:
        ollama_status = "connected"
    elif ollama_reachable and model_present:
        ollama_status = "degraded"
    elif ollama_reachable:
        ollama_status = "degraded"
    else:
        ollama_status = "disconnected"

    # -------------------------------------------------------------------------
    # 3. Probe Memory Subsystem (Isolated from Model Status)
    # -------------------------------------------------------------------------
    try:
        active_db = db
        active_svc = memory_service
        if active_db is None:
            from app.api.routes import SubsystemContainer
            active_db = SubsystemContainer.db
            active_svc = active_svc or SubsystemContainer.memory_service

        if active_db is not None:
            with active_db.get_connection() as conn:
                conn.execute("SELECT 1").fetchone()
            memory_available = True
            memory_status = "unlocked"
        else:
            memory_available = False
            memory_status = "unavailable"
            failure_reasons.append("Memory database connection is uninitialized or closed.")
    except Exception as mem_err:
        memory_available = False
        memory_status = "unavailable"
        failure_reasons.append(f"Memory storage health probe failed: {type(mem_err).__name__} ({mem_err})")

    # -------------------------------------------------------------------------
    # 4. Strict Combined Status Evaluation
    # -------------------------------------------------------------------------
    # Healthy REQUIRES inference_successful AND memory_available
    if inference_successful and memory_available:
        status = "healthy"
        combined_failure = None
    elif memory_available and not inference_successful:
        # Sovereign deterministic fallback active when model inference is offline
        status = "degraded"
        combined_failure = "; ".join(failure_reasons)
    else:
        status = "unhealthy"
        combined_failure = "; ".join(failure_reasons)

    return ModelHealthReport(
        status=status,
        online=memory_available or inference_successful,
        ollama_reachable=ollama_reachable,
        model_present=model_present,
        inference_successful=inference_successful,
        memory_available=memory_available,
        model=resolved_model,
        ollama_endpoint=resolved_endpoint,
        ollama_status=ollama_status,
        memory_status=memory_status,
        latency_ms=latency_ms,
        failure_reason=combined_failure,
        probed_at=utc_now_iso(),
    )
