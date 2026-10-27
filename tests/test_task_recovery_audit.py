"""
Task Recovery Audit & Verification Suite (Member 2).
Exhaustively tests:
1. Saving and retrieving checkpoints.
2. Loading incomplete checkpoints.
3. Crash / reboot recovery across fresh database and manager instances with persistent SQLite storage.
4. Completed steps remaining completed after recovery.
5. Pending steps remaining pending until explicitly completed.
6. Detecting already-completed steps (idempotency guard).
7. Task-scoped idempotency hash isolation (preventing cross-task false positives).
8. Failsafe handling of corrupted ciphertext, missing keys, and wrong keys without silent data loss.
9. Ambiguous external side effect reconciliation flagging and operator resolution.
10. Excluding COMPLETED and FAILED tasks from incomplete task listings.
11. HTTP API endpoints and status codes (GET/POST checkpoints, recover, reconcile).
"""

import json
import os
import sqlite3
import tempfile
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
from app.memory.models import TaskCheckpoint, TaskStatus
from app.memory.recovery import TaskRecoveryManager, compute_action_hash


@pytest.fixture
def recovery_harness():
    """Provides a temporary, isolated SQLite database and fresh TaskRecoveryManager."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "recovery_audit.db")
        key_provider = TestKeyProvider()
        key_bytes = key_provider.get_key()
        crypto = EncryptionService(key_provider)
        db = DatabaseManager(db_path)
        mgr = TaskRecoveryManager(db, crypto)
        yield {
            "tmpdir": tmpdir,
            "db_path": db_path,
            "key_bytes": key_bytes,
            "crypto": crypto,
            "db": db,
            "mgr": mgr,
        }


@pytest.fixture
def api_client():
    """Initializes TestClient with an isolated database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "api_audit.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        with TestClient(app) as client:
            yield client, SubsystemContainer.recovery_manager


# -----------------------------------------------------------------------------
# 1. Saving and retrieving checkpoints
# -----------------------------------------------------------------------------
def test_01_save_and_retrieve_checkpoint(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]

    chk = TaskCheckpoint(
        task_id="task-audit-001",
        workflow_id="wf-audit",
        status=TaskStatus.RUNNING,
        current_step="init_pipeline",
        completed_step_ids=[],
        pending_step_ids=["init_pipeline", "process_data", "finalize"],
        approval_references=["appr-tok-123"],
        retry_count=1,
        state_data={"batch_size": 256, "auth_header": "Bearer secret-token"},
    )
    mgr.save_task_checkpoint(chk)

    retrieved = mgr.get_task_checkpoint("task-audit-001")
    assert retrieved is not None
    assert retrieved.task_id == "task-audit-001"
    assert retrieved.workflow_id == "wf-audit"
    assert retrieved.status == TaskStatus.RUNNING
    assert retrieved.current_step == "init_pipeline"
    assert retrieved.pending_step_ids == ["init_pipeline", "process_data", "finalize"]
    assert retrieved.approval_references == ["appr-tok-123"]
    assert retrieved.retry_count == 1
    assert retrieved.state_data["batch_size"] == 256
    assert retrieved.state_data["auth_header"] == "Bearer secret-token"


# -----------------------------------------------------------------------------
# 2. Loading incomplete checkpoints
# -----------------------------------------------------------------------------
def test_02_load_incomplete_checkpoints(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]

    statuses = [
        ("task-p", TaskStatus.PENDING),
        ("task-r", TaskStatus.RUNNING),
        ("task-pa", TaskStatus.PAUSED),
        ("task-rec", TaskStatus.REQUIRES_RECONCILIATION),
        ("task-c", TaskStatus.COMPLETED),
        ("task-f", TaskStatus.FAILED),
    ]

    for tid, st in statuses:
        chk = TaskCheckpoint(
            task_id=tid,
            workflow_id="wf-test",
            status=st,
            current_step="step_x",
            state_data={"status_label": st.value},
        )
        mgr.save_task_checkpoint(chk)

    incomplete = mgr.load_incomplete_tasks()
    incomplete_ids = {t.task_id for t in incomplete}

    assert "task-p" in incomplete_ids
    assert "task-r" in incomplete_ids
    assert "task-pa" in incomplete_ids
    assert "task-rec" in incomplete_ids
    assert "task-c" not in incomplete_ids
    assert "task-f" not in incomplete_ids
    assert len(incomplete) == 4


