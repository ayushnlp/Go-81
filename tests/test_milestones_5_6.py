"""
Integration tests for Milestone 5 (Memory Handshake) and Milestone 6 (Frontend Handshake).
Tests:
- Milestone 5: query_relevant_context() invocation, verified facts & preference injection into gemma4:e2b prompt.
- Milestone 6: CORSMiddleware origins, SSE stream (media_type="text/event-stream"), and DAG approval resumption.
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from backend.main import app, get_orchestrator, get_planner
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.models import RiskLevel, SemanticCategory, VerificationStatus
from app.memory.service import query_relevant_context
from backend.planner import TaskPlanner


@pytest.fixture
def client_and_services():
    """Initializes temporary encrypted DB and clean test client."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "handshake_test.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        # Pre-seed verified facts and preferences for Milestone 5 testing
        mem_svc = SubsystemContainer.memory_service
        assert mem_svc is not None

        # Seed preference: language Python
        mem_svc.store_memory(
            category=SemanticCategory.PREFERENCE,
            subject="operator",
            predicate="preferred_runtime",
            object_value="Python 3.12",
            verification_status=VerificationStatus.USER_PROVIDED,
        )

        # Seed verified constraint: sovereign local execution only
        mem_svc.store_memory(
            category=SemanticCategory.PROJECT_CONTEXT,
            subject="security_policy",
            predicate="telemetry_allowed",
            object_value="False",
            verification_status=VerificationStatus.VERIFIED,
        )

        # Seed verified fact: backup directory
        mem_svc.store_memory(
            category=SemanticCategory.FACT,
            subject="go81_backup",
            predicate="destination_path",
            object_value="/var/data/go81_backups",
            verification_status=VerificationStatus.VERIFIED,
        )

        # Reset backend singletons
        import backend.main
        backend.main.orchestrator = None
        backend.main.planner = None

        with TestClient(app) as test_client:
            yield test_client, mem_svc

        # Teardown
        SubsystemContainer.db = None
        SubsystemContainer.memory_service = None
        SubsystemContainer.recovery_manager = None
        SubsystemContainer.permission_gateway = None
        SubsystemContainer.consolidation_engine = None
        backend.main.orchestrator = None
        backend.main.planner = None


# ============================================================================
# Milestone 5: Memory Handshake & Task Planner Tests
# ============================================================================

def test_query_relevant_context_retrieves_facts_and_preferences(client_and_services):
    """Verifies query_relevant_context retrieves verified facts and preferences for user goal."""
    client, mem_svc = client_and_services

    goal = "Create an automated database backup script and verify files"
    context = query_relevant_context(goal, memory_service=mem_svc)

    assert "verified_facts" in context
    assert "preferences" in context
    assert "constraints" in context
    assert "formatted_context" in context

    # Check preferences
    pref_values = [p["object_value"] for p in context["preferences"]]
    assert "Python 3.12" in pref_values

    # Check constraints
    constraint_values = [c["object_value"] for c in context["constraints"]]
    assert "False" in constraint_values

    # Check verified facts
    fact_values = [f["object_value"] for f in context["verified_facts"]]
    assert "/var/data/go81_backups" in fact_values


def test_task_planner_injects_context_into_gemma4_system_prompt(client_and_services):
    """Verifies TaskPlanner injects retrieved verified facts into system prompt passed to gemma4:e2b."""
    client, mem_svc = client_and_services

    planner = TaskPlanner(
        model="gemma4:e2b",
        ollama_endpoint="http://127.0.0.1:11434",
        memory_service=mem_svc,
    )

    user_goal = "Backup the database using local toolchain"
    dag = planner.generate_dag(user_goal)

    assert dag.model == "gemma4:e2b"
    assert dag.goal == user_goal
    assert "gemma4:e2b" in dag.system_prompt

    # Verify memory injection into the prompt
    assert "USER PREFERENCES:" in dag.system_prompt
    assert "Python 3.12" in dag.system_prompt
    assert "CONSTRAINTS & POLICIES:" in dag.system_prompt
    assert "telemetry_allowed" in dag.system_prompt
    assert "/var/data/go81_backups" in dag.system_prompt

    # Verify DAG structure and risk classification
    assert len(dag.steps) >= 3
    # High-risk step must require approval
    high_risk_steps = [s for s in dag.steps if s.risk_level == RiskLevel.HIGH]
    assert len(high_risk_steps) >= 1
    for hs in high_risk_steps:
        assert hs.requires_approval is True


# ============================================================================
# Milestone 6: Frontend Handshake Tests (CORS, SSE, Approval Resumption)
# ============================================================================

