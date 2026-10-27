"""
Tests for FastAPI REST endpoints for Member 3 (Frontend Lead) and Member 1 (Agent Architect).
Validates memory CRUD, search, export, task checkpoints, and security permissions over HTTP.
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.api.routes import SubsystemContainer
from app.main import app
from app.memory.crypto import EncryptionService, TestKeyProvider


@pytest.fixture
def client():
    """Initializes a temporary database and test client for API tests."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = os.path.join(tmpdir, "api_test.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        with TestClient(app) as test_client:
            yield test_client
        SubsystemContainer.db = None
        SubsystemContainer.memory_service = None


def test_root_and_health(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "online"
    assert "Go 81" in data["service"]

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "healthy"}


def test_episodic_and_semantic_api_flow(client: TestClient):
    # 1. Post episodic event
    event_payload = {
        "session_id": "session-http-1",
        "event_type": "user_message",
        "content": {"message": "Hello Go 81, remember my name is Ayush"},
        "source_ref": "web_chat",
    }
    r_evt = client.post("/api/memory/events", json=event_payload)
    assert r_evt.status_code == 201
    evt_data = r_evt.json()
    assert "id" in evt_data
    assert evt_data["session_id"] == "session-http-1"
    evt_id = evt_data["id"]

    # 2. Post semantic memory
    fact_payload = {
        "category": "preference",
        "subject": "Ayush",
        "predicate": "preferred_language",
        "object_value": "Python",
        "verification_status": "user_provided",
        "confidence": 1.0,
    }
    r_fact = client.post("/api/memory/semantic", json=fact_payload)
    assert r_fact.status_code == 201
    fact_data = r_fact.json()
    assert "id" in fact_data
    fact_id = fact_data["id"]

    # 3. Inspect single memory
    r_inspect = client.get(f"/api/memory/{evt_id}")
    assert r_inspect.status_code == 200
    inspected = r_inspect.json()
    assert inspected["id"] == evt_id
    assert inspected["payload"]["content"]["message"] == "Hello Go 81, remember my name is Ayush"

    # 4. Search memories
    r_search = client.get("/api/memory", params={"query": "Ayush"})
    assert r_search.status_code == 200
    results = r_search.json()
    assert len(results) >= 2

    # 5. Edit memory
    r_edit = client.put(
        f"/api/memory/{fact_id}",
        json={"object_value": "Python 3.13", "confidence": 0.99},
    )
    assert r_edit.status_code == 200
    edited = r_edit.json()
    assert edited["payload"]["object_value"] == "Python 3.13"
    assert edited["confidence"] == 0.99

    # 6. Export memories
    r_export = client.get("/api/memory/export/all")
    assert r_export.status_code == 200
    exported = r_export.json()
    assert exported["total_records"] >= 2

    # 7. Delete memory (soft)
    r_del = client.delete(f"/api/memory/{evt_id}?hard=false")
    assert r_del.status_code == 200
    assert r_del.json()["deletion_type"] == "soft"

    # Verify excluded from normal inspection and search
    r_after_del = client.get(f"/api/memory/{evt_id}")
    assert r_after_del.status_code == 404

    # 8. Delete memory (hard)
    r_hard = client.delete(f"/api/memory/{fact_id}?hard=true")
    assert r_hard.status_code == 200
    assert r_hard.json()["deletion_type"] == "hard"


def test_consolidation_api(client: TestClient):
    # Store episodic event with preference phrase
    client.post(
        "/api/memory/events",
        json={
            "session_id": "session-pref",
            "event_type": "user_message",
            "content": {"message": "I prefer dark mode over light mode"},
        },
    )

    # Trigger consolidation
    r_cons = client.post("/api/memory/consolidate")
    assert r_cons.status_code == 200
    res = r_cons.json()
    assert res["promoted_count"] >= 1


def test_tasks_recovery_api(client: TestClient):
    # Post task checkpoint
    chk_payload = {
        "task_id": "task-api-999",
        "workflow_id": "wf-http-test",
        "status": "RUNNING",
        "current_step": "step_one",
        "completed_step_ids": [],
        "pending_step_ids": ["step_one", "step_two"],
        "approval_references": [],
        "retry_count": 0,
        "state_data": {"counter": 10},
    }
    r_save = client.post("/api/tasks/checkpoints", json=chk_payload)
    assert r_save.status_code == 200

    # Query incomplete tasks
    r_list = client.get("/api/tasks/incomplete")
    assert r_list.status_code == 200
    tasks = r_list.json()
    assert any(t["task_id"] == "task-api-999" for t in tasks)


def test_permissions_api_flow(client: TestClient):
    # 1. High-risk tool check -> Default Deny
    check_payload = {
        "user_id": "agent-007",
        "action": "delete_file",
        "resource": "database.sqlite",
        "risk_level": "HIGH",
    }
    r_check = client.post("/api/security/check-permission", json=check_payload)
    assert r_check.status_code == 200
    dec = r_check.json()
    assert dec["allowed"] is False
    assert dec["approval_required"] is True
    assert dec["approval_id"] is not None

    # 2. Grant approval token
    r_app = client.post(
        "/api/security/approve",
        json={"action": "delete_file", "resource": "database.sqlite", "ttl_seconds": 120},
    )
    assert r_app.status_code == 200
    app_data = r_app.json()
    token = app_data["token"]

    # 3. Check again with approval token -> Allowed
    check_payload["approval_token"] = token
    r_check2 = client.post("/api/security/check-permission", json=check_payload)
    assert r_check2.status_code == 200
    assert r_check2.json()["allowed"] is True
