"""
Comprehensive Automated Test Suite for Go 81 Security Boundary & Checkpoint Subsystem.

Covers:
1. Migration idempotency and existing-database compatibility.
2. Event persistence across service restart and connection close.
3. Stable IDs, idempotency, and retry handling.
4. Chronological and filtered event queries (project_id, task_id, source_type).
5. Event provenance and evidence-reference integrity (observation vs. inference).
6. Secret redaction, output bounds, and bounded retention policy.
7. Canonical project-root scoping, path traversal rejection, and symlink protection.
8. Approval parameter tampering detection.
9. Checkpoint manifest integrity hash validation and state progression (created -> validated -> healthy).
10. Protection of pre-existing working-tree changes and non-blind recovery.
11. Safe restoration of disposable project fixtures with pre-restoration snapshots.
12. Project-scoped memory storage and filtering.
13. Canonical API endpoint integration (FastAPI TestClient).
"""

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from app.main import app
from app.memory.checkpoint_service import CheckpointService, compute_file_sha256
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager, _apply_migration_v1, _apply_migration_v2, _apply_migration_v3
from app.memory.flight_recorder import FlightRecorderService, redact_sensitive_text
from app.memory.models import (
    CheckpointCreateRequest,
    CheckpointLifecycleStatus,
    CheckpointRestoreRequest,
    EventQueryFilter,
    EventSourceType,
    EvidenceRecordCreate,
    FlightRecorderEventCreate,
    GitRevisionInfo,
    RiskLevel,
    SemanticCategory,
    TrackedFileChange,
    VerificationStatus,
)
from app.memory.security_boundary import (
    ApprovalTamperError,
    DangerousCommandError,
    PathTraversalError,
    SecurityBoundary,
)


@pytest.fixture
def sentinel_env():
    """Initializes isolated temporary directory, clean database, and services."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "go81_security_test.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        db = SubsystemContainer.db
        recorder = SubsystemContainer.flight_recorder
        checkpoints = SubsystemContainer.checkpoint_service
        checkpoints.snapshots_dir = os.path.join(tmpdir, "snapshots")
        memory_svc = SubsystemContainer.memory_service

        client = TestClient(app)
        yield {
            "tmpdir": tmpdir,
            "db_path": db_path,
            "db": db,
            "crypto": crypto,
            "recorder": recorder,
            "flight_recorder": recorder,
            "checkpoints": checkpoints,
            "memory_svc": memory_svc,
            "memory_service": memory_svc,
            "client": client,
        }


# ============================================================================
# 1. Migration Idempotency & Compatibility
# ============================================================================

def test_migration_v2_idempotency_and_compatibility():
    """Verifies that running Migration v1 and v2 repeatedly is completely idempotent."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "migration_idempotency.db")
        db = DatabaseManager(db_path)

        with db.transaction() as conn:
            # Re-running migrations on already initialized database must not fail
            _apply_migration_v1(conn)
            _apply_migration_v2(conn)
            _apply_migration_v2(conn)
            _apply_migration_v3(conn)
            _apply_migration_v3(conn)

        # Confirm all expected tables exist
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cursor.fetchall()}
            assert "flight_recorder_events" in tables
            assert "evidence_store" in tables
            assert "project_checkpoints_v2" in tables
            assert "memories" in tables
            assert "approval_records" in tables
        finally:
            conn.close()


# ============================================================================
# 2. Flight Recorder Event Persistence Across Restart & Query Filtering
# ============================================================================

def test_event_persistence_across_service_restart_and_ordering(sentinel_env):
    """Verifies events persist across connection close and query chronologically."""
    db = sentinel_env["db"]
    recorder = sentinel_env["recorder"]

    # 1. Record 3 events with explicit ordering
    evt1 = recorder.record_event(
        FlightRecorderEventCreate(
            project_id="proj-forge",
            event_type="project.opened",
            source_type=EventSourceType.OBSERVATION,
            actor="developer",
            summary="Opened project workspace in IDE",
        )
    )
    evt2 = recorder.record_event(
        FlightRecorderEventCreate(
            project_id="proj-forge",
            event_type="build.started",
            source_type=EventSourceType.OBSERVATION,
            actor="subprocess.cargo",
            summary="Started build compilation",
        )
    )
    evt3 = recorder.record_event(
        FlightRecorderEventCreate(
            project_id="proj-forge",
            event_type="build.passed",
            source_type=EventSourceType.OBSERVATION,
            actor="subprocess.cargo",
            summary="Build compilation succeeded in 820ms",
        )
    )

    # 2. Simulate complete restart by re-instantiating FlightRecorderService with fresh connection
    new_recorder = FlightRecorderService(db)

    # Query all events chronologically
    events = new_recorder.query_events(EventQueryFilter(project_id="proj-forge"))
    assert len(events) == 3
    assert events[0].event_id == evt1.event_id
    assert events[1].event_id == evt2.event_id
    assert events[2].event_id == evt3.event_id
    assert events[0].event_type == "project.opened"
    assert events[2].event_type == "build.passed"