def test_cors_middleware_configuration(client_and_services):
    """Verifies CORS headers allow http://localhost:5173, http://localhost:3000, and *."""
    client, _ = client_and_services

    # Preflight request from Vite port 5173
    res_5173 = client.options(
        "/api/tasks",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert res_5173.status_code == 200
    assert res_5173.headers.get("access-control-allow-origin") in ("*", "http://localhost:5173")

    # Preflight request from Next.js port 3000
    res_3000 = client.options(
        "/api/tasks",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert res_3000.status_code == 200
    assert res_3000.headers.get("access-control-allow-origin") in ("*", "http://localhost:3000")


def test_sse_event_stream_media_type_and_flushing(client_and_services):
    """
    Verifies GET /api/tasks/{task_id}/events/stream sets media_type="text/event-stream"
    and streams task connection and step events.
    """
    client, _ = client_and_services

    # 1. Create a task via API
    r_task = client.post("/api/tasks", json={"goal": "Audit project permissions"})
    assert r_task.status_code == 201
    task_data = r_task.json()
    task_id = task_data["task_id"]

    # 2. Connect to SSE stream
    with client.stream("GET", f"/api/tasks/{task_id}/events/stream") as stream:
        assert stream.status_code == 200
        # Verify media_type="text/event-stream"
        content_type = stream.headers.get("content-type", "")
        assert "text/event-stream" in content_type

        # Read initial events from the stream
        events_received = []
        for line in stream.iter_lines():
            if line:
                events_received.append(line)
            if len(events_received) >= 4:
                break

        # Verify stream contains structured SSE events
        joined = "\n".join(events_received)
        assert "event: task_connected" in joined
        assert task_id in joined


def test_post_approval_resumes_paused_dag_branch(client_and_services):
    """
    Verifies POST /api/approvals/{approval_id} successfully resumes paused DAG branches.
    """
    client, _ = client_and_services
    orchestrator = get_orchestrator()

    # 1. Create task that will pause on high-risk step
    r_create = client.post("/api/tasks", json={"goal": "Deploy updated smart contracts"})
    assert r_create.status_code == 201
    task_data = r_create.json()
    task_id = task_data["task_id"]

    # 2. Query pending approvals
    r_appr = client.get("/api/approvals")
    assert r_appr.status_code == 200
    pending_list = r_appr.json()
    assert len(pending_list) >= 1

    appr = pending_list[0]
    approval_id = appr["approval_id"]
    assert appr["task_id"] == task_id

    # 3. Verify task is in PAUSED_APPROVAL state
    r_task = client.get(f"/api/tasks/{task_id}")
    assert r_task.status_code == 200
    task_state = r_task.json()
    assert task_state["status"] == "PAUSED_APPROVAL"

    # 4. Submit approval decision via POST /api/approvals/{approval_id}
    r_submit = client.post(
        f"/api/approvals/{approval_id}",
        json={"decision": "approved", "notes": "Approved by security officer"},
    )
    assert r_submit.status_code == 200
    submit_data = r_submit.json()
    assert submit_data["success"] is True
    assert submit_data["status"] == "approved"
    assert submit_data["approval_id"] == approval_id

    # 5. Verify task is no longer paused and step completed
    r_resumed_task = client.get(f"/api/tasks/{task_id}")
    assert r_resumed_task.status_code == 200
    resumed_data = r_resumed_task.json()
    # Task should now be COMPLETED or RUNNING, not paused
    assert resumed_data["status"] in ("RUNNING", "COMPLETED")
    resumed_step = next(s for s in resumed_data["steps"] if s["step_id"] == appr["step_id"])
    assert resumed_step["status"] == "COMPLETED"


def test_post_approval_rejection_marks_task_failed(client_and_services):
    """Verifies rejecting an approval terminates the paused DAG branch."""
    client, _ = client_and_services

    # 1. Create task
    r_create = client.post("/api/tasks", json={"goal": "Execute dangerous wipe"})
    assert r_create.status_code == 201
    task_id = r_create.json()["task_id"]

    # 2. Get approval ID
    pending = client.get("/api/approvals").json()
    target_appr = next(a for a in pending if a["task_id"] == task_id)

    # 3. Reject
    r_rej = client.post(
        f"/api/approvals/{target_appr['approval_id']}",
        json={"decision": "rejected", "notes": "Unauthorized operation"},
    )
    assert r_rej.status_code == 200
    assert r_rej.json()["status"] == "rejected"

    # 4. Check task is FAILED
    r_task = client.get(f"/api/tasks/{task_id}")
    assert r_task.json()["status"] == "FAILED"
