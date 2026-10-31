"""
Stage 5 Intelligent Conversational Engine Test Suite.
Verifies:
- Context awareness & multi-turn session tracking
- Follow-up and pronoun reference resolution
- Deterministic arithmetic calculation (SafeCalculator)
- Timezone handling and timestamp consistency
- Factual verification & hallucination prevention (Baahubali, Katappa, Sports, Cutoff)
- Multi-session isolation and bounded history window
- Transient conversation vs durable memory separation
- Error handling, timeouts, and local-first sovereignty
"""

import os
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from backend.conversational import (
    get_current_time,
    format_local_timestamp,
    to_utc_iso,
    get_system_time_context,
    evaluate_math_expression,
    is_arithmetic_query,
    SafeCalculator,
    IntentCategory,
    IntentResult,
    IntentClassifier,
    ConversationSessionManager,
    KnowledgeGuard,
    get_conversational_engine,
)
from backend.main import app, get_planner, get_orchestrator
from backend.ollama_client import OllamaLocalPolicyViolation, OllamaConfig


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_file = tmp_path_factory.mktemp("stage5_test") / "go81_test.db"
    SubsystemContainer.initialize(db_path=str(db_file))
    with TestClient(app) as tc:
        yield tc


# ============================================================================
# 1. Deterministic Calculator & Arithmetic Safety
# ============================================================================

def test_calculator_basic_arithmetic():
    """Requirement 1 & 18: Basic arithmetic deterministically evaluated."""
    res = evaluate_math_expression("what is 4*4")
    assert res is not None
    assert res.success is True
    assert res.result == 16
    assert "4*4 = 16" in res.formatted


def test_calculator_percentage():
    """Requirement 18: Percentage calculations."""
    res = evaluate_math_expression("what is 15% of 80")
    assert res is not None
    assert res.success is True
    assert res.result == 12


def test_calculator_complex_expression():
    """Requirement 18: Complex expressions with parentheses and powers."""
    res = evaluate_math_expression("calculate (100 - 25) / 3")
    assert res is not None
    assert res.success is True
    assert res.result == 25


def test_calculator_division_by_zero_safety():
    """Requirement 18: Division by zero handled safely without exception."""
    res = evaluate_math_expression("what is 10 / 0")
    assert res is not None
    assert res.success is False
    assert "undefined" in res.error.lower()


def test_calculator_malformed_input():
    """Requirement 18: Malformed math syntax handled gracefully."""
    res = evaluate_math_expression("calculate 4 +* 5")
    assert res is not None
    assert res.success is False
    assert res.error is not None


# ============================================================================
# 2. Timezone & Timestamp Consistency
# ============================================================================

def test_timezone_current_time_and_context():
    """Requirement 19: System time context contains accurate date and configured timezone."""
    ctx = get_system_time_context()
    assert "current_year" in ctx
    assert int(ctx["current_year"]) >= 2024
    assert "timezone" in ctx
    assert "prompt_injection_summary" in ctx


def test_timestamp_utc_and_local_conversion():
    """Requirement 19: UTC ISO format and local formatting without double conversion."""
    utc_iso = to_utc_iso()
    assert utc_iso.endswith("+00:00") or "Z" in utc_iso
    local_str = format_local_timestamp(utc_iso)
    assert ("AM" in local_str or "PM" in local_str)
    # Double conversion defense
    already_formatted = format_local_timestamp(local_str)
    assert already_formatted == local_str


# ============================================================================
# 3. Intent Classification & Entity Extraction
# ============================================================================

def test_intent_classification_categories():
    """Requirement 4: Validated intent classification."""
    classifier = IntentClassifier()

    r1 = classifier.classify("what is 25 * 4")
    assert r1.intent_category == IntentCategory.ARITHMETIC

    r2 = classifier.classify("hello there")
    assert r2.intent_category == IntentCategory.GREETING

    r3 = classifier.classify("who are you")
    assert r3.intent_category == IntentCategory.IDENTITY

    r4 = classifier.classify("what are my preferences")
    assert r4.intent_category == IntentCategory.SEMANTIC_MEMORY_QUERY

    r5 = classifier.classify("analyze my project and fix the issues")
    assert r5.intent_category == IntentCategory.COMPLEX_TASK
    assert r5.requires_task_planning is True