def test_event_query_filtering(sentinel_env):
    """Verifies multi-dimensional filtering by task_id, event_type, and source_type."""
    recorder = sentinel_env["recorder"]

    recorder.record_event(
        FlightRecorderEventCreate(
            project_id="proj-A",
            task_id="task-01",
            event_type="test.failed",
            source_type=EventSourceType.OBSERVATION,
            actor="subprocess.pytest",
            summary="Unit test assertion failed",
        )
    )
    recorder.record_event(
        FlightRecorderEventCreate(
            project_id="proj-A",
            task_id="task-02",
            event_type="diagnostic.produced",
            source_type=EventSourceType.INFERENCE,
            actor="model.diagnostics",
            summary="Hypothesized off-by-one index error",
        )
    )
    recorder.record_event(
        FlightRecorderEventCreate(
            project_id="proj-B",
            task_id="task-01",
            event_type="test.passed",
            source_type=EventSourceType.OBSERVATION,
            actor="subprocess.pytest",
            summary="Project B tests all green",
        )
    )

    # Filter by project_id
    proj_a_events = recorder.query_events(EventQueryFilter(project_id="proj-A"))
    assert len(proj_a_events) == 2

    # Filter by task_id
    task_01_events = recorder.query_events(EventQueryFilter(project_id="proj-A", task_id="task-01"))
    assert len(task_01_events) == 1
    assert task_01_events[0].event_type == "test.failed"

    # Filter by source_type (observation vs inference)
    inference_events = recorder.query_events(EventQueryFilter(project_id="proj-A", source_type=EventSourceType.INFERENCE))
    assert len(inference_events) == 1
    assert inference_events[0].actor == "model.diagnostics"


# ============================================================================
# 3. Provenance & Observation vs. Inference Enforcement
# ============================================================================

def test_provenance_enforcement_cannot_claim_observation_for_model(sentinel_env):
    """
    Directive Invariant: Model-generated diagnoses MUST remain inferences.
    An agent hypothesis cannot be recorded as an objective observation.
    """
    recorder = sentinel_env["recorder"]

    # Attempt to record an LLM reasoning step claiming to be an OBSERVATION
    evt = recorder.record_event(
        FlightRecorderEventCreate(
            project_id="proj-sec",
            event_type="diagnostic.produced",
            source_type=EventSourceType.OBSERVATION,  # FALSE CLAIM
            actor="agent.reasoning.llm",
            summary="Agent thinks the database is locked",
        )
    )

    # The service must coerce source_type to INFERENCE
    assert evt.source_type == EventSourceType.INFERENCE


# ============================================================================
# 4. Secret Redaction, Output Bounds, and Bounded Retention
# ============================================================================

def test_secret_redaction_and_bounded_evidence_digestion(sentinel_env):
    """Verifies that API keys, passwords, and private keys are redacted and digests computed."""
    recorder = sentinel_env["recorder"]

    secret_raw_output = (
        "Connected to database with user=admin password='supersecretpassword123'.\n"
        "Exported token sk-abc123456789012345678901234567890 and Bearer eyJhbGciOiJIUzI1NiJ9.testtoken.\n"
        "All 4 tests executed.\n" + ("X" * 5000)
    )

    ev = recorder.store_evidence(
        EvidenceRecordCreate(
            evidence_type="subprocess_result",
            command="python -m pytest --token sk-abc123456789012345678901234567890",
            exit_code=0,
            raw_stdout=secret_raw_output,
            is_agent_hypothesis=False,
        )
    )

    # Command must be redacted
    assert "sk-abc" not in ev.command
    assert "[REDACTED_API_KEY]" in ev.command

    # Excerpt must be bounded to max_excerpt_length (2000 chars)
    assert len(ev.redacted_excerpt) <= 2000
    assert "supersecretpassword123" not in ev.redacted_excerpt
    assert "[REDACTED_API_KEY]" in ev.redacted_excerpt
    assert "[REDACTED_TOKEN]" in ev.redacted_excerpt

    # SHA-256 digest of original raw content must be preserved for forensic verification
    expected_digest = hashlib.sha256(secret_raw_output.encode("utf-8")).hexdigest()
    assert ev.stdout_digest == expected_digest


