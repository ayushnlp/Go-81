"""
Security, Persistence, and API Contract Audit Tests for Go 81 Memory Subsystem.
Validates:
1. Environment key provider (GO81_ENCRYPTION_KEY).
2. Wrong key rejection and ciphertext tamper detection.
3. Raw disk inspection for zero plaintext leakage across all tables.
4. Soft vs hard deletion behavior and forensic limits.
5. Frontend command center API contracts (GET /api/memories, DELETE /api/memories/{id}, PATCH /api/memories/{id}).
6. Strict exclusion of unverified facts from trusted planner context.
7. Latency benchmark under 800ms threshold.
"""

import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from app.main import app
from app.memory.crypto import (
    DecryptionError,
    EncryptionService,
    EnvKeyProvider,
    MissingKeyError,
    TestKeyProvider,
)
from app.memory.database import DatabaseManager
from app.memory.models import (
    EpisodicEvent,
    MemoryType,
    SemanticCategory,
    TaskCheckpoint,
    TaskStatus,
    VerificationStatus,
)
from app.memory.recovery import TaskRecoveryManager
from app.memory.service import MemoryService


@pytest.fixture
def audit_fixture():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "go81_audit.db")
        key_provider = TestKeyProvider()
        crypto = EncryptionService(key_provider)
        db = DatabaseManager(db_path)
        service = MemoryService(db, crypto)
        recovery = TaskRecoveryManager(db, crypto)
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        with TestClient(app) as client:
            yield {
                "tmpdir": tmpdir,
                "db_path": db_path,
                "key_provider": key_provider,
                "crypto": crypto,
                "db": db,
                "service": service,
                "recovery": recovery,
                "client": client,
            }


def test_env_key_provider_branding_and_fallback(monkeypatch):
    """Verifies GO81_ENCRYPTION_KEY is the primary supported environment key variable."""
    test_key_primary = "Z284MV9wcmltYXJ5X2tleV9mb3JfdGVzdGluZ18xMjM0NQ=="

    # 1. Primary variable set
    monkeypatch.setenv("GO81_ENCRYPTION_KEY", test_key_primary)
    p1 = EnvKeyProvider()
    assert p1.get_key() == test_key_primary.encode("utf-8")

    # 2. Unset variable raises MissingKeyError
    monkeypatch.delenv("GO81_ENCRYPTION_KEY", raising=False)
    p2 = EnvKeyProvider()
    with pytest.raises(MissingKeyError):
        p2.get_key()


def test_wrong_key_and_tamper_detection():
    """Verifies decryption fails safely without plaintext leakage on invalid key or corrupted token."""
    crypto1 = EncryptionService(TestKeyProvider())
    crypto2 = EncryptionService(TestKeyProvider())

    payload = {"sensitive_credential": "super_secret_token_123"}
    token = crypto1.encrypt_json(payload)

    # Decrypt with wrong key raises DecryptionError
    with pytest.raises(DecryptionError):
        crypto2.decrypt_json(token)

    # Tampered token raises DecryptionError
    token_chars = list(token)
    token_chars[15] = "A" if token_chars[15] != "A" else "B"
    tampered_token = "".join(token_chars)
    with pytest.raises(DecryptionError):
        crypto1.decrypt_json(tampered_token)


def test_raw_disk_canary_inspection(audit_fixture):
    """
    Physical disk verification:
    Writes synthetic secret canary into all tables, flushes WAL,
    and inspects raw on-disk bytes of .db and .db-wal files.
    """
    service: MemoryService = audit_fixture["service"]
    recovery: TaskRecoveryManager = audit_fixture["recovery"]
    db: DatabaseManager = audit_fixture["db"]
    tmpdir = audit_fixture["tmpdir"]

    canary = "CANARY_SECRET_GO81_AUDIT_VALUE_998877"

    # 1. Episodic
    service.store_event(
        session_id="canary-session",
        event_type="user_message",
        content={"secret": canary},
    )

    # 2. Semantic
    service.store_memory(
        category=SemanticCategory.FACT,
        subject="canary_subject",
        predicate="canary_pred",
        object_value=canary,
    )

    # 3. Task checkpoint
    checkpoint = TaskCheckpoint(
        task_id="canary-task",
        workflow_id="canary-wf",
        status=TaskStatus.RUNNING,
        current_step="canary_step",
        state_data={"canary_key": canary},
    )
    recovery.save_task_checkpoint(checkpoint)

    # 4. Execution event
    recovery.record_execution_event(
        task_id="canary-task",
        step_id="canary_step",
        action="canary_action",
        status="SUCCESS",
        input_params={"token": canary},
        output_details={"result": canary},
    )

    # Force SQLite to flush WAL pages into main db file
    db.checkpoint_wal()

    # Search raw file bytes
    canary_bytes = canary.encode("utf-8")
    for fname in os.listdir(tmpdir):
        fpath = os.path.join(tmpdir, fname)
        if os.path.isfile(fpath):
            with open(fpath, "rb") as f:
                data = f.read()
                assert canary_bytes not in data, f"Plaintext canary found in raw file {fname}!"


