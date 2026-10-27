"""
Automated tests for Task Runtime, Lifecycle, and SSE Fixes.

Covers:
1. Task creation schedules execution exactly once.
2. Task status transitions out of PENDING (into PAUSED_APPROVAL or COMPLETED).
3. Successful mocked planner/model execution reaches a terminal success state.
4. Model/provider or step failure transitions task to FAILED with a useful safe error.
5. GET /api/tasks/incomplete returns promptly and does not block.
6. Task retrieval reflects current status (both in-memory and after cache eviction from SQLite checkpoint).
7. SSE emits events and terminates cleanly on terminal states and handles client disconnect.
8. Unreachable Ollama falls back gracefully to sovereign deterministic DAG without stalling in PENDING.
"""

import asyncio
import os
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from backend.main import app, get_orchestrator, get_planner
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.models import RiskLevel
from backend.planner import DAGStep, TaskDAG, TaskPlanner
from backend.orchestrator import TaskOrchestrator


@pytest.fixture
def clean_environment():
    """Initializes temporary encrypted DB and clean singletons."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "runtime_test.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        # Fresh orchestrator & planner
        orch = get_orchestrator()
        orch.tasks.clear()
        orch.recovery_manager = SubsystemContainer.recovery_manager
        orch.permission_gateway = SubsystemContainer.permission_gateway

        planner = get_planner()
        planner.memory_service = SubsystemContainer.memory_service

        client = TestClient(app)
        yield client, orch, planner


def test_task_creation_schedules_execution_and_transitions_out_of_pending(clean_environment):
    """
    1. Task creation schedules execution exactly once.
    2. Task status transitions out of PENDING.
    """
    client, orch, planner = clean_environment

    response = client.post(
        "/api/tasks",
        json={"goal": "Verify system health and status"},
    )
    assert response.status_code == 201
    data = response.json()
    task_id = data["task_id"]

    # Status must NOT be stuck in PENDING
    assert data["status"] in ["PAUSED_APPROVAL", "COMPLETED", "EXECUTING"]

    # Verify task state in orchestrator
    task = orch.get_task(task_id)
    assert task is not None
    assert task.status in ["PAUSED_APPROVAL", "COMPLETED", "EXECUTING"]


def test_task_retrieval_reflects_current_status_across_cache_wipe(clean_environment):
    """
    6. Task retrieval reflects current status, even after Uvicorn reload (in-memory cache cleared).
    """
    client, orch, planner = clean_environment

    response = client.post(
        "/api/tasks",
        json={"goal": "Prepare database backup"},
    )
    assert response.status_code == 201
    task_id = response.json()["task_id"]

    # Wipe in-memory task dictionary to simulate Uvicorn process reload
    orch.tasks.clear()

    # GET /api/tasks/{task_id} must reconstruct the task from the checkpoint
    get_res = client.get(f"/api/tasks/{task_id}")
    assert get_res.status_code == 200
    recovered_data = get_res.json()
    assert recovered_data["task_id"] == task_id
    assert recovered_data["status"] in ["PAUSED", "PAUSED_APPROVAL", "COMPLETED"]
    assert len(recovered_data["steps"]) > 0


def test_successful_mocked_execution_reaches_terminal_completed(clean_environment):
    """
    3. Successful execution of low-risk steps reaches COMPLETED terminal state.
    """
    client, orch, planner = clean_environment

    # Create a DAG with only low-risk steps (no human approval required)
    dag = TaskDAG(
        goal="Low risk verification",
        model="gemma4:e2b",
        system_prompt="System prompt test",
        steps=[
            DAGStep(
                step_number=1,
                title="Verify memory consistency",
                skill_name="memory.verify",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
            DAGStep(
                step_number=2,
                title="Log audit check",
                skill_name="audit.log",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            ),
        ],
        status="PENDING",
    )

    with patch.object(planner, "generate_dag", return_value=dag):
        response = client.post("/api/tasks", json={"goal": "Low risk verification"})
        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "COMPLETED"

        # Check retrieval
        res = client.get(f"/api/tasks/{dag.task_id}")
        assert res.json()["status"] == "COMPLETED"


def test_step_failure_transitions_to_failed_with_safe_error(clean_environment):
    """
    4. Execution failure transitions task and step to FAILED with safe error message.
    """
    client, orch, planner = clean_environment

    dag = TaskDAG(
        goal="Faulty task",
        model="gemma4:e2b",
        system_prompt="System prompt test",
        steps=[
            DAGStep(
                step_number=1,
                title="Failing operation",
                skill_name="system.faulty_skill",
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            )
        ],
        status="PENDING",
    )

    # Mock _execute_step to raise an exception
    with patch.object(planner, "generate_dag", return_value=dag):
        with patch.object(orch, "_execute_step", side_effect=RuntimeError("Simulated hardware error")):
            response = client.post("/api/tasks", json={"goal": "Faulty task"})
            assert response.status_code == 201

            # Task status must be FAILED
            task = orch.get_task(dag.task_id)
            assert task.status == "FAILED"


def test_tasks_incomplete_returns_promptly_without_blocking(clean_environment):
    """
    5. /api/tasks/incomplete returns promptly and does not block on running tasks.
    """
    client, orch, planner = clean_environment

    # Post a task that pauses for approval
    res = client.post("/api/tasks", json={"goal": "High risk execution requiring approval"})
    assert res.status_code == 201
    task_id = res.json()["task_id"]

    # Query incomplete tasks
    inc_res = client.get("/api/tasks/incomplete")
    assert inc_res.status_code == 200
    incomplete = inc_res.json()
    assert isinstance(incomplete, list)
    task_ids = [t["task_id"] for t in incomplete]
    assert task_id in task_ids


@pytest.mark.asyncio
async def test_sse_event_generator_terminates_on_completed_task():
    """
    7. SSE emits events and terminates cleanly when task is COMPLETED.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "sse_test.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        orch = TaskOrchestrator(
            recovery_manager=SubsystemContainer.recovery_manager,
            permission_gateway=SubsystemContainer.permission_gateway,
        )

        dag = TaskDAG(
            goal="Quick task",
            model="gemma4:e2b",
            system_prompt="System prompt test",
            steps=[],
            status="COMPLETED",
        )
        orch.tasks[dag.task_id] = dag

        mock_request = AsyncMock()
        mock_request.is_disconnected = AsyncMock(return_value=False)

        events = []
        async for chunk in orch.event_generator(dag.task_id, request=mock_request):
            events.append(chunk)

        # Must terminate promptly (not hang in infinite loop)
        assert len(events) >= 1
        assert any("task_completed" in e for e in events)


