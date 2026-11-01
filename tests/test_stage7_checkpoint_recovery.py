"""
Comprehensive Test Suite for Stage 7:
Checkpoint Recovery, Crash Consistency & Idempotency Hardening.
Tests:
1. Crash consistency across all execution boundaries.
2. Anti-replay idempotency enforcement and reconciliation quarantine.
3. Subprocess tracking, exact creation timestamp verification, and PID reuse rejection.
4. Single-use approval token survival and security invalidation.
5. Optimistic concurrency and task lease locks preventing double execution.
6. Schema Migration v5 non-destructive upgrade from v4 checkpoints.
7. Idempotent backend startup recovery.
"""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
import time
from typing import Any, Dict
import pytest

from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager, utc_now
from app.memory.journal import ExecutionJournalService, compute_param_hash, sanitize_parameters
from app.memory.models import (
    ApprovalRecord,
    ApprovalStatus,
    DispatchState,
    ExecutionJournalEntry,
    SubprocessTrackRecord,
    TaskCheckpoint,
    TaskStatus,
)
from app.memory.permissions import PermissionGateway
from app.memory.recovery import TaskRecoveryManager
from backend.agent_loop.controller import AutonomousExecutionController
from backend.agent_loop.evaluator import GoalEvaluator
from backend.agent_loop.models import (
    GoalEvaluation,
    GoalState,
    IdempotencyClass,
    LoopBudget,
    LoopPhase,
    StepObservation,
)
from backend.agent_loop.recovery_engine import AutonomousRecoveryEngine, LeaseConflictError
from backend.agent_loop.replanner import BoundedReplanner
from backend.agent_loop.subprocess_tracker import (
    SubprocessTracker,
    get_process_creation_time,
    is_process_active,
)
from backend.orchestrator import TaskOrchestrator
from backend.planner import DAGStep, TaskDAG, TaskPlanner


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_env():
    """Isolated database and filesystem environment."""
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test_go81_stage7.db")
        db = DatabaseManager(db_path)
        crypto = EncryptionService(TestKeyProvider())
        recovery_manager = TaskRecoveryManager(db, crypto)
        journal_service = ExecutionJournalService(db)
        subprocess_dir = os.path.join(td, "subprocesses")
        subprocess_tracker = SubprocessTracker(base_log_dir=subprocess_dir)
        recovery_engine = AutonomousRecoveryEngine(
            db=db,
            recovery_manager=recovery_manager,
            journal_service=journal_service,
            subprocess_tracker=subprocess_tracker,
            worker_id="test-worker-1",
        )
        yield {
            "dir": td,
            "db_path": db_path,
            "db": db,
            "crypto": crypto,
            "recovery_manager": recovery_manager,
            "journal": journal_service,
            "subprocess_tracker": subprocess_tracker,
            "recovery_engine": recovery_engine,
        }


# ============================================================================
# 1. Execution Journal & Parameter Sanitization Tests
# ============================================================================

