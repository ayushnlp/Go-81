"""
Reproducible Performance Benchmark for Go 81 Memory and Conversational Engine.
Measures:
1. Embedding generation (nomic-embed-text)
2. Episodic memory retrieval
3. Semantic vector retrieval
4. Hybrid retrieval (keyword + vector)
5. Complete memory query (query_relevant_context)
6. Intent classification
7. Combined conversational request
"""

import os
import sys
import time
import tempfile
import statistics
import platform
from typing import Any, Dict, List

# Ensure repository root is on sys.path
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import httpx
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager
from app.memory.service import MemoryService
from app.memory.models import SemanticCategory, VerificationStatus, EpisodicEvent, EpisodicEventType
from app.memory.vector_index import VectorIndexManager
from backend.ollama_client import OllamaClient, OllamaConfig
from backend.conversational.intent import IntentClassifier
from backend.conversational.engine import IntelligentConversationalEngine


def compute_stats(latencies_ms: List[float]) -> Dict[str, float]:
    if not latencies_ms:
        return {"p50": 0.0, "p95": 0.0, "max": 0.0, "min": 0.0, "mean": 0.0}
    sorted_l = sorted(latencies_ms)
    n = len(sorted_l)
    p50 = sorted_l[int(n * 0.50)]
    idx_95 = min(int(n * 0.95), n - 1)
    p95 = sorted_l[idx_95]
    return {
        "p50": round(p50, 2),
        "p95": round(p95, 2),
        "max": round(max(sorted_l), 2),
        "min": round(min(sorted_l), 2),
        "mean": round(statistics.mean(sorted_l), 2),
    }


