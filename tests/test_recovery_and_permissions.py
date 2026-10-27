"""
Tests for Task Recovery, Idempotency Guard, and Default-Deny Permissions.
Validates reboot recovery without duplicate side-effect execution and human-in-the-loop gates.
"""

import os
import tempfile
import pytest
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager
from app.memory.models import (
    PermissionCheckRequest,
    RiskLevel,
    TaskCheckpoint,
    TaskStatus,
)
from app.memory.permissions import DefaultDenyAuthorizationAdapter, PermissionGateway
from app.memory.recovery import TaskRecoveryManager, compute_action_hash


@pytest.fixture
def recovery_env():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "recovery_test.db")
        crypto = EncryptionService(TestKeyProvider())
        db = DatabaseManager(db_path)
        recovery_mgr = TaskRecoveryManager(db, crypto)
        perm_gateway = PermissionGateway(db)
        yield {
            "tmpdir": tmpdir,
            "db_path": db_path,
            "crypto": crypto,
            "db": db,
            "recovery_mgr": recovery_mgr,
            "perm_gateway": perm_gateway,
        }


def test_task_checkpoint_recovery_across_restart(recovery_env):
    """Validates that incomplete tasks are recovered across process restarts."""
    recovery_mgr: TaskRecoveryManager = recovery_env["recovery_mgr"]
    db_path = recovery_env["db_path"]
    key_bytes = recovery_env["crypto"].key_provider.get_key()

    # Create task with 3 steps
    checkpoint = TaskCheckpoint(
        task_id="task-scrape-101",
        workflow_id="wf-data-pipeline",
        status=TaskStatus.RUNNING,
        current_step="fetch_raw_html",
        completed_step_ids=[],
        pending_step_ids=["fetch_raw_html", "extract_entities", "index_data"],
        state_data={"target_url": "https://example.com/docs", "records_found": 0},
    )
    recovery_mgr.save_task_checkpoint(checkpoint)

    # Step 1 executes
    recovery_mgr.mark_step_completed(
        task_id="task-scrape-101",
        step_id="fetch_raw_html",
        next_step="extract_entities",
        state_updates={"records_found": 42},
    )

    # Record execution event with idempotency hash
    recovery_mgr.record_execution_event(
        task_id="task-scrape-101",
        step_id="fetch_raw_html",
        action="http_get",
        status="SUCCESS",
        input_params={"url": "https://example.com/docs"},
        output_details={"status_code": 200, "bytes": 1024},
    )

    # Simulate CRASH / PROCESS REBOOT
    recovery_env["db"].checkpoint_wal()
    del recovery_mgr
    del recovery_env["db"]

    # Re-initialize subsystem from disk
    new_crypto = EncryptionService(TestKeyProvider(key_bytes))
    new_db = DatabaseManager(db_path)
    new_recovery_mgr = TaskRecoveryManager(new_db, new_crypto)

    # 1. Recover incomplete tasks
    incomplete = new_recovery_mgr.load_incomplete_tasks()
    assert len(incomplete) == 1
    recovered_task = incomplete[0]
    assert recovered_task.task_id == "task-scrape-101"
    assert recovered_task.current_step == "extract_entities"
    assert "fetch_raw_html" in recovered_task.completed_step_ids
    assert recovered_task.state_data["records_found"] == 42

    # 2. Idempotency Guard verification:
    # fetch_raw_html MUST NOT be re-executed
    assert new_recovery_mgr.is_step_already_executed(
        task_id="task-scrape-101",
        step_id="fetch_raw_html",
    ) is True

    # Check via action hash
    action_hash = compute_action_hash("http_get", {"url": "https://example.com/docs"})
    assert new_recovery_mgr.is_step_already_executed(
        task_id="task-scrape-101",
        step_id="any_step",
        idempotency_hash=action_hash,
    ) is True

    # A step not yet executed must return False
    assert new_recovery_mgr.is_step_already_executed(
        task_id="task-scrape-101",
        step_id="extract_entities",
    ) is False