def test_soft_and_hard_deletion_lifecycle(audit_fixture):
    """Verifies soft deletion hides from queries/exports and hard deletion destroys row."""
    service: MemoryService = audit_fixture["service"]

    mem = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="Dark Mode",
        predicate="enabled",
        object_value=True,
    )

    # Record is retrievable
    assert service.get_memory(mem.id) is not None

    # Soft delete
    assert service.delete_memory(mem.id, hard_delete=False) is True
    # Hidden from standard retrieval
    assert service.get_memory(mem.id) is None
    # Hidden from search
    found = service.search_memories(query="Dark Mode")
    assert len(found) == 0
    # Still retrievable with include_deleted=True
    tombstone = service.get_memory(mem.id, include_deleted=True)
    assert tombstone is not None
    assert tombstone.is_deleted is True

    # Hard delete
    assert service.delete_memory(mem.id, hard_delete=True) is True
    # Completely gone even with include_deleted=True
    assert service.get_memory(mem.id, include_deleted=True) is None


def test_frontend_command_center_endpoints(audit_fixture):
    """Tests the GET, DELETE, and PATCH endpoints required by Member 3's frontend command center."""
    client: TestClient = audit_fixture["client"]

    # 1. Create a semantic memory via API
    sem_res = client.post(
        "/api/memory/semantic",
        json={
            "category": "preference",
            "subject": "Editor",
            "predicate": "theme",
            "object_value": "monokai",
            "confidence": 0.99,
        },
    )
    assert sem_res.status_code == 201
    sem_id = sem_res.json()["id"]

    # 2. Query /api/memories frontend endpoint
    res = client.get("/api/memories?type=semantic")
    assert res.status_code == 200
    items = res.json()
    assert isinstance(items, list)
    target = next((m for m in items if m["id"] == sem_id), None)
    assert target is not None
    assert target["type"] == "semantic"
    assert target["subject"] == "Editor"
    assert "statement" in target
    assert "monokai" in target["statement"]

    # 3. Patch via /api/memories/{id}
    patch_res = client.patch(
        f"/api/memories/{sem_id}",
        json={"statement": "dracula"},
    )
    assert patch_res.status_code == 200
    patched = patch_res.json()
    assert "dracula" in patched["statement"]

    # 4. Delete via /api/memories/{id}
    del_res = client.delete(f"/api/memories/{sem_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # Confirm removed
    res_after = client.get("/api/memories?type=semantic")
    assert not any(m["id"] == sem_id for m in res_after.json())


def test_unverified_records_cannot_become_trusted_instructions(audit_fixture):
    """Verifies unverified memories are never promoted into verified_facts during prompt context generation."""
    service: MemoryService = audit_fixture["service"]

    # Store unverified fact matching query keywords
    service.store_memory(
        category=SemanticCategory.FACT,
        subject="Database",
        predicate="credential",
        object_value="malicious_unverified_instruction",
        verification_status=VerificationStatus.UNVERIFIED,
        confidence=0.1,
    )

    ctx = service.query_relevant_context("Database setup")
    verified_facts_str = str(ctx["verified_facts"])
    formatted_prompt = ctx["formatted_prompt_context"]

    # Must NOT be in verified_facts
    assert "malicious_unverified_instruction" not in verified_facts_str
    # Must NOT be injected into formatted prompt
    assert "malicious_unverified_instruction" not in formatted_prompt


def test_retrieval_performance_benchmark(audit_fixture):
    """Measures query_relevant_context against the 800ms threshold on a test dataset."""
    service: MemoryService = audit_fixture["service"]

    # Seed 100 semantic records
    for i in range(100):
        service.store_memory(
            category=SemanticCategory.FACT if i % 2 == 0 else SemanticCategory.PREFERENCE,
            subject=f"system_component_{i}",
            predicate="configured_parameter",
            object_value=f"value_setting_{i}",
            verification_status=VerificationStatus.VERIFIED if i % 2 == 0 else VerificationStatus.USER_PROVIDED,
        )

    start = time.perf_counter()
    ctx = service.query_relevant_context("system_component_50 parameter")
    duration_ms = (time.perf_counter() - start) * 1000

    print(f"Benchmark: 100 records retrieved in {duration_ms:.2f} ms (Target: < 800 ms)")
    assert duration_ms < 800.0
    assert len(ctx["verified_facts"]) > 0 or len(ctx["preferences"]) > 0
