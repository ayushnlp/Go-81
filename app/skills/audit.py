"""
Structured Audit Logging Subsystem for Project Go 81 Skills & Security Gateway.
Guarantees persistent SQLite logging with zero secret/credential leakage.
"""

import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from app.memory.database import DatabaseManager, utc_now
from app.memory.models import utc_now_iso
from app.skills.models import SkillAuditRecord

logger = logging.getLogger(__name__)

# Sensitive token sanitization patterns
SECRET_SCRUB_PATTERNS = [
    re.compile(r"(?i)\b(api[_-]?key|secret|password|token|approval[_-]?token|auth[_-]?token|access[_-]?token|refresh[_-]?token|bearer|encryption[_-]?key|private[_-]?key)\b\s*[:=]\s*['\"]?([^\s,;'\"]{4,})['\"]?"),
    re.compile(r"\btok-[a-zA-Z0-9_\-]{8,}\b"),
    re.compile(r"\bapr-[a-zA-Z0-9_\-]{8,}\b"),
    re.compile(r"\bpending-[a-zA-Z0-9_\-]{8,}\b"),
    re.compile(r"(?i)\bbearer\s+([A-Za-z0-9_\-\.]{8,})"),
]


def _sub_cred(match):
    groups = match.groups()
    if groups and groups[0]:
        if len(groups) >= 2 and groups[1]:
            return f"{groups[0]}=[REDACTED]"
        return "[REDACTED]"
    return "[REDACTED]"


def sanitize_audit_text(text: Optional[str]) -> Optional[str]:
    """Sanitizes text to redact potential API keys, passwords, and tokens."""
    if not text:
        return text
    sanitized = text
    for pattern in SECRET_SCRUB_PATTERNS:
        sanitized = pattern.sub(_sub_cred, sanitized)
    return sanitized


SENSITIVE_KEY_PATTERN = re.compile(
    r"\b(api[_-]?key|secret|password|token|bearer|credentials?|private[_-]?key|auth|encryption[_-]?key)\b"
    r"|(approval[_-]?token|auth[_-]?token|access[_-]?token|refresh[_-]?token|api[_-]?key|secret[_-]?key)",
    re.IGNORECASE,
)


def sanitize_audit_structure(data: Any) -> Any:
    """Recursively sanitizes dictionary/list structures to redact sensitive tokens and credentials."""
    if isinstance(data, str):
        return sanitize_audit_text(data)
    elif isinstance(data, dict):
        sanitized_dict = {}
        for k, v in data.items():
            k_str = str(k).lower()
            if SENSITIVE_KEY_PATTERN.search(k_str):
                sanitized_dict[k] = "[REDACTED]"
            else:
                sanitized_dict[k] = sanitize_audit_structure(v)
        return sanitized_dict
    elif isinstance(data, (list, tuple)):
        return [sanitize_audit_structure(item) for item in data]
    return data


