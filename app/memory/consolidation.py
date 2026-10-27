"""
Consolidation and Forgetting Subsystem.
Implements explainable rule-based promotion of episodic interactions into durable semantic facts,
enforces TTL expiry, and manages data deletion with SQLite limitation documentation.
"""

import logging
import re
from typing import Any, Dict, List, Optional
from app.memory.models import (
    MemoryRecord,
    MemoryType,
    SemanticCategory,
    SemanticMemory,
    VerificationStatus,
)
from app.memory.service import MemoryService

logger = logging.getLogger(__name__)

# Explainable regex heuristics for promotion
PROMOTION_RULES = [
    # (Regex pattern, category, subject_group, predicate_group, object_group, default_status, default_confidence)
    (
        re.compile(r"i prefer ([\w\s-]+) over ([\w\s-]+)", re.IGNORECASE),
        SemanticCategory.PREFERENCE,
        lambda m: m.group(1).strip(),
        "preferred_over",
        lambda m: m.group(2).strip(),
        VerificationStatus.USER_PROVIDED,
        1.0,
    ),
    (
        re.compile(r"i prefer ([\w\s-]+)", re.IGNORECASE),
        SemanticCategory.PREFERENCE,
        lambda m: "general_preference",
        "prefers",
        lambda m: m.group(1).strip(),
        VerificationStatus.USER_PROVIDED,
        1.0,
    ),
    (
        re.compile(r"my favorite ([\w\s-]+) is ([\w\s-]+)", re.IGNORECASE),
        SemanticCategory.PREFERENCE,
        lambda m: m.group(1).strip(),
        "favorite",
        lambda m: m.group(2).strip(),
        VerificationStatus.USER_PROVIDED,
        1.0,
    ),
    (
        re.compile(r"always use ([\w\s-]+) for ([\w\s-]+)", re.IGNORECASE),
        SemanticCategory.PREFERENCE,
        lambda m: m.group(2).strip(),
        "standard_tool",
        lambda m: m.group(1).strip(),
        VerificationStatus.USER_PROVIDED,
        1.0,
    ),
    (
        re.compile(r"project ([\w\s-]+) uses ([\w\s-]+)", re.IGNORECASE),
        SemanticCategory.PROJECT_CONTEXT,
        lambda m: m.group(1).strip(),
        "technology_stack",
        lambda m: m.group(2).strip(),
        VerificationStatus.VERIFIED,
        0.95,
    ),
    (
        re.compile(r"the repo(?:sitory)? (?:is|uses) ([\w\s-]+)", re.IGNORECASE),
        SemanticCategory.PROJECT_CONTEXT,
        lambda m: "repository",
        "description",
        lambda m: m.group(1).strip(),
        VerificationStatus.VERIFIED,
        0.9,
    ),
]