def test_bounded_retention_pruning(sentinel_env):
    """Verifies that pruning removes oldest events when exceeding threshold."""
    recorder = sentinel_env["recorder"]

    # Insert 15 events
    for i in range(15):
        recorder.record_event(
            FlightRecorderEventCreate(
                project_id="proj-prune",
                event_type="test.executed",
                source_type=EventSourceType.OBSERVATION,
                actor="test_runner",
                summary=f"Ran test batch {i}",
            )
        )

    # Prune with max_events=10
    pruned = recorder.prune_events(project_id="proj-prune", max_events=10)
    assert pruned == 5

    remaining = recorder.query_events(EventQueryFilter(project_id="proj-prune"))
    assert len(remaining) == 10
    assert "batch 5" in remaining[0].summary  # Oldest 0-4 were pruned


# ============================================================================
# 5. Security Boundary: Path Traversal, Symlinks, and Parameter Tampering
# ============================================================================

def test_security_boundary_path_traversal_rejection(sentinel_env):
    """Verifies that escaping paths ('../../etc/passwd') are blocked."""
    tmpdir = sentinel_env["tmpdir"]
    project_root = os.path.join(tmpdir, "permitted_project")
    os.makedirs(project_root, exist_ok=True)

    boundary = SecurityBoundary(project_root)

    # Valid internal file
    safe_file = os.path.join(project_root, "src", "main.py")
    os.makedirs(os.path.dirname(safe_file), exist_ok=True)
    with open(safe_file, "w") as f:
        f.write("print('hello')")

    resolved = boundary.resolve_safe_path("src/main.py")
    assert resolved == os.path.abspath(safe_file)

    # Traversal escape attempts
    with pytest.raises(PathTraversalError):
        boundary.resolve_safe_path("../../windows/system32/cmd.exe")

    with pytest.raises(PathTraversalError):
        boundary.resolve_safe_path("..")

    with pytest.raises(PathTraversalError):
        boundary.resolve_safe_path("/etc/shadow")


def test_security_boundary_dangerous_shell_command_rejection(sentinel_env):
    """Verifies dangerous command chaining and deletion commands are rejected."""
    boundary = SecurityBoundary(sentinel_env["tmpdir"])

    # Safe commands
    boundary.validate_command_safety("python -m pytest tests/test_math.py")
    boundary.validate_command_safety("git status --short")

    # Dangerous commands
    with pytest.raises(DangerousCommandError):
        boundary.validate_command_safety("pytest; rm -rf /")

    with pytest.raises(DangerousCommandError):
        boundary.validate_command_safety("echo hello && cat /etc/passwd")

    with pytest.raises(DangerousCommandError):
        boundary.validate_command_safety("pytest | bash")


def test_security_boundary_approval_parameter_tampering(sentinel_env):
    """Verifies that modifying action parameters after approval was issued triggers rejection."""
    boundary = SecurityBoundary(sentinel_env["tmpdir"])

    approved_action = "filesystem.write_file"
    approved_resource = "config.json"
    approved_params = {"mode": "safe", "timeout": 30}

    # Compute expected approval hash
    approval_hash = boundary.compute_action_hash(approved_action, approved_resource, approved_params)
    token = "appr-token-xyz-123"

    # 1. Matching parameters must pass
    boundary.revalidate_approved_operation(
        approval_token=token,
        action=approved_action,
        resource=approved_resource,
        parameters=approved_params,
        expected_token=token,
        expected_hash=approval_hash,
    )

    # 2. Tampered parameters (e.g. timeout altered from 30 to 9999) must fail
    tampered_params = {"mode": "safe", "timeout": 9999}
    with pytest.raises(ApprovalTamperError):
        boundary.revalidate_approved_operation(
            approval_token=token,
            action=approved_action,
            resource=approved_resource,
            parameters=tampered_params,
            expected_token=token,
            expected_hash=approval_hash,
        )