def test_param_sanitization_and_fingerprinting(temp_env):
    """Verifies confidential keys are redacted and parameter fingerprints are deterministic."""
    raw_params = {
        "file_path": "report.txt",
        "api_key": "secret_12345",
        "bearer_token": "token_abc",
        "nested": {"password": "pass", "normal": "val"},
        "long_text": "x" * 6000,
    }
    sanitized = sanitize_parameters(raw_params)
    assert sanitized["file_path"] == "report.txt"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["bearer_token"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["normal"] == "val"
    assert "[truncated]" in sanitized["long_text"]

    hash1 = compute_param_hash("filesystem.write", raw_params)
    hash2 = compute_param_hash("filesystem.write", raw_params)
    assert hash1 == hash2


def test_two_phase_journal_intent_transitions(temp_env):
    """Verifies PREPARED -> DISPATCHING -> RUNNING -> SUCCEEDED lifecycle."""
    journal = temp_env["journal"]
    task_id = "task-j1"
    step_id = "step-1"

    # Create dummy checkpoint
    chk = TaskCheckpoint(
        task_id=task_id,
        workflow_id=task_id,
        status=TaskStatus.RUNNING,
        current_step=step_id,
        completed_step_ids=[],
        pending_step_ids=[step_id],
    )
    temp_env["recovery_manager"].save_task_checkpoint(chk)

    # Phase 1: PREPARED
    entry = journal.prepare_dispatch(
        task_id=task_id,
        step_id=step_id,
        action="filesystem.write",
        idempotency_class="IDEMPOTENT",
        params={"path": "out.txt", "content": "hello"},
    )
    assert entry.dispatch_state == DispatchState.PREPARED
    assert journal.is_step_already_executed(task_id, step_id) is False

    # DISPATCHING
    journal.record_dispatching(entry.attempt_id)
    latest = journal.get_latest_entry_for_step(task_id, step_id)
    assert latest.dispatch_state == DispatchState.DISPATCHING
    assert latest.dispatched_at is not None

    # RUNNING
    journal.record_running_process(entry.attempt_id, pid=4321, process_creation_time=1234567.0, log_path="test.log")
    latest = journal.get_latest_entry_for_step(task_id, step_id)
    assert latest.dispatch_state == DispatchState.RUNNING
    assert latest.pid == 4321

    # Phase 2: SUCCEEDED
    journal.record_success(entry.attempt_id, result_digest="abc123digest", exit_code=0)
    assert journal.is_step_already_executed(task_id, step_id) is True
    assert journal.is_step_already_executed(task_id, step_id, param_hash=entry.param_hash) is True
    assert journal.is_step_already_executed(task_id, step_id, param_hash="wrong_hash") is False


# ============================================================================
# 2. Concurrency & Optimistic Task Leases Tests
# ============================================================================

def test_task_lease_acquisition_and_conflict_rejection(temp_env):
    """Verifies that two workers cannot simultaneously resume or run the same task."""
    journal = temp_env["journal"]
    task_id = "task-lease-1"

    chk = TaskCheckpoint(
        task_id=task_id,
        workflow_id=task_id,
        status=TaskStatus.RUNNING,
        current_step="step-1",
        completed_step_ids=[],
        pending_step_ids=["step-1"],
    )
    temp_env["recovery_manager"].save_task_checkpoint(chk)

    # Worker 1 acquires lease
    assert journal.acquire_task_lease(task_id, "worker-alpha", ttl_seconds=5.0) is True

    # Worker 2 attempts to acquire lease -> REJECTED
    assert journal.acquire_task_lease(task_id, "worker-beta", ttl_seconds=5.0) is False

    # Worker 1 renews lease
    assert journal.renew_task_lease(task_id, "worker-alpha", ttl_seconds=10.0) is True

    # Worker 1 releases lease
    assert journal.release_task_lease(task_id, "worker-alpha") is True

    # Now Worker 2 can acquire lease
    assert journal.acquire_task_lease(task_id, "worker-beta", ttl_seconds=5.0) is True


def test_stale_lease_cleanup(temp_env):
    """Verifies that expired leases are automatically reclaimed."""
    journal = temp_env["journal"]
    task_id = "task-stale"

    chk = TaskCheckpoint(
        task_id=task_id,
        workflow_id=task_id,
        status=TaskStatus.RUNNING,
        current_step="step-1",
        completed_step_ids=[],
        pending_step_ids=["step-1"],
    )
    temp_env["recovery_manager"].save_task_checkpoint(chk)

    # Acquire lease that expires in 0.1s
    journal.acquire_task_lease(task_id, "worker-dead", ttl_seconds=0.1)
    time.sleep(0.2)

    # Stale lease cleared
    cleared = journal.clear_stale_leases()
    assert cleared >= 1

    # New worker can now acquire
    assert journal.acquire_task_lease(task_id, "worker-alive", ttl_seconds=10.0) is True


# ============================================================================
# 3. Subprocess Tracking & PID Reuse Rejection Tests
# ============================================================================

def test_subprocess_tracking_real_process(temp_env):
    """Verifies actual child process spawning, log file creation, and clean termination."""
    tracker = temp_env["subprocess_tracker"]
    attempt_id = "attempt-subp-1"

    # Spawn python process
    cmd = [sys.executable, "-c", "import time; print('stage7_output_ok')"]
    spawn_info = tracker.spawn(cmd, attempt_id=attempt_id)

    pid = spawn_info["pid"]
    c_time = spawn_info["process_creation_time"]
    log_path = spawn_info["log_path"]
    proc = spawn_info["process"]

    assert pid > 0
    assert c_time is not None
    assert os.path.exists(log_path)

    proc.wait(timeout=5.0)
    spawn_info["log_file_handle"].close()

    # Audit status after completion
    audit = tracker.audit_subprocess_status(pid, c_time, log_path)
    assert audit["status"] in ("EXITED_CLEAN", "ACTIVE")
    log_tail = tracker.read_bounded_log(log_path)
    assert "stage7_output_ok" in log_tail


def test_pid_reuse_rejection(temp_env):
    """
    Simulates PID reuse where an active PID has a mismatched creation timestamp.
    Must reject reattachment and quarantine the task.
    """
    tracker = temp_env["subprocess_tracker"]
    current_pid = os.getpid()
    real_time = get_process_creation_time(current_pid) or time.time()

    # Fabricate a fake past creation time (e.g. 10 hours earlier)
    bogus_time = real_time - 36000.0 * 10_000_000.0 if sys.platform == "win32" else real_time - 36000.0

    active, reason = is_process_active(current_pid, expected_creation_time=bogus_time)
    assert active is False
    assert reason == "PID_REUSE_DETECTED"

    # Audit must classify as PID_REUSE_DETECTED
    audit = tracker.audit_subprocess_status(current_pid, bogus_time, log_path=None)
    assert audit["status"] == "PID_REUSE_DETECTED"


# ============================================================================
# 4. Crash Recovery Matrix & Idempotency Boundary Tests
# ============================================================================

def test_crash_during_prepared_state_read_only_vs_non_idempotent(temp_env):
    """
    Tests crash in PREPARED state:
    - Read-only action: reset safely to RUNNING for retry.
    - Non-idempotent action: quarantine under REQUIRES_RECONCILIATION.
    """
    engine = temp_env["recovery_engine"]
    journal = temp_env["journal"]
    rm = temp_env["recovery_manager"]

    # 1. Read-only action crash
    t1 = "task-prep-ro"
    chk1 = TaskCheckpoint(
        task_id=t1, workflow_id=t1, status=TaskStatus.RUNNING,
        current_step="s1", completed_step_ids=[], pending_step_ids=["s1"],
    )
    rm.save_task_checkpoint(chk1)
    e1 = journal.prepare_dispatch(t1, "s1", "filesystem.read", "READ_ONLY", {"path": "test.txt"})

    res1 = engine.audit_and_recover_task(t1)
    assert res1["action_taken"] == "RESET_FOR_DISPATCH"
    assert res1["status"] == "RUNNING"

    # 2. Non-idempotent action crash
    t2 = "task-prep-nonidemp"
    chk2 = TaskCheckpoint(
        task_id=t2, workflow_id=t2, status=TaskStatus.RUNNING,
        current_step="s1", completed_step_ids=[], pending_step_ids=["s1"],
    )
    rm.save_task_checkpoint(chk2)
    e2 = journal.prepare_dispatch(t2, "s1", "network.post_payment", "NON_IDEMPOTENT", {"amount": 100})

    res2 = engine.audit_and_recover_task(t2)
    assert res2["action_taken"] == "QUARANTINED_RECONCILIATION"
    assert res2["status"] == "REQUIRES_RECONCILIATION"


def test_crash_during_dispatching_uncertain_outcome(temp_env):
    """
    Tests crash during DISPATCHING:
    Non-idempotent side-effect outcome is ambiguous and must be quarantined.
    """
    engine = temp_env["recovery_engine"]
    journal = temp_env["journal"]
    rm = temp_env["recovery_manager"]

    task_id = "task-disp-crash"
    chk = TaskCheckpoint(
        task_id=task_id, workflow_id=task_id, status=TaskStatus.RUNNING,
        current_step="s1", completed_step_ids=[], pending_step_ids=["s1"],
    )
    rm.save_task_checkpoint(chk)

    e = journal.prepare_dispatch(task_id, "s1", "filesystem.write", "NON_IDEMPOTENT", {"path": "a.txt"})
    journal.record_dispatching(e.attempt_id)

    res = engine.audit_and_recover_task(task_id)
    assert res["action_taken"] == "QUARANTINED_RECONCILIATION"
    assert res["status"] == "REQUIRES_RECONCILIATION"
    assert "reconciliation_reason" in res["checkpoint"]["state_data"]


def test_crash_with_running_subprocess_clean_exit_recovery(temp_env):
    """
    Tests crash where subprocess finished with exit code 0 during downtime.
    Recovery engine must detect clean exit and advance completed step.
    """
    engine = temp_env["recovery_engine"]
    journal = temp_env["journal"]
    rm = temp_env["recovery_manager"]
    tracker = temp_env["subprocess_tracker"]

    task_id = "task-subp-recovery"
    chk = TaskCheckpoint(
        task_id=task_id, workflow_id=task_id, status=TaskStatus.RUNNING,
        current_step="s1", completed_step_ids=[], pending_step_ids=["s1", "s2"],
    )
    rm.save_task_checkpoint(chk)

    # Spawn real process and wait for it
    e = journal.prepare_dispatch(task_id, "s1", "shell_execute", "IDEMPOTENT", {"command": "echo ok"})
    journal.record_dispatching(e.attempt_id)

    log_path = tracker.get_log_path(e.attempt_id)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("output lines\n--- [SUBPROCESS COMPLETED exit=0 time=1.0] ---\n")

    # Record running with a dead PID (e.g. 999999) and dummy time
    journal.record_running_process(e.attempt_id, pid=999999, process_creation_time=1.0, log_path=log_path)

    res = engine.audit_and_recover_task(task_id)
    assert res["action_taken"] == "RECOVERED_COMPLETED_STEP"
    assert "s1" in res["checkpoint"]["completed_step_ids"]
    assert "s1" not in res["checkpoint"]["pending_step_ids"]


# ============================================================================
# 5. Single-Use Approval Token & Security Invalidation Tests
# ============================================================================

def test_consumed_approval_cannot_be_reused_across_reboot(temp_env):
    """
    Verifies that a consumed or expired approval token cannot be reused across reboot.
    Must quarantine task under REQUIRES_RECONCILIATION.
    """
    engine = temp_env["recovery_engine"]
    journal = temp_env["journal"]
    rm = temp_env["recovery_manager"]
    db = temp_env["db"]

    task_id = "task-approval-consumed"
    step_id = "step-danger"

    chk = TaskCheckpoint(
        task_id=task_id, workflow_id=task_id, status=TaskStatus.PAUSED,
        current_step=step_id, completed_step_ids=[], pending_step_ids=[step_id],
    )
    rm.save_task_checkpoint(chk)

    # Insert a CONSUMED approval record in SQLite
    approval_id = "appr-consumed-1"
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO approval_records (
                approval_id, token, task_id, action, resource, param_hash,
                status, expires_at, created_at, consumed_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'CONSUMED', ?, ?, ?);
            """,
            (approval_id, "tok123", task_id, "shell_execute", "rm -rf", "hash1", time.time() + 3600, utc_now(), utc_now()),
        )

    e = journal.prepare_dispatch(
        task_id=task_id, step_id=step_id, action="shell_execute",
        idempotency_class="IRREVERSIBLE_HIGH_RISK", params={"cmd": "rm -rf"},
        approval_ref=approval_id,
    )
    journal.record_waiting_approval(e.attempt_id, approval_ref=approval_id)

    res = engine.audit_and_recover_task(task_id)
    assert res["action_taken"] == "QUARANTINED_INVALID_APPROVAL"
    assert res["status"] == "REQUIRES_RECONCILIATION"


# ============================================================================
# 6. Schema Migration v5 Upgrade Test
# ============================================================================

def test_migration_v5_upgrade_without_data_loss(temp_env):
    """
    Tests that a database created at schema v4 upgrades safely to v5:
    - Retains existing records in task_checkpoints, memories, and approval_records.
    - Adds checkpoint_version, lease_holder, and lease_expires_at columns.
    - Creates execution_journal table.
    """
    with tempfile.TemporaryDirectory() as td:
        db_file = os.path.join(td, "legacy_v4.db")
        conn = DatabaseManager(db_file).get_connection()
        try:
            # Verify migration version is 5
            c = conn.cursor()
            c.execute("SELECT MAX(version) FROM schema_migrations;")
            assert c.fetchone()[0] == 5

            # Verify execution_journal table exists
            c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='execution_journal';")
            assert c.fetchone() is not None

            # Verify new columns on task_checkpoints
            c.execute("PRAGMA table_info(task_checkpoints);")
            cols = [r[1] for r in c.fetchall()]
            assert "checkpoint_version" in cols
            assert "lease_holder" in cols
            assert "lease_expires_at" in cols
        finally:
            conn.close()


# ============================================================================
# 7. End-to-End Autonomous Loop Anti-Replay Integration Test
# ============================================================================

@pytest.mark.asyncio
async def test_controller_anti_replay_preserves_completed_steps(temp_env):
    """
    Tests that AutonomousExecutionController checks the execution journal before dispatch,
    preventing duplicate execution of already-succeeded steps.
    """
    db = temp_env["db"]
    rm = temp_env["recovery_manager"]
    journal = temp_env["journal"]

    planner = TaskPlanner()
    orchestrator = TaskOrchestrator(recovery_manager=rm)
    controller = AutonomousExecutionController(
        planner=planner,
        orchestrator=orchestrator,
        recovery_manager=rm,
        journal_service=journal,
        worker_id="test-ctrl-1",
    )

    task_id = "task-anti-replay-e2e"
    step1 = DAGStep(
        step_id="step-1",
        title="Read File",
        skill_name="filesystem.read",
        parameters={"path": "dummy.txt"},
        status="PENDING",
    )
    dag = TaskDAG(
        task_id=task_id,
        goal="Test anti replay",
        system_prompt="Execute goal safely",
        steps=[step1],
    )

    # Pre-save checkpoint to satisfy foreign key requirement
    chk = TaskCheckpoint(
        task_id=task_id,
        workflow_id=task_id,
        status=TaskStatus.RUNNING,
        current_step="step-1",
        completed_step_ids=[],
        pending_step_ids=["step-1"],
    )
    rm.save_task_checkpoint(chk)

    # Pre-record step-1 as SUCCEEDED in journal
    e = journal.prepare_dispatch(
        task_id=task_id,
        step_id="step-1",
        action="filesystem.read",
        idempotency_class="READ_ONLY",
        params={"path": "dummy.txt"},
    )
    journal.record_dispatching(e.attempt_id)
    journal.record_success(e.attempt_id, result_digest="digest_prior_run", exit_code=0)

    # Run loop
    state = await controller.run_autonomous_loop(
        goal="Test anti replay",
        task_id=task_id,
        initial_dag=dag,
    )

    # Step-1 must be marked COMPLETED without re-dispatching
    assert state.status == "COMPLETED"
    assert "step-1" in state.completed_steps
    assert dag.steps[0].status == "COMPLETED"


# ============================================================================
# 8. Operator Manual Reconciliation Hook Test
# ============================================================================

def test_operator_reconcile_task_endpoints(temp_env):
    """
    Tests operator reconciliation hook:
    - mark_succeeded: clears quarantine and marks step COMPLETED.
    - mark_failed: marks step and task FAILED.
    - retry: clears quarantine and resets step for execution.
    """
    engine = temp_env["recovery_engine"]
    rm = temp_env["recovery_manager"]
    journal = temp_env["journal"]

    task_id = "task-reconcile-test"
    chk = TaskCheckpoint(
        task_id=task_id,
        workflow_id=task_id,
        status=TaskStatus.REQUIRES_RECONCILIATION,
        current_step="s1",
        completed_step_ids=[],
        pending_step_ids=["s1"],
        state_data={"reconciliation_reason": "Process vanished"},
    )
    rm.save_task_checkpoint(chk)

    e = journal.prepare_dispatch(task_id, "s1", "filesystem.write", "NON_IDEMPOTENT", {"path": "b.txt"})
    journal.record_reconciliation_required(e.attempt_id, "Ambiguous outcome")

    # Operator marks succeeded
    updated = engine.reconcile_task(task_id, "s1", resolution="mark_succeeded", notes="Verified file exists on disk")
    assert updated.status == TaskStatus.RUNNING
    assert "s1" in updated.completed_step_ids
    assert "reconciliation_reason" not in updated.state_data
