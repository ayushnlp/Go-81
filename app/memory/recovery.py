"""
Task persistence, checkpointing, and crash recovery subsystem.
Enforces explicit state transitions, task-aware idempotency guards to prevent
re-execution of completed side effects, and safe human-in-the-loop reconciliation for ambiguous outcomes.
"""

import hashlib
import json
import logging
import threading
import uuid
from typing import Any, Dict, List, Optional

from app.memory.crypto import DecryptionError, EncryptionService, MissingKeyError
from app.memory.database import DatabaseManager, utc_now
from app.memory.models import TaskCheckpoint, TaskExecutionEvent, TaskStatus
from app.memory.repository import MemoryRepository

logger = logging.getLogger(__name__)


def compute_action_hash(action: str, params: Dict[str, Any]) -> str:
    """Computes a deterministic SHA-256 hash representing an external side-effect invocation."""
    canonical_params = json.dumps(params, sort_keys=True, ensure_ascii=False)
    raw = f"{action}::{canonical_params}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TaskRecoveryManager:
    """
    Manages transactional workflow state persistence and reboot recovery.
    All task state variables are encrypted at rest with Fernet.
    Guarantees thread-safe in-process mutations and task-scoped idempotency.
    """

    def __init__(self, db: DatabaseManager, crypto: EncryptionService):
        self.db = db
        self.crypto = crypto
        self.repo = MemoryRepository(db)
        self._lock = threading.RLock()

    def save_task_checkpoint(self, checkpoint: TaskCheckpoint) -> None:
        """
        Encrypts state_data and writes task checkpoint to SQLite.
        Atomic write protected by mutex and SQLite transaction.
        """
        with self._lock:
            checkpoint.updated_at = utc_now()
            encrypted_state = self.crypto.encrypt_json(checkpoint.state_data)
            self.repo.save_task_checkpoint(checkpoint, encrypted_state)

    def get_task_checkpoint(self, task_id: str) -> Optional[TaskCheckpoint]:
        """
        Fetches and decrypts a specific task checkpoint.
        Fails safely if decryption key is missing or invalid.
        Never silently replaces unreadable state with empty dict.
        """
        with self._lock:
            row = self.repo.get_task_checkpoint_row(task_id)
            if not row:
                return None
            return self._row_to_checkpoint(row)

    def load_incomplete_tasks(self, raise_on_error: bool = True) -> List[TaskCheckpoint]:
        """
        Loads all tasks that were in progress (PENDING, RUNNING, PAUSED, REQUIRES_RECONCILIATION)
        prior to process shutdown or crash.
        Fails safely if decryption fails or encryption key is missing/invalid.
        Never silently replaces unreadable state with empty state.
        """
        with self._lock:
            rows = self.repo.list_incomplete_task_rows()
            tasks: List[TaskCheckpoint] = []
            for r in rows:
                try:
                    tasks.append(self._row_to_checkpoint(r))
                except (DecryptionError, MissingKeyError) as e:
                    logger.error(
                        f"Cryptographic failure loading task checkpoint id='{r['task_id']}': "
                        f"{type(e).__name__} (key unavailable or ciphertext invalid)."
                    )
                    if raise_on_error:
                        raise
                except Exception as e:
                    logger.error(f"Error loading task checkpoint id='{r['task_id']}': {type(e).__name__}")
                    if raise_on_error:
                        raise
            return tasks

    def recover_task(self, task_id: str) -> TaskCheckpoint:
        """
        Restores an incomplete task checkpoint from disk after crash or restart:
        1. Fetches and decrypts the persisted checkpoint state from SQLite.
        2. Preserves task ID, workflow ID, status, completed/pending steps, and state data.
        3. Fails safely if decryption fails or the task is not found.
        4. Detects in-flight crash windows: if a step event was left in 'PENDING',
           it automatically marks it AMBIGUOUS and flags the task for human reconciliation.
        5. Returns the restored checkpoint without blindly re-running steps.
        """
        with self._lock:
            chk = self.get_task_checkpoint(task_id)
            if not chk:
                raise KeyError(f"Task with ID '{task_id}' not found.")

            if chk.status == TaskStatus.REQUIRES_RECONCILIATION:
                logger.warning(
                    f"Task '{task_id}' requires operator reconciliation. "
                    "Automated resumption halted until human review."
                )
                return chk

            if chk.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
                logger.info(f"Task '{task_id}' is in terminal state '{chk.status.value}'.")
                return chk

            # Crash window audit: check if any event was left in PENDING status
            pending_events = self.repo.get_pending_events_for_task(task_id)
            if pending_events:
                event_summary = ", ".join(f"'{e['action']}' (step '{e['step_id']}')" for e in pending_events)
                logger.warning(
                    f"Crash window detected for task '{task_id}': In-flight execution event(s) found ({event_summary}). "
                    "Quarantining task under REQUIRES_RECONCILIATION to prevent blind duplicate execution."
                )
                chk.status = TaskStatus.REQUIRES_RECONCILIATION
                chk.state_data["reconciliation_reason"] = (
                    f"Crash window detected: Process terminated while executing {event_summary}. "
                    "External outcome is ambiguous and requires human verification."
                )
                chk.state_data["reconciliation_flagged_at"] = utc_now()
                self.save_task_checkpoint(chk)
                return chk

            # Ensure current_step reflects the next pending step if prior step completed
            if chk.current_step in chk.completed_step_ids and chk.pending_step_ids:
                chk.current_step = chk.pending_step_ids[0]
                chk.updated_at = utc_now()
                self.save_task_checkpoint(chk)

            return chk

    def list_execution_events(self, task_id: str) -> List[TaskExecutionEvent]:
        """Fetches and decrypts all execution events for a task."""
        with self._lock:
            rows = self.repo.list_execution_events_for_task(task_id.strip())
            events: List[TaskExecutionEvent] = []
            for r in rows:
                try:
                    decrypted_details = self.crypto.decrypt_json(r["encrypted_details"])
                except Exception:
                    decrypted_details = {"error": "unreadable_ciphertext"}
                events.append(
                    TaskExecutionEvent(
                        event_id=r["event_id"],
                        task_id=r["task_id"],
                        step_id=r["step_id"],
                        action=r["action"],
                        status=r["status"],
                        idempotency_hash=r["idempotency_hash"],
                        details=decrypted_details,
                        recorded_at=r["recorded_at"],
                    )
                )
            return events

    def begin_step_execution(
        self,
        task_id: str,
        step_id: str,
        action: str,
        input_params: Dict[str, Any],
    ) -> TaskExecutionEvent:
        """
        Two-Phase Execution Guard (Phase 1):
        Pre-execution intent registration:
        1. Checks idempotency guard before invoking external side effect.
        2. Records 'PENDING' execution event in SQLite to bridge crash windows.
        """
        with self._lock:
            action_hash = compute_action_hash(action, input_params)
            if self.is_step_already_executed(task_id, step_id, idempotency_hash=action_hash):
                raise RuntimeError(
                    f"Idempotency violation: Step '{step_id}' with action '{action}' "
                    f"has already succeeded or is locked for reconciliation in task '{task_id}'."
                )

            return self.record_execution_event(
                task_id=task_id,
                step_id=step_id,
                action=action,
                status="PENDING",
                input_params=input_params,
                output_details={"state": "in_flight", "started_at": utc_now()},
            )

    def complete_step_execution(
        self,
        task_id: str,
        step_id: str,
        action: str,
        input_params: Dict[str, Any],
        output_details: Dict[str, Any],
        next_step: Optional[str] = None,
        state_updates: Optional[Dict[str, Any]] = None,
    ) -> TaskCheckpoint:
        """
        Two-Phase Execution Guard (Phase 2):
        Post-execution success confirmation:
        1. Records 'SUCCESS' execution event.
        2. Atomically marks the step completed in the checkpoint.
        """
        with self._lock:
            self.record_execution_event(
                task_id=task_id,
                step_id=step_id,
                action=action,
                status="SUCCESS",
                input_params=input_params,
                output_details=output_details,
            )
            return self.mark_step_completed(
                task_id=task_id,
                step_id=step_id,
                next_step=next_step,
                state_updates=state_updates,
            )

    def handle_step_failure(
        self,
        task_id: str,
        step_id: str,
        action: str,
        input_params: Dict[str, Any],
        reason: str,
        is_ambiguous: bool = True,
    ) -> TaskCheckpoint:
        """
        Handles failure or timeout of a side effect:
        - If is_ambiguous (e.g. timeout, connection reset): records AMBIGUOUS and flags REQUIRES_RECONCILIATION.
        - If not ambiguous (e.g. 400 Bad Request): records FAILED and marks task FAILED.
        """
        with self._lock:
            if is_ambiguous:
                self.record_ambiguous_event(
                    task_id=task_id,
                    step_id=step_id,
                    action=action,
                    input_params=input_params,
                    reason=reason,
                )
                return self.get_task_checkpoint(task_id)
            else:
                self.record_execution_event(
                    task_id=task_id,
                    step_id=step_id,
                    action=action,
                    status="FAILED",
                    input_params=input_params,
                    output_details={"error": reason, "failed_at": utc_now()},
                )
                chk = self.get_task_checkpoint(task_id)
                if chk:
                    chk.status = TaskStatus.FAILED
                    chk.state_data["failure_reason"] = reason
                    self.save_task_checkpoint(chk)
                return chk

    def record_execution_event(
        self,
        task_id: str,
        step_id: str,
        action: str,
        status: str,
        input_params: Dict[str, Any],
        output_details: Dict[str, Any],
    ) -> TaskExecutionEvent:
        """
        Records an execution event with an idempotency hash.
        Encrypts output/error details at rest.
        """
        with self._lock:
            idempotency_hash = compute_action_hash(action, input_params)
            event_id = str(uuid.uuid4())
            now = utc_now()

            encrypted_details = self.crypto.encrypt_json(output_details)

            event = TaskExecutionEvent(
                event_id=event_id,
                task_id=task_id,
                step_id=step_id,
                action=action,
                status=status,
                idempotency_hash=idempotency_hash,
                details=output_details,
                recorded_at=now,
            )

            self.repo.save_execution_event(event, encrypted_details)
            return event

    def record_ambiguous_event(
        self,
        task_id: str,
        step_id: str,
        action: str,
        input_params: Dict[str, Any],
        reason: str,
    ) -> TaskExecutionEvent:
        """
        Records an ambiguous side-effect outcome and flags the task for operator reconciliation.
        Prevents blind automated re-execution of uncertain external operations.
        """
        with self._lock:
            event = self.record_execution_event(
                task_id=task_id,
                step_id=step_id,
                action=action,
                status="AMBIGUOUS",
                input_params=input_params,
                output_details={"ambiguity_reason": reason, "recorded_at": utc_now()},
            )
            self.flag_for_reconciliation(
                task_id=task_id,
                reason=f"Ambiguous outcome in step '{step_id}' ({action}): {reason}",
            )
            return event

    def is_step_already_executed(
        self,
        task_id: str,
        step_id: str,
        idempotency_hash: Optional[str] = None,
    ) -> bool:
        """
        Idempotency Guard:
        Verifies whether a step has already been completed in the task DAG
        or if an identical side-effect has already succeeded within this task.
        Scopes event lookups to task_id to prevent cross-task contamination.
        Blocks execution if the task or step is in an ambiguous/reconciliation state.
        """
        with self._lock:
            chk = self.get_task_checkpoint(task_id)
            if chk:
                if chk.status == TaskStatus.REQUIRES_RECONCILIATION:
                    # Locked for human review; must not auto-execute
                    return True
                if step_id in chk.completed_step_ids:
                    return True

            if idempotency_hash:
                # Check task-scoped execution event
                row = self.repo.get_execution_event_by_hash(
                    idempotency_hash=idempotency_hash,
                    task_id=task_id,
                    step_id=step_id,
                )
                if not row:
                    # Also check task-level match
                    row = self.repo.get_execution_event_by_hash(
                        idempotency_hash=idempotency_hash,
                        task_id=task_id,
                    )
                if row and row["status"] == "SUCCESS":
                    return True
                if row and row["status"] == "AMBIGUOUS":
                    # Ambiguous side effect: must not blindly re-execute
                    return True

            return False

    def is_step_ambiguous(
        self,
        task_id: str,
        step_id: str,
        idempotency_hash: Optional[str] = None,
    ) -> bool:
        """Returns True if the step outcome is ambiguous or pending operator reconciliation."""
        with self._lock:
            chk = self.get_task_checkpoint(task_id)
            if chk and chk.status == TaskStatus.REQUIRES_RECONCILIATION:
                return True
            if idempotency_hash:
                row = self.repo.get_execution_event_by_hash(
                    idempotency_hash=idempotency_hash,
                    task_id=task_id,
                )
                if row and row["status"] == "AMBIGUOUS":
                    return True
            return False

    def mark_step_completed(
        self,
        task_id: str,
        step_id: str,
        next_step: Optional[str] = None,
        state_updates: Optional[Dict[str, Any]] = None,
    ) -> TaskCheckpoint:
        """
        Transitions a step to completed.
        Removes step from pending_step_ids, appends to completed_step_ids,
        updates state_data, and sets next_step.
        Guarantees task cannot be silently marked completed if flagged for reconciliation.
        """
        with self._lock:
            chk = self.get_task_checkpoint(task_id)
            if not chk:
                raise KeyError(f"Task with ID '{task_id}' not found.")

            if chk.status == TaskStatus.REQUIRES_RECONCILIATION:
                raise ValueError(
                    f"Task '{task_id}' is flagged for reconciliation. "
                    "Operator must resolve reconciliation before completing steps."
                )

            if step_id not in chk.completed_step_ids:
                chk.completed_step_ids.append(step_id)

            if step_id in chk.pending_step_ids:
                chk.pending_step_ids.remove(step_id)

            if next_step:
                chk.current_step = next_step
            elif chk.pending_step_ids:
                # Advance to next pending step automatically
                chk.current_step = chk.pending_step_ids[0]
            else:
                chk.status = TaskStatus.COMPLETED
                chk.current_step = "COMPLETED"

            if state_updates:
                chk.state_data.update(state_updates)

            self.save_task_checkpoint(chk)
            return chk

    def flag_for_reconciliation(self, task_id: str, reason: str) -> TaskCheckpoint:
        """
        Flags an ambiguous or partially failed side effect for human reconciliation.
        Prevents any automated re-execution until human intervention.
        """
        with self._lock:
            chk = self.get_task_checkpoint(task_id)
            if not chk:
                raise KeyError(f"Task with ID '{task_id}' not found.")

            chk.status = TaskStatus.REQUIRES_RECONCILIATION
            chk.state_data["reconciliation_reason"] = reason
            chk.state_data["reconciliation_flagged_at"] = utc_now()
            self.save_task_checkpoint(chk)
            return chk

    def resolve_reconciliation(
        self,
        task_id: str,
        resolution: str,
        notes: str = "",
        next_step: Optional[str] = None,
    ) -> TaskCheckpoint:
        """
        Allows human operator to unblock a task flagged for reconciliation.
        - 'resume': unblocks task and resets status to RUNNING.
        - 'abort': marks task as FAILED with operator explanation.
        """
        with self._lock:
            chk = self.get_task_checkpoint(task_id)
            if not chk:
                raise KeyError(f"Task with ID '{task_id}' not found.")

            chk.state_data["reconciliation_resolved_at"] = utc_now()
            chk.state_data["reconciliation_resolution"] = resolution
            chk.state_data["reconciliation_notes"] = notes

            res_lower = resolution.lower().strip()
            if res_lower == "resume":
                chk.status = TaskStatus.RUNNING
                if next_step:
                    chk.current_step = next_step
                elif chk.pending_step_ids:
                    chk.current_step = chk.pending_step_ids[0]
            elif res_lower == "abort":
                chk.status = TaskStatus.FAILED
            else:
                raise ValueError(f"Invalid resolution '{resolution}'. Must be 'resume' or 'abort'.")

            self.save_task_checkpoint(chk)
            return chk

    # =========================================================================
    # Helpers
    # =========================================================================

    def _row_to_checkpoint(self, row: Any) -> TaskCheckpoint:
        """Decrypts and converts SQLite row into TaskCheckpoint."""
        decrypted_state = self.crypto.decrypt_json(row["encrypted_state"])
        return TaskCheckpoint(
            task_id=row["task_id"],
            workflow_id=row["workflow_id"],
            status=TaskStatus(row["status"]),
            current_step=row["current_step"],
            completed_step_ids=json.loads(row["completed_step_ids"]),
            pending_step_ids=json.loads(row["pending_step_ids"]),
            approval_references=json.loads(row["approval_references"]),
            retry_count=row["retry_count"],
            state_data=decrypted_state,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
