"""
Repository layer for Go 81 Memory & Security Subsystem.
Handles low-level parameterized SQL operations for memories, task checkpoints, and security policies.
"""

import os
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Union
from app.memory.database import DatabaseManager, utc_now
from app.memory.models import MemoryRecord, TaskCheckpoint, TaskExecutionEvent


def normalize_id(identifier: Any) -> str:
    """
    Normalizes any identifier (str, UUID instance, unhyphenated hex, uppercase, with whitespace)
    to a trimmed lowercase canonical string.
    """
    if identifier is None:
        return ""
    if isinstance(identifier, uuid.UUID):
        return str(identifier).lower()
    raw = str(identifier).strip()
    try:
        parsed = uuid.UUID(raw)
        return str(parsed).lower()
    except (ValueError, AttributeError):
        return raw.lower()


class MemoryRepository:
    """Encapsulates SQL operations on the SQLite database."""

    def __init__(self, db: DatabaseManager):
        self.db = db

    # =========================================================================
    # Memories (Episodic & Semantic)
    # =========================================================================

    def insert_memory(self, record: MemoryRecord, encrypted_payload: str) -> None:
        """Inserts a new memory record with its encrypted ciphertext payload."""
        sql = """
            INSERT INTO memories (
                id, memory_type, category, verification_status, confidence,
                dedup_hash, source_ref, schema_version, project_id, encrypted_payload,
                created_at, updated_at, expires_at, is_deleted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.transaction() as conn:
            conn.execute(
                sql,
                (
                    record.id,
                    record.memory_type.value if hasattr(record.memory_type, "value") else str(record.memory_type),
                    record.category,
                    record.verification_status.value if hasattr(record.verification_status, "value") else str(record.verification_status),
                    record.confidence,
                    record.dedup_hash,
                    record.source_ref,
                    record.schema_version,
                    getattr(record, "project_id", None),
                    encrypted_payload,
                    record.created_at,
                    record.updated_at,
                    record.expires_at,
                    1 if record.is_deleted else 0,
                ),
            )

    def get_memory_row(self, memory_id: Union[str, uuid.UUID, Any], include_deleted: bool = False) -> Optional[sqlite3.Row]:
        """Fetches a single raw database row by ID, supporting canonical UUIDs, whitespace stripping, and case normalization."""
        if memory_id is None:
            return None
        raw_id = str(memory_id).strip()
        canonical_id = normalize_id(memory_id)

        sql = "SELECT * FROM memories WHERE (id = ? OR id = ? OR LOWER(id) = LOWER(?))"
        if not include_deleted:
            sql += " AND is_deleted = 0"
        conn = self.db.get_connection()
        try:
            return conn.execute(sql, (raw_id, canonical_id, canonical_id)).fetchone()
        finally:
            conn.close()

    def find_by_dedup_hash(self, dedup_hash: str) -> Optional[sqlite3.Row]:
        """Looks up an active semantic memory by its deterministic deduplication hash."""
        conn = self.db.get_connection()
        try:
            return conn.execute(
                "SELECT * FROM memories WHERE dedup_hash = ? AND is_deleted = 0;",
                (dedup_hash,),
            ).fetchone()
        finally:
            conn.close()

    def update_memory_row(
        self,
        memory_id: Union[str, uuid.UUID, Any],
        encrypted_payload: Optional[str] = None,
        verification_status: Optional[str] = None,
        confidence: Optional[float] = None,
    ) -> bool:
        """Updates verification status, confidence, payload, and updated_at."""
        raw_id = str(memory_id).strip()
        canonical_id = normalize_id(memory_id)

        clauses = ["updated_at = ?"]
        params: List[Any] = [utc_now()]

        if encrypted_payload is not None:
            clauses.append("encrypted_payload = ?")
            params.append(encrypted_payload)
        if verification_status is not None:
            clauses.append("verification_status = ?")
            params.append(verification_status)
        if confidence is not None:
            clauses.append("confidence = ?")
            params.append(confidence)

        params.extend([raw_id, canonical_id, canonical_id])
        sql = f"UPDATE memories SET {', '.join(clauses)} WHERE (id = ? OR id = ? OR LOWER(id) = LOWER(?)) AND is_deleted = 0;"

        with self.db.transaction() as conn:
            cursor = conn.execute(sql, params)
            return cursor.rowcount > 0

    def soft_delete_memory(self, memory_id: Union[str, uuid.UUID, Any]) -> bool:
        """Marks a record as deleted (tombstone) without removing physical row."""
        raw_id = str(memory_id).strip()
        canonical_id = normalize_id(memory_id)
        sql = "UPDATE memories SET is_deleted = 1, updated_at = ? WHERE (id = ? OR id = ? OR LOWER(id) = LOWER(?)) AND is_deleted = 0;"
        with self.db.transaction() as conn:
            cursor = conn.execute(sql, (utc_now(), raw_id, canonical_id, canonical_id))
            return cursor.rowcount > 0

    def hard_delete_memory(self, memory_id: Union[str, uuid.UUID, Any]) -> bool:
        """
        Permanently destroys a memory record:
        1. Overwrites encrypted_payload with random cryptographic garbage.
        2. Deletes the row from SQLite.
        """
        raw_id = str(memory_id).strip()
        canonical_id = normalize_id(memory_id)
        garbage = os.urandom(64).hex()
        with self.db.transaction() as conn:
            # Overwrite first
            conn.execute(
                "UPDATE memories SET encrypted_payload = ?, updated_at = ? WHERE (id = ? OR id = ? OR LOWER(id) = LOWER(?));",
                (garbage, utc_now(), raw_id, canonical_id, canonical_id),
            )
            # Delete row
            cursor = conn.execute(
                "DELETE FROM memories WHERE (id = ? OR id = ? OR LOWER(id) = LOWER(?));",
                (raw_id, canonical_id, canonical_id),
            )
            return cursor.rowcount > 0

    def list_active_memories(
        self,
        memory_type: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        include_expired: bool = False,
    ) -> List[sqlite3.Row]:
        """Lists active non-deleted memories ordered chronologically (newest first)."""
        clauses = ["is_deleted = 0"]
        params: List[Any] = []

        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(utc_now())

        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)

        if category:
            clauses.append("category = ?")
            params.append(category)

        where_sql = f"WHERE {' AND '.join(clauses)}"
        sql = f"SELECT * FROM memories {where_sql} ORDER BY created_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        conn = self.db.get_connection()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def get_all_active_candidate_rows(
        self,
        memory_type: Optional[str] = None,
        category: Optional[str] = None,
        include_expired: bool = False,
    ) -> List[sqlite3.Row]:
        """Fetches all active candidate rows for local in-process decryption & search/export."""
        clauses = ["is_deleted = 0"]
        params: List[Any] = []

        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            params.append(utc_now())

        if memory_type:
            clauses.append("memory_type = ?")
            params.append(memory_type)

        if category:
            clauses.append("category = ?")
            params.append(category)

        where_sql = f"WHERE {' AND '.join(clauses)}"
        sql = f"SELECT * FROM memories {where_sql} ORDER BY created_at DESC;"

        conn = self.db.get_connection()
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def purge_expired_records(self) -> int:
        """Soft-deletes all records that have passed their expiration timestamp."""
        now = utc_now()
        sql = """
            UPDATE memories
            SET is_deleted = 1, updated_at = ?
            WHERE is_deleted = 0 AND expires_at IS NOT NULL AND expires_at <= ?;
        """
        with self.db.transaction() as conn:
            cursor = conn.execute(sql, (now, now))
            return cursor.rowcount

    # =========================================================================
    # Task Checkpoints & Execution Events
    # =========================================================================

    def save_task_checkpoint(self, checkpoint: TaskCheckpoint, encrypted_state: str) -> None:
        """Upserts a persistent task checkpoint."""
        import json
        sql = """
            INSERT INTO task_checkpoints (
                task_id, workflow_id, status, current_step, completed_step_ids,
                pending_step_ids, approval_references, retry_count,
                encrypted_state, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                workflow_id = excluded.workflow_id,
                status = excluded.status,
                current_step = excluded.current_step,
                completed_step_ids = excluded.completed_step_ids,
                pending_step_ids = excluded.pending_step_ids,
                approval_references = excluded.approval_references,
                retry_count = excluded.retry_count,
                encrypted_state = excluded.encrypted_state,
                updated_at = excluded.updated_at;
        """
        with self.db.transaction() as conn:
            conn.execute(
                sql,
                (
                    checkpoint.task_id,
                    checkpoint.workflow_id,
                    checkpoint.status.value if hasattr(checkpoint.status, "value") else str(checkpoint.status),
                    checkpoint.current_step,
                    json.dumps(checkpoint.completed_step_ids),
                    json.dumps(checkpoint.pending_step_ids),
                    json.dumps(checkpoint.approval_references),
                    checkpoint.retry_count,
                    encrypted_state,
                    checkpoint.created_at,
                    checkpoint.updated_at,
                ),
            )

    def get_task_checkpoint_row(self, task_id: str) -> Optional[sqlite3.Row]:
        """Fetches a task checkpoint by task ID with trimmed whitespace support."""
        raw_id = str(task_id).strip()
        conn = self.db.get_connection()
        try:
            return conn.execute(
                "SELECT * FROM task_checkpoints WHERE (task_id = ? OR task_id = ?);",
                (task_id, raw_id),
            ).fetchone()
        finally:
            conn.close()

    def list_incomplete_task_rows(self) -> List[sqlite3.Row]:
        """Fetches all tasks that have not completed or permanently failed."""
        conn = self.db.get_connection()
        try:
            return conn.execute(
                """
                SELECT * FROM task_checkpoints
                WHERE status NOT IN ('COMPLETED', 'FAILED')
                ORDER BY updated_at DESC;
                """
            ).fetchall()
        finally:
            conn.close()

    def save_execution_event(self, event: TaskExecutionEvent, encrypted_details: str) -> None:
        """Records an execution event with an idempotency hash for side-effect guard."""
        sql = """
            INSERT INTO execution_events (
                event_id, task_id, step_id, action, status, idempotency_hash,
                encrypted_details, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
        """
        with self.db.transaction() as conn:
            conn.execute(
                sql,
                (
                    event.event_id,
                    event.task_id,
                    event.step_id,
                    event.action,
                    event.status,
                    event.idempotency_hash,
                    encrypted_details,
                    event.recorded_at,
                ),
            )

    def get_execution_event_by_hash(
        self,
        idempotency_hash: str,
        task_id: Optional[str] = None,
        step_id: Optional[str] = None,
    ) -> Optional[sqlite3.Row]:
        """
        Checks if an action with identical input hash has already been recorded.
        When task_id and/or step_id are provided, scopes lookup to avoid cross-task false positives.
        """
        clauses = ["idempotency_hash = ?"]
        params: List[Any] = [idempotency_hash]
        if task_id:
            clauses.append("task_id = ?")
            params.append(str(task_id).strip())
        if step_id:
            clauses.append("step_id = ?")
            params.append(str(step_id).strip())

        sql = f"SELECT * FROM execution_events WHERE {' AND '.join(clauses)} ORDER BY recorded_at DESC LIMIT 1;"
        conn = self.db.get_connection()
        try:
            return conn.execute(sql, params).fetchone()
        finally:
            conn.close()

    def list_execution_events_for_task(self, task_id: str) -> List[sqlite3.Row]:
        """Fetches all execution event rows for a given task ID."""
        conn = self.db.get_connection()
        try:
            return conn.execute(
                "SELECT * FROM execution_events WHERE task_id = ? ORDER BY recorded_at ASC;",
                (task_id,),
            ).fetchall()
        finally:
            conn.close()

    def get_pending_events_for_task(self, task_id: str) -> List[sqlite3.Row]:
        """Fetches execution events in 'PENDING' status for a task, indicating crash windows."""
        conn = self.db.get_connection()
        try:
            return conn.execute(
                "SELECT * FROM execution_events WHERE task_id = ? AND status = 'PENDING' ORDER BY recorded_at ASC;",
                (task_id.strip(),),
            ).fetchall()
        finally:
            conn.close()

    # =========================================================================
    # Permission Policies
    # =========================================================================

    def get_permission_policy(self, action: str) -> Optional[sqlite3.Row]:
        """Fetches default risk and approval requirements for an action."""
        conn = self.db.get_connection()
        try:
            return conn.execute(
                "SELECT * FROM permission_policies WHERE action = ?;",
                (action,),
            ).fetchone()
        finally:
            conn.close()