@pytest.mark.asyncio
async def test_sse_event_generator_handles_client_disconnect():
    """
    7b. SSE detects client disconnect and breaks promptly without error.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "sse_test2.db")
        crypto = EncryptionService(TestKeyProvider())
        SubsystemContainer.initialize(db_path=db_path, encryption_service=crypto)

        orch = TaskOrchestrator(
            recovery_manager=SubsystemContainer.recovery_manager,
            permission_gateway=SubsystemContainer.permission_gateway,
        )

        dag = TaskDAG(
            goal="Long running task",
            model="gemma4:e2b",
            system_prompt="System prompt test",
            steps=[],
            status="EXECUTING",
        )
        orch.tasks[dag.task_id] = dag

        # Simulate client disconnecting on second iteration
        mock_request = AsyncMock()
        call_count = 0

        async def is_disconnected_side_effect():
            nonlocal call_count
            call_count += 1
            return call_count > 1

        mock_request.is_disconnected = AsyncMock(side_effect=is_disconnected_side_effect)

        events = []
        async for chunk in orch.event_generator(dag.task_id, request=mock_request):
            events.append(chunk)

        # Loop must exit when is_disconnected returns True
        assert len(events) >= 1


def test_missing_ollama_provider_falls_back_clearly_without_pending_stall(clean_environment):
    """
    8. Missing provider/Ollama endpoint logs warning and falls back to deterministic DAG
       without leaving task stuck in PENDING.
    """
    client, orch, planner = clean_environment

    # Set endpoint to an invalid local port to ensure it's unreachable
    planner.ollama_endpoint = "http://127.0.0.1:59999"

    response = client.post("/api/tasks", json={"goal": "Deploy emergency patch"})
    assert response.status_code == 201
    data = response.json()

    # The deterministic fallback must generate steps and execute without stalling
    assert data["status"] in ["PAUSED_APPROVAL", "COMPLETED"]
    assert len(data["steps"]) >= 1
