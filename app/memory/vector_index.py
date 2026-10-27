"""
SQLite-Backed Local Vector Index for Project Go 81.

Strict Invariants:
1. 100% Local Inference: Vectors generated strictly via OllamaClient (POST /api/embed).
2. Pure Python & SQLite Storage: Vectors stored as packed float32 BLOBs in SQLite;
   zero external heavy vector databases or cloud embedding APIs required.
3. Model-Aware & Self-Healing: Tracks embedding model tag and vector dimensions.
4. Resilient Fallback: If Ollama daemon is offline, fails gracefully to enable keyword fallback.
"""

from __future__ import annotations

import logging
import math
import struct
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple, Union

from app.memory.database import DatabaseManager, utc_now

if TYPE_CHECKING:
    from backend.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


def pack_vector(vector: Sequence[float]) -> bytes:
    """Serializes a float sequence into a compact binary float32 BLOB."""
    return struct.pack(f"{len(vector)}f", *vector)


def unpack_vector(blob: bytes) -> List[float]:
    """Deserializes a binary float32 BLOB back into a list of floats."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


def cosine_similarity(v1: Sequence[float], v2: Sequence[float]) -> float:
    """Computes cosine similarity between two numeric vectors in [-1.0, 1.0]."""
    if len(v1) != len(v2) or len(v1) == 0:
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm_a += a * a
        norm_b += b * b

    if norm_a <= 0.0 or norm_b <= 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


class VectorIndexManager:
    """
    Manages vector embeddings persistence, retrieval, and indexing inside SQLite.
    Integrates directly with local OllamaClient for local vector generation.
    """

    def __init__(
        self,
        db: DatabaseManager,
        ollama_client: Optional[OllamaClient] = None,
    ):
        self.db = db
        self._ollama_client = ollama_client

    @property
    def ollama_client(self) -> Any:
        if self._ollama_client is None:
            from backend.ollama_client import get_ollama_client
            self._ollama_client = get_ollama_client()
        return self._ollama_client

    # ------------------------------------------------------------------------
    # Indexing Operations
    # ------------------------------------------------------------------------

    def index_memory(
        self,
        memory_id: str,
        text: str,
        model_name: Optional[str] = None,
    ) -> bool:
        """
        Generates local Ollama embedding for text and persists vector in memory_embeddings table.
        Returns True on success, False if Ollama daemon is unreachable or embedding failed.
        """
        clean_text = text.strip() if text else ""
        if not clean_text:
            return False

        try:
            target_model = model_name or self.ollama_client.config.embed_model
            embed_resp = self.ollama_client.embed(texts=clean_text, model=target_model)
            if not embed_resp.embeddings:
                return False

            vector = embed_resp.embeddings[0]
            return self.save_vector(
                memory_id=memory_id,
                vector=vector,
                model_name=embed_resp.model,
                dimensions=embed_resp.dimensions,
            )
        except Exception as e:
            logger.debug(f"Local embedding generation unavailable for memory '{memory_id}': {e}")
            return False

    def save_vector(
        self,
        memory_id: str,
        vector: Sequence[float],
        model_name: str,
        dimensions: int,
    ) -> bool:
        """Persists a pre-computed vector directly into memory_embeddings table."""
        blob = pack_vector(vector)
        now = utc_now()
        sql = """
            INSERT INTO memory_embeddings (
                memory_id, model_name, dimensions, embedding_blob, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                model_name = excluded.model_name,
                dimensions = excluded.dimensions,
                embedding_blob = excluded.embedding_blob,
                updated_at = excluded.updated_at;
        """
        with self.db.transaction() as conn:
            conn.execute(sql, (memory_id, model_name, dimensions, blob, now, now))
        return True

    def remove_embedding(self, memory_id: str) -> bool:
        """Removes the vector representation of a memory record upon update or deletion."""
        sql = "DELETE FROM memory_embeddings WHERE memory_id = ?;"
        with self.db.transaction() as conn:
            cursor = conn.execute(sql, (str(memory_id).strip(),))
            return cursor.rowcount > 0

    def get_embedding(self, memory_id: str) -> Optional[List[float]]:
        """Retrieves and unpacks vector from SQLite."""
        sql = "SELECT embedding_blob FROM memory_embeddings WHERE memory_id = ?;"
        conn = self.db.get_connection()
        try:
            row = conn.execute(sql, (str(memory_id).strip(),)).fetchone()
            if not row or not row["embedding_blob"]:
                return None
            return unpack_vector(row["embedding_blob"])
        finally:
            conn.close()

    # ------------------------------------------------------------------------
    # Similarity Search
    # ------------------------------------------------------------------------

    def search_similar(
        self,
        query: str,
        top_k: int = 10,
        candidate_ids: Optional[Sequence[str]] = None,
        model_name: Optional[str] = None,
        min_similarity: float = 0.0,
    ) -> List[Tuple[str, float]]:
        """
        Embeds search query and computes cosine similarities against active embeddings.
        Returns list of (memory_id, similarity_score) sorted descending by similarity.
        Returns empty list if local Ollama daemon is offline or query is empty.
        """
        clean_query = query.strip() if query else ""
        if not clean_query:
            return []

        # 0. Check if any embeddings exist before attempting inference
        conn = self.db.get_connection()
        try:
            has_records = conn.execute("SELECT 1 FROM memory_embeddings LIMIT 1;").fetchone()
            if not has_records:
                return []
        finally:
            conn.close()

        # 1. Generate query embedding
        try:
            target_model = model_name or self.ollama_client.config.embed_model
            query_resp = self.ollama_client.embed(texts=clean_query, model=target_model, timeout=0.6)
            if not query_resp.embeddings:
                return []
            query_vec = query_resp.embeddings[0]
            query_dims = query_resp.dimensions
        except Exception as e:
            logger.debug(f"Semantic search query embedding failed: {e}. Falling back to degraded keyword search.")
            return []

        # 2. Retrieve candidate embedding blobs
        clauses = ["m.is_deleted = 0", "e.dimensions = ?"]
        params: List[Any] = [query_dims]

        if candidate_ids is not None:
            if not candidate_ids:
                return []
            placeholders = ",".join("?" for _ in candidate_ids)
            clauses.append(f"e.memory_id IN ({placeholders})")
            params.extend(list(candidate_ids))

        sql = f"""
            SELECT e.memory_id, e.embedding_blob
            FROM memory_embeddings e
            JOIN memories m ON e.memory_id = m.id
            WHERE {' AND '.join(clauses)};
        """

        conn = self.db.get_connection()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        # 3. Compute cosine similarities
        scores: List[Tuple[str, float]] = []
        for row in rows:
            blob = row["embedding_blob"]
            if not blob:
                continue
            stored_vec = unpack_vector(blob)
            sim = cosine_similarity(query_vec, stored_vec)
            if sim >= min_similarity:
                scores.append((row["memory_id"], round(sim, 4)))

        # 4. Sort descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        """Returns diagnostic statistics for local vector store."""
        sql = """
            SELECT model_name, dimensions, COUNT(*) as count
            FROM memory_embeddings
            GROUP BY model_name, dimensions;
        """
        conn = self.db.get_connection()
        try:
            rows = conn.execute(sql).fetchall()
            stats: List[Dict[str, Any]] = []
            total = 0
            for r in rows:
                stats.append({
                    "model_name": r["model_name"],
                    "dimensions": r["dimensions"],
                    "count": r["count"],
                })
                total += r["count"]
            return {"total_embeddings": total, "models": stats}
        finally:
            conn.close()
