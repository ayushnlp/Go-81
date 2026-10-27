"""
Tests for Milestone: Memory Models, SQLite Persistence, CRUD, Search, and Consolidation.
Validates true database restart persistence, deduplication, and forgetting.
"""

import os
import tempfile
import time
import pytest
from app.memory.consolidation import MemoryConsolidationEngine
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager
from app.memory.models import (
    MemoryType,
    MemoryUpdate,
    SemanticCategory,
    VerificationStatus,
)
from app.memory.service import MemoryService


@pytest.fixture
def temp_env():
    """Provides an isolated temporary database and test encryption service."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_memory.db")
        crypto = EncryptionService(TestKeyProvider())
        db = DatabaseManager(db_path)
        service = MemoryService(db, crypto)
        consolidation = MemoryConsolidationEngine(service)
        yield {
            "tmpdir": tmpdir,
            "db_path": db_path,
            "crypto": crypto,
            "db": db,
            "service": service,
            "consolidation": consolidation,
        }


def test_episodic_persistence_and_chronology(temp_env):
    service: MemoryService = temp_env["service"]

    # Store 3 events
    e1 = service.store_event(
        session_id="session-alpha",
        event_type="user_message",
        content={"text": "First interaction"},
        source_ref="chat_ui",
    )
    time.sleep(0.01)
    e2 = service.store_event(
        session_id="session-alpha",
        event_type="agent_message",
        content={"thought": "Processing request", "action": "search"},
        source_ref="agent_runtime",
    )
    time.sleep(0.01)
    e3 = service.store_event(
        session_id="session-beta",
        event_type="tool_execution",
        content={"tool": "read_file", "path": "main.py"},
        source_ref="tool_sandbox",
    )

    # Chronological query (newest first)
    records = service.search_memories(memory_type=MemoryType.EPISODIC)
    assert len(records) == 3
    assert records[0].id == e3.id
    assert records[1].id == e2.id
    assert records[2].id == e1.id

    # Filter by category/event_type
    tool_events = service.search_memories(
        memory_type=MemoryType.EPISODIC,
        category="tool_execution",
    )
    assert len(tool_events) == 1
    assert tool_events[0].id == e3.id


def test_persistence_across_process_restart(temp_env):
    """
    Simulates complete application shutdown and restart by tearing down
    the in-memory objects, closing SQLite handles, and instantiating brand new managers.
    """
    db_path = temp_env["db_path"]
    key_bytes = temp_env["crypto"].key_provider.get_key()
    service: MemoryService = temp_env["service"]

    # Write an episodic event and a semantic fact
    e = service.store_event(
        session_id="sess-persist",
        event_type="user_message",
        content={"message": "Save this durable memory"},
    )
    s = service.store_memory(
        category=SemanticCategory.FACT,
        subject="Agent Architecture",
        predicate="Memory Mode",
        object_value="Local SQLite WAL",
    )

    # Simulate shutdown
    temp_env["db"].checkpoint_wal()
    del service
    del temp_env["db"]

    # Reboot: Instantiate fresh managers targeting the existing db_path
    new_crypto = EncryptionService(TestKeyProvider(key_bytes))
    new_db = DatabaseManager(db_path)
    new_service = MemoryService(new_db, new_crypto)

    # Verify data survived reboot
    recovered_e = new_service.get_memory(e.id)
    assert recovered_e is not None
    assert recovered_e.payload["content"]["message"] == "Save this durable memory"

    recovered_s = new_service.get_memory(s.id)
    assert recovered_s is not None
    assert recovered_s.payload["object_value"] == "Local SQLite WAL"


def test_semantic_deduplication_and_confidence_update(temp_env):
    service: MemoryService = temp_env["service"]

    # Store fact first time (inferred with confidence 0.7)
    s1 = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="Editor",
        predicate="theme",
        object_value="dark",
        verification_status=VerificationStatus.INFERRED,
        confidence=0.7,
    )

    # Store exact same fact later, but user-confirmed with confidence 1.0
    s2 = service.store_memory(
        category=SemanticCategory.PREFERENCE,
        subject="editor",  # Different casing
        predicate="theme ",  # Trailing whitespace
        object_value="dark",
        verification_status=VerificationStatus.USER_PROVIDED,
        confidence=1.0,
    )

    # Must be the exact same memory ID (no duplicate row created)
    assert s1.id == s2.id
    assert s2.verification_status == VerificationStatus.USER_PROVIDED
    assert s2.confidence == 1.0

    # Ensure repository total count is 1
    export = service.export_memories(memory_type=MemoryType.SEMANTIC)
    assert export.total_records == 1


def test_in_process_keyword_search_and_pagination(temp_env):
    service: MemoryService = temp_env["service"]

    service.store_memory(
        category=SemanticCategory.PROJECT_CONTEXT,
        subject="Database",
        predicate="driver",
        object_value="sqlite3 with WAL",
    )
    service.store_memory(
        category=SemanticCategory.PROJECT_CONTEXT,
        subject="Encryption",
        predicate="standard",
        object_value="Fernet authenticated tokens",
    )
    service.store_memory(
        category=SemanticCategory.FACT,
        subject="Go 81",
        predicate="status",
        object_value="Online sovereign agent",
    )

    # Keyword search for "fernet"
    results = service.search_memories(query="fernet")
    assert len(results) == 1
    assert "Fernet" in results[0].payload["object_value"]

    # Pagination test
    page1 = service.search_memories(limit=2, offset=0)
    page2 = service.search_memories(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 1
    assert page1[0].id != page2[0].id


def test_memory_editing_and_json_export(temp_env):
    service: MemoryService = temp_env["service"]

    mem = service.store_memory(
        category=SemanticCategory.FACT,
        subject="Project",
        predicate="Name",
        object_value="Go 81 v0.1",
    )

    # Edit memory
    updated = service.update_memory(
        mem.id,
        MemoryUpdate(
            object_value="Go 81 v1.0",
            verification_status=VerificationStatus.VERIFIED,
            confidence=0.99,
        ),
    )
    assert updated.payload["object_value"] == "Go 81 v1.0"
    assert updated.verification_status == VerificationStatus.VERIFIED
    assert updated.confidence == 0.99

    # Test JSON export
    exported = service.export_memories()
    assert exported.total_records >= 1
    found = [r for r in exported.records if r.id == mem.id]
    assert len(found) == 1
    assert found[0].payload["object_value"] == "Go 81 v1.0"


def test_soft_and_hard_deletion(temp_env):
    service: MemoryService = temp_env["service"]

    m1 = service.store_memory(
        category=SemanticCategory.FACT,
        subject="TempFact1",
        predicate="state",
        object_value="to_be_soft_deleted",
    )
    m2 = service.store_memory(
        category=SemanticCategory.FACT,
        subject="TempFact2",
        predicate="state",
        object_value="to_be_hard_deleted",
    )

    # Soft delete m1
    assert service.delete_memory(m1.id, hard_delete=False) is True
    # Search must exclude soft deleted records
    assert service.get_memory(m1.id) is None
    assert len(service.search_memories(query="to_be_soft_deleted")) == 0

    # Hard delete m2
    assert service.delete_memory(m2.id, hard_delete=True) is True
    assert service.get_memory(m2.id, include_deleted=True) is None
    assert len(service.search_memories(query="to_be_hard_deleted")) == 0


def test_expiration_and_consolidation(temp_env):
    service: MemoryService = temp_env["service"]
    consolidation: MemoryConsolidationEngine = temp_env["consolidation"]

    # 1. Test expiration retention
    short_lived = service.store_event(
        session_id="ttl-test",
        event_type="user_message",
        content={"text": "Transient secret message"},
        ttl_seconds=1,  # 1 second TTL
    )
    time.sleep(1.2)  # Wait for TTL expiry
    purged_count = consolidation.enforce_retention_and_expiration()
    assert purged_count >= 1
    # Expired item excluded from search
    assert len(service.search_memories(query="Transient secret message")) == 0

    # 2. Test explainable episodic-to-semantic consolidation
    service.store_event(
        session_id="chat-prefs",
        event_type="user_message",
        content={"message": "I prefer dark mode over light mode"},
    )
    service.store_event(
        session_id="chat-prefs",
        event_type="user_message",
        content={"message": "Project Go 81 uses FastAPI"},
    )

    promoted = consolidation.consolidate_recent_events()
    assert len(promoted) >= 2

    # Verify promoted facts now exist in semantic store
    pref_facts = service.search_memories(
        memory_type=MemoryType.SEMANTIC,
        category="preference",
    )
    assert any("dark mode" in str(f.payload) for f in pref_facts)

    proj_facts = service.search_memories(
        memory_type=MemoryType.SEMANTIC,
        category="project_context",
    )
    assert any("FastAPI" in str(f.payload) for f in proj_facts)