# -----------------------------------------------------------------------------
# 3. Crash recovery across process restart (fresh DB manager and recovery manager)
# -----------------------------------------------------------------------------
def test_03_reboot_recovery_persistence(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]
    db_path = recovery_harness["db_path"]
    key_bytes = recovery_harness["key_bytes"]

    chk = TaskCheckpoint(
        task_id="task-crash-test-999",
        workflow_id="wf-deploy",
        status=TaskStatus.RUNNING,
        current_step="compile_assets",
        completed_step_ids=[],
        pending_step_ids=["compile_assets", "run_smoke_tests", "upload_artifacts"],
        state_data={"env": "production", "artifact_id": "art-4567"},
    )
    mgr.save_task_checkpoint(chk)

    # Step 1 completes
    mgr.mark_step_completed(
        task_id="task-crash-test-999",
        step_id="compile_assets",
        state_updates={"build_hash": "sha256-abcdef"},
    )

    # Simulate CRASH / PROCESS SHUTDOWN
    recovery_harness["db"].checkpoint_wal()
    del mgr
    del recovery_harness["db"]

    # Reopen fresh application instances from disk
    new_crypto = EncryptionService(TestKeyProvider(key_bytes))
    new_db = DatabaseManager(db_path)
    new_mgr = TaskRecoveryManager(new_db, new_crypto)

    # Recover task
    recovered = new_mgr.recover_task("task-crash-test-999")
    assert recovered.task_id == "task-crash-test-999"
    assert recovered.workflow_id == "wf-deploy"
    assert recovered.status == TaskStatus.RUNNING
    # Current step correctly advanced to next pending step
    assert recovered.current_step == "run_smoke_tests"
    assert recovered.completed_step_ids == ["compile_assets"]
    assert recovered.pending_step_ids == ["run_smoke_tests", "upload_artifacts"]
    assert recovered.state_data["env"] == "production"
    assert recovered.state_data["artifact_id"] == "art-4567"
    assert recovered.state_data["build_hash"] == "sha256-abcdef"


# -----------------------------------------------------------------------------
# 4 & 5. Confirming completed steps remain completed and pending remain pending
# -----------------------------------------------------------------------------
def test_04_05_step_progression_integrity(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]

    chk = TaskCheckpoint(
        task_id="task-step-integrity",
        workflow_id="wf-steps",
        status=TaskStatus.RUNNING,
        current_step="step_1",
        completed_step_ids=[],
        pending_step_ids=["step_1", "step_2", "step_3"],
        state_data={"val": 1},
    )
    mgr.save_task_checkpoint(chk)

    # Mark step 1 completed
    mgr.mark_step_completed("task-step-integrity", "step_1")
    t1 = mgr.get_task_checkpoint("task-step-integrity")
    assert t1.completed_step_ids == ["step_1"]
    assert t1.pending_step_ids == ["step_2", "step_3"]
    assert t1.current_step == "step_2"

    # Mark step 2 completed
    mgr.mark_step_completed("task-step-integrity", "step_2")
    t2 = mgr.get_task_checkpoint("task-step-integrity")
    assert t2.completed_step_ids == ["step_1", "step_2"]
    assert t2.pending_step_ids == ["step_3"]
    assert t2.current_step == "step_3"

    # Mark step 3 completed -> task completes
    mgr.mark_step_completed("task-step-integrity", "step_3")
    t3 = mgr.get_task_checkpoint("task-step-integrity")
    assert t3.completed_step_ids == ["step_1", "step_2", "step_3"]
    assert t3.pending_step_ids == []
    assert t3.status == TaskStatus.COMPLETED


