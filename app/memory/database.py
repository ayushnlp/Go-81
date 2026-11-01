"""
SQLite database engine with WAL mode, foreign keys, and versioned schema migrations.
Never deletes or recreates databases on startup; safely runs pending incremental migrations.
"""

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, List, Optional

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Migration Definitions
# ============================================================================

def _apply_migration_v1(conn: sqlite3.Connection) -> None:
    """Initial schema for Go 81 Memory & Security Subsystem."""
    cursor = conn.cursor()

    # 1. Memories Table (Episodic & Semantic)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            memory_type TEXT NOT NULL,
            category TEXT,
            verification_status TEXT NOT NULL DEFAULT 'unverified',
            confidence REAL NOT NULL DEFAULT 1.0,
            dedup_hash TEXT UNIQUE,
            source_ref TEXT,
            schema_version INTEGER NOT NULL DEFAULT 1,
            encrypted_payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            is_deleted INTEGER NOT NULL DEFAULT 0
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_type_deleted ON memories(memory_type, is_deleted);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_dedup ON memories(dedup_hash);")

    # 2. Task Checkpoints Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_checkpoints (
            task_id TEXT PRIMARY KEY,
            workflow_id TEXT NOT NULL,
            status TEXT NOT NULL,
            current_step TEXT NOT NULL,
            completed_step_ids TEXT NOT NULL DEFAULT '[]',
            pending_step_ids TEXT NOT NULL DEFAULT '[]',
            approval_references TEXT NOT NULL DEFAULT '[]',
            retry_count INTEGER NOT NULL DEFAULT 0,
            encrypted_state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_status ON task_checkpoints(status);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_workflow ON task_checkpoints(workflow_id);")

    # 3. Execution Events Table (Idempotency Guard)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS execution_events (
            event_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES task_checkpoints(task_id) ON DELETE CASCADE,
            step_id TEXT NOT NULL,
            action TEXT NOT NULL,
            status TEXT NOT NULL,
            idempotency_hash TEXT NOT NULL,
            encrypted_details TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exec_task ON execution_events(task_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_exec_idempotency ON execution_events(idempotency_hash);")

    # 4. Permission Policies Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS permission_policies (
            action TEXT PRIMARY KEY,
            default_risk TEXT NOT NULL,
            requires_approval INTEGER NOT NULL DEFAULT 1,
            description TEXT
        );
    """)

    # Seed default policies
    default_policies = [
        ("read_local_file", "LOW", 0, "Read access to local non-sensitive files"),
        ("write_local_file", "MEDIUM", 1, "Modify or create local files in workspace"),
        ("shell_execute", "HIGH", 1, "Execution of system commands in shell/terminal"),
        ("delete_file", "HIGH", 1, "Permanent deletion of local resources"),
        ("network_egress", "HIGH", 1, "Outbound network requests to external servers"),
        ("read_secrets", "HIGH", 1, "Access to credentials, tokens, or encryption keys"),
    ]
    cursor.executemany(
        """
        INSERT OR IGNORE INTO permission_policies (action, default_risk, requires_approval, description)
        VALUES (?, ?, ?, ?);
        """,
        default_policies,
    )


def _apply_migration_v2(conn: sqlite3.Connection) -> None:
    """Migration v2: Project Flight Recorder, Evidence Store, and Project Checkpoints."""
    cursor = conn.cursor()

    # 1. Flight Recorder Events Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS flight_recorder_events (
            event_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            task_id TEXT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            source_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            summary TEXT NOT NULL,
            phase TEXT,
            evidence_refs TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            schema_version INTEGER NOT NULL DEFAULT 1
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fre_project_time ON flight_recorder_events(project_id, timestamp);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fre_task ON flight_recorder_events(task_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fre_type ON flight_recorder_events(event_type);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_fre_source ON flight_recorder_events(source_type);")

    # 2. Evidence Store (Redacted & Bounded)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evidence_store (
            evidence_id TEXT PRIMARY KEY,
            evidence_type TEXT NOT NULL,
            command TEXT,
            exit_code INTEGER,
            started_at TEXT,
            completed_at TEXT,
            duration_ms INTEGER,
            working_dir TEXT,
            stdout_digest TEXT,
            stderr_digest TEXT,
            redacted_excerpt TEXT,
            is_agent_hypothesis INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_type ON evidence_store(evidence_type);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_created ON evidence_store(created_at);")

    # 3. Project Checkpoints (Durable Project Manifests)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_checkpoints_v2 (
            checkpoint_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            permitted_root TEXT NOT NULL,
            git_revision TEXT NOT NULL DEFAULT '{}',
            tracked_changes TEXT NOT NULL DEFAULT '[]',
            dependency_fingerprints TEXT NOT NULL DEFAULT '{}',
            toolchain_versions TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL,
            integrity_hash TEXT NOT NULL,
            validation_notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chk_v2_project ON project_checkpoints_v2(project_id, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chk_v2_status ON project_checkpoints_v2(status);")

    # 4. Add project_id column to memories table if not present
    cursor.execute("PRAGMA table_info(memories);")
    columns = [row[1] for row in cursor.fetchall()]
    if "project_id" not in columns:
        cursor.execute("ALTER TABLE memories ADD COLUMN project_id TEXT;")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);")


def _apply_migration_v3(conn: sqlite3.Connection) -> None:
    """
    Migration v3: Durable Approval and Replay Protection Subsystem.
    Creates approval_records table for persistent, single-use, anti-tamper authorizations.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approval_records (
            approval_id TEXT PRIMARY KEY,
            token TEXT UNIQUE NOT NULL,
            task_id TEXT,
            action TEXT NOT NULL,
            resource TEXT NOT NULL,
            param_hash TEXT NOT NULL,
            parameters TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'PENDING',
            risk_level TEXT NOT NULL DEFAULT 'HIGH',
            notes TEXT,
            created_at TEXT NOT NULL,
            expires_at REAL NOT NULL,
            consumed_at TEXT,
            resolved_at TEXT,
            rejection_reason TEXT,
            audit_evidence_id TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        );
    """)
def _apply_migration_v4(conn: sqlite3.Connection) -> None:
    """
    Migration v4: Local Vector Embeddings Storage for Go 81.
    Maintains packed vector blobs and metadata indexed by memory_id and model_name.
    """
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS memory_embeddings (
            memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
            model_name TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            embedding_blob BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_emb_model ON memory_embeddings(model_name);")


def _apply_migration_v5(conn: sqlite3.Connection) -> None:
    """
    Migration v5: Relational Durable Execution Journal and Lease Concurrency Controls.
    Supports atomic dispatch state transitions, subprocess tracking, and optimistic task leases.
    """
    cursor = conn.cursor()

    # 1. Execution Journal Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS execution_journal (
            entry_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES task_checkpoints(task_id) ON DELETE CASCADE,
            step_id TEXT NOT NULL,
            attempt_id TEXT UNIQUE NOT NULL,
            action TEXT NOT NULL,
            idempotency_class TEXT NOT NULL DEFAULT 'READ_ONLY',
            param_hash TEXT NOT NULL,
            sanitized_params TEXT NOT NULL DEFAULT '{}',
            dispatch_state TEXT NOT NULL DEFAULT 'PREPARED',
            approval_ref TEXT,
            pid INTEGER,
            process_creation_time REAL,
            log_path TEXT,
            exit_code INTEGER,
            result_digest TEXT,
            error_message TEXT,
            checkpoint_version INTEGER NOT NULL DEFAULT 1,
            recovery_attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            dispatched_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_journal_task ON execution_journal(task_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_journal_step ON execution_journal(task_id, step_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_journal_state ON execution_journal(dispatch_state);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_journal_attempt ON execution_journal(attempt_id);")

    # 2. Add lease and versioning columns to task_checkpoints
    cursor.execute("PRAGMA table_info(task_checkpoints);")
    chk_cols = [row[1] for row in cursor.fetchall()]
    if "checkpoint_version" not in chk_cols:
        cursor.execute("ALTER TABLE task_checkpoints ADD COLUMN checkpoint_version INTEGER NOT NULL DEFAULT 1;")
    if "lease_holder" not in chk_cols:
        cursor.execute("ALTER TABLE task_checkpoints ADD COLUMN lease_holder TEXT;")
    if "lease_expires_at" not in chk_cols:
        cursor.execute("ALTER TABLE task_checkpoints ADD COLUMN lease_expires_at REAL;")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_checkpoints_lease ON task_checkpoints(lease_holder, lease_expires_at);")


def _apply_migration_v6(conn: sqlite3.Connection) -> None:
    """
    Migration v6: Background Sentinels, Persistent Scheduler, and Internal Notification Store.
    Supports autonomous proactive event handling, cron/interval schedules, and bounded alerts.
    """
    cursor = conn.cursor()

    # 1. Background Schedules Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS background_schedules (
            schedule_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            schedule_type TEXT NOT NULL,
            schedule_expr TEXT NOT NULL,
            timezone TEXT NOT NULL DEFAULT 'UTC',
            goal TEXT NOT NULL,
            parameters TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'ENABLED',
            missed_run_policy TEXT NOT NULL DEFAULT 'SKIP',
            max_runs INTEGER,
            runs_completed INTEGER NOT NULL DEFAULT 0,
            next_run_at TEXT,
            last_run_at TEXT,
            lease_holder TEXT,
            lease_expires_at REAL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sched_state_next ON background_schedules(state, next_run_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sched_type ON background_schedules(schedule_type);")

    # 2. Scheduled Job Runs Table (Deduplication & Run History)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_job_runs (
            run_id TEXT PRIMARY KEY,
            schedule_id TEXT NOT NULL REFERENCES background_schedules(schedule_id) ON DELETE CASCADE,
            idempotency_key TEXT UNIQUE NOT NULL,
            scheduled_time TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            task_id TEXT,
            error_message TEXT,
            result_summary TEXT,
            created_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sjr_schedule ON scheduled_job_runs(schedule_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sjr_idempotency ON scheduled_job_runs(idempotency_key);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sjr_status ON scheduled_job_runs(status);")

    # 3. Sentinel Configurations Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sentinel_configs (
            sentinel_id TEXT PRIMARY KEY,
            sentinel_type TEXT NOT NULL,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            config_data TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sentinel_type ON sentinel_configs(sentinel_type);")

    # 4. Sentinel Event Journal Table (Idempotent Event Log)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sentinel_event_journal (
            event_id TEXT PRIMARY KEY,
            sentinel_id TEXT NOT NULL REFERENCES sentinel_configs(sentinel_id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            fingerprint TEXT UNIQUE NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            handled INTEGER NOT NULL DEFAULT 0,
            task_id TEXT,
            created_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sej_fingerprint ON sentinel_event_journal(fingerprint);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sej_sentinel ON sentinel_event_journal(sentinel_id);")

    # 5. Internal Notifications Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS internal_notifications (
            notification_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            read INTEGER NOT NULL DEFAULT 0,
            dedup_key TEXT,
            created_at TEXT NOT NULL
        );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_read_created ON internal_notifications(read, created_at);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notif_dedup ON internal_notifications(dedup_key);")


MIGRATIONS = {
    1: _apply_migration_v1,
    2: _apply_migration_v2,
    3: _apply_migration_v3,
    4: _apply_migration_v4,
    5: _apply_migration_v5,
    6: _apply_migration_v6,
}


# ============================================================================
# Database Manager
# ============================================================================

class DatabaseManager:
    """
    Manages SQLite connections with WAL mode, foreign keys, and versioned migrations.
    Guarantees thread-safe connections and persistence across application restarts.
    """

    def __init__(self, db_path: str = "go81_memory.db", auto_upgrade_v6: bool = False):
        resolved_path = db_path
        if db_path == "go81_memory.db":
            resolved_path = os.environ.get("GO81_DB_PATH", db_path)
        self.db_path = os.path.abspath(resolved_path)
        self.auto_upgrade_v6 = auto_upgrade_v6 or (os.environ.get("GO81_AUTO_MIGRATE_V6") == "1")
        # Ensure parent directory exists
        parent_dir = os.path.dirname(self.db_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        self._initialize_database()

    def get_connection(self) -> sqlite3.Connection:
        """Creates a properly configured SQLite connection."""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for high-concurrency read/write
        conn.execute("PRAGMA journal_mode = WAL;")
        # Enforce foreign key constraints
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        return conn

    @contextmanager
    def transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for atomic transaction block with immediate lock."""
        conn = self.get_connection()
        try:
            conn.execute("BEGIN IMMEDIATE;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize_database(self) -> None:
        """
        Initializes schema migrations table and applies any pending migrations.
        Never drops or truncates existing tables.
        """
        conn = self.get_connection()
        try:
            # Create schema_migrations table if not present
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
            """)
            conn.commit()

            # Check currently applied version
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(version) FROM schema_migrations;")
            row = cursor.fetchone()
            current_version = row[0] if (row and row[0] is not None) else 0

            # Apply pending migrations incrementally
            max_ver = 6 if self.auto_upgrade_v6 else 5
            for ver in sorted(MIGRATIONS.keys()):
                if ver <= max_ver and ver > current_version:
                    logger.info(f"Applying schema migration version {ver} to {self.db_path}")
                    with self.transaction() as tx_conn:
                        MIGRATIONS[ver](tx_conn)
                        tx_conn.execute(
                            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                            (ver, utc_now()),
                        )
        finally:
            conn.close()

    def apply_migration_v6(self) -> None:
        """Applies schema migration version 6 if not already applied."""
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(version) FROM schema_migrations;")
            row = cursor.fetchone()
            current_version = row[0] if (row and row[0] is not None) else 0
            if current_version < 6:
                logger.info(f"Applying schema migration version 6 to {self.db_path}")
                with self.transaction() as tx_conn:
                    _apply_migration_v6(tx_conn)
                    tx_conn.execute(
                        "INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (?, ?);",
                        (6, utc_now()),
                    )
        finally:
            conn.close()

    def checkpoint_wal(self) -> None:
        """Forces SQLite to flush WAL pages to the primary database file."""
        conn = self.get_connection()
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        finally:
            conn.close()
