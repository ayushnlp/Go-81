"""
Tests for Model and System Health / Status Probe (backend/health.py).
Validates that the probe accurately distinguishes:
1. Ollama reachable (daemon listening)
2. Configured model present in tags registry
3. Live inference successful (prompt generation succeeds)
4. Memory available (encrypted SQLite storage active)

And verifies strict component isolation:
- Stale or unrelated results cannot mark the model unavailable when inference works.
- Stale or unrelated results cannot mark status healthy when inference fails.
"""

import os
import tempfile
import httpx
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager
from backend.health import ModelHealthReport, probe_model_health
from backend.main import app


@pytest.fixture
def clean_env():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "probe_test.db")
        crypto = EncryptionService(TestKeyProvider())
        db = DatabaseManager(db_path)
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)
        yield {
            "tmpdir": tmpdir,
            "db": db,
            "crypto": crypto,
            "db_path": db_path,
        }
        SubsystemContainer.db = None
        SubsystemContainer.memory_service = None


def test_probe_distinguishes_ollama_unreachable(clean_env):
    """When Ollama daemon is down, reachability is False, and failure reason indicates connection error."""
    # Mock client raising connect error
    mock_client = MagicMock(spec=httpx.Client)
    mock_client.get.side_effect = httpx.ConnectError("Connection refused on 127.0.0.1:11434")

    report = probe_model_health(
        ollama_endpoint="http://127.0.0.1:11434",
        model="gemma4:e2b",
        db=clean_env["db"],
        client=mock_client,
    )

    assert report.ollama_reachable is False
    assert report.model_present is False
    assert report.inference_successful is False
    assert report.memory_available is True  # Memory is independently healthy
    assert report.ollama_status == "disconnected"
    assert report.status == "degraded"  # Degraded because sovereign fallback is available via memory
    assert "Connection refused" in report.failure_reason


def test_probe_distinguishes_model_not_present(clean_env):
    """When Ollama is reachable but target model is not pulled, model_present is False."""
    mock_client = MagicMock(spec=httpx.Client)
    # Return 200 with other models, but not gemma4:e2b
    tags_response = MagicMock(status_code=200)
    tags_response.json.return_value = {
        "models": [{"name": "llama3.2:3b"}, {"name": "mistral:7b"}]
    }
    mock_client.get.return_value = tags_response

    report = probe_model_health(
        ollama_endpoint="http://127.0.0.1:11434",
        model="gemma4:e2b",
        db=clean_env["db"],
        client=mock_client,
    )

    assert report.ollama_reachable is True
    assert report.model_present is False
    assert report.inference_successful is False
    assert report.memory_available is True
    assert report.ollama_status == "degraded"
    assert "Configured model 'gemma4:e2b' not found" in report.failure_reason


def test_probe_distinguishes_inference_failure_when_model_present(clean_env):
    """When model is present but generate endpoint errors (e.g. CUDA OOM), inference_successful is False."""
    mock_client = MagicMock(spec=httpx.Client)
    tags_response = MagicMock(status_code=200)
    tags_response.json.return_value = {"models": [{"name": "gemma4:e2b"}]}
    mock_client.get.return_value = tags_response

    # Generate endpoint returns 500 CUDA out of memory
    gen_response = MagicMock(status_code=500, text="CUDA error: out of memory")
    mock_client.post.return_value = gen_response

    report = probe_model_health(
        ollama_endpoint="http://127.0.0.1:11434",
        model="gemma4:e2b",
        db=clean_env["db"],
        client=mock_client,
    )

    assert report.ollama_reachable is True
    assert report.model_present is True
    # Crucial: Must NOT mark healthy even though daemon and model are present!
    assert report.inference_successful is False
    assert report.status != "healthy"
    assert report.ollama_status == "degraded"
    assert "Inference execution failed" in report.failure_reason