# -----------------------------------------------------------------------------
# 6. Detecting an already-completed step
# -----------------------------------------------------------------------------
def test_06_detect_already_completed_step(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]

    chk = TaskCheckpoint(
        task_id="task-detect-01",
        workflow_id="wf-detect",
        status=TaskStatus.RUNNING,
        current_step="step_a",
        completed_step_ids=["step_a"],
        pending_step_ids=["step_b"],
        state_data={},
    )
    mgr.save_task_checkpoint(chk)

    assert mgr.is_step_already_executed("task-detect-01", "step_a") is True
    assert mgr.is_step_already_executed("task-detect-01", "step_b") is False


# -----------------------------------------------------------------------------
# 7. Task-scoped idempotency hash isolation
# -----------------------------------------------------------------------------
def test_07_task_scoped_idempotency_hash_isolation(recovery_harness):
    """
    CRITICAL RELIABILITY REQUIREMENT:
    Duplicate action hashes across different tasks must NOT create false positives.
    Task A's execution must not fool Task B into thinking Task B already executed.
    """
    mgr: TaskRecoveryManager = recovery_harness["mgr"]

    action = "shell_execute"
    params = {"command": "npm run build", "cwd": "/workspace"}
    action_hash = compute_action_hash(action, params)

    # Task A executes action
    chk_a = TaskCheckpoint(
        task_id="task-A",
        workflow_id="wf-multi",
        status=TaskStatus.RUNNING,
        current_step="build_step",
        completed_step_ids=[],
        pending_step_ids=["build_step"],
    )
    mgr.save_task_checkpoint(chk_a)

    mgr.record_execution_event(
        task_id="task-A",
        step_id="build_step",
        action=action,
        status="SUCCESS",
        input_params=params,
        output_details={"exit_code": 0},
    )

    # Task A idempotency check must return True
    assert mgr.is_step_already_executed("task-A", "build_step", idempotency_hash=action_hash) is True

    # Task B has identical step & action params, but has NOT run yet
    chk_b = TaskCheckpoint(
        task_id="task-B",
        workflow_id="wf-multi",
        status=TaskStatus.RUNNING,
        current_step="build_step",
        completed_step_ids=[],
        pending_step_ids=["build_step"],
    )
    mgr.save_task_checkpoint(chk_b)

    # Task B MUST return False (Task B has NOT executed yet!)
    assert mgr.is_step_already_executed("task-B", "build_step", idempotency_hash=action_hash) is False


# -----------------------------------------------------------------------------
# 8. Corrupted ciphertext and wrong/missing key safety
# -----------------------------------------------------------------------------
def test_08_corrupted_ciphertext_and_wrong_key_safety(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]
    db_path = recovery_harness["db_path"]

    chk = TaskCheckpoint(
        task_id="task-crypto-fail",
        workflow_id="wf-crypto",
        status=TaskStatus.RUNNING,
        current_step="step_1",
        state_data={"top_secret": "confidential_payload_xyz"},
    )
    mgr.save_task_checkpoint(chk)

    # 1. Tamper directly with the ciphertext in SQLite
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE task_checkpoints SET encrypted_state = 'CORRUPTED_CIPHERTEXT' WHERE task_id = 'task-crypto-fail';")
    conn.commit()
    conn.close()

    # Re-reading corrupted state must raise DecryptionError (never silently return empty dict)
    with pytest.raises(DecryptionError):
        mgr.get_task_checkpoint("task-crypto-fail")

    with pytest.raises(DecryptionError):
        mgr.load_incomplete_tasks(raise_on_error=True)

    # 2. Reading with wrong key must raise DecryptionError
    wrong_crypto = EncryptionService(TestKeyProvider())
    wrong_mgr = TaskRecoveryManager(DatabaseManager(db_path), wrong_crypto)
    with pytest.raises(DecryptionError):
        wrong_mgr.get_task_checkpoint("task-crypto-fail")

    # 3. Missing key provider must raise MissingKeyError
    missing_key_crypto = EncryptionService(EnvKeyProvider(env_var="UNSET_KEY_VAR_12345"))
    missing_key_mgr = TaskRecoveryManager(DatabaseManager(db_path), missing_key_crypto)
    with pytest.raises(MissingKeyError):
        missing_key_mgr.get_task_checkpoint("task-crypto-fail")


