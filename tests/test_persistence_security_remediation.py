"""
Go 81 Persistence and Security Remediation Regression Tests.

Validates the 12 Required Regression Test Directives from Section 9:
1. Pending and consumed approvals survive process restart.
2. Approval tokens cannot be replayed or reused concurrently.
3. Expired and mismatched approvals are rejected.
4. Healthy checkpoint status requires real, persisted passing evidence.
5. Nonexistent evidence IDs are rejected.
6. Dirty and untracked files survive unrelated recovery operations.
7. Files changed after approval cannot be silently overwritten.
8. Symlink/path traversal and corrupted checkpoint data are handled safely.
9. Flight Recorder data persists across restarts.
10. Encryption corruption and missing-key failures are safe and explicit.
11. SQLite migrations preserve existing records.
12. Concurrent task/event writes do not create inconsistent state.
"""

import concurrent.futures
import hashlib
import json
import os
import shutil
import tempfile
import time
from datetime import datetime, timezone

import pytest

from app.memory.checkpoint_service import CheckpointService, compute_file_sha256
from app.memory.crypto import (
    CryptoError,
    DecryptionError,
    EncryptionService,
    EnvKeyProvider,
    MissingKeyError,
    TestKeyProvider,
)
from app.memory.database import (
    DatabaseManager,
    _apply_migration_v1,
    _apply_migration_v2,
    _apply_migration_v3,
)
from app.memory.flight_recorder import FlightRecorderService
from app.memory.models import (
    ApprovalRecord,
    ApprovalStatus,
    CheckpointCreateRequest,
    CheckpointLifecycleStatus,
    CheckpointRestoreRequest,
    EventQueryFilter,
    EventSourceType,
    EvidenceRecordCreate,
    FlightRecorderEventCreate,
    GitRevisionInfo,
    TrackedFileChange,
)
from app.memory.security_boundary import (
    ApprovalTamperError,
    DangerousCommandError,
    PathTraversalError,
    SecurityBoundary,
)


# ============================================================================
# 1. Pending and Consumed Approvals Survive Process Restart
# ============================================================================

def test_approvals_survive_process_restart():
    """
    Directive 1: Approval records must persist durably in SQLite across
    process termination and maintain valid pending/consumed state.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "restart_approval.db")
        db = DatabaseManager(db_path)
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        # 1. Create durable approval token
        params = {"file": "config.yaml", "sha256": "abc1234"}
        token = boundary.create_approval_token(
            task_id="task-restart-01",
            action="overwrite_file",
            resource=os.path.join(tmpdir, "config.yaml"),
            parameters=params,
            ttl_seconds=300,
        )
        assert token.startswith("tok-")

        # 2. Simulate process termination by tearing down instances
        del boundary
        del db

        # 3. Reopen SQLite database and create a brand new SecurityBoundary instance
        db_restarted = DatabaseManager(db_path)
        boundary_restarted = SecurityBoundary(permitted_root=tmpdir, db=db_restarted)

        # 4. Durable consumption must succeed on the restarted instance
        consumed = boundary_restarted.consume_approval_token(
            approval_token=token,
            action="overwrite_file",
            resource=os.path.join(tmpdir, "config.yaml"),
            parameters=params,
        )
        assert consumed is True

        # 5. Verify status in SQLite database is durably CONSUMED
        conn = db_restarted.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status, consumed_at FROM approval_records WHERE token = ?", (token,))
            row = cursor.fetchone()
            assert row is not None
            assert row[0] == ApprovalStatus.CONSUMED.value
            assert row[1] is not None
        finally:
            conn.close()

        # 6. Simulate second restart: verify token cannot be re-consumed
        del boundary_restarted
        del db_restarted

        db_restarted_2 = DatabaseManager(db_path)
        boundary_restarted_2 = SecurityBoundary(permitted_root=tmpdir, db=db_restarted_2)

        with pytest.raises(ApprovalTamperError, match="Replay detected"):
            boundary_restarted_2.consume_approval_token(
                approval_token=token,
                action="overwrite_file",
                resource=os.path.join(tmpdir, "config.yaml"),
                parameters=params,
            )


# ============================================================================
# 2. Approval Tokens Cannot Be Replayed or Reused Concurrently
# ============================================================================

def test_approvals_cannot_be_replayed_or_reused_concurrently():
    """
    Directive 2: Single-use consumption must be atomic; concurrent requests
    cannot reuse the same authorization.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "replay_approval.db")
        db = DatabaseManager(db_path)
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        token = boundary.create_approval_token(
            task_id="task-concurrent-01",
            action="apply_patch",
            resource=os.path.join(tmpdir, "patch.diff"),
            parameters={"hunk_count": 3},
            ttl_seconds=120,
        )

        success_count = 0
        error_count = 0

        def attempt_consumption(worker_id: int):
            worker_boundary = SecurityBoundary(permitted_root=tmpdir, db=db)
            try:
                ok = worker_boundary.consume_approval_token(
                    approval_token=token,
                    action="apply_patch",
                    resource=os.path.join(tmpdir, "patch.diff"),
                    parameters={"hunk_count": 3},
                )
                return ok
            except ApprovalTamperError:
                return False

        # Run 12 concurrent consumption attempts across multiple threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(attempt_consumption, i) for i in range(12)]
            results = [f.result() for f in futures]

        for res in results:
            if res is True:
                success_count += 1
            else:
                error_count += 1

        # Exactly ONE consumption must succeed; all others must be rejected
        assert success_count == 1
        assert error_count == 11