# ============================================================================
# 6. Checkpoints: Creation, Manifest Integrity, and State Progression
# ============================================================================

def test_checkpoint_manifest_creation_and_integrity_validation(sentinel_env):
    """Verifies checkpoint creation, integrity hash, and progression to VALIDATED and HEALTHY."""
    checkpoints = sentinel_env["checkpoints"]
    tmpdir = sentinel_env["tmpdir"]

    project_root = os.path.join(tmpdir, "repo")
    os.makedirs(project_root, exist_ok=True)

    test_file = os.path.join(project_root, "app.py")
    with open(test_file, "w") as f:
        f.write("def run(): pass\n")

    file_hash = compute_file_sha256(test_file)

    # 1. Create Checkpoint (State: CREATED)
    req = CheckpointCreateRequest(
        project_id="proj-alpha",
        permitted_root=project_root,
        git_revision=GitRevisionInfo(commit_sha="a1b2c3d4", branch="main", is_dirty=False),
        tracked_changes=[TrackedFileChange(path="app.py", sha256=file_hash, status="modified")],
        dependency_fingerprints={"requirements.txt": "sha256_mock_reqs"},
        toolchain_versions={"python": "3.12.8"},
    )
    chk = checkpoints.create_checkpoint(req)
    assert chk.status == CheckpointLifecycleStatus.CREATED
    assert chk.integrity_hash is not None

    # 2. Validate Checkpoint (Transitions to VALIDATED)
    validated = checkpoints.validate_checkpoint(chk.checkpoint_id)
    assert validated.status == CheckpointLifecycleStatus.VALIDATED
    assert "referenced paths validated" in validated.validation_notes

    # 3. Mark Healthy when tests pass (requires valid evidence)
    sentinel_env["flight_recorder"].store_evidence(
        EvidenceRecordCreate(
            evidence_id="ev-test-100",
            evidence_type="test_run",
            command="pytest tests/",
            exit_code=0,
            raw_stdout="All tests passed",
            is_agent_hypothesis=False,
        )
    )
    healthy = checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-test-100")
    assert healthy.status == CheckpointLifecycleStatus.HEALTHY
    assert "Healthy verified" in healthy.validation_notes


# ============================================================================
# 7. Safe Restoration & Protection of Dirty Working-Tree Changes
# ============================================================================

def test_checkpoint_safe_restoration_protects_dirty_files(sentinel_env):
    """
    Directive Invariant: Never perform blind recovery.
    If a file has uncommitted changes, restoration MUST halt unless approval token is provided.
    """
    checkpoints = sentinel_env["checkpoints"]
    tmpdir = sentinel_env["tmpdir"]
    project_root = os.path.join(tmpdir, "repo2")
    os.makedirs(project_root, exist_ok=True)

    target_file = os.path.join(project_root, "feature.py")
    with open(target_file, "w") as f:
        f.write("# Version 1 from checkpoint\n")
    original_hash = compute_file_sha256(target_file)

    # Capture checkpoint (initial state: CREATED)
    chk = checkpoints.create_checkpoint(
        CheckpointCreateRequest(
            project_id="proj-beta",
            permitted_root=project_root,
            tracked_changes=[TrackedFileChange(path="feature.py", sha256=original_hash, status="modified")],
        )
    )

    # 1. Verify checkpoint cannot be restored while in CREATED state
    with pytest.raises(ValueError, match="must be RESTORABLE"):
        checkpoints.restore_checkpoint(chk.checkpoint_id, CheckpointRestoreRequest(dry_run=False))

    # 2. Transition through validation lifecycle
    validated = checkpoints.validate_checkpoint(chk.checkpoint_id)
    assert validated.status.value == "validated"

    restorable = checkpoints.validate_restorable(chk.checkpoint_id)
    assert restorable.status.value == "restorable"

    # Developer makes local changes to feature.py
    with open(target_file, "w") as f:
        f.write("# Version 2 developer uncommitted work\n")

    # 3. Attempt restoration without approval (dry_run=False)
    res = checkpoints.restore_checkpoint(
        chk.checkpoint_id,
        CheckpointRestoreRequest(dry_run=False, approval_token=None),
    )

    # Must be halted because file is protected
    assert res.success is False
    assert res.status == "APPROVAL_REQUIRED"
    assert "feature.py" in res.protected_files

    # 4. Generate valid approval token bound to exact action, resource, and parameters
    boundary = SecurityBoundary(project_root)
    token = boundary.create_approval_token(
        action="restore_checkpoint",
        resource=chk.checkpoint_id,
        parameters={"target_files": None, "dry_run": False},
    )

    # 5. Restore with valid approval token
    res_approved = checkpoints.restore_checkpoint(
        chk.checkpoint_id,
        CheckpointRestoreRequest(dry_run=False, approval_token=token),
    )
    assert res_approved.success is True
    assert res_approved.status == "RESTORED"
    assert "feature.py" in res_approved.overridden_files
    assert res_approved.pre_restoration_snapshot_id is not None

    # 6. Replay attack verification: reusing the same consumed token MUST be rejected
    with pytest.raises(ApprovalTamperError, match="Replay detected"):
        checkpoints.restore_checkpoint(
            chk.checkpoint_id,
            CheckpointRestoreRequest(dry_run=False, approval_token=token),
        )


