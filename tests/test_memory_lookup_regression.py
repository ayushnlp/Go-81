"""
Regression tests for Memory-by-ID lookup and update in Member 2 subsystem.
Validates:
1. Creating semantic memory, retrieving it by returned ID, and updating it by returned ID.
2. Resilience across UUID types (str, uuid.UUID instance, uppercase, whitespace, unhyphenated hex).
3. Non-existent IDs cleanly returning 404 without weakening access controls.
4. HTTP API flow via FastAPI TestClient.
"""

import os
import tempfile
import uuid
import pytest
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from app.main import app
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager
from app.memory.models import MemoryType, MemoryUpdate, SemanticCategory, VerificationStatus
from app.memory.service import MemoryService


@pytest.fixture
def service_env():
    """Provides a fresh isolated database and MemoryService."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "regression_mem.db")
        db = DatabaseManager(db_path)
        crypto = EncryptionService(TestKeyProvider())
        service = MemoryService(db, crypto)
        yield service, db, crypto


@pytest.fixture
def test_client():
    """Initializes a temporary database and TestClient."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "regression_api.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        with TestClient(app) as client:
            yield client


def test_service_create_retrieve_update_by_returned_id(service_env):
    """
    Direct service regression test:
    Store semantic memory, retrieve using the returned ID, update using the returned ID,
    and verify all representations (exact str, uuid.UUID, uppercase, whitespace, hex).
    """
    service, _, _ = service_env

    # 1. Create a semantic memory
    created = service.store_memory(
        category=SemanticCategory.FACT,
        subject="Go 81",
        predicate="uses_memory_system",
        object_value="persistent local memory",
        verification_status=VerificationStatus.USER_PROVIDED,
        confidence=1.0,
        source_ref="manual-test-001",
    )

    returned_id = created.id
    assert returned_id is not None
    assert len(returned_id) == 36

    # 2. Retrieve using exact returned ID
    retrieved = service.get_memory(returned_id)
    assert retrieved is not None
    assert retrieved.id == returned_id
    assert retrieved.payload["subject"] == "Go 81"
    assert retrieved.payload["object_value"] == "persistent local memory"
    assert not retrieved.is_deleted

    # 3. Retrieve using uuid.UUID object
    uuid_obj = uuid.UUID(returned_id)
    retrieved_from_uuid = service.get_memory(uuid_obj)
    assert retrieved_from_uuid is not None
    assert retrieved_from_uuid.id == returned_id

    # 4. Retrieve using uppercase string
    retrieved_upper = service.get_memory(returned_id.upper())
    assert retrieved_upper is not None
    assert retrieved_upper.id == returned_id

    # 5. Retrieve with surrounding whitespace
    retrieved_spaced = service.get_memory(f"   {returned_id}   \n")
    assert retrieved_spaced is not None
    assert retrieved_spaced.id == returned_id

    # 6. Retrieve using unhyphenated 32-character hex UUID
    unhyphenated = returned_id.replace("-", "")
    retrieved_unhyphenated = service.get_memory(unhyphenated)
    assert retrieved_unhyphenated is not None
    assert retrieved_unhyphenated.id == returned_id

    # 7. Update using returned ID
    update_data = MemoryUpdate(
        object_value="updated sovereign memory",
        confidence=0.98,
        verification_status=VerificationStatus.VERIFIED,
    )
    updated = service.update_memory(returned_id, update_data)
    assert updated.id == returned_id
    assert updated.payload["object_value"] == "updated sovereign memory"
    assert updated.confidence == 0.98
    assert updated.verification_status == VerificationStatus.VERIFIED

    # 8. Re-fetch and confirm persistence of update
    fresh_fetch = service.get_memory(returned_id)
    assert fresh_fetch is not None
    assert fresh_fetch.payload["object_value"] == "updated sovereign memory"
    assert fresh_fetch.confidence == 0.98

    # 9. Verify non-existent ID lookup returns None without error
    non_existent_id = "14621711-2897-4912-8005-0471d0ce2411"
    assert service.get_memory(non_existent_id) is None


def test_api_create_retrieve_update_flow(test_client: TestClient):
    """
    HTTP endpoint regression test:
    POST /api/memory/semantic -> get returned ID -> GET /api/memory/{id} -> PUT /api/memory/{id} -> GET
    """
    client = test_client

    # 1. Create semantic memory via API
    payload = {
        "category": "fact",
        "subject": "Go 81",
        "predicate": "architecture_tier",
        "object_value": "Member 2 Sovereign Security",
        "verification_status": "user_provided",
        "confidence": 1.0,
        "source_ref": "regression-test-suite",
    }
    resp = client.post("/api/memory/semantic", json=payload)
    assert resp.status_code == 201
    created_data = resp.json()
    returned_id = created_data["id"]
    assert returned_id

    # 2. List endpoint contains the record
    resp_list = client.get("/api/memory?query=Go+81&limit=50&offset=0&include_expired=false")
    assert resp_list.status_code == 200
    listed_ids = [r["id"] for r in resp_list.json()]
    assert returned_id in listed_ids

    # 3. GET /api/memory/{returned_id}
    resp_get = client.get(f"/api/memory/{returned_id}?include_deleted=false")
    assert resp_get.status_code == 200
    rec = resp_get.json()
    assert rec["id"] == returned_id
    assert rec["payload"]["object_value"] == "Member 2 Sovereign Security"
    assert rec["is_deleted"] is False

    # 4. GET with uppercase ID
    resp_get_upper = client.get(f"/api/memory/{returned_id.upper()}?include_deleted=false")
    assert resp_get_upper.status_code == 200
    assert resp_get_upper.json()["id"] == returned_id

    # 5. PUT /api/memory/{returned_id}
    put_payload = {
        "object_value": "Member 2 Hardened Vault",
        "confidence": 0.99,
        "verification_status": "verified",
    }
    resp_put = client.put(f"/api/memory/{returned_id}", json=put_payload)
    assert resp_put.status_code == 200
    updated_rec = resp_put.json()
    assert updated_rec["payload"]["object_value"] == "Member 2 Hardened Vault"
    assert updated_rec["confidence"] == 0.99

    # 6. Verify GET returns updated data
    resp_get_after = client.get(f"/api/memory/{returned_id}?include_deleted=false")
    assert resp_get_after.status_code == 200
    assert resp_get_after.json()["payload"]["object_value"] == "Member 2 Hardened Vault"

    # 7. Non-existent ID returns 404 cleanly
    non_existent_id = "14621711-2897-4912-8005-0471d0ce2411"
    resp_404 = client.get(f"/api/memory/{non_existent_id}?include_deleted=false")
    assert resp_404.status_code == 404

    resp_put_404 = client.put(f"/api/memory/{non_existent_id}", json={"object_value": "test"})
    assert resp_put_404.status_code == 404