# ============================================================================
# 3. Expired and Mismatched Approvals Are Rejected
# ============================================================================

def test_expired_and_mismatched_approvals_are_rejected():
    """
    Directive 3: Approvals that are expired, or have mismatched action,
    resource, or parameters, must fail closed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "mismatch.db"))
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        # 1. Expired token rejection
        expired_token = boundary.create_approval_token(
            task_id="task-exp",
            action="delete_file",
            resource=os.path.join(tmpdir, "old.log"),
            parameters={"force": False},
            ttl_seconds=-5,  # immediately expired
        )
        with pytest.raises(ApprovalTamperError, match="has expired"):
            boundary.consume_approval_token(
                approval_token=expired_token,
                action="delete_file",
                resource=os.path.join(tmpdir, "old.log"),
                parameters={"force": False},
            )

        # 2. Action mismatch rejection
        valid_token = boundary.create_approval_token(
            task_id="task-valid",
            action="restore_file",
            resource=os.path.join(tmpdir, "main.py"),
            parameters={"sha256": "abcdef"},
            ttl_seconds=300,
        )
        with pytest.raises(ApprovalTamperError, match="cannot be repurposed"):
            boundary.consume_approval_token(
                approval_token=valid_token,
                action="delete_file",  # Mismatch
                resource=os.path.join(tmpdir, "main.py"),
                parameters={"sha256": "abcdef"},
            )

        # 3. Resource mismatch rejection
        with pytest.raises(ApprovalTamperError, match="cannot be repurposed"):
            boundary.consume_approval_token(
                approval_token=valid_token,
                action="restore_file",
                resource=os.path.join(tmpdir, "other.py"),  # Mismatch
                parameters={"sha256": "abcdef"},
            )

        # 4. Parameter tampering rejection
        with pytest.raises(ApprovalTamperError, match="parameters were modified"):
            boundary.consume_approval_token(
                approval_token=valid_token,
                action="restore_file",
                resource=os.path.join(tmpdir, "main.py"),
                parameters={"sha256": "TAMPERED_SHA"},  # Mismatch
            )

        # 5. Nonexistent token rejection
        with pytest.raises(ApprovalTamperError, match="invalid, unrecognized, or already expired"):
            boundary.consume_approval_token(
                approval_token="appr_completely_fake_token_12345",
                action="restore_file",
                resource=os.path.join(tmpdir, "main.py"),
            )


# ============================================================================
# 4. Healthy Checkpoint Status Requires Real, Persisted Passing Evidence
# ============================================================================

def test_healthy_checkpoint_status_requires_real_persisted_passing_evidence():
    """
    Directive 4: A checkpoint cannot be marked healthy based on caller claims.
    Requires verified evidence with exit_code == 0 and is_agent_hypothesis == False.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "evidence_healthy.db"))
        fr = FlightRecorderService(db=db)
        checkpoints = CheckpointService(db=db, snapshots_dir=os.path.join(tmpdir, "snapshots"))

        test_file = os.path.join(tmpdir, "code.py")
        with open(test_file, "w") as f:
            f.write("print('hello')")

        chk = checkpoints.create_checkpoint(
            CheckpointCreateRequest(
                project_id="proj-evidence",
                permitted_root=tmpdir,
                tracked_changes=[
                    TrackedFileChange(
                        path="code.py",
                        sha256=compute_file_sha256(test_file),
                        status="added",
                    )
                ],
            )
        )
        checkpoints.validate_checkpoint(chk.checkpoint_id)

        # Case A: Evidence has exit_code != 0 (failing verification)
        fr.store_evidence(
            EvidenceRecordCreate(
                evidence_id="ev-failing-tests",
                evidence_type="test_run",
                command="pytest",
                exit_code=1,
                raw_stdout="1 test failed",
                is_agent_hypothesis=False,
            )
        )
        with pytest.raises(ValueError, match=r"indicates failure \(exit_code=1\)"):
            checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-failing-tests")

        # Case B: Evidence is an agent hypothesis, not an empirical observation
        fr.store_evidence(
            EvidenceRecordCreate(
                evidence_id="ev-hypothesis-claim",
                evidence_type="observation",
                command="pytest",
                exit_code=0,
                raw_stdout="Simulated pass",
                is_agent_hypothesis=True,
            )
        )
        with pytest.raises(ValueError, match="is an unverified agent hypothesis"):
            checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-hypothesis-claim")

        # Case C: Valid, passing empirical test evidence
        fr.store_evidence(
            EvidenceRecordCreate(
                evidence_id="ev-verified-passing",
                evidence_type="test_run",
                command="pytest -v",
                exit_code=0,
                raw_stdout="All 10 tests passed",
                is_agent_hypothesis=False,
            )
        )
        healthy = checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-verified-passing")
        assert healthy.status == CheckpointLifecycleStatus.HEALTHY
        assert "Healthy verified by evidence 'ev-verified-passing'" in healthy.validation_notes