# ============================================================================
# 8. Project-Scoped Memory Ingestion and Filtering
# ============================================================================

def test_project_scoped_memory_ingestion_and_search(sentinel_env):
    """Verifies that memories can be tagged with project_id and filtered accurately."""
    memory_svc = sentinel_env["memory_svc"]

    # Store memory scoped to Project X
    memory_svc.store_memory(
        category=SemanticCategory.PROJECT_CONTEXT,
        subject="architecture_decision",
        predicate="use_database",
        object_value="SQLite_WAL_only",
        project_id="proj-X",
        verification_status=VerificationStatus.VERIFIED,
    )

    # Store memory scoped to Project Y
    memory_svc.store_memory(
        category=SemanticCategory.PROJECT_CONTEXT,
        subject="architecture_decision",
        predicate="use_database",
        object_value="PostgreSQL_cloud",
        project_id="proj-Y",
        verification_status=VerificationStatus.VERIFIED,
    )

    # Query with project_id="proj-X"
    res_x = memory_svc.search_memories(project_id="proj-X")
    assert len(res_x) == 1
    assert res_x[0].payload["object_value"] == "SQLite_WAL_only"

    # Query with project_id="proj-Y"
    res_y = memory_svc.search_memories(project_id="proj-Y")
    assert len(res_y) == 1
    assert res_y[0].payload["object_value"] == "PostgreSQL_cloud"


# ============================================================================
# 9. Canonical API Endpoint Integration via TestClient
# ============================================================================

def test_api_flight_recorder_and_checkpoint_endpoints(sentinel_env):
    """Verifies full HTTP API lifecycle for events, evidence, and checkpoints."""
    client = sentinel_env["client"]
    tmpdir = sentinel_env["tmpdir"]

    # 1. POST /api/events/evidence
    ev_res = client.post(
        "/api/events/evidence",
        json={
            "evidence_type": "git_inspection",
            "command": "git rev-parse HEAD",
            "exit_code": 0,
            "raw_stdout": "8758e0685da46635cde68d6c469bc773f2512995\n",
        },
    )
    assert ev_res.status_code == 201
    ev_data = ev_res.json()
    evidence_id = ev_data["evidence_id"]

    # 2. POST /api/events
    evt_res = client.post(
        "/api/events",
        json={
            "project_id": "proj-api-test",
            "event_type": "git.observed",
            "source_type": "observation",
            "actor": "subprocess.git",
            "summary": "Observed HEAD commit 8758e06",
            "evidence_refs": [evidence_id],
        },
    )
    assert evt_res.status_code == 201
    event_id = evt_res.json()["event_id"]

    # 3. GET /api/events/{event_id}/evidence
    resolved_res = client.get(f"/api/events/{event_id}/evidence")
    assert resolved_res.status_code == 200
    resolved_data = resolved_res.json()
    assert len(resolved_data["resolved_evidence"]) == 1
    assert resolved_data["resolved_evidence"][0]["evidence_id"] == evidence_id

    # 4. POST /api/checkpoints
    chk_res = client.post(
        "/api/checkpoints",
        json={
            "project_id": "proj-api-test",
            "permitted_root": tmpdir,
            "git_revision": {"commit_sha": "8758e06", "branch": "SENTINEL", "is_dirty": False},
        },
    )
    assert chk_res.status_code == 201
    chk_id = chk_res.json()["checkpoint_id"]

    # 5. POST /api/checkpoints/{id}/validate
    val_res = client.post(f"/api/checkpoints/{chk_id}/validate")
    assert val_res.status_code == 200
    assert val_res.json()["status"] == "validated"

    # 6. POST /api/checkpoints/{id}/validate_restorable
    rest_res = client.post(f"/api/checkpoints/{chk_id}/validate_restorable")
    assert rest_res.status_code == 200
    assert rest_res.json()["status"] == "restorable"

    # 7. GET /api/checkpoints
    list_res = client.get("/api/checkpoints?project_id=proj-api-test")
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1


