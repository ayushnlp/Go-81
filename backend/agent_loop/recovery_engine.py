"""
Autonomous Recovery Engine for Project Go 81.
Enforces deterministic crash recovery, idempotency protection, subprocess reattachment,
single-use authorization checks, and task lease concurrency guards.
"""

import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.memory.database import DatabaseManager, utc_now
from app.memory.journal import ExecutionJournalService, compute_param_hash
from app.memory.models import (
    ApprovalRecord,
    ApprovalStatus,
    DispatchState,
    ExecutionJournalEntry,
    TaskCheckpoint,
    TaskStatus,
)
from app.memory.recovery import TaskRecoveryManager
from backend.agent_loop.models import GoalState, IdempotencyClass, LoopBudget, LoopPhase, StepObservation
from backend.agent_loop.subprocess_tracker import SubprocessTracker, is_process_active

logger = logging.getLogger(__name__)


class LeaseConflictError(RuntimeError):
    """Raised when an operation cannot acquire or renew an exclusive task lease."""
    pass


class AutonomousRecoveryEngine:
    """
    Coordinates crash-consistent task recovery and idempotency auditing.
    Never re-executes non-idempotent actions blindly across crashes.
    """

    def __init__(
        self,
        db: DatabaseManager,
        recovery_manager: TaskRecoveryManager,
        journal_service: Optional[ExecutionJournalService] = None,
        subprocess_tracker: Optional[SubprocessTracker] = None,
        worker_id: Optional[str] = None,
    ):
        self.db = db
        self.recovery_manager = recovery_manager
        self.journal = journal_service or ExecutionJournalService(db)
        self.subprocess_tracker = subprocess_tracker or SubprocessTracker()
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"

    def audit_and_recover_task(self, task_id: str) -> Dict[str, Any]:
        """
        Audits a single task checkpoint against the durable execution journal.
        Applies strict recovery rules to prevent duplicate side effects.
        """
        # 1. Acquire task lease for recovery operation
        acquired = self.journal.acquire_task_lease(task_id, self.worker_id, ttl_seconds=60.0)
        if not acquired:
            raise LeaseConflictError(
                f"Cannot recover task '{task_id}': Active lease held by another worker."
            )

        try:
            chk = self.recovery_manager.get_task_checkpoint(task_id)
            if not chk:
                return {"task_id": task_id, "status": "NOT_FOUND", "action_taken": "NONE"}

            # If already in terminal state
            if chk.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                return {
                    "task_id": task_id,
                    "status": chk.status.value,
                    "action_taken": "PRESERVED_TERMINAL",
                    "checkpoint": chk.model_dump(),
                }

            # Retrieve journal entries for this task
            entries = self.journal.get_journal_for_task(task_id)
            active_entries = [
                e for e in entries
                if e.dispatch_state in (
                    DispatchState.PREPARED,
                    DispatchState.DISPATCHING,
                    DispatchState.RUNNING,
                    DispatchState.WAITING_APPROVAL,
                    DispatchState.UNKNOWN_OUTCOME,
                    DispatchState.RECONCILIATION_REQUIRED,
                )
            ]

            # If no active entries, check checkpoint status
            if not active_entries:
                # If current step is completed, advance to next pending step
                if chk.current_step in chk.completed_step_ids and chk.pending_step_ids:
                    chk.current_step = chk.pending_step_ids[0]
                    chk.updated_at = utc_now()
                    self.recovery_manager.save_task_checkpoint(chk)
                return {
                    "task_id": task_id,
                    "status": chk.status.value,
                    "action_taken": "READY_TO_RESUME",
                    "checkpoint": chk.model_dump(),
                }

            # Evaluate the most recent active attempt
            latest_active = active_entries[-1]
            recovery_outcome = self._evaluate_active_entry(chk, latest_active)

            # Persist updated checkpoint
            self.recovery_manager.save_task_checkpoint(chk)

            return {
                "task_id": task_id,
                "status": chk.status.value,
                "action_taken": recovery_outcome["action_taken"],
                "reason": recovery_outcome.get("reason"),
                "entry_id": latest_active.entry_id,
                "dispatch_state": latest_active.dispatch_state.value,
                "checkpoint": chk.model_dump(),
            }
        finally:
            self.journal.release_task_lease(task_id, self.worker_id)

    def _evaluate_active_entry(
        self,
        chk: TaskCheckpoint,
        entry: ExecutionJournalEntry,
    ) -> Dict[str, Any]:
        """Evaluates an active journal entry against the crash recovery matrix."""
        state = entry.dispatch_state
        idemp = entry.idempotency_class.upper()

        # --------------------------------------------------------------------
        # 1. State: PREPARED
        # Intent recorded, but execution was never dispatched before crash.
        # Safe to reset and proceed through normal permission/validation.
        # --------------------------------------------------------------------
        if state == DispatchState.PREPARED:
            # Check if read-only or idempotent
            if idemp in ("READ_ONLY", "IDEMPOTENT"):
                self.journal.record_failure(entry.attempt_id, "Interrupted prior to dispatch. Safe for retry.")
                chk.status = TaskStatus.RUNNING
                return {"action_taken": "RESET_FOR_DISPATCH", "reason": "Pre-dispatch crash; intent reset safely."}
            else:
                # For non-idempotent actions, verify no side-effects were dispatched
                self.journal.record_reconciliation_required(
                    entry.attempt_id,
                    "Crash occurred while preparing non-idempotent action. Verifying dispatch boundary."
                )
                chk.status = TaskStatus.REQUIRES_RECONCILIATION
                chk.state_data["reconciliation_reason"] = (
                    f"Task crashed while preparing non-idempotent action '{entry.action}'. Operator confirmation required."
                )
                return {"action_taken": "QUARANTINED_RECONCILIATION", "reason": "Non-idempotent action prepared before crash."}

        # --------------------------------------------------------------------
        # 2. State: DISPATCHING
        # Action was in the process of being sent to the sandbox or OS.
        # Potential uncertainty window: external side effect may have commenced.
        # --------------------------------------------------------------------
        if state == DispatchState.DISPATCHING:
            if idemp == "READ_ONLY":
                # Safe to retry within budget
                self.journal.record_failure(entry.attempt_id, "Dispatch interrupted. Safe read-only retry allowed.")
                chk.status = TaskStatus.RUNNING
                return {"action_taken": "RESET_READONLY_RETRY", "reason": "Interrupted during read-only dispatch."}
            else:
                # Non-idempotent side effect outcome is ambiguous! Must quarantine.
                self.journal.record_unknown_outcome(
                    entry.attempt_id,
                    f"Crash during dispatch of {entry.action}. External side effect outcome cannot be proven."
                )
                self.journal.record_reconciliation_required(
                    entry.attempt_id,
                    "Ambiguous side-effect outcome across backend restart."
                )
                chk.status = TaskStatus.REQUIRES_RECONCILIATION
                chk.state_data["reconciliation_reason"] = (
                    f"Crash during dispatch of '{entry.action}'. Side effect may have executed. Human verification required."
                )
                return {"action_taken": "QUARANTINED_RECONCILIATION", "reason": "Dispatch crash on side-effect action."}

        # --------------------------------------------------------------------
        # 3. State: RUNNING
        # External subprocess was launched. Verify via SubprocessTracker.
        # --------------------------------------------------------------------
        if state == DispatchState.RUNNING:
            audit = self.subprocess_tracker.audit_subprocess_status(
                pid=entry.pid,
                process_creation_time=entry.process_creation_time,
                log_path=entry.log_path,
                recorded_exit_code=entry.exit_code,
            )

            status = audit.get("status")

            if status == "ACTIVE":
                # Process is STILL RUNNING with exact matching creation time!
                logger.info(
                    f"Subprocess verified active across restart: PID={entry.pid}, "
                    f"attempt={entry.attempt_id}. Reattaching."
                )
                chk.status = TaskStatus.RUNNING
                return {
                    "action_taken": "REATTACHED_ACTIVE_SUBPROCESS",
                    "reason": f"Live process PID={entry.pid} reattached with verified creation timestamp.",
                }

            elif status == "EXITED_CLEAN":
                # Process finished with exit code 0! Mark SUCCEEDED.
                self.journal.record_success(
                    entry.attempt_id,
                    result_digest=hashlib.sha256(audit.get("log_tail", "").encode("utf-8")).hexdigest(),
                    exit_code=0,
                )
                if entry.step_id not in chk.completed_step_ids:
                    chk.completed_step_ids.append(entry.step_id)
                if entry.step_id in chk.pending_step_ids:
                    chk.pending_step_ids.remove(entry.step_id)
                chk.status = TaskStatus.RUNNING
                return {
                    "action_taken": "RECOVERED_COMPLETED_STEP",
                    "reason": "Subprocess terminated cleanly with exit code 0 during downtime.",
                }

            elif status == "EXITED_ERROR":
                # Process terminated with non-zero exit code
                exit_c = audit.get("exit_code", 1)
                self.journal.record_failure(
                    entry.attempt_id,
                    error_message=f"Subprocess exited with code {exit_c}",
                    exit_code=exit_c,
                )
                chk.status = TaskStatus.RUNNING
                return {
                    "action_taken": "RECORDED_SUBPROCESS_FAILURE",
                    "reason": f"Subprocess exited with non-zero code {exit_c}.",
                }

            elif status == "PID_REUSE_DETECTED":
                # PID collision rejected!
                logger.warning(
                    f"PID reuse detected for task '{chk.task_id}', PID={entry.pid}! "
                    "Halting automatic reattachment to avoid corrupting foreign process."
                )
                self.journal.record_unknown_outcome(
                    entry.attempt_id,
                    "PID reuse detected: OS reassigned PID to foreign process."
                )
                self.journal.record_reconciliation_required(
                    entry.attempt_id,
                    "PID reuse detected. Cannot verify subprocess outcome."
                )
                chk.status = TaskStatus.REQUIRES_RECONCILIATION
                chk.state_data["reconciliation_reason"] = (
                    f"PID reuse detected for action '{entry.action}' (PID {entry.pid}). Foreign process rejected."
                )
                return {
                    "action_taken": "QUARANTINED_PID_REUSE",
                    "reason": "Rejected foreign process claiming previous PID.",
                }

            else:
                # UNKNOWN_TERMINATED or missing process
                if idemp == "READ_ONLY":
                    self.journal.record_failure(entry.attempt_id, "Subprocess vanished without clean exit code.")
                    chk.status = TaskStatus.RUNNING
                    return {"action_taken": "RESET_READONLY_RETRY", "reason": "Lost read-only subprocess reset."}
                else:
                    self.journal.record_unknown_outcome(
                        entry.attempt_id,
                        "Process vanished without verifiable exit code or completion marker."
                    )
                    self.journal.record_reconciliation_required(
                        entry.attempt_id,
                        "Subprocess lost without verifiable exit status."
                    )
                    chk.status = TaskStatus.REQUIRES_RECONCILIATION
                    chk.state_data["reconciliation_reason"] = (
                        f"Process running '{entry.action}' terminated abruptly. Outcome cannot be proven."
                    )
                    return {"action_taken": "QUARANTINED_LOST_PROCESS", "reason": "Lost process with uncertain side effect."}

        # --------------------------------------------------------------------
        # 4. State: WAITING_APPROVAL
        # Restore approval-waiting state, verifying single-use tokens.
        # --------------------------------------------------------------------
        if state == DispatchState.WAITING_APPROVAL:
            # Check SQLite approval record
            approval_valid = self._verify_approval_record(entry.approval_ref)
            if approval_valid:
                chk.status = TaskStatus.PAUSED
                return {
                    "action_taken": "RESTORED_WAITING_APPROVAL",
                    "reason": "Approval request remains valid and unconsumed.",
                }
            else:
                # Token was already consumed, expired, or revoked
                self.journal.record_reconciliation_required(
                    entry.attempt_id,
                    "Approval record is no longer valid (consumed, expired, or missing)."
                )
                chk.status = TaskStatus.REQUIRES_RECONCILIATION
                chk.state_data["reconciliation_reason"] = (
                    "Approval token cannot be reused across reboot. Fresh authorization required."
                )
                return {
                    "action_taken": "QUARANTINED_INVALID_APPROVAL",
                    "reason": "Approval token consumed or expired across reboot.",
                }

        # --------------------------------------------------------------------
        # 5. State: UNKNOWN_OUTCOME or RECONCILIATION_REQUIRED
        # Always maintain quarantine! Never automatically unblock.
        # --------------------------------------------------------------------
        chk.status = TaskStatus.REQUIRES_RECONCILIATION
        return {
            "action_taken": "MAINTAINED_RECONCILIATION_QUARANTINE",
            "reason": "Task was already flagged for human reconciliation.",
        }

    def _verify_approval_record(self, approval_ref: Optional[str]) -> bool:
        """Verifies if an approval record is still in valid PENDING status."""
        if not approval_ref:
            return False
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT status, expires_at FROM approval_records
                WHERE approval_id = ? OR token = ? LIMIT 1;
                """,
                (approval_ref, approval_ref),
            )
            row = cursor.fetchone()
            if not row:
                return False
            status, expires_at = row[0], row[1]
            if status != "PENDING":
                return False
            if expires_at and expires_at < time.time():
                return False
            return True
        finally:
            conn.close()

    def perform_startup_audit_and_recovery(self) -> Dict[str, Any]:
        """
        Idempotent Startup Audit:
        Runs automatically on backend startup.
        1. Cleans up stale leases.
        2. Inspects incomplete tasks.
        3. Recovers or quarantines each task deterministically.
        """
        logger.info("Starting Autonomous Recovery Startup Audit...")
        stale_cleared = self.journal.clear_stale_leases()
        incomplete_tasks = self.recovery_manager.load_incomplete_tasks(raise_on_error=False)

        results: List[Dict[str, Any]] = []
        for chk in incomplete_tasks:
            try:
                task_res = self.audit_and_recover_task(chk.task_id)
                results.append(task_res)
            except Exception as e:
                logger.error(f"Error auditing task '{chk.task_id}': {e}")
                results.append({"task_id": chk.task_id, "error": str(e)})

        summary = {
            "stale_leases_cleared": stale_cleared,
            "incomplete_tasks_audited": len(incomplete_tasks),
            "results": results,
            "audited_at": utc_now(),
        }
        logger.info(
            f"Autonomous Recovery Startup Audit completed: {len(incomplete_tasks)} tasks audited, "
            f"{stale_cleared} stale leases cleared."
        )
        return summary

    def reconcile_task(
        self,
        task_id: str,
        step_id: str,
        resolution: str,
        notes: Optional[str] = None,
    ) -> TaskCheckpoint:
        """
        Operator Reconciliation Hook:
        Allows manual resolution of quarantined tasks:
        - "mark_succeeded": Confirms external side effect succeeded.
        - "mark_failed": Confirms step failed; terminates task safely.
        - "retry": Clears quarantine and allows a fresh re-execution.
        """
        chk = self.recovery_manager.get_task_checkpoint(task_id)
        if not chk:
            raise KeyError(f"Task '{task_id}' not found.")

        latest_entry = self.journal.get_latest_entry_for_step(task_id, step_id)

        if resolution == "mark_succeeded":
            if latest_entry:
                self.journal.record_success(
                    latest_entry.attempt_id,
                    result_digest="manual_reconciliation_confirmed",
                    exit_code=0,
                )
            if step_id not in chk.completed_step_ids:
                chk.completed_step_ids.append(step_id)
            if step_id in chk.pending_step_ids:
                chk.pending_step_ids.remove(step_id)
            chk.status = TaskStatus.RUNNING
            chk.state_data["reconciliation_notes"] = notes or "Manually marked succeeded by operator."
            chk.state_data.pop("reconciliation_reason", None)

        elif resolution == "mark_failed":
            if latest_entry:
                self.journal.record_failure(
                    latest_entry.attempt_id,
                    error_message=notes or "Manually marked failed by operator.",
                    exit_code=1,
                )
            chk.status = TaskStatus.FAILED
            chk.state_data["reconciliation_notes"] = notes or "Manually terminated by operator."

        elif resolution == "retry":
            if latest_entry:
                self.journal.record_failure(
                    latest_entry.attempt_id,
                    error_message="Quarantined attempt cleared for manual operator retry.",
                )
            chk.status = TaskStatus.RUNNING
            if step_id in chk.completed_step_ids:
                chk.completed_step_ids.remove(step_id)
            if step_id not in chk.pending_step_ids:
                chk.pending_step_ids.insert(0, step_id)
            chk.current_step = step_id
            chk.state_data["reconciliation_notes"] = notes or "Quarantine cleared for retry."
            chk.state_data.pop("reconciliation_reason", None)

        else:
            raise ValueError(f"Unknown reconciliation resolution: '{resolution}'")

        chk.updated_at = utc_now()
        self.recovery_manager.save_task_checkpoint(chk)
        logger.info(f"Task '{task_id}' step '{step_id}' reconciled with resolution '{resolution}'.")
        return chk