# ============================================================================
# 5. Nonexistent Evidence IDs Are Rejected
# ============================================================================

def test_nonexistent_evidence_ids_are_rejected():
    """
    Directive 5: Supplying fabricated evidence strings must fail closed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "fake_ev.db"))
        checkpoints = CheckpointService(db=db)

        test_file = os.path.join(tmpdir, "mod.py")
        with open(test_file, "w") as f:
            f.write("# module")

        chk = checkpoints.create_checkpoint(
            CheckpointCreateRequest(
                project_id="proj-fake-ev",
                permitted_root=tmpdir,
                tracked_changes=[
                    TrackedFileChange(
                        path="mod.py",
                        sha256=compute_file_sha256(test_file),
                        status="added",
                    )
                ],
            )
        )
        checkpoints.validate_checkpoint(chk.checkpoint_id)

        # 1. Arbitrary string that does not exist in evidence_store
        with pytest.raises(ValueError, match="does not exist in canonical evidence store"):
            checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-test-pass-001")

        # 2. Empty or blank evidence strings
        with pytest.raises(ValueError, match="must be a non-empty evidence identifier"):
            checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="")

        with pytest.raises(ValueError, match="must be a non-empty evidence identifier"):
            checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="   ")


# ============================================================================
# 6. Dirty and Untracked Files Survive Unrelated Recovery Operations
# ============================================================================

def test_dirty_and_untracked_files_survive_unrelated_recovery():
    """
    Directive 6: Never delete untracked files or overwrite dirty user work
    during restoration of unrelated files.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "recovery_safe.db"))
        fr = FlightRecorderService(db=db)
        checkpoints = CheckpointService(db=db, snapshots_dir=os.path.join(tmpdir, "snapshots"))
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        # Setup tracked file and untracked developer files
        tracked_file = os.path.join(tmpdir, "service.py")
        untracked_file_1 = os.path.join(tmpdir, "developer_scratch.txt")
        untracked_dir = os.path.join(tmpdir, "local_data")
        os.makedirs(untracked_dir, exist_ok=True)
        untracked_file_2 = os.path.join(untracked_dir, "notes.json")

        with open(tracked_file, "w") as f:
            f.write("def original_service(): pass\n")
        with open(untracked_file_1, "w") as f:
            f.write("My secret scratch notes that must never be deleted!")
        with open(untracked_file_2, "w") as f:
            f.write('{"untracked": true}')

        orig_sha = compute_file_sha256(tracked_file)
        chk = checkpoints.create_checkpoint(
            CheckpointCreateRequest(
                project_id="proj-safe-recovery",
                permitted_root=tmpdir,
                tracked_changes=[
                    TrackedFileChange(path="service.py", sha256=orig_sha, status="added")
                ],
            )
        )
        checkpoints.validate_checkpoint(chk.checkpoint_id)

        # Store passing evidence
        fr.store_evidence(
            EvidenceRecordCreate(
                evidence_id="ev-pass-6",
                evidence_type="test_run",
                command="pytest",
                exit_code=0,
                raw_stdout="OK",
                is_agent_hypothesis=False,
            )
        )
        checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-pass-6")
        checkpoints.validate_restorable(chk.checkpoint_id)

        # Modify tracked file
        with open(tracked_file, "w") as f:
            f.write("def dirty_work(): pass\n")

        # Attempt restore without token -> must halt with APPROVAL_REQUIRED
        halt_res = checkpoints.restore_checkpoint(chk.checkpoint_id, CheckpointRestoreRequest(dry_run=False))
        assert halt_res.status == "APPROVAL_REQUIRED"
        assert halt_res.success is False
        assert "service.py" in halt_res.protected_files

        # Create valid approval token bound to restore operation
        approval_token = boundary.create_approval_token(
            task_id="task-restore-safe",
            action="restore_checkpoint",
            resource=chk.checkpoint_id,
            parameters={"target_files": None, "dry_run": False},
        )

        # Restore with approval token
        res = checkpoints.restore_checkpoint(
            chk.checkpoint_id,
            CheckpointRestoreRequest(dry_run=False, approval_token=approval_token),
        )
        assert res.success is True
        assert res.status == "RESTORED"
        assert "service.py" in res.overridden_files
        assert res.pre_restoration_snapshot_id is not None

        # Assert untracked files are COMPLETELY UNTOUCHED
        assert os.path.exists(untracked_file_1)
        with open(untracked_file_1, "r") as f:
            assert f.read() == "My secret scratch notes that must never be deleted!"

        assert os.path.exists(untracked_file_2)
        with open(untracked_file_2, "r") as f:
            assert f.read() == '{"untracked": true}'