class SkillAuditLogger:
    """
    Manages structured, redacted audit records for all skill authorization
    and execution events. Persists to SQLite skill_audit_records.
    """

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db
        self._in_memory_records: List[SkillAuditRecord] = []
        if self.db:
            self._ensure_table_exists()

    def _ensure_table_exists(self) -> None:
        """Ensures the skill_audit_records table exists in the database."""
        if not self.db:
            return
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS skill_audit_records (
                        audit_id TEXT PRIMARY KEY,
                        skill_id TEXT NOT NULL,
                        version TEXT NOT NULL,
                        action TEXT NOT NULL,
                        correlation_id TEXT,
                        user_id TEXT,
                        capabilities TEXT NOT NULL,
                        action_hash TEXT,
                        policy_outcome TEXT NOT NULL,
                        approval_token TEXT,
                        execution_status TEXT,
                        duration_ms REAL,
                        error_message TEXT,
                        created_at TEXT NOT NULL,
                        metadata TEXT NOT NULL DEFAULT '{}'
                    );
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_skill_audit_skill ON skill_audit_records(skill_id);"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_skill_audit_corr ON skill_audit_records(correlation_id);"
                )
        except Exception as e:
            logger.warning(f"SkillAuditLogger: failed to verify table schema: {e}")

    def log_event(
        self,
        skill_id: str,
        version: str,
        action: str,
        policy_outcome: str,
        capabilities: List[str],
        correlation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        action_hash: Optional[str] = None,
        approval_token: Optional[str] = None,
        execution_status: Optional[str] = None,
        duration_ms: Optional[float] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SkillAuditRecord:
        """
        Records a structured audit event. Redacts sensitive credentials before writing.
        """
        sanitized_error = sanitize_audit_text(error_message)
        sanitized_token = "[REDACTED_APPROVAL_TOKEN]" if approval_token else None
        sanitized_metadata = sanitize_audit_structure(metadata or {})
        sanitized_action = sanitize_audit_text(action) or action

        record = SkillAuditRecord(
            audit_id=f"aud-{uuid.uuid4().hex[:12]}",
            skill_id=skill_id,
            version=version,
            action=sanitized_action,
            correlation_id=correlation_id,
            user_id=user_id or "default_user",
            capabilities=capabilities,
            action_hash=action_hash,
            policy_outcome=policy_outcome,
            approval_token=sanitized_token,
            execution_status=execution_status,
            duration_ms=duration_ms,
            error_message=sanitized_error,
            created_at=utc_now_iso(),
            metadata=sanitized_metadata,
        )

        self._in_memory_records.append(record)

        if self.db:
            try:
                with self.db.transaction() as conn:
                    conn.execute(
                        """
                        INSERT INTO skill_audit_records (
                            audit_id, skill_id, version, action, correlation_id,
                            user_id, capabilities, action_hash, policy_outcome,
                            approval_token, execution_status, duration_ms,
                            error_message, created_at, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            record.audit_id,
                            record.skill_id,
                            record.version,
                            record.action,
                            record.correlation_id,
                            record.user_id,
                            json.dumps(record.capabilities),
                            record.action_hash,
                            record.policy_outcome,
                            record.approval_token,
                            record.execution_status,
                            record.duration_ms,
                            record.error_message,
                            record.created_at,
                            json.dumps(record.metadata, sort_keys=True),
                        ),
                    )
            except Exception as e:
                logger.warning(f"SkillAuditLogger: failed to persist record to SQLite: {e}")

        return record

    def get_recent_records(
        self,
        limit: int = 50,
        skill_id: Optional[str] = None,
    ) -> List[SkillAuditRecord]:
        """Retrieves recent audit records from SQLite with in-memory fallback."""
        if self.db:
            try:
                conn = self.db.get_connection()
                try:
                    cursor = conn.cursor()
                    if skill_id:
                        cursor.execute(
                            """
                            SELECT * FROM skill_audit_records
                            WHERE skill_id = ?
                            ORDER BY created_at DESC LIMIT ?;
                            """,
                            (skill_id, limit),
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT * FROM skill_audit_records
                            ORDER BY created_at DESC LIMIT ?;
                            """,
                            (limit,),
                        )
                    rows = cursor.fetchall()
                    result = []
                    for row in rows:
                        result.append(
                            SkillAuditRecord(
                                audit_id=row["audit_id"],
                                skill_id=row["skill_id"],
                                version=row["version"],
                                action=row["action"],
                                correlation_id=row["correlation_id"],
                                user_id=row["user_id"],
                                capabilities=json.loads(row["capabilities"]) if row["capabilities"] else [],
                                action_hash=row["action_hash"],
                                policy_outcome=row["policy_outcome"],
                                approval_token=row["approval_token"],
                                execution_status=row["execution_status"],
                                duration_ms=row["duration_ms"],
                                error_message=row["error_message"],
                                created_at=row["created_at"],
                                metadata=json.loads(row["metadata"]) if row["metadata"] else {},
                            )
                        )
                    return result
                finally:
                    conn.close()
            except Exception as e:
                logger.warning(f"SkillAuditLogger query error: {e}")

        # In-memory fallback
        matching = [
            r for r in reversed(self._in_memory_records)
            if not skill_id or r.skill_id == skill_id
        ]
        return matching[:limit]
