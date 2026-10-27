"""
Project Flight Recorder Subsystem for Project Go 81.

Provides:
- Durable, transaction-backed local event recording for meaningful development activities.
- Separation of verified observations from model-generated inferences.
- Automated secret redaction for command outputs, metadata, and summaries.
- Bounded retention policy to prevent uncontrolled database growth.
- Evidence digest hashing (SHA-256) and bounded excerpt capture.
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.memory.database import DatabaseManager
from app.memory.models import (
    EventQueryFilter,
    EventSourceType,
    EvidenceRecord,
    EvidenceRecordCreate,
    FlightRecorderEvent,
    FlightRecorderEventCreate,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

# ============================================================================
# Secret Redaction Patterns
# ============================================================================

REDACTION_PATTERNS = [
    # Generic API Keys / Tokens (OpenAI, GitHub, Anthropic, AWS, etc.)
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"gh[pousr]-[a-zA-Z0-9]{20,}", re.IGNORECASE), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(api[_-]?key|secret|password|token)\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE), r"\1='[REDACTED]'"),
    (re.compile(r"-----BEGIN[ A-Z0-9_-]+PRIVATE KEY-----.*?-----END[ A-Z0-9_-]+PRIVATE KEY-----", re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(https?://[^:]+:)[^@]+(@)", re.IGNORECASE), r"\1[REDACTED_PASS]\2"),
]


def redact_sensitive_text(text: Optional[str]) -> Optional[str]:
    """Redacts secrets, tokens, and credentials from string payloads."""
    if not text:
        return text
    sanitized = text
    for pattern, replacement in REDACTION_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def redact_dictionary(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively redacts dictionary values."""
    clean: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            clean[k] = redact_sensitive_text(v)
        elif isinstance(v, dict):
            clean[k] = redact_dictionary(v)
        elif isinstance(v, list):
            clean[k] = [
                redact_sensitive_text(item) if isinstance(item, str)
                else (redact_dictionary(item) if isinstance(item, dict) else item)
                for item in v
            ]
        else:
            clean[k] = v
    return clean


# ============================================================================
# Flight Recorder Service
# ============================================================================