# ============================================================================
# 7. Files Changed After Approval Cannot Be Silently Overwritten
# ============================================================================

def test_files_changed_after_approval_cannot_be_silently_overwritten():
    """
    Directive 7: If a file changes after approval was granted, parameter hash binding
    must reject the stale approval to protect subsequent user work.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "toctou_approval.db"))
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        target_file = os.path.join(tmpdir, "main.py")
        with open(target_file, "w") as f:
            f.write("version = 1.0\n")

        # Approval was granted when the file had hash of "version = 1.0"
        sha_v1 = hashlib.sha256(b"version = 1.0\n").hexdigest()
        token = boundary.create_approval_token(
            task_id="task-toctou",
            action="apply_patch",
            resource=target_file,
            parameters={"precondition_sha256": sha_v1, "target": "main.py"},
        )

        # Developer or concurrent process changes file to version 2.0
        with open(target_file, "w") as f:
            f.write("version = 2.0 (critical user edit)\n")

        sha_v2 = hashlib.sha256(b"version = 2.0 (critical user edit)\n").hexdigest()

        # Caller attempts to use approval token, but current precondition hash has changed
        with pytest.raises(ApprovalTamperError, match="parameters were modified after human approval"):
            boundary.consume_approval_token(
                approval_token=token,
                action="apply_patch",
                resource=target_file,
                parameters={"precondition_sha256": sha_v2, "target": "main.py"},  # Changed!
            )

        # The user's critical edit remains preserved
        with open(target_file, "r") as f:
            assert "critical user edit" in f.read()


# ============================================================================
# 8. Symlink/Path Traversal and Corrupted Checkpoint Data Are Handled Safely
# ============================================================================

def test_symlink_path_traversal_and_corrupted_data_handled_safely():
    """
    Directive 8: Path traversal attempts outside permitted root and corrupted
    manifests must fail closed.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "traversal.db"))
        checkpoints = CheckpointService(db=db)
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        # 1. Path traversal outside permitted root
        with pytest.raises(PathTraversalError):
            boundary.resolve_safe_path(os.path.join(tmpdir, "../../../windows/system32/cmd.exe"))

        # 2. Checkpoint manifest tampering detection
        test_file = os.path.join(tmpdir, "valid.txt")
        with open(test_file, "w") as f:
            f.write("content")

        chk = checkpoints.create_checkpoint(
            CheckpointCreateRequest(
                project_id="proj-corrupt",
                permitted_root=tmpdir,
                tracked_changes=[
                    TrackedFileChange(
                        path="valid.txt",
                        sha256=compute_file_sha256(test_file),
                        status="added",
                    )
                ],
            )
        )

        # Directly tamper with manifest integrity hash in SQLite
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE project_checkpoints_v2 SET integrity_hash = 'tampered_hash_0000' WHERE checkpoint_id = ?",
                (chk.checkpoint_id,),
            )
            conn.commit()
        finally:
            conn.close()

        # Validation must detect the integrity hash mismatch and refuse VALIDATED state
        validated = checkpoints.validate_checkpoint(chk.checkpoint_id)
        assert validated.status != CheckpointLifecycleStatus.VALIDATED
        assert "Integrity hash mismatch" in validated.validation_notes

        # Cannot mark healthy or restore while unvalidated
        with pytest.raises(ValueError, match="must be in VALIDATED state"):
            checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-anything")