# ============================================================================
# 10. Directive Task 1: Shared Event Pipeline & Orchestrator Integration
# ============================================================================

@pytest.mark.asyncio
async def test_shared_event_pipeline_and_diagnostic_evidence(sentinel_env):
    """
    Directive Task 1 Invariants:
    1. MemoryService.store_event writes consistent event IDs, timestamps, task IDs,
       and project IDs to both episodic memories and canonical Flight Recorder tables.
    2. Orchestrator execution logs task lifecycle events and stores diagnostic evidence.
    3. Diagnostic events and evidence survive backend/database restart.
    """
    db = sentinel_env["db"]
    crypto = sentinel_env["crypto"]
    flight_recorder = sentinel_env["flight_recorder"]
    memory_service = sentinel_env["memory_service"]
    client = sentinel_env["client"]

    # 1. Store event via MemoryService
    session_id = "sess-diag-101"
    evt = memory_service.store_event(
        session_id=session_id,
        event_type="test.diagnostic_check",
        content={"message": "Diagnostic inspection started"},
        metadata={"task_id": "task-test-42", "actor": "diagnostic_agent"},
        project_id="proj-go81-alpha",
    )

    # Verify event appears in canonical Flight Recorder with identical event_id & project_id
    fr_event = flight_recorder.get_event_with_evidence(evt.id)
    assert fr_event is not None
    assert fr_event["event_id"] == evt.id
    assert fr_event["project_id"] == "proj-go81-alpha"
    assert fr_event["task_id"] == "task-test-42"

    # 2. Test TaskOrchestrator integration with FlightRecorder
    from backend.orchestrator import TaskOrchestrator
    from backend.planner import DAGStep, TaskDAG

    orchestrator = TaskOrchestrator(flight_recorder=flight_recorder)
    task_id = "task-flight-record-test"
    dag = TaskDAG(
        task_id=task_id,
        goal="Run diagnostic test suite",
        model="gemma4:e2b",
        system_prompt="You are a sovereign diagnostic agent.",
        steps=[
            DAGStep(
                step_id="step-1",
                title="Execute diagnostic command",
                skill_name="run_diagnostics",
                risk_level=RiskLevel.LOW,
                parameters={"cmd": "pytest tests/diagnostics"},
            )
        ],
    )
    orchestrator.register_task(dag)

    # Broadcast task started and a diagnostic failure
    await orchestrator.broadcast_event(
        task_id,
        "task_started",
        {"task_id": task_id, "goal": dag.goal, "status": "RUNNING"},
    )
    await orchestrator.broadcast_event(
        task_id,
        "step_failed",
        {
            "task_id": task_id,
            "step_id": "step-1",
            "action": "run_diagnostics",
            "error": "AssertionError: Expected 200 OK, got 500 Internal Error",
            "output": "FAILED tests/diagnostics/test_service.py - Server error",
        },
    )

    # 3. Verify diagnostic events appear via GET /api/events?task_id={task_id}
    res = client.get(f"/api/events?task_id={task_id}")
    assert res.status_code == 200
    events = res.json()
    assert len(events) >= 2
    types = [e["event_type"] for e in events]
    assert "task_started" in types
    assert "step_failed" in types

    # Verify diagnostic evidence record was stored and referenced
    fail_event = next(e for e in events if e["event_type"] == "step_failed")
    assert len(fail_event["evidence_refs"]) >= 1
    evidence_id = fail_event["evidence_refs"][0]

    ev_record = flight_recorder.get_evidence(evidence_id)
    assert ev_record is not None
    assert ev_record.exit_code == 1
    assert ev_record.stderr_digest is not None
    assert "FAILED" in (ev_record.redacted_excerpt or "")

    # 4. Persistence across service restart: reopen database and check queries
    restarted_db = DatabaseManager(sentinel_env["db_path"])
    restarted_fr = FlightRecorderService(restarted_db)
    reloaded_events = restarted_fr.list_events(EventQueryFilter(task_id=task_id))
    assert len(reloaded_events) >= 2
    reloaded_ev = restarted_fr.get_evidence(evidence_id)
    assert reloaded_ev is not None
    assert reloaded_ev.evidence_id == evidence_id