class FlightRecorderService:
    """
    Manages the durable Project Flight Recorder and Evidence Store.
    Thread-safe and transaction-backed via DatabaseManager.
    """

    def __init__(self, db: DatabaseManager, max_excerpt_length: int = 2000):
        self.db = db
        self.max_excerpt_length = max_excerpt_length

    # ------------------------------------------------------------------------
    # Evidence Recording
    # ------------------------------------------------------------------------

    def store_evidence(self, req: EvidenceRecordCreate) -> EvidenceRecord:
        """
        Stores command metadata, digests, and a bounded, redacted excerpt.
        Never duplicates large raw file contents or unbounded output streams.
        """
        evidence_id = req.evidence_id or f"ev-{uuid.uuid4().hex[:12]}"
        created_at = utc_now_iso()

        stdout_digest = None
        stderr_digest = None
        redacted_excerpt = req.redacted_excerpt

        if req.raw_stdout is not None:
            stdout_digest = hashlib.sha256(req.raw_stdout.encode("utf-8", errors="replace")).hexdigest()
            if not redacted_excerpt:
                # Capture bounded head of stdout
                bounded_raw = req.raw_stdout[: self.max_excerpt_length]
                redacted_excerpt = redact_sensitive_text(bounded_raw)

        if req.raw_stderr is not None:
            stderr_digest = hashlib.sha256(req.raw_stderr.encode("utf-8", errors="replace")).hexdigest()
            if not redacted_excerpt and req.raw_stderr:
                bounded_err = req.raw_stderr[: self.max_excerpt_length]
                redacted_excerpt = redact_sensitive_text(bounded_err)

        redacted_command = redact_sensitive_text(req.command)

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO evidence_store (
                    evidence_id, evidence_type, command, exit_code,
                    started_at, completed_at, duration_ms, working_dir,
                    stdout_digest, stderr_digest, redacted_excerpt,
                    is_agent_hypothesis, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    evidence_id,
                    req.evidence_type,
                    redacted_command,
                    req.exit_code,
                    req.started_at,
                    req.completed_at,
                    req.duration_ms,
                    req.working_dir,
                    stdout_digest,
                    stderr_digest,
                    redacted_excerpt,
                    1 if req.is_agent_hypothesis else 0,
                    created_at,
                ),
            )

        return EvidenceRecord(
            evidence_id=evidence_id,
            evidence_type=req.evidence_type,
            command=redacted_command,
            exit_code=req.exit_code,
            started_at=req.started_at,
            completed_at=req.completed_at,
            duration_ms=req.duration_ms,
            working_dir=req.working_dir,
            stdout_digest=stdout_digest,
            stderr_digest=stderr_digest,
            redacted_excerpt=redacted_excerpt,
            is_agent_hypothesis=req.is_agent_hypothesis,
            created_at=created_at,
        )

    def get_evidence(self, evidence_id: str) -> Optional[EvidenceRecord]:
        """Retrieves a single evidence record by ID."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT evidence_id, evidence_type, command, exit_code,
                       started_at, completed_at, duration_ms, working_dir,
                       stdout_digest, stderr_digest, redacted_excerpt,
                       is_agent_hypothesis, created_at
                FROM evidence_store
                WHERE evidence_id = ?;
                """,
                (evidence_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return EvidenceRecord(
                evidence_id=row["evidence_id"],
                evidence_type=row["evidence_type"],
                command=row["command"],
                exit_code=row["exit_code"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                duration_ms=row["duration_ms"],
                working_dir=row["working_dir"],
                stdout_digest=row["stdout_digest"],
                stderr_digest=row["stderr_digest"],
                redacted_excerpt=row["redacted_excerpt"],
                is_agent_hypothesis=bool(row["is_agent_hypothesis"]),
                created_at=row["created_at"],
            )
        finally:
            conn.close()

    # ------------------------------------------------------------------------
    # Event Recording & Provenance Guard
    # ------------------------------------------------------------------------

    def record_event(self, req: FlightRecorderEventCreate) -> FlightRecorderEvent:
        """
        Records a new development event with strict provenance enforcement.
        Enforces:
        1. Agent-generated hypotheses MUST be tagged source_type='inference'.
        2. All text and metadata are redacted before writing to disk.
        3. Stable event_id and UTC timestamp assigned.
        """
        event_id = req.event_id or f"evt-{uuid.uuid4().hex[:12]}"
        timestamp = utc_now_iso()

        # Provenance invariant: if the actor is an LLM or reasoning component,
        # it cannot claim to be an objective observation.
        source_type = req.source_type
        actor_lower = req.actor.lower()
        if any(term in actor_lower for term in ("model", "llm", "gemma", "agent.reasoning", "hypothesis")):
            if source_type == EventSourceType.OBSERVATION:
                logger.warning(
                    f"Provenance enforcement: Actor '{req.actor}' cannot record verified observation. "
                    "Coercing source_type to 'inference'."
                )
                source_type = EventSourceType.INFERENCE

        clean_summary = redact_sensitive_text(req.summary) or ""
        clean_metadata = redact_dictionary(req.metadata)

        evidence_refs_json = json.dumps(req.evidence_refs)
        metadata_json = json.dumps(clean_metadata)

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO flight_recorder_events (
                    event_id, project_id, task_id, timestamp, event_type,
                    source_type, actor, summary, phase, evidence_refs,
                    metadata, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    event_id,
                    req.project_id,
                    req.task_id,
                    timestamp,
                    req.event_type,
                    source_type.value,
                    req.actor,
                    clean_summary,
                    req.phase,
                    evidence_refs_json,
                    metadata_json,
                    1,
                ),
            )

        return FlightRecorderEvent(
            event_id=event_id,
            project_id=req.project_id,
            task_id=req.task_id,
            timestamp=timestamp,
            event_type=req.event_type,
            source_type=source_type,
            actor=req.actor,
            summary=clean_summary,
            phase=req.phase,
            evidence_refs=req.evidence_refs,
            metadata=clean_metadata,
            schema_version=1,
        )

    def get_event(self, event_id: str) -> Optional[FlightRecorderEvent]:
        """Retrieves a single flight recorder event by ID."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT event_id, project_id, task_id, timestamp, event_type,
                       source_type, actor, summary, phase, evidence_refs,
                       metadata, schema_version
                FROM flight_recorder_events
                WHERE event_id = ?;
                """,
                (event_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event(row)
        finally:
            conn.close()

    def query_events(self, f: EventQueryFilter) -> List[FlightRecorderEvent]:
        """
        Performs chronological, filtered event queries across projects and tasks.
        Ordered by timestamp ASC for reproducible replay.
        """
        conn = self.db.get_connection()
        try:
            query = """
                SELECT event_id, project_id, task_id, timestamp, event_type,
                       source_type, actor, summary, phase, evidence_refs,
                       metadata, schema_version
                FROM flight_recorder_events
                WHERE 1=1
            """
            params: List[Any] = []

            if f.project_id:
                query += " AND project_id = ?"
                params.append(f.project_id)
            if f.task_id:
                query += " AND task_id = ?"
                params.append(f.task_id)
            if f.event_type:
                query += " AND event_type = ?"
                params.append(f.event_type)
            if f.source_type:
                query += " AND source_type = ?"
                params.append(f.source_type.value)
            if f.start_time:
                query += " AND timestamp >= ?"
                params.append(f.start_time)
            if f.end_time:
                query += " AND timestamp <= ?"
                params.append(f.end_time)

            query += " ORDER BY timestamp ASC LIMIT ? OFFSET ?;"
            params.extend([f.limit, f.offset])

            cursor = conn.cursor()
            cursor.execute(query, params)
            return [self._row_to_event(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    # Alias for API consistency
    list_events = query_events

    def get_event_with_evidence(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Resolves an event along with all its linked evidence records."""
        event = self.get_event(event_id)
        if not event:
            return None
        evidence_records = []
        for ref_id in event.evidence_refs:
            ev = self.get_evidence(ref_id)
            if ev:
                evidence_records.append(ev.model_dump())

        data = event.model_dump()
        data["resolved_evidence"] = evidence_records
        return data

    # ------------------------------------------------------------------------
    # Bounded Retention Policy
    # ------------------------------------------------------------------------

    def prune_events(
        self,
        project_id: Optional[str] = None,
        max_events: int = 5000,
        retention_days: Optional[int] = None,
    ) -> int:
        """
        Enforces bounded retention.
        Removes oldest events exceeding max_events cap per project, or older than retention_days.
        """
        deleted_count = 0
        with self.db.transaction() as conn:
            # 1. Prune by age if retention_days specified
            if retention_days is not None and retention_days > 0:
                cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
                if project_id:
                    cursor = conn.execute(
                        "DELETE FROM flight_recorder_events WHERE project_id = ? AND timestamp < ?;",
                        (project_id, cutoff),
                    )
                else:
                    cursor = conn.execute(
                        "DELETE FROM flight_recorder_events WHERE timestamp < ?;",
                        (cutoff,),
                    )
                deleted_count += cursor.rowcount

            # 2. Prune by max_events threshold
            if max_events > 0:
                if project_id:
                    # Count existing
                    cursor = conn.execute(
                        "SELECT COUNT(*) FROM flight_recorder_events WHERE project_id = ?;",
                        (project_id,),
                    )
                    total = cursor.fetchone()[0]
                    if total > max_events:
                        to_prune = total - max_events
                        cursor = conn.execute(
                            """
                            DELETE FROM flight_recorder_events
                            WHERE event_id IN (
                                SELECT event_id FROM flight_recorder_events
                                WHERE project_id = ?
                                ORDER BY timestamp ASC
                                LIMIT ?
                            );
                            """,
                            (project_id, to_prune),
                        )
                        deleted_count += cursor.rowcount

        return deleted_count

    def prune_orphaned_evidence(self, retention_days: int = 30) -> int:
        """
        Prunes evidence records ONLY if they are:
        1. Older than retention_days, AND
        2. NOT referenced by any retained event in flight_recorder_events.
        Guarantees that active events never lose their underlying evidence.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
        with self.db.transaction() as conn:
            # Gather all referenced evidence_ids
            cursor = conn.execute("SELECT evidence_refs FROM flight_recorder_events WHERE evidence_refs != '[]';")
            referenced_ids = set()
            for r in cursor.fetchall():
                try:
                    refs = json.loads(r[0])
                    if isinstance(refs, list):
                        referenced_ids.update(refs)
                except Exception:
                    pass

            # Query candidates older than cutoff
            cursor = conn.execute("SELECT evidence_id FROM evidence_store WHERE created_at < ?;", (cutoff,))
            candidate_ids = [row[0] for row in cursor.fetchall()]

            # Filter only orphaned candidates
            orphaned = [eid for eid in candidate_ids if eid not in referenced_ids]
            if not orphaned:
                return 0

            placeholders = ",".join(["?"] * len(orphaned))
            conn.execute(f"DELETE FROM evidence_store WHERE evidence_id IN ({placeholders});", orphaned)
            return len(orphaned)

    # ------------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------------

    def _row_to_event(self, row: Any) -> FlightRecorderEvent:
        evidence_refs = []
        if row["evidence_refs"]:
            try:
                evidence_refs = json.loads(row["evidence_refs"])
            except Exception:
                evidence_refs = []

        metadata = {}
        if row["metadata"]:
            try:
                metadata = json.loads(row["metadata"])
            except Exception:
                metadata = {}

        return FlightRecorderEvent(
            event_id=row["event_id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            source_type=EventSourceType(row["source_type"]),
            actor=row["actor"],
            summary=row["summary"],
            phase=row["phase"],
            evidence_refs=evidence_refs,
            metadata=metadata,
            schema_version=row["schema_version"],
        )