# ============================================================================
# 9. Flight Recorder Data Persists Across Restarts
# ============================================================================

def test_flight_recorder_persists_across_restarts():
    """
    Directive 9: SQLite Flight Recorder is canonical; events persist across
    process restarts and can be filtered with exact ordering.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "fr_restart.db")
        db = DatabaseManager(db_path)
        fr = FlightRecorderService(db=db)

        # Record events
        for i in range(5):
            fr.record_event(
                FlightRecorderEventCreate(
                    project_id="proj-persist",
                    task_id=f"task-{i}",
                    event_type="test.execution",
                    source_type=EventSourceType.OBSERVATION,
                    actor="pytest-runner",
                    summary=f"Test run {i}",
                    metadata={"index": i},
                )
            )

        # Simulate shutdown
        del fr
        del db

        # Reopen on restarted system
        db_reopened = DatabaseManager(db_path)
        fr_reopened = FlightRecorderService(db=db_reopened)

        events = fr_reopened.list_events(EventQueryFilter(project_id="proj-persist"))
        assert len(events) == 5
        assert [e.summary for e in events] == [f"Test run {i}" for i in range(5)]
        assert all(e.source_type == EventSourceType.OBSERVATION for e in events)


# ============================================================================
# 10. Encryption Corruption and Missing-Key Failures Are Safe and Explicit
# ============================================================================

def test_encryption_corruption_and_missing_key_failures_are_safe_and_explicit():
    """
    Directive 10: Authenticated encryption must fail explicitly on key absence,
    wrong key, or ciphertext tampering.
    """
    # 1. Tampered ciphertext failure
    crypto_a = EncryptionService(TestKeyProvider())
    ciphertext = crypto_a.encrypt_json({"secret": "Super secret data"})
    assert isinstance(ciphertext, str)

    # Flip a byte in the base64 ciphertext
    tampered_bytes = bytearray(ciphertext.encode("ascii"))
    tampered_bytes[20] = (tampered_bytes[20] + 1) % 256
    tampered_ciphertext = tampered_bytes.decode("ascii", errors="ignore")

    with pytest.raises(DecryptionError):
        crypto_a.decrypt_json(tampered_ciphertext)

    # 2. Wrong key failure
    crypto_b = EncryptionService(TestKeyProvider())  # Independent key
    with pytest.raises(DecryptionError):
        crypto_b.decrypt_json(ciphertext)

    # 3. Missing key environment provider
    missing_env_provider = EnvKeyProvider(env_var="NONEXISTENT_KEY_VAR_XYZ_987")
    with pytest.raises(MissingKeyError, match="is not set"):
        missing_env_provider.get_key()


# ============================================================================
# 11. SQLite Migrations Preserve Existing Records
# ============================================================================

def test_sqlite_migrations_preserve_existing_records():
    """
    Directive 11: Applying sequential migrations v1 -> v2 -> v3 preserves
    existing rows and structures without data loss.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "migration_preserve.db")
        db = DatabaseManager(db_path)

        # 1. Apply v1 and insert record
        with db.transaction() as conn:
            _apply_migration_v1(conn)
            conn.execute(
                """
                INSERT INTO flight_recorder_events
                (event_id, project_id, timestamp, event_type, source_type, actor, summary)
                VALUES ('ev-v1-01', 'proj-1', '2026-01-01T00:00:00Z', 'init', 'system', 'tester', 'V1 event');
                """
            )

        # 2. Apply v2 and insert record
        with db.transaction() as conn:
            _apply_migration_v2(conn)
            conn.execute(
                """
                INSERT INTO evidence_store
                (evidence_id, evidence_type, command, exit_code, created_at)
                VALUES ('ev-store-01', 'test_run', 'pytest', 0, '2026-01-01T00:01:00Z');
                """
            )

        # 3. Apply v3 and insert approval record
        with db.transaction() as conn:
            _apply_migration_v3(conn)
            conn.execute(
                """
                INSERT INTO approval_records
                (approval_id, token, task_id, action, resource, param_hash, status, created_at, expires_at)
                VALUES ('appr-01', 'appr_tok_01', 'task-1', 'write', 'file.txt', 'hash', 'APPROVED', '2026-01-01T00:02:00Z', '2026-01-01T01:00:00Z');
                """
            )

        # 4. Verify all records survived
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT summary FROM flight_recorder_events WHERE event_id = 'ev-v1-01'")
            assert cursor.fetchone()[0] == "V1 event"

            cursor.execute("SELECT command FROM evidence_store WHERE evidence_id = 'ev-store-01'")
            assert cursor.fetchone()[0] == "pytest"

            cursor.execute("SELECT status FROM approval_records WHERE approval_id = 'appr-01'")
            assert cursor.fetchone()[0] == "APPROVED"
        finally:
            conn.close()


