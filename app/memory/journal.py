"""
Durable Relational Execution Journal Service for Project Go 81.
Provides transactional intent registration, 2-phase dispatch state transitions,
parameter fingerprinting, anti-tamper idempotency enforcement, and task-level execution leases.
"""

import hashlib
import json
import logging
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.memory.database import DatabaseManager, utc_now
from app.memory.models import DispatchState, ExecutionJournalEntry

logger = logging.getLogger(__name__)

# Sanitization regex for confidential argument keys
SECRET_KEY_PATTERN = re.compile(
    r"(token|secret|password|key|auth|bearer|credential|cert|priv|access_key)",
    re.IGNORECASE,
)


def sanitize_parameters(params: Dict[str, Any], max_str_len: int = 4096) -> Dict[str, Any]:
    """
    Sanitizes action arguments to eliminate plaintext secrets and bounds memory growth.
    Replaces sensitive keys with '[REDACTED]' and truncates long strings.
    """
    if not isinstance(params, dict):
        return {}

    sanitized: Dict[str, Any] = {}
    for k, v in params.items():
        if SECRET_KEY_PATTERN.search(str(k)):
            sanitized[k] = "[REDACTED]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_parameters(v, max_str_len)
        elif isinstance(v, list):
            sanitized[k] = [
                sanitize_parameters(item, max_str_len) if isinstance(item, dict)
                else (str(item)[:max_str_len] + "...[truncated]" if isinstance(item, str) and len(item) > max_str_len else item)
                for item in v
            ]
        elif isinstance(v, str):
            if len(v) > max_str_len:
                sanitized[k] = v[:max_str_len] + "...[truncated]"
            else:
                sanitized[k] = v
        else:
            sanitized[k] = v
    return sanitized