# -----------------------------------------------------------------------------
# 9. Ambiguous external side effect reconciliation flow
# -----------------------------------------------------------------------------
def test_09_ambiguous_side_effect_reconciliation_flow(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]

    chk = TaskCheckpoint(
        task_id="task-ambig-01",
        workflow_id="wf-payment",
        status=TaskStatus.RUNNING,
        current_step="charge_card",
        completed_step_ids=[],
        pending_step_ids=["charge_card", "send_receipt"],
        state_data={"amount": 100},
    )
    mgr.save_task_checkpoint(chk)

    # Record ambiguous external call
    action = "stripe_charge"
    params = {"amount": 100, "currency": "usd"}
    action_hash = compute_action_hash(action, params)

    mgr.record_ambiguous_event(
        task_id="task-ambig-01",
        step_id="charge_card",
        action=action,
        input_params=params,
        reason="HTTP connection timed out after 30s. Remote gateway state unknown.",
    )

    # Verify task is flagged for reconciliation
    flagged = mgr.get_task_checkpoint("task-ambig-01")
    assert flagged.status == TaskStatus.REQUIRES_RECONCILIATION
    assert "reconciliation_reason" in flagged.state_data

    # is_step_already_executed must block auto re-execution
    assert mgr.is_step_already_executed("task-ambig-01", "charge_card", idempotency_hash=action_hash) is True
    assert mgr.is_step_ambiguous("task-ambig-01", "charge_card", idempotency_hash=action_hash) is True

    # mark_step_completed must fail until reconciliation is resolved
    with pytest.raises(ValueError) as exc:
        mgr.mark_step_completed("task-ambig-01", "charge_card")
    assert "reconciliation" in str(exc.value).lower()

    # Operator resolves reconciliation by resuming
    resolved = mgr.resolve_reconciliation(
        task_id="task-ambig-01",
        resolution="resume",
        notes="Operator confirmed transaction failed on Stripe dashboard. Safe to retry.",
        next_step="charge_card",
    )
    assert resolved.status == TaskStatus.RUNNING
    assert resolved.state_data["reconciliation_notes"] == "Operator confirmed transaction failed on Stripe dashboard. Safe to retry."


# -----------------------------------------------------------------------------
# 10. Completed tasks excluded from incomplete listings
# -----------------------------------------------------------------------------
def test_10_completed_tasks_excluded(recovery_harness):
    mgr: TaskRecoveryManager = recovery_harness["mgr"]

    chk = TaskCheckpoint(
        task_id="task-done-1",
        workflow_id="wf-done",
        status=TaskStatus.RUNNING,
        current_step="finish",
        completed_step_ids=[],
        pending_step_ids=["finish"],
    )
    mgr.save_task_checkpoint(chk)

    # Complete it
    mgr.mark_step_completed("task-done-1", "finish")
    done = mgr.get_task_checkpoint("task-done-1")
    assert done.status == TaskStatus.COMPLETED

    incomplete = mgr.load_incomplete_tasks()
    assert not any(t.task_id == "task-done-1" for t in incomplete)