# ============================================================================
# 12. Concurrent Task/Event Writes Do Not Create Inconsistent State
# ============================================================================

def test_concurrent_task_event_writes_do_not_create_inconsistent_state():
    """
    Directive 12: Multi-threaded writers recording events, storing evidence,
    and handling approvals simultaneously do not encounter lock corruptions or lost writes.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "concurrent_stress.db")
        db = DatabaseManager(db_path)
        fr = FlightRecorderService(db=db)
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        def worker_task(worker_id: int):
            # 1. Record event
            fr.record_event(
                FlightRecorderEventCreate(
                    project_id="proj-stress",
                    task_id=f"task-{worker_id}",
                    event_type="stress.event",
                    source_type=EventSourceType.SYSTEM,
                    actor=f"worker-{worker_id}",
                    summary=f"Worker {worker_id} executed",
                )
            )

            # 2. Store evidence
            fr.store_evidence(
                EvidenceRecordCreate(
                    evidence_id=f"ev-stress-{worker_id}",
                    evidence_type="test_run",
                    command=f"pytest worker_{worker_id}",
                    exit_code=0,
                    raw_stdout=f"Worker {worker_id} passed",
                    is_agent_hypothesis=False,
                )
            )

            # 3. Create and consume approval
            tok = boundary.create_approval_token(
                task_id=f"task-{worker_id}",
                action="worker_action",
                resource=os.path.join(tmpdir, f"file_{worker_id}.txt"),
                parameters={"id": worker_id},
                ttl_seconds=60,
            )
            ok = boundary.consume_approval_token(
                approval_token=tok,
                action="worker_action",
                resource=os.path.join(tmpdir, f"file_{worker_id}.txt"),
                parameters={"id": worker_id},
            )
            return ok

        # Launch 20 concurrent threads
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(worker_task, i) for i in range(20)]
            results = [f.result() for f in futures]

        assert all(res is True for res in results)

        # Verify all 20 events, 20 evidence rows, and 20 consumed approvals are accounted for
        events = fr.list_events(EventQueryFilter(project_id="proj-stress", limit=100))
        assert len(events) == 20

        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM evidence_store")
            assert cursor.fetchone()[0] == 20

            cursor.execute("SELECT COUNT(*) FROM approval_records WHERE status = 'CONSUMED'")
            assert cursor.fetchone()[0] == 20
        finally:
            conn.close()


# ============================================================================
# 13. Pending vs Approved vs Rejected Approval State Invariants
# ============================================================================

def test_approval_lifecycle_pending_vs_approved_vs_rejected():
    """
    Directive Invariant:
    1. A pending approval is strictly 'pending' and NEVER represented as 'Authorized'.
    2. Only an explicit valid approval authorizes the exact action.
    3. Rejection permanently locks the token and cannot execute the action.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "approval_lifecycle.db"))
        boundary = SecurityBoundary(permitted_root=tmpdir, db=db)

        # --------------------------------------------------------------------
        # Phase 1: PENDING State
        # --------------------------------------------------------------------
        # Create a pending approval record
        params = {"command": "rm -rf /test", "sandbox": True}
        token_pending = boundary.create_approval_token(
            action="shell_execute",
            resource="/test",
            parameters=params,
            ttl_seconds=300,
            task_id="task-lifecycle-01",
        )

        # Update to PENDING in canonical database and in-memory registry
        with db.transaction() as conn:
            conn.execute(
                "UPDATE approval_records SET status = 'PENDING' WHERE token = ?",
                (token_pending,),
            )
        SecurityBoundary._approval_registry[token_pending]["status"] = "PENDING"

        # Cannot consume a pending approval (must fail closed)
        with pytest.raises(ApprovalTamperError, match="is not in APPROVED state"):
            boundary.consume_approval_token(
                approval_token=token_pending,
                action="shell_execute",
                resource="/test",
                parameters=params,
            )

        # --------------------------------------------------------------------
        # Phase 2: REJECTED State
        # --------------------------------------------------------------------
        # Transition token to REJECTED in database and in-memory registry
        with db.transaction() as conn:
            conn.execute(
                "UPDATE approval_records SET status = 'REJECTED' WHERE token = ?",
                (token_pending,),
            )
        SecurityBoundary._approval_registry[token_pending]["status"] = "REJECTED"

        # Rejected approval must be blocked from execution
        with pytest.raises(ApprovalTamperError, match="has been rejected"):
            boundary.consume_approval_token(
                approval_token=token_pending,
                action="shell_execute",
                resource="/test",
                parameters=params,
            )

        # --------------------------------------------------------------------
        # Phase 3: Explicit APPROVED State
        # --------------------------------------------------------------------
        token_approved = boundary.create_approval_token(
            action="apply_patch",
            resource="/test/patch.diff",
            parameters={"hunks": 1},
            ttl_seconds=300,
            task_id="task-lifecycle-02",
        )

        # Confirm status is APPROVED in canonical database
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM approval_records WHERE token = ?", (token_approved,))
            assert cursor.fetchone()[0] == "APPROVED"
        finally:
            conn.close()

        # Consumption succeeds only for exact action and parameters
        ok = boundary.consume_approval_token(
            approval_token=token_approved,
            action="apply_patch",
            resource="/test/patch.diff",
            parameters={"hunks": 1},
        )
        assert ok is True

        # Status is now CONSUMED in canonical database
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM approval_records WHERE token = ?", (token_approved,))
            assert cursor.fetchone()[0] == "CONSUMED"
        finally:
            conn.close()

        # Cannot replay consumed token
        with pytest.raises(ApprovalTamperError, match="Replay detected"):
            boundary.consume_approval_token(
                approval_token=token_approved,
                action="apply_patch",
                resource="/test/patch.diff",
                parameters={"hunks": 1},
            )