def test_probe_distinguishes_all_healthy_when_inference_succeeds(clean_env):
    """When Ollama is up, model present, inference succeeds, and memory active: status is healthy."""
    mock_client = MagicMock(spec=httpx.Client)
    tags_response = MagicMock(status_code=200)
    tags_response.json.return_value = {"models": [{"name": "gemma4:e2b"}]}
    mock_client.get.return_value = tags_response

    gen_response = MagicMock(status_code=200)
    gen_response.json.return_value = {"response": "pong"}
    mock_client.post.return_value = gen_response

    report = probe_model_health(
        ollama_endpoint="http://127.0.0.1:11434",
        model="gemma4:e2b",
        db=clean_env["db"],
        client=mock_client,
    )

    assert report.ollama_reachable is True
    assert report.model_present is True
    assert report.inference_successful is True
    assert report.memory_available is True
    assert report.status == "healthy"
    assert report.ollama_status == "connected"
    assert report.failure_reason is None
    assert report.latency_ms is not None


def test_isolation_unrelated_memory_failure_does_not_mark_model_unavailable(clean_env):
    """If memory database fails, model inference success must still be reported accurately."""
    mock_client = MagicMock(spec=httpx.Client)
    tags_response = MagicMock(status_code=200)
    tags_response.json.return_value = {"models": [{"name": "gemma4:e2b"}]}
    mock_client.get.return_value = tags_response

    gen_response = MagicMock(status_code=200)
    gen_response.json.return_value = {"response": "pong"}
    mock_client.post.return_value = gen_response

    # Pass a broken database mock
    broken_db = MagicMock()
    broken_db.get_connection.side_effect = RuntimeError("SQLite database file is corrupted or locked")

    report = probe_model_health(
        ollama_endpoint="http://127.0.0.1:11434",
        model="gemma4:e2b",
        db=broken_db,
        client=mock_client,
    )

    # Model inference works: must NOT be marked unavailable due to memory!
    assert report.ollama_reachable is True
    assert report.model_present is True
    assert report.inference_successful is True
    assert report.ollama_status == "connected"

    # Memory failure is isolated to memory fields
    assert report.memory_available is False
    assert report.memory_status == "unavailable"
    assert report.status == "unhealthy"  # Overall system unhealthy because memory is down
    assert "Memory storage health probe failed" in report.failure_reason


def test_freshness_no_stale_cache_between_probes(clean_env):
    """Verifies that state changes between subsequent probes are immediately reflected without stale caching."""
    mock_client = MagicMock(spec=httpx.Client)

    # First probe: Ollama is down
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")
    report1 = probe_model_health(db=clean_env["db"], client=mock_client, model="llama3.2:3b")
    assert report1.inference_successful is False
    assert report1.ollama_reachable is False

    # Second probe: Ollama came online and inference works
    mock_client.get.side_effect = None
    mock_client.get.return_value = MagicMock(status_code=200, json=lambda: {"models": [{"name": "llama3.2:3b"}]})
    mock_client.post.return_value = MagicMock(status_code=200, json=lambda: {"response": "live"})

    report2 = probe_model_health(db=clean_env["db"], client=mock_client, model="llama3.2:3b")
    # Stale failure does NOT persist
    assert report2.ollama_reachable is True
    assert report2.inference_successful is True
    assert report2.status == "healthy"


def test_api_endpoints_model_health_and_agent_status(clean_env):
    """Tests GET /api/model/health and GET /api/agent/status endpoints over HTTP."""
    with TestClient(app) as client:
        # GET /api/model/health
        res = client.get("/api/model/health")
        assert res.status_code == 200
        data = res.json()
        assert "ollama_reachable" in data
        assert "model_present" in data
        assert "inference_successful" in data
        assert "memory_available" in data
        assert "failure_reason" in data

        # GET /api/agent/status
        res_status = client.get("/api/agent/status")
        assert res_status.status_code == 200
        status_data = res_status.json()
        assert "model" in status_data
        assert "ollamaStatus" in status_data
        assert "encryptedDatabase" in status_data
        assert "inferenceSuccessful" in status_data
        assert "modelPresent" in status_data
        assert "ollamaReachable" in status_data
        assert "memoryAvailable" in status_data
        assert "failureReason" in status_data

        # GET /health liveness probe backwards compatibility
        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"status": "healthy"}