def compute_param_hash(action: str, params: Dict[str, Any]) -> str:
    """Computes deterministic SHA-256 fingerprint representing action and parameters."""
    canonical_params = json.dumps(params, sort_keys=True, ensure_ascii=False)
    raw = f"{action}::{canonical_params}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExecutionJournalService:
    """
    Transactional Execution Journal Service for crash consistency and idempotency.
    Persists intents before dispatch, records real-time state transitions,
    and coordinates optimistic task leases.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._lock = threading.RLock()

    def _row_to_entry(self, row: Any) -> ExecutionJournalEntry:
        """Converts an SQLite row to an ExecutionJournalEntry model."""
        sanitized = {}
        if row["sanitized_params"]:
            try:
                sanitized = json.loads(row["sanitized_params"])
            except Exception:
                sanitized = {"raw": str(row["sanitized_params"])}

        return ExecutionJournalEntry(
            entry_id=row["entry_id"],
            task_id=row["task_id"],
            step_id=row["step_id"],
            attempt_id=row["attempt_id"],
            action=row["action"],
            idempotency_class=row["idempotency_class"],
            param_hash=row["param_hash"],
            sanitized_params=sanitized,
            dispatch_state=DispatchState(row["dispatch_state"]),
            approval_ref=row["approval_ref"],
            pid=row["pid"],
            process_creation_time=row["process_creation_time"],
            log_path=row["log_path"],
            exit_code=row["exit_code"],
            result_digest=row["result_digest"],
            error_message=row["error_message"],
            checkpoint_version=row["checkpoint_version"] or 1,
            recovery_attempts=row["recovery_attempts"] or 0,
            created_at=row["created_at"],
            dispatched_at=row["dispatched_at"],
            completed_at=row["completed_at"],
            updated_at=row["updated_at"],
        )

    def prepare_dispatch(
        self,
        task_id: str,
        step_id: str,
        action: str,
        idempotency_class: str,
        params: Dict[str, Any],
        approval_ref: Optional[str] = None,
        checkpoint_version: int = 1,
    ) -> ExecutionJournalEntry:
        """
        Phase 1: Pre-Execution Intent Persistence.
        Transactionally records a PREPARED state before an action is dispatched.
        """
        param_hash = compute_param_hash(action, params)
        sanitized = sanitize_parameters(params)
        attempt_id = f"attempt-{uuid.uuid4().hex[:12]}"
        entry_id = f"ej-{uuid.uuid4().hex[:12]}"
        now = utc_now()

        entry = ExecutionJournalEntry(
            entry_id=entry_id,
            task_id=task_id,
            step_id=step_id,
            attempt_id=attempt_id,
            action=action,
            idempotency_class=idempotency_class,
            param_hash=param_hash,
            sanitized_params=sanitized,
            dispatch_state=DispatchState.PREPARED,
            approval_ref=approval_ref,
            checkpoint_version=checkpoint_version,
            created_at=now,
            updated_at=now,
        )

        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO execution_journal (
                    entry_id, task_id, step_id, attempt_id, action, idempotency_class,
                    param_hash, sanitized_params, dispatch_state, approval_ref,
                    checkpoint_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    entry.entry_id,
                    entry.task_id,
                    entry.step_id,
                    entry.attempt_id,
                    entry.action,
                    entry.idempotency_class,
                    entry.param_hash,
                    json.dumps(entry.sanitized_params),
                    entry.dispatch_state.value,
                    entry.approval_ref,
                    entry.checkpoint_version,
                    entry.created_at,
                    entry.updated_at,
                ),
            )

        logger.info(
            f"Execution Journal: PREPARED intent recorded for task={task_id}, "
            f"step={step_id}, attempt={attempt_id}, action={action}"
        )
        return entry

    def record_dispatching(self, attempt_id: str) -> None:
        """Transitions intent to DISPATCHING immediately before launching the action."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, dispatched_at = ?, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.DISPATCHING.value, now, now, attempt_id),
            )

    def record_running_process(
        self,
        attempt_id: str,
        pid: int,
        process_creation_time: float,
        log_path: str,
    ) -> None:
        """Records active OS subprocess metadata under RUNNING state."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, pid = ?, process_creation_time = ?,
                    log_path = ?, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.RUNNING.value, pid, process_creation_time, log_path, now, attempt_id),
            )

    def record_success(
        self,
        attempt_id: str,
        result_digest: Optional[str] = None,
        exit_code: int = 0,
    ) -> None:
        """Phase 2: Confirms successful execution completion."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, completed_at = ?, exit_code = ?,
                    result_digest = ?, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.SUCCEEDED.value, now, exit_code, result_digest, now, attempt_id),
            )

    def record_failure(
        self,
        attempt_id: str,
        error_message: str,
        exit_code: Optional[int] = None,
    ) -> None:
        """Records explicit failure of a dispatched action."""
        now = utc_now()
        sanitized_error = error_message[:2048] if error_message else "Unknown execution error"
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, completed_at = ?, exit_code = ?,
                    error_message = ?, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.FAILED.value, now, exit_code, sanitized_error, now, attempt_id),
            )

    def record_waiting_approval(self, attempt_id: str, approval_ref: Optional[str] = None) -> None:
        """Transitions state to WAITING_APPROVAL."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, approval_ref = COALESCE(?, approval_ref), updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.WAITING_APPROVAL.value, approval_ref, now, attempt_id),
            )

    def record_unknown_outcome(self, attempt_id: str, reason: str) -> None:
        """Records ambiguous outcome where side effect status cannot be proven."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, error_message = ?, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.UNKNOWN_OUTCOME.value, reason[:2048], now, attempt_id),
            )

    def record_reconciliation_required(self, attempt_id: str, reason: str) -> None:
        """Quarantines the attempt for human reconciliation."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, error_message = ?, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.RECONCILIATION_REQUIRED.value, reason[:2048], now, attempt_id),
            )

    def record_cancelled(self, attempt_id: str, reason: str = "Task cancelled") -> None:
        """Marks attempt as CANCELLED."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            conn.execute(
                """
                UPDATE execution_journal
                SET dispatch_state = ?, error_message = ?, completed_at = ?, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (DispatchState.CANCELLED.value, reason[:2048], now, now, attempt_id),
            )

    def increment_recovery_attempts(self, attempt_id: str) -> int:
        """Increments recovery attempt counter and returns the new count."""
        now = utc_now()
        with self._lock, self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE execution_journal
                SET recovery_attempts = recovery_attempts + 1, updated_at = ?
                WHERE attempt_id = ?;
                """,
                (now, attempt_id),
            )
            cursor.execute(
                "SELECT recovery_attempts FROM execution_journal WHERE attempt_id = ?;",
                (attempt_id,),
            )
            row = cursor.fetchone()
            return int(row[0]) if (row and row[0] is not None) else 1

    def is_step_already_executed(
        self,
        task_id: str,
        step_id: str,
        param_hash: Optional[str] = None,
    ) -> bool:
        """
        Anti-Replay Idempotency Guard:
        Checks whether this exact step has already SUCCEEDED in the execution journal.
        If param_hash is provided, verifies that arguments matched.
        """
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if param_hash:
                cursor.execute(
                    """
                    SELECT 1 FROM execution_journal
                    WHERE task_id = ? AND step_id = ? AND dispatch_state = 'SUCCEEDED' AND param_hash = ?
                    LIMIT 1;
                    """,
                    (task_id, step_id, param_hash),
                )
            else:
                cursor.execute(
                    """
                    SELECT 1 FROM execution_journal
                    WHERE task_id = ? AND step_id = ? AND dispatch_state = 'SUCCEEDED'
                    LIMIT 1;
                    """,
                    (task_id, step_id),
                )
            return cursor.fetchone() is not None
        finally:
            conn.close()

    def get_latest_entry_for_step(self, task_id: str, step_id: str) -> Optional[ExecutionJournalEntry]:
        """Fetches the most recent journal entry for a specific step."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM execution_journal
                WHERE task_id = ? AND step_id = ?
                ORDER BY created_at DESC LIMIT 1;
                """,
                (task_id, step_id),
            )
            row = cursor.fetchone()
            if row:
                return self._row_to_entry(row)
            return None
        finally:
            conn.close()

    def get_journal_for_task(self, task_id: str) -> List[ExecutionJournalEntry]:
        """Fetches all journal entries for a task in chronological order."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM execution_journal
                WHERE task_id = ?
                ORDER BY created_at ASC;
                """,
                (task_id,),
            )
            return [self._row_to_entry(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_incomplete_entries(self, task_id: Optional[str] = None) -> List[ExecutionJournalEntry]:
        """
        Fetches entries in non-terminal states across reboot / restart:
        PREPARED, DISPATCHING, RUNNING, UNKNOWN_OUTCOME, RECONCILIATION_REQUIRED.
        """
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            query = """
                SELECT * FROM execution_journal
                WHERE dispatch_state IN (
                    'PREPARED', 'DISPATCHING', 'RUNNING',
                    'UNKNOWN_OUTCOME', 'RECONCILIATION_REQUIRED', 'WAITING_APPROVAL'
                )
            """
            params: List[Any] = []
            if task_id:
                query += " AND task_id = ?"
                params.append(task_id)
            query += " ORDER BY created_at ASC;"
            cursor.execute(query, params)
            return [self._row_to_entry(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    # ========================================================================
    # Task Lease & Optimistic Concurrency Controls
    # ========================================================================

    def acquire_task_lease(
        self,
        task_id: str,
        lease_holder: str,
        ttl_seconds: float = 30.0,
    ) -> bool:
        """
        Optimistic Concurrency Lease Acquisition.
        Atomically grants exclusive execution control of task_id to lease_holder.
        Succeeds only if:
        1. Task is unleased, OR
        2. Lease is already held by this lease_holder, OR
        3. Prior lease has expired.
        """
        now = time.time()
        expires_at = now + ttl_seconds
        now_iso = utc_now()

        with self._lock, self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT lease_holder, lease_expires_at FROM task_checkpoints WHERE task_id = ?;",
                (task_id,),
            )
            row = cursor.fetchone()
            if not row:
                # Task checkpoint has not yet been persisted to SQLite (brand new task).
                # Initiator holds initial execution lease.
                return True

            holder, exp = row[0], row[1]
            if holder is not None and holder != lease_holder and (exp is not None and exp >= now):
                logger.warning(
                    f"Task lease conflict: task={task_id} is currently held by another worker ('{holder}')."
                )
                return False

            cursor.execute(
                """
                UPDATE task_checkpoints
                SET lease_holder = ?,
                    lease_expires_at = ?,
                    checkpoint_version = checkpoint_version + 1,
                    updated_at = ?
                WHERE task_id = ?;
                """,
                (lease_holder, expires_at, now_iso, task_id),
            )
            logger.debug(
                f"Task lease acquired: task={task_id}, holder={lease_holder}, "
                f"expires_in={ttl_seconds}s"
            )
            return True

    def renew_task_lease(
        self,
        task_id: str,
        lease_holder: str,
        ttl_seconds: float = 30.0,
    ) -> bool:
        """Extends lease expiration for active worker."""
        now = time.time()
        expires_at = now + ttl_seconds
        now_iso = utc_now()

        with self._lock, self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE task_checkpoints
                SET lease_expires_at = ?, updated_at = ?
                WHERE task_id = ? AND lease_holder = ?;
                """,
                (expires_at, now_iso, task_id, lease_holder),
            )
            return cursor.rowcount > 0

    def release_task_lease(self, task_id: str, lease_holder: str) -> bool:
        """Releases the task lease upon step/task completion or pause."""
        now_iso = utc_now()
        with self._lock, self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE task_checkpoints
                SET lease_holder = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE task_id = ? AND (lease_holder = ? OR lease_expires_at < ?);
                """,
                (now_iso, task_id, lease_holder, time.time()),
            )
            return cursor.rowcount > 0

    def clear_stale_leases(self, now_ts: Optional[float] = None) -> int:
        """Cleans up expired leases across application restarts."""
        cutoff = now_ts or time.time()
        now_iso = utc_now()
        with self._lock, self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE task_checkpoints
                SET lease_holder = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE lease_expires_at IS NOT NULL AND lease_expires_at < ?;
                """,
                (now_iso, cutoff),
            )
            return cursor.rowcount