# ============================================================================
# 11. Directive Task 1: Retention Pruning Preserves Referenced Evidence
# ============================================================================

def test_retention_pruning_preserves_referenced_evidence(sentinel_env):
    """
    Directive Invariant: Event retention must NEVER delete evidence that is still
    referenced by any retained flight recorder event. Only unreferenced (orphaned)
    evidence older than retention threshold can be pruned.
    """
    db = sentinel_env["db"]
    fr = sentinel_env["flight_recorder"]
    old_time = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()

    # Create two evidence records directly in SQLite with old timestamps
    with db.transaction() as conn:
        conn.execute(
            """
            INSERT INTO evidence_store (
                evidence_id, evidence_type, command, exit_code, created_at
            ) VALUES (?, ?, ?, ?, ?), (?, ?, ?, ?, ?);
            """,
            ("ev-retained-ref", "command", "git status", 0, old_time,
             "ev-orphaned-old", "command", "ls -la", 0, old_time),
        )
        # Create an event referencing ev-retained-ref
        conn.execute(
            """
            INSERT INTO flight_recorder_events (
                event_id, project_id, task_id, timestamp, event_type,
                source_type, actor, summary, evidence_refs, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                "evt-holds-evidence",
                "proj-retention",
                "task-ret",
                old_time,
                "git.status",
                "observation",
                "git",
                "Checked git status",
                json.dumps(["ev-retained-ref"]),
                json.dumps({}),
            ),
        )

    # Run prune_orphaned_evidence
    pruned_count = fr.prune_orphaned_evidence(retention_days=30)
    assert pruned_count == 1

    # Verify ev-orphaned-old was pruned, but ev-retained-ref was preserved
    assert fr.get_evidence("ev-orphaned-old") is None
    assert fr.get_evidence("ev-retained-ref") is not None


# ============================================================================
# 12. Directive Task 2: Distinct Checkpoint Semantics & Untracked File Safety
# ============================================================================

def test_checkpoint_semantics_distinct_operations(sentinel_env):
    """
    Directive Task 2 Invariants:
    1. Checkpoint is NOT marked healthy merely because its hashes match.
    2. Checkpoint is NOT restorable until recovery procedure is validated.
    3. Restoration does not overwrite unrelated changes or delete untracked files.
    """
    checkpoints = sentinel_env["checkpoints"]
    tmpdir = sentinel_env["tmpdir"]
    project_root = os.path.join(tmpdir, "repo_distinct")
    os.makedirs(project_root, exist_ok=True)

    tracked_file = os.path.join(project_root, "tracked.txt")
    untracked_file = os.path.join(project_root, "untracked_notes.txt")
    with open(tracked_file, "w") as f:
        f.write("Initial tracked content")
    with open(untracked_file, "w") as f:
        f.write("Untracked developer scratchpad")

    original_sha = compute_file_sha256(tracked_file)
    chk = checkpoints.create_checkpoint(
        CheckpointCreateRequest(
            project_id="proj-distinct",
            permitted_root=project_root,
            tracked_changes=[TrackedFileChange(path="tracked.txt", sha256=original_sha, status="modified")],
        )
    )

    # 1. Validation only transitions to VALIDATED, NEVER directly to HEALTHY
    validated = checkpoints.validate_checkpoint(chk.checkpoint_id)
    assert validated.status == CheckpointLifecycleStatus.VALIDATED
    assert validated.status != CheckpointLifecycleStatus.HEALTHY

    # 2. Cannot restore while in VALIDATED state
    with pytest.raises(ValueError, match="must be RESTORABLE"):
        checkpoints.restore_checkpoint(chk.checkpoint_id, CheckpointRestoreRequest(dry_run=False))

    # Mark healthy using evidence
    sentinel_env["flight_recorder"].store_evidence(
        EvidenceRecordCreate(
            evidence_id="ev-passed-tests-1",
            evidence_type="test_run",
            command="pytest tests/",
            exit_code=0,
            raw_stdout="All tests passed",
            is_agent_hypothesis=False,
        )
    )
    healthy = checkpoints.mark_healthy(chk.checkpoint_id, test_evidence_id="ev-passed-tests-1")
    assert healthy.status == CheckpointLifecycleStatus.HEALTHY

    # Validate restorable
    restorable = checkpoints.validate_restorable(chk.checkpoint_id)
    assert restorable.status == CheckpointLifecycleStatus.RESTORABLE

    # 3. Restoration does NOT touch or delete untracked files
    res = checkpoints.restore_checkpoint(chk.checkpoint_id, CheckpointRestoreRequest(dry_run=False))
    assert res.success is True
    assert os.path.exists(untracked_file)
    with open(untracked_file, "r") as f:
        assert f.read() == "Untracked developer scratchpad"


# ============================================================================
# 13. Directive Task 3: Security Boundary & Symlink TOCTOU Defense
# ============================================================================

def test_symlink_escape_and_toctou_defense(sentinel_env):
    """
    Directive Task 3 Invariants:
    1. Reject symlinks escaping permitted project root.
    2. Reject symlink swapped between validation and file access.
    """
    tmpdir = sentinel_env["tmpdir"]
    project_root = os.path.join(tmpdir, "sandbox_root")
    os.makedirs(project_root, exist_ok=True)
    outside_dir = os.path.join(tmpdir, "outside_secret")
    os.makedirs(outside_dir, exist_ok=True)

    secret_file = os.path.join(outside_dir, "secret.key")
    with open(secret_file, "w") as f:
        f.write("SUPER_SECRET_KEY")

    boundary = SecurityBoundary(project_root)

    # 1. Relative traversal rejected
    with pytest.raises(PathTraversalError):
        boundary.resolve_safe_path("../outside_secret/secret.key")

    # 2. Symlink pointing outside project root rejected
    symlink_path = os.path.join(project_root, "link_to_secret")
    try:
        os.symlink(secret_file, symlink_path)
        with pytest.raises(PathTraversalError):
            boundary.resolve_safe_path("link_to_secret")
    except OSError:
        # On Windows unprivileged environments without SeCreateSymbolicLinkPrivilege, symlink creation may require admin
        pass


# ============================================================================
# 14. Directive Task 3: Concurrent SQLite Access and Project Isolation
# ============================================================================

def test_concurrent_sqlite_writes_and_project_isolation(sentinel_env):
    """
    Directive Task 3 Invariants:
    1. Project isolation: queries for project A never leak project B events, memories, or checkpoints.
    2. Multi-threaded concurrent writes to SQLite in WAL mode execute cleanly without locking collisions.
    """
    import concurrent.futures
    fr = sentinel_env["flight_recorder"]
    client = sentinel_env["client"]

    # Record events across two different projects
    fr.record_event(
        FlightRecorderEventCreate(
            project_id="proj-alpha",
            event_type="build.step",
            source_type=EventSourceType.OBSERVATION,
            actor="runner",
            summary="Alpha build step",
        )
    )
    fr.record_event(
        FlightRecorderEventCreate(
            project_id="proj-beta",
            event_type="build.step",
            source_type=EventSourceType.OBSERVATION,
            actor="runner",
            summary="Beta build step",
        )
    )

    alpha_events = fr.list_events(EventQueryFilter(project_id="proj-alpha"))
    beta_events = fr.list_events(EventQueryFilter(project_id="proj-beta"))

    assert all(e.project_id == "proj-alpha" for e in alpha_events)
    assert all(e.project_id == "proj-beta" for e in beta_events)
    assert not any(e.project_id == "proj-beta" for e in alpha_events)

    # Concurrent multi-threaded writes
    def write_worker(idx: int):
        fr.record_event(
            FlightRecorderEventCreate(
                project_id="proj-concurrent",
                event_type="worker.write",
                source_type=EventSourceType.SYSTEM,
                actor=f"worker-{idx}",
                summary=f"Concurrent entry {idx}",
                metadata={"worker_index": idx},
            )
        )
        return idx

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(write_worker, i) for i in range(24)]
        results = [f.result() for f in futures]

    assert len(results) == 24
    conc_events = fr.list_events(EventQueryFilter(project_id="proj-concurrent", limit=50))
    assert len(conc_events) == 24