# -----------------------------------------------------------------------------
# 11. API endpoints & HTTP status codes
# -----------------------------------------------------------------------------
def test_11_api_recovery_endpoints(api_client):
    client, mgr = api_client

    # 1. POST /api/tasks/checkpoints
    payload = {
        "task_id": "task-api-endpoint-001",
        "workflow_id": "wf-endpoint",
        "status": "RUNNING",
        "current_step": "step_one",
        "completed_step_ids": [],
        "pending_step_ids": ["step_one", "step_two"],
        "approval_references": [],
        "retry_count": 0,
        "state_data": {"test_metric": 42},
    }
    r_save = client.post("/api/tasks/checkpoints", json=payload)
    assert r_save.status_code == 200
    assert r_save.json()["status"] == "saved"

    # 2. GET /api/tasks/checkpoints/{task_id}
    r_get = client.get("/api/tasks/checkpoints/task-api-endpoint-001")
    assert r_get.status_code == 200
    rec = r_get.json()
    assert rec["task_id"] == "task-api-endpoint-001"
    assert rec["state_data"]["test_metric"] == 42

    # 3. GET non-existent -> 404
    r_404 = client.get("/api/tasks/checkpoints/non-existent-task-id")
    assert r_404.status_code == 404

    # 4. POST /api/tasks/checkpoints/{task_id}/recover
    r_rec = client.post("/api/tasks/checkpoints/task-api-endpoint-001/recover")
    assert r_rec.status_code == 200
    assert r_rec.json()["task_id"] == "task-api-endpoint-001"

    # 5. Flag for reconciliation & POST /api/tasks/checkpoints/{task_id}/reconcile
    mgr.flag_for_reconciliation("task-api-endpoint-001", reason="Ambiguous timeout")

    r_reconcile = client.post(
        "/api/tasks/checkpoints/task-api-endpoint-001/reconcile",
        json={"decision": "resume", "notes": "Approved by operator"},
    )
    assert r_reconcile.status_code == 200
    assert r_reconcile.json()["status"] == "RUNNING"
    assert r_reconcile.json()["state_data"]["reconciliation_notes"] == "Approved by operator"

    # 6. Reconcile with invalid decision -> 400
    r_bad = client.post(
        "/api/tasks/checkpoints/task-api-endpoint-001/reconcile",
        json={"decision": "invalid_action"},
    )
    assert r_bad.status_code == 400


# -----------------------------------------------------------------------------
# 12. compute_action_hash determinism, parameter sensitivity & key invariance
# -----------------------------------------------------------------------------
def test_12_compute_action_hash_determinism_and_sensitivity():
    # Identical parameters with different key order must produce identical hashes
    h1 = compute_action_hash("send_email", {"to": "alice@example.com", "subject": "Hello", "priority": 1})
    h2 = compute_action_hash("send_email", {"priority": 1, "to": "alice@example.com", "subject": "Hello"})
    assert h1 == h2

    # Different parameters must produce different hashes
    h3 = compute_action_hash("send_email", {"to": "bob@example.com", "subject": "Hello", "priority": 1})
    assert h1 != h3

    # Different action with identical parameters must produce different hashes
    h4 = compute_action_hash("queue_email", {"to": "alice@example.com", "subject": "Hello", "priority": 1})
    assert h1 != h4