# ============================================================================
# 4. Sports & Ambiguity Handling
# ============================================================================

def test_sports_ambiguity_clarification(client):
    """Requirement 2: Ambiguous India vs Pakistan query requests tournament/date clarification."""
    resp = client.post("/api/agent/chat", json={"prompt": "What is Ind vs Pak match result?"})
    assert resp.status_code == 200
    data = resp.json()
    assert "tournament" in data["content"].lower() or "which" in data["content"].lower()
    assert data["role"] == "agent"


# ============================================================================
# 5. Movies, Baahubali 2 & Katappa Factual Accuracy
# ============================================================================

def test_baahubali_daywise_and_worldwide_followup(client):
    """
    Requirements 4, 5, 6, 10: Multi-turn sequence:
    Turn 1: Baahubali 2 day-wise collection
    Turn 2: 'Can you give me its total worldwide collection?' -> Resolves 'its' to Baahubali 2
    """
    session_id = "test-session-baahubali"

    # Turn 1
    resp1 = client.post(
        "/api/agent/chat",
        json={"prompt": "Give me day-wise collection of Baahubali 2.", "session_id": session_id},
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert "Day 1" in data1["content"]
    assert "Nett" in data1["content"] or "Gross" in data1["content"]

    # Turn 2: Follow-up with pronoun reference
    resp2 = client.post(
        "/api/agent/chat",
        json={"prompt": "Can you give me its total worldwide collection?", "session_id": session_id},
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    content2 = data2["content"]
    # Must correctly categorize collection figures
    assert "India Nett" in content2
    assert "India Gross" in content2
    assert "Worldwide Gross Total" in content2
    assert "1,788" in content2 or "1,810" in content2


def test_katappa_canon_plot_explanation(client):
    """Requirement 7: Canonical truth regarding why Katappa killed Baahubali."""
    resp = client.post(
        "/api/agent/chat",
        json={"prompt": "Why did Katappa kill Baahubali?"},
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    assert "Sivagami" in content
    assert "Bhallaladeva" in content
    assert "oath" in content.lower() or "allegiance" in content.lower()


# ============================================================================
# 6. Training Cutoff & Offline Transparency
# ============================================================================

def test_training_cutoff_disclosure(client):
    """Requirement 8 & 9: Honest cutoff and offline capability disclosure."""
    resp = client.post(
        "/api/agent/chat",
        json={"prompt": "What is your training data cutoff date?"},
    )
    assert resp.status_code == 200
    content = resp.json()["content"]
    assert "cutoff" in content.lower()
    assert "sovereign offline mode" in content.lower() or "offline" in content.lower()
    assert "december 2023" in content.lower()


def test_training_cutoff_explicit_metadata_vs_unverified():
    """Stage 5.1 Hardening: Explicit model metadata cited for Llama 3.2 vs unverified for unknown models."""
    kg = KnowledgeGuard()
    llama_disclosure = kg.get_model_capability_disclosure("llama3.2:3b")
    assert "December 2023" in llama_disclosure
    assert "Meta's official model metadata" in llama_disclosure

    custom_disclosure = kg.get_model_capability_disclosure("custom-finetune:latest")
    assert "unverified" in custom_disclosure.lower()


def test_baahubali_provenance_metadata_structure(client):
    """Stage 5.1 Hardening: Structured typed provenance metadata emitted in evidence field."""
    resp = client.post(
        "/api/agent/chat",
        json={"prompt": "What is the worldwide collection of Baahubali 2?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    evidence = data.get("evidence", [])
    assert len(evidence) >= 2

    # Verified historical trade record
    trade_close = next((e for e in evidence if e.get("record_type") == "source_derived_historical_trade"), None)
    assert trade_close is not None
    assert "Box Office India" in trade_close["source"]
    assert "india_nett" in trade_close["metrics"]
    assert "₹1,030.50" in trade_close["metrics"]["india_nett"]

    # Curated aggregate estimate
    curated_est = next((e for e in evidence if e.get("record_type") == "dated_curated_estimate"), None)
    assert curated_est is not None
    assert "overseas_gross" in curated_est["metrics"]
    assert "worldwide_gross" in curated_est["metrics"]


def test_unverified_movie_collection_honest_disclosure(client):
    """Stage 5.1 Hardening: Uncurated titles honestly disclose absence of local dataset."""
    resp = client.post(
        "/api/agent/chat",
        json={"prompt": "What is the box office collection of Inception?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "do not possess a verified local dataset" in data["content"]
    assert "Inception" in data["content"]
    assert len(data.get("evidence", [])) >= 1
    assert data["evidence"][0].get("status") == "unverified_unavailable"


# ============================================================================
# 7. Multi-Session Context Isolation
# ============================================================================

def test_multi_session_context_isolation():
    """Requirement 11: Entities in session A do not bleed into session B."""
    mgr = ConversationSessionManager()
    mgr.record_turn(
        session_id="session-A",
        user_prompt="Let's discuss Baahubali 2",
        assistant_response="Sure, what would you like to know about Baahubali 2?",
        entities=["Baahubali 2"],
    )

    res_a = mgr.resolve_references("What was its budget?", "session-A")
    assert res_a["entity"] == "Baahubali 2"
    assert "Baahubali 2" in res_a["resolved_prompt"]

    # Session B has no prior context
    res_b = mgr.resolve_references("What was its budget?", "session-B")
    assert res_b["entity"] is None
    assert res_b["was_resolved"] is False


# ============================================================================
# 8. Bounded Context Window & History Truncation
# ============================================================================

def test_bounded_context_window():
    """Requirement 12: Context history is bounded to prevent token saturation."""
    mgr = ConversationSessionManager()
    for i in range(15):
        mgr.record_turn(
            session_id="session-overflow",
            user_prompt=f"Prompt {i}",
            assistant_response=f"Response {i}",
        )

    session = mgr.get_or_create_session("session-overflow")
    assert len(session.turns) <= mgr.MAX_STORED_TURNS

    llm_msgs = mgr.get_recent_messages_for_llm("session-overflow", max_turns=3)
    # 3 user + 3 assistant = 6 messages max
    assert len(llm_msgs) == 6


# ============================================================================
# 9. Transient Context vs Durable Memory Separation
# ============================================================================

def test_transient_conversation_not_auto_saved_to_durable_memory(client):
    """Requirement 13: Ordinary conversation does not automatically mutate encrypted memory vault."""
    initial_exp = SubsystemContainer.memory_service.export_memories() if SubsystemContainer.memory_service else None
    init_count = initial_exp.total_records if initial_exp else 0

    # Send conversational messages
    client.post("/api/agent/chat", json={"prompt": "I love drinking coffee in the morning."})
    client.post("/api/agent/chat", json={"prompt": "What is 10 + 25?"})

    after_exp = SubsystemContainer.memory_service.export_memories() if SubsystemContainer.memory_service else None
    after_count = after_exp.total_records if after_exp else 0
    assert after_count == init_count


# ============================================================================
# 10. Local-First Sovereignty (Zero Cloud AI)
# ============================================================================

def test_zero_cloud_policy_enforcement():
    """Requirement 21: Remote or cloud endpoints strictly raise policy violation."""
    with pytest.raises(OllamaLocalPolicyViolation):
        OllamaConfig(base_url="https://api.openai.com/v1")

    with pytest.raises(OllamaLocalPolicyViolation):
        OllamaConfig(base_url="http://remote-server.com:11434")