class MemoryConsolidationEngine:
    """
    Consolidates transient episodic memories into durable semantic knowledge
    and executes forgetting/retention policies.
    """

    def __init__(self, memory_service: MemoryService):
        self.memory_service = memory_service

    def consolidate_recent_events(
        self,
        lookback_limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Scans recent episodic interaction events, extracts declarative facts
        and preferences using explainable rules, and promotes them to semantic memories.
        """
        # Fetch recent episodic memories
        episodic_records = self.memory_service.search_memories(
            memory_type=MemoryType.EPISODIC,
            limit=lookback_limit,
            include_expired=False,
        )

        promoted: List[Dict[str, Any]] = []

        for record in episodic_records:
            content_dict = record.payload.get("content", {})
            text_candidates: List[str] = []

            # Extract textual components
            if isinstance(content_dict, str):
                text_candidates.append(content_dict)
            elif isinstance(content_dict, dict):
                for k in ["message", "text", "query", "user_input", "observation"]:
                    val = content_dict.get(k)
                    if isinstance(val, str) and val.strip():
                        text_candidates.append(val)

            for text in text_candidates:
                for pattern, category, subj_fn, predicate, obj_fn, status, conf in PROMOTION_RULES:
                    match = pattern.search(text)
                    if match:
                        try:
                            subject = subj_fn(match)
                            object_val = obj_fn(match)
                        except Exception as e:
                            logger.warning(f"Error evaluating rule extraction: {e}")
                            continue

                        # Store or update semantic memory with deduplication
                        semantic_mem = self.memory_service.store_memory(
                            category=category,
                            subject=subject,
                            predicate=predicate,
                            object_value=object_val,
                            verification_status=status,
                            confidence=conf,
                            source_ref=f"episodic_consolidation:{record.id}",
                            context={"source_event_id": record.id, "extracted_text": text},
                        )

                        promoted.append({
                            "event_id": record.id,
                            "semantic_id": semantic_mem.id,
                            "category": category.value,
                            "subject": subject,
                            "predicate": predicate,
                            "object_value": object_val,
                            "status": status.value,
                            "confidence": conf,
                        })

        return promoted

    def forget_fact(self, subject: str, predicate: Optional[str] = None) -> int:
        """
        Explicitly removes durable semantic facts matching subject (and optional predicate).
        Enforces forgetting by soft-deleting records and removing vector index embeddings.
        Returns the count of forgotten facts.
        """
        active_semantic = self.memory_service.search_memories(
            memory_type=MemoryType.SEMANTIC,
            limit=200,
            include_expired=True,
            use_vector=False,
        )
        forgotten_count = 0
        norm_subj = subject.strip().lower()
        norm_pred = predicate.strip().lower() if predicate else None

        for rec in active_semantic:
            payload = rec.payload or {}
            rec_subj = str(payload.get("subject", "")).strip().lower()
            rec_pred = str(payload.get("predicate", "")).strip().lower()

            if rec_subj == norm_subj:
                if norm_pred is None or rec_pred == norm_pred:
                    self.memory_service.delete_memory(rec.id, hard_delete=False)
                    forgotten_count += 1

        return forgotten_count

    def enforce_retention_and_expiration(self) -> int:
        """
        Enforces retention policies by purging expired records.
        Also evicts associated vector embeddings for expired records.
        Returns the number of expired records soft-deleted.
        """
        purged = self.memory_service.purge_expired()
        if hasattr(self.memory_service, "vector_index") and self.memory_service.vector_index:
            try:
                sql = "DELETE FROM memory_embeddings WHERE memory_id NOT IN (SELECT id FROM memories WHERE is_deleted = 0);"
                with self.memory_service.db.transaction() as conn:
                    conn.execute(sql)
            except Exception as e:
                logger.debug(f"Expired vector cleanup error: {e}")
        return purged


# ============================================================================
# Deletion Documentation
# ============================================================================
SQLITE_DELETION_LIMITATIONS_NOTE = """
SQLITE & LOCAL STORAGE DELETION LIMITATIONS:
1. Soft Deletion:
   Soft deletion flags rows with `is_deleted = 1`. These rows are excluded from all
   agent queries, keyword searches, and exports.
2. Hard Deletion:
   Hard deletion overwrites the record's `encrypted_payload` column with cryptographic
   randomness before executing `DELETE FROM memories`. This ensures the ciphertext cannot
   be deciphered from SQLite freelist pages using the database file.
3. WAL & Freelists:
   SQLite maintains unused deleted pages in an internal freelist for reuse.
   Furthermore, Write-Ahead Logging (WAL) writes transactions to `.db-wal` before
   checkpointing to the main database file. Running `PRAGMA wal_checkpoint(FULL);`
   flushes WAL pages.
4. Forensic Limits:
   Neither soft nor hard deletion provides government-grade or military forensic erasure
   against raw physical drive hardware recovery (e.g. unallocated flash memory blocks).
5. Exports & Backups:
   External backups or previously exported JSON files are outside the custody of this
   subsystem and must be independently managed by the user.
"""