# -----------------------------------------------------------------------------
# 13. Two-phase execution & crash window detection across restart
# -----------------------------------------------------------------------------
def test_13_two_phase_crash_window_detection_across_restart(recovery_harness):
    """
    CRITICAL RELIABILITY REQUIREMENT:
    Simulates a crash occurring in the exact window where an external side effect
    is in-flight before success was recorded. Recovery MUST flag REQUIRES_RECONCILIATION.
    """
    mgr: TaskRecoveryManager = recovery_harness["mgr"]
    db_path = recovery_harness["db_path"]
    key_bytes = recovery_harness["key_bytes"]

    chk = TaskCheckpoint(
        task_id="task-crash-window-01",
        workflow_id="wf-card-charge",
        status=TaskStatus.RUNNING,
        current_step="charge_payment",
        completed_step_ids=[],
        pending_step_ids=["charge_payment", "generate_invoice"],
        state_data={"user": "Ayush", "amount": 250},
    )
    mgr.save_task_checkpoint(chk)

    # Phase 1: Begin step execution (records PENDING event)
    mgr.begin_step_execution(
        task_id="task-crash-window-01",
        step_id="charge_payment",
        action="external_bank_charge",
        input_params={"amount": 250, "account": "ACC-789"},
    )

    # SIMULATE SUDDEN POWER LOSS / CRASH (Phase 2 complete_step_execution never runs)
    recovery_harness["db"].checkpoint_wal()
    del mgr
    del recovery_harness["db"]

    # Reopen fresh application instances from raw disk
    new_crypto = EncryptionService(TestKeyProvider(key_bytes))
    new_db = DatabaseManager(db_path)
    new_mgr = TaskRecoveryManager(new_db, new_crypto)

    # Recover task across reboot
    recovered = new_mgr.recover_task("task-crash-window-01")

    # MUST be flagged as REQUIRES_RECONCILIATION because in-flight event was pending!
    assert recovered.status == TaskStatus.REQUIRES_RECONCILIATION
    assert "crash window" in recovered.state_data["reconciliation_reason"].lower()

    # Step must NOT be allowed to execute again automatically
    assert new_mgr.is_step_already_executed("task-crash-window-01", "charge_payment") is True

    # Re-running begin_step_execution must raise idempotency violation
    with pytest.raises(RuntimeError) as exc:
        new_mgr.begin_step_execution(
            task_id="task-crash-window-01",
            step_id="charge_payment",
            action="external_bank_charge",
            input_params={"amount": 250, "account": "ACC-789"},
        )
    assert "reconciliation" in str(exc.value).lower()


# -----------------------------------------------------------------------------
# 14. Execution events encrypted at rest on raw disk
# -----------------------------------------------------------------------------
def test_14_execution_events_encrypted_at_rest_raw_disk_verification(recovery_harness):
    """
    CRITICAL SECURITY REQUIREMENT:
    Execution event output details containing sensitive API credentials or tokens
    must remain encrypted at rest and never leak in plaintext to SQLite disk bytes.
    """
    mgr: TaskRecoveryManager = recovery_harness["mgr"]
    db_path = recovery_harness["db_path"]
    key_bytes = recovery_harness["key_bytes"]

    sensitive_secret = "LIVE_OAUTH_REFRESH_TOKEN_987654321_SUPER_SECRET"

    chk = TaskCheckpoint(
        task_id="task-secret-audit",
        workflow_id="wf-auth",
        status=TaskStatus.RUNNING,
        current_step="refresh_tokens",
        completed_step_ids=[],
        pending_step_ids=["refresh_tokens"],
    )
    mgr.save_task_checkpoint(chk)

    mgr.record_execution_event(
        task_id="task-secret-audit",
        step_id="refresh_tokens",
        action="oauth_token_exchange",
        status="SUCCESS",
        input_params={"grant_type": "refresh_token"},
        output_details={"refresh_token": sensitive_secret, "expires_in": 3600},
    )

    # Flush WAL and close
    recovery_harness["db"].checkpoint_wal()
    del mgr
    del recovery_harness["db"]

    # Read raw disk bytes of .db file
    with open(db_path, "rb") as f:
        raw_bytes = f.read()

    # Raw disk bytes MUST NOT contain the secret in plaintext
    assert sensitive_secret.encode("utf-8") not in raw_bytes

    # Reopen with correct key and verify retrieval and decryption
    new_crypto = EncryptionService(TestKeyProvider(key_bytes))
    new_db = DatabaseManager(db_path)
    new_mgr = TaskRecoveryManager(new_db, new_crypto)

    events = new_mgr.list_execution_events("task-secret-audit")
    assert len(events) == 1
    assert events[0].details["refresh_token"] == sensitive_secret