def run_benchmark():
    print("=" * 80)
    print("GO 81 — STAGE 5.1 MEMORY & CONVERSATIONAL PERFORMANCE BENCHMARK")
    print("=" * 80)
    
    # 0. Environment & Hardware Documentation
    hw_info = {
        "os": f"{platform.system()} {platform.release()} ({platform.version()})",
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "chat_model": os.environ.get("OLLAMA_CHAT_MODEL", "llama3.2:3b"),
        "embed_model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest"),
        "target_ms": 800.0,
    }
    print(f"OS: {hw_info['os']}")
    print(f"Processor: {hw_info['processor']}")
    print(f"Chat Model: {hw_info['chat_model']}")
    print(f"Embed Model: {hw_info['embed_model']}")
    print(f"Performance SLA Target: < {hw_info['target_ms']} ms")
    print("-" * 80)

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = os.path.join(tmp_dir, "benchmark.db")
        crypto = EncryptionService(key_provider=TestKeyProvider())
        db = DatabaseManager(db_path)

        cfg = OllamaConfig(
            base_url="http://127.0.0.1:11434",
            chat_model=hw_info["chat_model"],
            embed_model=hw_info["embed_model"],
        )
        ollama_client = OllamaClient(config=cfg)
        vector_index = VectorIndexManager(db=db, ollama_client=ollama_client)
        service = MemoryService(db=db, crypto=crypto, vector_index=vector_index, ollama_client=ollama_client)

        print("\n[Setup] Seeding test dataset (20 episodic records, 50 semantic records)...")
        # Seed 20 episodic events
        for i in range(20):
            service.store_event(
                session_id=f"task-bench-{i % 5}",
                event_type="tool_execution" if i % 2 == 0 else "task_outcome",
                content={"output": f"Executed deployment step {i} on environment worker node {i % 3}."},
                metadata={"step_index": i, "status": "completed"},
            )

        # Seed 50 semantic records
        for i in range(50):
            cat = SemanticCategory.FACT if i % 2 == 0 else SemanticCategory.PREFERENCE
            service.store_memory(
                category=cat,
                subject=f"service_component_{i}",
                predicate="configuration_setting" if i % 2 == 0 else "preferred_tool",
                object_value=f"active_profile_{i} with logging enabled",
                verification_status=VerificationStatus.VERIFIED if i % 2 == 0 else VerificationStatus.USER_PROVIDED,
                source_ref="benchmark_setup",
            )
        print("[Setup] Seeding completed successfully.")

        results = {}

        # -------------------------------------------------------------
        # Benchmark 1: Embedding Generation (Local nomic-embed-text)
        # -------------------------------------------------------------
        print("\n--- 1. Embedding Generation (nomic-embed-text) ---")
        embed_latencies = []
        cold_embed = None
        for i in range(6):
            t0 = time.perf_counter()
            resp = ollama_client.embed(
                texts=f"Benchmark query sample for semantic search iteration {i}",
                model=hw_info["embed_model"]
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if i == 0:
                cold_embed = round(elapsed_ms, 2)
            else:
                embed_latencies.append(elapsed_ms)
        stats_embed = compute_stats(embed_latencies)
        results["embedding_generation"] = {"cold_ms": cold_embed, **stats_embed}
        print(f"Cold: {cold_embed} ms | Warm P50: {stats_embed['p50']} ms | P95: {stats_embed['p95']} ms | Max: {stats_embed['max']} ms")

        # -------------------------------------------------------------
        # Benchmark 2: Episodic Memory Retrieval
        # -------------------------------------------------------------
        print("\n--- 2. Episodic Memory Retrieval ---")
        episodic_latencies = []
        cold_episodic = None
        for i in range(6):
            t0 = time.perf_counter()
            events = service.get_events(session_id="task-bench-1", limit=10)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if i == 0:
                cold_episodic = round(elapsed_ms, 2)
            else:
                episodic_latencies.append(elapsed_ms)
        stats_episodic = compute_stats(episodic_latencies)
        results["episodic_retrieval"] = {"cold_ms": cold_episodic, **stats_episodic}
        print(f"Cold: {cold_episodic} ms | Warm P50: {stats_episodic['p50']} ms | P95: {stats_episodic['p95']} ms | Max: {stats_episodic['max']} ms (Found {len(events)} events)")

        # -------------------------------------------------------------
        # Benchmark 3: Semantic Vector Retrieval
        # -------------------------------------------------------------
        print("\n--- 3. Semantic Vector Retrieval (Cosine Similarity) ---")
        vector_latencies = []
        cold_vector = None
        for i in range(6):
            t0 = time.perf_counter()
            matches = service.vector_index.search_similar("service_component_25 logging profile", top_k=5)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if i == 0:
                cold_vector = round(elapsed_ms, 2)
            else:
                vector_latencies.append(elapsed_ms)
        stats_vector = compute_stats(vector_latencies)
        results["semantic_vector_retrieval"] = {"cold_ms": cold_vector, **stats_vector}
        print(f"Cold: {cold_vector} ms | Warm P50: {stats_vector['p50']} ms | P95: {stats_vector['p95']} ms | Max: {stats_vector['max']} ms (Matches: {len(matches)})")

        # -------------------------------------------------------------
        # Benchmark 4: Hybrid Retrieval (Keyword + Vector)
        # -------------------------------------------------------------
        print("\n--- 4. Hybrid Retrieval (Keyword + Vector) ---")
        hybrid_latencies = []
        cold_hybrid = None
        for i in range(6):
            t0 = time.perf_counter()
            memories = service.search_memories(query="service_component_10 active profile", limit=5)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if i == 0:
                cold_hybrid = round(elapsed_ms, 2)
            else:
                hybrid_latencies.append(elapsed_ms)
        stats_hybrid = compute_stats(hybrid_latencies)
        results["hybrid_retrieval"] = {"cold_ms": cold_hybrid, **stats_hybrid}
        print(f"Cold: {cold_hybrid} ms | Warm P50: {stats_hybrid['p50']} ms | P95: {stats_hybrid['p95']} ms | Max: {stats_hybrid['max']} ms (Retrieved: {len(memories)})")

        # -------------------------------------------------------------
        # Benchmark 5: Complete Memory Query (query_relevant_context)
        # -------------------------------------------------------------
        print("\n--- 5. Complete Memory Query (query_relevant_context) ---")
        ctx_latencies = []
        cold_ctx = None
        for i in range(6):
            t0 = time.perf_counter()
            ctx = service.query_relevant_context("What is preferred tool for service_component_5?")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if i == 0:
                cold_ctx = round(elapsed_ms, 2)
            else:
                ctx_latencies.append(elapsed_ms)
        stats_ctx = compute_stats(ctx_latencies)
        results["complete_memory_query"] = {"cold_ms": cold_ctx, **stats_ctx}
        print(f"Cold: {cold_ctx} ms | Warm P50: {stats_ctx['p50']} ms | P95: {stats_ctx['p95']} ms | Max: {stats_ctx['max']} ms")

        # -------------------------------------------------------------
        # Benchmark 6: Intent Classification
        # -------------------------------------------------------------
        print("\n--- 6. Intent Classification ---")
        classifier = IntentClassifier()
        intent_latencies = []
        cold_intent = None
        for i in range(10):
            t0 = time.perf_counter()
            res = classifier.classify("What is 15 * 8?")
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if i == 0:
                cold_intent = round(elapsed_ms, 2)
            else:
                intent_latencies.append(elapsed_ms)
        stats_intent = compute_stats(intent_latencies)
        results["intent_classification"] = {"cold_ms": cold_intent, **stats_intent}
        print(f"Cold: {cold_intent} ms | Warm P50: {stats_intent['p50']} ms | P95: {stats_intent['p95']} ms | Max: {stats_intent['max']} ms")

        # -------------------------------------------------------------
        # Benchmark 7: Combined Conversational Request
        # -------------------------------------------------------------
        print("\n--- 7. Combined Conversational Request (Engine Pipeline) ---")
        engine = IntelligentConversationalEngine(ollama_endpoint=cfg.base_url, chat_model=cfg.chat_model)
        conv_latencies = []
        cold_conv = None
        # 7A: Fast deterministic calculation
        t0 = time.perf_counter()
        math_resp = engine.handle_message(prompt="Calculate 25 * 4", session_id="bench-math")
        math_ms = (time.perf_counter() - t0) * 1000
        print(f"Deterministic Math Turn: {math_ms:.2f} ms (Target: < 800 ms)")

        # 7B: Conversational turn with grounded memory context
        for i in range(3):
            t0 = time.perf_counter()
            ans = engine.handle_message(
                prompt="What tool do I prefer for service_component_5?",
                session_id=f"bench-conv-{i}",
                memory_service=service,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000
            if i == 0:
                cold_conv = round(elapsed_ms, 2)
            else:
                conv_latencies.append(elapsed_ms)
        stats_conv = compute_stats(conv_latencies)
        results["combined_conversational_turn"] = {"cold_ms": cold_conv, **stats_conv, "math_turn_ms": round(math_ms, 2)}
        print(f"Cold LLM Turn: {cold_conv} ms | Warm P50: {stats_conv['p50']} ms | P95: {stats_conv['p95']} ms | Max: {stats_conv['max']} ms")

        # -------------------------------------------------------------
        # Final SLA Evaluation Table
        # -------------------------------------------------------------
        print("\n" + "=" * 80)
        print("FINAL BENCHMARK EVALUATION TABLE (800ms Target)")
        print("=" * 80)
        print(f"{'Operation':<35} | {'Cold (ms)':<10} | {'P50 (ms)':<10} | {'P95 (ms)':<10} | {'SLA Status':<10}")
        print("-" * 80)
        for op, data in results.items():
            p50 = data.get("p50", 0.0)
            status = "MEETS" if p50 < hw_info["target_ms"] else "EXCEEDS"
            print(f"{op:<35} | {data.get('cold_ms', 0.0):<10} | {p50:<10} | {data.get('p95', 0.0):<10} | {status:<10}")

        print("=" * 80)
        return results

if __name__ == "__main__":
    run_benchmark()