def test_ambiguous_side_effect_reconciliation_flag(recovery_env):
    """
    CRITICAL RULE:
    For ambiguous outcomes of external side effects, require reconciliation or human review.
    Never promise exactly-once execution of arbitrary external operations.
    """
    recovery_mgr: TaskRecoveryManager = recovery_env["recovery_mgr"]

    checkpoint = TaskCheckpoint(
        task_id="task-payment-505",
        workflow_id="wf-checkout",
        status=TaskStatus.RUNNING,
        current_step="dispatch_external_webhook",
        completed_step_ids=[],
        pending_step_ids=["dispatch_external_webhook"],
        state_data={"order_id": "ORD-999"},
    )
    recovery_mgr.save_task_checkpoint(checkpoint)

    # External webhook timed out with network socket drop (ambiguous state)
    flagged = recovery_mgr.flag_for_reconciliation(
        task_id="task-payment-505",
        reason="External webhook timed out after 30s. Gateway state unknown.",
    )

    assert flagged.status == TaskStatus.REQUIRES_RECONCILIATION
    assert "reconciliation_reason" in flagged.state_data

    # Verify task is returned in incomplete list for operator review
    incomplete = recovery_mgr.load_incomplete_tasks()
    assert any(t.task_id == "task-payment-505" for t in incomplete)


def test_default_deny_permission_behavior(recovery_env):
    """
    Validates default-deny policy:
    - High-risk tools (shell, file delete, network) are DENIED by default.
    - Model cannot grant itself permission.
    - Ephemeral human approval token unlocks execution once and is consumed.
    """
    gateway: PermissionGateway = recovery_env["perm_gateway"]
    adapter = DefaultDenyAuthorizationAdapter(gateway)

    # 1. Low risk action without approval required -> ALLOWED
    dec1 = adapter.check(PermissionCheckRequest(
        user_id="agent-01",
        action="read_local_file",
        resource="notes.txt",
        risk_level=RiskLevel.LOW,
    ))
    assert dec1.allowed is True
    assert dec1.approval_required is False

    # 2. High risk action (shell_execute) without approval token -> DENIED
    dec2 = adapter.check(PermissionCheckRequest(
        user_id="agent-01",
        action="shell_execute",
        resource="rm -rf /data",
        risk_level=RiskLevel.HIGH,
    ))
    assert dec2.allowed is False
    assert dec2.approval_required is True
    assert dec2.approval_id is not None  # Approval ID issued for human review

    # 3. Model invents fake approval token -> DENIED
    dec3 = adapter.check(PermissionCheckRequest(
        user_id="agent-01",
        action="shell_execute",
        resource="rm -rf /data",
        risk_level=RiskLevel.HIGH,
        approval_token="fake-model-generated-token-xyz",
    ))
    assert dec3.allowed is False
    assert "invalid" in dec3.reason.lower()

    # 4. Legitimate human grants approval token via UI/CLI
    token = gateway.grant_approval(action="shell_execute", resource="rm -rf /data", ttl_seconds=60)
    assert token.startswith("tok-")

    # 5. Execute with valid human approval token -> ALLOWED
    dec4 = adapter.check(PermissionCheckRequest(
        user_id="agent-01",
        action="shell_execute",
        resource="rm -rf /data",
        risk_level=RiskLevel.HIGH,
        approval_token=token,
    ))
    assert dec4.allowed is True
    assert dec4.approval_required is False

    # 6. Re-using single-use approval token -> DENIED (consumed)
    dec5 = adapter.check(PermissionCheckRequest(
        user_id="agent-01",
        action="shell_execute",
        resource="rm -rf /data",
        risk_level=RiskLevel.HIGH,
        approval_token=token,
    ))
    assert dec5.allowed is False
    assert "invalid" in dec5.reason.lower()
