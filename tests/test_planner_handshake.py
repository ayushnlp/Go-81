"""
Tests for Milestone 5: Memory Handshake between TaskPlanner (Member 1) and Memory Subsystem (Member 2).
Validates that query_relevant_context retrieves verified facts & preferences,
and that TaskPlanner injects them into the Ollama (gemma4:e2b) system prompt before DAG generation.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager
from app.memory.models import SemanticCategory, VerificationStatus
from app.memory.service import MemoryService, query_relevant_context
from backend.planner import TaskPlanner


@pytest.fixture
def memory_fixture():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "handshake_test.db")
        crypto = EncryptionService(TestKeyProvider())
        db = DatabaseManager(db_path)
        service = MemoryService(db, crypto)
        yield {
            "db_path": db_path,
            "crypto": crypto,
            "db": db,
            "service": service,
        }


def test_query_relevant_context_filters_preferences_and_verified_facts(memory_fixture):
    service: MemoryService = memory_fixture["service"]

    # 1. Store user preference
    service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="Database",
        predicate="choice",
        object_value="SQLite WAL",
        verification_status=VerificationStatus.USER_PROVIDED,
        confidence=1.0,
    )

    # 2. Store verified fact
    service.store_memory(
        category=SemanticCategory.PROJECT_CONTEXT,
        subject="Project",
        predicate="framework",
        object_value="FastAPI and Next.js",
        verification_status=VerificationStatus.VERIFIED,
        confidence=0.98,
    )

    # 3. Store unverified / low confidence fact
    service.store_memory(
        category=SemanticCategory.FACT,
        subject="UnverifiedRumor",
        predicate="cloud_host",
        object_value="AWS",
        verification_status=VerificationStatus.UNVERIFIED,
        confidence=0.3,
    )

    # Invoke handshake function
    context = service.query_relevant_context(user_goal="Setup database connection for Project")

    # Assertions
    assert "preferences" in context
    assert "verified_facts" in context
    assert "formatted_prompt_context" in context

    # Preferences should be present
    pref_text = str(context["preferences"])
    assert "SQLite WAL" in pref_text

    # Verified fact should be present
    facts_text = str(context["verified_facts"])
    assert "FastAPI and Next.js" in facts_text

    # Unverified rumor must be excluded from verified_facts
    assert "UnverifiedRumor" not in facts_text

    # Formatted prompt context must be ready for system prompt injection
    prompt_str = context["formatted_prompt_context"]
    assert "SQLite WAL" in prompt_str
    assert "FastAPI and Next.js" in prompt_str


def test_task_planner_handshake_and_system_prompt_injection(memory_fixture):
    service: MemoryService = memory_fixture["service"]

    # Store user preference and verified fact
    service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="Testing",
        predicate="runner",
        object_value="pytest",
        verification_status=VerificationStatus.USER_PROVIDED,
    )
    service.store_memory(
        category=SemanticCategory.FACT,
        subject="TargetArchitecture",
        predicate="deployment",
        object_value="local-only sovereign daemon",
        verification_status=VerificationStatus.VERIFIED,
    )

    planner = TaskPlanner(model="gemma4:e2b", memory_service=service)

    # Generate DAG
    result = planner.generate_dag(user_goal="Add integration test suite")

    # Verify memory context was injected into the system prompt
    assert result["model"] == "gemma4:e2b"
    system_prompt = result["system_prompt"]

    assert "MEMBER 2 HANDSHAKE" in system_prompt
    assert "pytest" in system_prompt
    assert "local-only sovereign daemon" in system_prompt
    assert "gemma4:e2b" in system_prompt

    # Verify DAG steps are generated
    steps = result["steps"]
    assert len(steps) >= 2
    assert "id" in steps[0]
    assert "skill_name" in steps[0]


def test_planner_with_mocked_ollama_response(memory_fixture):
    service: MemoryService = memory_fixture["service"]

    service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="UI",
        predicate="theme",
        object_value="dark",
        verification_status=VerificationStatus.USER_PROVIDED,
    )

    planner = TaskPlanner(model="gemma4:e2b", memory_service=service)

    # Mock Ollama API response
    mock_ollama_steps = [
        {
            "id": "step-01",
            "step_number": 1,
            "title": "Query Local Preferences",
            "skill_name": "memory.recall_episodic",
            "parameters": {"theme": "dark"},
            "requires_approval": False,
        },
        {
            "id": "step-02",
            "step_number": 2,
            "title": "Apply Dark Mode Styling",
            "skill_name": "filesystem.write_file",
            "parameters": {"file": "styles.css"},
            "requires_approval": True,
        },
    ]
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": json.dumps({"steps": mock_ollama_steps})
    }

    with patch("httpx.Client.post", return_value=mock_response):
        result = planner.generate_dag("Build dark mode dashboard")
        assert result["steps"] == mock_ollama_steps
        assert "dark" in result["system_prompt"]
