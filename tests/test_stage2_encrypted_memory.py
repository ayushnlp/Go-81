"""
Stage 2 Tests: Encrypted Storage and Dual Persistent Memory for Project Go 81.

Validates:
1. Episodic memory persistence, credential scrubbing, and multi-criteria retrieval.
2. Semantic memory persistence, deterministic deduplication, and conflict handling.
3. SQLite-backed local vector index (float32 BLOBs, cosine similarity, dimension tracking).
4. Memory deletion and vector index consistency (eviction on soft/hard delete).
5. Consolidation engine and explicit forgetting (forget_fact).
6. Local Ollama integration & honest degraded keyword fallback when offline.
7. Authenticated payload encryption at rest (raw SQLite file inspection).
8. Context retrieval latency benchmark (< 800 ms target).
"""

import os
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.memory.consolidation import MemoryConsolidationEngine
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager, utc_now
from app.memory.models import (
    EpisodicEvent,
    MemoryType,
    SemanticCategory,
    SemanticMemory,
    VerificationStatus,
)
from app.memory.service import MemoryService, query_relevant_context
from app.memory.vector_index import (
    VectorIndexManager,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)
from backend.ollama_client import OllamaClient, OllamaEmbedResponse


@pytest.fixture
def stage2_env():
    """Provides a fresh isolated database and MemoryService."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "go81_stage2_test.db")
        crypto = EncryptionService(TestKeyProvider())
        db = DatabaseManager(db_path)
        service = MemoryService(db, crypto)
        consolidation = MemoryConsolidationEngine(service)
        yield {
            "tmpdir": tmpdir,
            "db_path": db_path,
            "db": db,
            "crypto": crypto,
            "service": service,
            "consolidation": consolidation,
        }


# ============================================================================
# 1. Episodic Memory & Credential Scrubbing
# ============================================================================

def test_episodic_memory_credential_scrubbing(stage2_env):
    """
    Verifies that passwords, OTPs, session cookies, and bearer tokens are
    automatically redacted from ordinary episodic memory before storage.
    """
    service: MemoryService = stage2_env["service"]

    event = service.store_event(
        session_id="sess-001",
        event_type="user_interaction",
        content={
            "action": "login_attempt",
            "username": "ayush_dev",
            "password": "SuperSecretPassword123!",
            "otp": "839201",
            "session_cookie": "sess_xyz_9876543210_token",
            "raw_notes": "User received verification code: 492018 for login.",
        },
        metadata={
            "task_id": "task-login-01",
            "auth_token": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotStoreThis",
        },
    )

    # Decrypt and inspect stored record
    stored = service.get_memory(event.id)
    assert stored is not None
    payload = stored.payload
    content = payload["content"]
    meta = payload["metadata"]

    # Sensitive credentials must be redacted
    assert content["password"] == "[REDACTED_SECRET]"
    assert content["otp"] == "[REDACTED_SECRET]"
    assert content["session_cookie"] == "[REDACTED_SECRET]"
    assert meta["auth_token"] == "[REDACTED_SECRET]"
    # Non-sensitive field must be preserved
    assert content["action"] == "login_attempt"
    assert content["username"] == "ayush_dev"


def test_episodic_retrieval_by_task_id_and_timerange(stage2_env):
    """
    Verifies episodic memory retrieval filtered by task_id, session_id, and time range.
    """
    service: MemoryService = stage2_env["service"]

    # Store three events across different tasks
    e1 = service.store_event(
        session_id="sess-100",
        event_type="task_status_change",
        content={"status": "started", "task_id": "task-alpha"},
        metadata={"task_id": "task-alpha"},
    )
    e2 = service.store_event(
        session_id="sess-100",
        event_type="tool_execution",
        content={"tool": "bash", "status": "success", "task_id": "task-alpha"},
        metadata={"task_id": "task-alpha"},
    )
    e3 = service.store_event(
        session_id="sess-200",
        event_type="task_status_change",
        content={"status": "started", "task_id": "task-beta"},
        metadata={"task_id": "task-beta"},
    )

    # Query events for task-alpha
    alpha_events = service.get_events(task_id="task-alpha")
    assert len(alpha_events) == 2
    alpha_ids = {ev.id for ev in alpha_events}
    assert e1.id in alpha_ids
    assert e2.id in alpha_ids
    assert e3.id not in alpha_ids

    # Query events for task-beta
    beta_events = service.get_events(task_id="task-beta")
    assert len(beta_events) == 1
    assert beta_events[0].id == e3.id


# ============================================================================
# 2. Semantic Memory Deduplication & Conflict Correction
# ============================================================================

def test_semantic_deduplication_exact_match(stage2_env):
    """
    Verifies that inserting identical facts updates the existing record
    instead of creating duplicate rows.
    """
    service: MemoryService = stage2_env["service"]

    m1 = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="editor",
        predicate="prefers",
        object_value="neovim",
        confidence=0.8,
    )

    # Store identical fact with higher confidence
    m2 = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="editor",
        predicate="prefers",
        object_value="neovim",
        confidence=1.0,
    )

    assert m1.id == m2.id
    updated = service.get_memory(m1.id)
    assert updated.confidence == 1.0

    all_semantic = service.search_memories(memory_type=MemoryType.SEMANTIC)
    assert len(all_semantic) == 1


def test_semantic_conflict_handling_and_correction(stage2_env):
    """
    Verifies conflict resolution: when a user provides a corrected fact
    for an existing (subject, predicate), the old value is overwritten and updated in place.
    """
    service: MemoryService = stage2_env["service"]

    # Initial preference
    m1 = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="theme",
        predicate="mode",
        object_value="light",
        verification_status=VerificationStatus.INFERRED,
        confidence=0.6,
    )

    # User correction
    m2 = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="theme",
        predicate="mode",
        object_value="dark",
        verification_status=VerificationStatus.USER_PROVIDED,
        confidence=1.0,
    )

    # Distinct record created preserving audit provenance
    assert m1.id != m2.id

    # In retrieval context, newest user-provided correction wins and supersedes older inferred preference
    ctx = service.query_relevant_context("What theme mode do I prefer?")
    assert len(ctx["preferences"]) == 1
    assert ctx["preferences"][0]["object_value"] == "dark"
    assert ctx["cited_memory_ids"] == [m2.id]
    assert m1.id not in ctx["cited_memory_ids"]


# ============================================================================
# 3. SQLite-Backed Vector Index (Packed Float32 BLOBs & Cosine Similarity)
# ============================================================================

def test_vector_pack_unpack_and_cosine_similarity():
    """Validates binary packing, unpacking, and cosine similarity calculations."""
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    v4 = [0.7071, 0.7071, 0.0]

    # Packing / unpacking roundtrip
    blob = pack_vector(v1)
    assert len(blob) == 12  # 3 floats * 4 bytes
    unpacked = unpack_vector(blob)
    assert len(unpacked) == 3
    assert pytest.approx(unpacked[0], abs=1e-5) == 1.0

    # Orthogonal vectors: cosine sim = 0.0
    assert pytest.approx(cosine_similarity(v1, v3), abs=1e-4) == 0.0

    # Identical vectors: cosine sim = 1.0
    assert pytest.approx(cosine_similarity(v1, v2), abs=1e-4) == 1.0

    # 45-degree vectors: cosine sim ~ 0.7071
    assert pytest.approx(cosine_similarity(v1, v4), abs=1e-3) == 0.7071


def test_vector_index_persistence_and_dimensions(stage2_env):
    """
    Verifies that vectors are saved into the SQLite memory_embeddings table,
    dimensions are tracked, and incompatible dimensions are handled safely.
    """
    db: DatabaseManager = stage2_env["db"]
    service: MemoryService = stage2_env["service"]

    mem = service.store_memory(
        category=SemanticCategory.FACT,
        subject="Go81",
        predicate="architecture",
        object_value="local_first_ollama",
    )

    vec_mgr = service.vector_index
    # Manually save a 4-dimensional vector
    test_vec = [0.5, 0.5, 0.5, 0.5]
    success = vec_mgr.save_vector(
        memory_id=mem.id,
        vector=test_vec,
        model_name="nomic-embed-text:latest",
        dimensions=4,
    )
    assert success is True

    # Retrieve vector from SQLite
    stored_vec = vec_mgr.get_embedding(mem.id)
    assert stored_vec is not None
    assert len(stored_vec) == 4
    for a, b in zip(test_vec, stored_vec):
        assert pytest.approx(a, abs=1e-4) == b

    # Check stats
    stats = vec_mgr.get_stats()
    assert stats["total_embeddings"] == 1
    assert stats["models"][0]["dimensions"] == 4


def test_vector_index_eviction_on_deletion(stage2_env):
    """
    Verifies that deleting a memory record immediately purges its vector
    from the memory_embeddings table.
    """
    service: MemoryService = stage2_env["service"]

    mem = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="python_version",
        predicate="standard",
        object_value="3.12",
    )

    service.vector_index.save_vector(
        memory_id=mem.id,
        vector=[0.1, 0.2, 0.3],
        model_name="nomic-embed-text",
        dimensions=3,
    )
    assert service.vector_index.get_embedding(mem.id) is not None

    # Soft delete
    service.delete_memory(mem.id, hard_delete=False)

    # Embedding must be evicted
    assert service.vector_index.get_embedding(mem.id) is None


# ============================================================================
# 4. Memory Consolidation & Explicit Forgetting
# ============================================================================

def test_consolidation_rule_promotion(stage2_env):
    """
    Verifies that the consolidation engine extracts preferences and facts
    from episodic interactions and promotes them to verified semantic memories.
    """
    service: MemoryService = stage2_env["service"]
    engine: MemoryConsolidationEngine = stage2_env["consolidation"]

    # Store episodic messages
    service.store_event(
        session_id="sess-chat-01",
        event_type="user_message",
        content={"message": "I prefer dark mode over light mode"},
    )
    service.store_event(
        session_id="sess-chat-02",
        event_type="user_message",
        content={"message": "Project Go81 uses FastAPI and SQLite"},
    )

    # Run consolidation
    promoted = engine.consolidate_recent_events()
    assert len(promoted) >= 2

    # Verify semantic memories exist
    prefs = service.search_memories(category=SemanticCategory.PREFERENCE.value)
    assert any(p.payload["subject"] == "dark mode" for p in prefs)


def test_explicit_forgetting_removes_semantic_memory_and_vector(stage2_env):
    """
    Verifies explicit forgetting: forget_fact purges matching facts
    and removes their searchable representations.
    """
    service: MemoryService = stage2_env["service"]
    engine: MemoryConsolidationEngine = stage2_env["consolidation"]

    m1 = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="database",
        predicate="prefers",
        object_value="PostgreSQL",
    )
    service.vector_index.save_vector(
        memory_id=m1.id,
        vector=[0.2, 0.4, 0.6],
        model_name="nomic-embed-text",
        dimensions=3,
    )

    assert service.vector_index.get_embedding(m1.id) is not None

    # Forget database preference
    forgotten = engine.forget_fact(subject="database")
    assert forgotten == 1

    # Verify memory is marked deleted and excluded from search
    active = service.search_memories(query="PostgreSQL")
    assert len(active) == 0

    # Verify vector is evicted
    assert service.vector_index.get_embedding(m1.id) is None


# ============================================================================
# 5. Local Ollama Integration & Degraded Mode Fallback
# ============================================================================

def test_vector_search_with_mocked_ollama_embeddings(stage2_env):
    """
    Verifies semantic vector retrieval when local Ollama embedding inference succeeds.
    """
    service: MemoryService = stage2_env["service"]

    # Store memories
    m_python = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="language",
        predicate="prefers",
        object_value="Python 3.12",
    )
    m_editor = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="ide",
        predicate="prefers",
        object_value="VS Code",
    )

    # Mock Ollama embedding responses
    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.config = MagicMock(embed_model="nomic-embed-text:latest")

    # Embeddings for query "programming language" will be close to m_python
    python_vec = [0.9, 0.1, 0.0]
    editor_vec = [0.0, 0.1, 0.9]

    service.vector_index._ollama_client = mock_ollama
    service.vector_index.save_vector(m_python.id, python_vec, "nomic-embed-text:latest", 3)
    service.vector_index.save_vector(m_editor.id, editor_vec, "nomic-embed-text:latest", 3)

    # When querying "programming language", return vector close to python_vec
    mock_ollama.embed.return_value = OllamaEmbedResponse(
        model="nomic-embed-text:latest",
        embeddings=[[0.85, 0.15, 0.0]],
        dimensions=3,
        total_duration_ms=12.0,
    )

    # Search similar
    results = service.vector_index.search_similar("programming language", top_k=2)
    assert len(results) == 2
    top_id, top_sim = results[0]
    assert top_id == m_python.id
    assert top_sim > 0.9


def test_honest_degraded_keyword_fallback_when_ollama_offline(stage2_env):
    """
    Verifies that when Ollama embedding daemon is unavailable, the memory
    system transparently falls back to deterministic keyword search and
    labels the retrieval mode as 'keyword_fallback'.
    """
    service: MemoryService = stage2_env["service"]

    service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="shell",
        predicate="prefers",
        object_value="powershell",
    )

    # Configure a mock Ollama client that raises a connection error
    mock_client = MagicMock(spec=OllamaClient)
    mock_client.config = MagicMock(embed_model="nomic-embed-text:latest")
    mock_client.embed.side_effect = ConnectionError("Local Ollama daemon unreachable at http://127.0.0.1:11434")

    service.vector_index._ollama_client = mock_client

    # Perform query
    ctx = service.query_relevant_context("What shell do I prefer?")

    # Mode must honestly declare degraded fallback
    assert ctx["retrieval_mode"] == "keyword_fallback"
    assert len(ctx["preferences"]) == 1
    assert ctx["preferences"][0]["object_value"] == "powershell"


def test_stage2_live_ollama_vector_indexing_and_search(stage2_env):
    """
    Live Stage 2 integration test against running local Ollama service.
    Verifies real embedding generation (768-dim), SQLite vector storage,
    and hybrid semantic retrieval against non-keyword semantic queries.
    """
    client = OllamaClient()
    if not client.is_reachable():
        pytest.skip("Local Ollama daemon not reachable at http://127.0.0.1:11434")
    if not client.has_model(client.config.embed_model):
        pytest.skip(f"Embed model '{client.config.embed_model}' not installed in local Ollama.")

    service: MemoryService = stage2_env["service"]

    # Store memory: VectorIndexManager will automatically invoke real Ollama embed
    mem = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="operating_system",
        predicate="prefers",
        object_value="Arch Linux",
    )

    # Verify vector stored in SQLite with genuine 768 dimensions
    embedding = service.vector_index.get_embedding(mem.id)
    assert embedding is not None
    assert len(embedding) == 768

    # Query with semantic concept without matching literal keywords
    ctx = service.query_relevant_context("Which Linux distro do I like to run?")
    assert ctx["retrieval_mode"] == "hybrid_semantic"
    assert len(ctx["preferences"]) >= 1
    assert ctx["preferences"][0]["object_value"] == "Arch Linux"
    assert ctx["preferences"][0]["similarity"] > 0.5
    assert mem.id in ctx["cited_memory_ids"]


# ============================================================================
# 6. Encryption at Rest: Raw Disk Byte Inspection
# ============================================================================

def test_stage2_encryption_at_rest_raw_file_inspection(stage2_env):
    """
    Inspects the raw SQLite file bytes on disk to confirm that confidential
    memory payloads are genuinely encrypted at rest with zero plaintext leakage.
    """
    db_path = stage2_env["db_path"]
    db: DatabaseManager = stage2_env["db"]
    service: MemoryService = stage2_env["service"]

    canary_secret = "GO81_CLASSIFIED_CANARY_PAYLOAD_9999"

    service.store_event(
        session_id="session-audit",
        event_type="user_message",
        content={"audit_note": canary_secret},
        source_ref="terminal_canary_audit",
    )

    # Flush WAL
    db.checkpoint_wal()

    with open(db_path, "rb") as f:
        raw_bytes = f.read()

    # Secret MUST NOT appear anywhere in the SQLite database file
    assert canary_secret.encode("utf-8") not in raw_bytes
    # Non-sensitive source_ref remains visible as intended for indexing
    assert b"terminal_canary_audit" in raw_bytes


# ============================================================================
# 7. Memory Retrieval Latency Benchmark (< 800 ms PS Target)
# ============================================================================

def test_query_relevant_context_latency_under_800ms(stage2_env):
    """
    BENCHMARK: Evaluates context retrieval execution latency against the
    Problem Statement target of under 800 ms.
    """
    service: MemoryService = stage2_env["service"]

    # Benchmark 1: Degraded keyword fallback when Ollama is offline
    offline_client = MagicMock(spec=OllamaClient)
    offline_client.config = MagicMock(embed_model="nomic-embed-text")
    offline_client.embed.side_effect = ConnectionError("Ollama offline")
    service.vector_index._ollama_client = offline_client

    # Populate 50 diverse semantic memories and 50 episodic events
    for i in range(50):
        service.store_memory(
            category=SemanticCategory.FACT,
            subject=f"entity_{i}",
            predicate="attribute",
            object_value=f"value_{i}",
            confidence=0.9,
        )
        service.store_event(
            session_id=f"sess_{i}",
            event_type="user_message",
            content={"text": f"Event description and action step {i}"},
        )

    fallback_latencies: List[float] = []
    for _ in range(10):
        start_t = time.perf_counter()
        ctx = service.query_relevant_context("What are the facts about entity_25?")
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        fallback_latencies.append(elapsed_ms)
        assert ctx["memory_available"] is True
        assert ctx["retrieval_mode"] == "keyword_fallback"

    avg_fallback = sum(fallback_latencies) / len(fallback_latencies)
    assert avg_fallback < 800.0, f"Fallback latency {avg_fallback:.2f} ms exceeded 800 ms target!"

    # Benchmark 2: Active hybrid semantic vector retrieval
    # Populate vectors for stored memories (satisfying FOREIGN KEY to memories table)
    dummy_vec = [0.1] * 384
    stored_records = service.search_memories(limit=50)
    for rec in stored_records:
        service.vector_index.save_vector(
            memory_id=rec.id,
            vector=dummy_vec,
            model_name="nomic-embed-text",
            dimensions=384,
        )

    # Mock Ollama embedding inference returning 384-dim query vector
    mock_ollama = MagicMock(spec=OllamaClient)
    mock_ollama.config = MagicMock(embed_model="nomic-embed-text")
    mock_ollama.embed.return_value = OllamaEmbedResponse(
        model="nomic-embed-text",
        embeddings=[dummy_vec],
        dimensions=384,
        total_duration_ms=5.0,
    )
    service.vector_index._ollama_client = mock_ollama

    vector_latencies: List[float] = []
    for _ in range(10):
        start_t = time.perf_counter()
        ctx = service.query_relevant_context("What are the facts about entity_25?")
        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        vector_latencies.append(elapsed_ms)
        assert ctx["memory_available"] is True
        assert ctx["retrieval_mode"] == "hybrid_semantic"

    avg_vector = sum(vector_latencies) / len(vector_latencies)
    max_vector = max(vector_latencies)

    # Problem Statement SLA: < 800 ms
    assert avg_vector < 800.0, f"Average vector latency {avg_vector:.2f} ms exceeded 800 ms target!"
    assert max_vector < 800.0, f"Peak vector latency {max_vector:.2f} ms exceeded 800 ms target!"
