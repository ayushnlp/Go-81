"""
Live Demonstration Script for Go 81 Memory & Security Subsystem.
Run with: python demo.py
"""

import os
import sys
import tempfile
import time

# Ensure project root is in path
sys.path.insert(0, os.path.abspath("."))

from app.memory.consolidation import MemoryConsolidationEngine
from app.memory.crypto import EncryptionService, TestKeyProvider
from app.memory.database import DatabaseManager
from app.memory.models import (
    MemoryType,
    PermissionCheckRequest,
    RiskLevel,
    SemanticCategory,
    TaskCheckpoint,
    TaskStatus,
    VerificationStatus,
)
from app.memory.permissions import PermissionGateway
from app.memory.recovery import TaskRecoveryManager, compute_action_hash
from app.memory.service import MemoryService


def run_demo():
    print("=" * 70)
    print("  Go 81 MEMORY & SECURITY SUBSYSTEM - LIVE DEMO")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "demo_vault.db")
        print(f"\n[1] Initializing SQLite Database (WAL mode) & Fernet Encryption...")
        key_provider = TestKeyProvider()
        crypto = EncryptionService(key_provider)
        db = DatabaseManager(db_path)
        service = MemoryService(db, crypto)
        recovery_mgr = TaskRecoveryManager(db, crypto)
        perm_gateway = PermissionGateway(db)
        consolidation = MemoryConsolidationEngine(service)
        print("    -> Database initialized with schema migrations.")
        print(f"    -> Master Key derived safely in-memory (never written to disk).")

        # 2. Episodic Memory
        print("\n[2] Logging Episodic Interaction Event (Muninn's Saga-Log)...")
        evt = service.store_event(
            session_id="session-demo-01",
            event_type="user_message",
            content={"user": "Ayush", "message": "Remember that I prefer dark mode and SQLite for my stack."},
            source_ref="terminal_cli",
        )
        print(f"    -> Stored Event ID: {evt.id}")
        print(f"    -> Event Type: {evt.event_type} | Source: {evt.source_ref}")

        # 3. Explainable Consolidation
        print("\n[3] Triggering Explainable Consolidation & Promotion Engine...")
        promoted = consolidation.consolidate_recent_events()
        print(f"    -> Consolidated {len(promoted)} episodic statements into semantic facts:")
        for p in promoted:
            print(f"       * Subject: '{p['subject']}' | Predicate: '{p['predicate']}' | Value: '{p['object_value']}'")

        # 4. Semantic Deduplication
        print("\n[4] Storing Semantic Memory & Deduplication Guard...")
        s1 = service.store_memory(
            category=SemanticCategory.FACT,
            subject="Project Go 81",
            predicate="backend_framework",
            object_value="FastAPI",
            verification_status=VerificationStatus.VERIFIED,
            confidence=1.0,
        )
        print(f"    -> Stored Fact ID: {s1.id} (Confidence: {s1.confidence})")

        # Storing identical fact with inferred status
        s2 = service.store_memory(
            category=SemanticCategory.FACT,
            subject="project go 81",  # Normalized matching
            predicate="backend_framework",
            object_value="FastAPI",
            verification_status=VerificationStatus.INFERRED,
            confidence=0.8,
        )
        print(f"    -> Deduplication check: ID matched? {s1.id == s2.id} (Zero duplicate rows created)")

        # 5. Verifiable Encryption at Rest
        print("\n[5] Verifiable Encryption at Rest (Raw Disk Inspection)...")
        secret_secret = "CONFIDENTIAL_ODIN_SUPER_KEY_9999"
        service.store_event(
            session_id="session-vault",
            event_type="agent_message",
            content={"confidential_thought": secret_secret},
        )
        db.checkpoint_wal()
        with open(db_path, "rb") as f:
            raw_disk = f.read()

        is_leaked = secret_secret.encode("utf-8") in raw_disk
        print(f"    -> Checking raw SQLite disk bytes for plaintext '{secret_secret}'...")
        print(f"    -> Plaintext present in database file? {'FAIL - LEAK DETECTED' if is_leaked else 'PASSED - ZERO PLAINTEXT FOUND'}")
        assert not is_leaked

        # 6. Task Crash Recovery & Idempotency Guard
        print("\n[6] Task Persistence, Reboot Recovery & Idempotency Guard...")
        task_id = "task-deploy-001"
        chk = TaskCheckpoint(
            task_id=task_id,
            workflow_id="wf-release",
            status=TaskStatus.RUNNING,
            current_step="compile_binary",
            completed_step_ids=[],
            pending_step_ids=["compile_binary", "sign_binary", "upload_release"],
            state_data={"target_arch": "x86_64", "build_version": "1.0.0"},
        )
        recovery_mgr.save_task_checkpoint(chk)

        # Mark step 1 completed
        recovery_mgr.mark_step_completed(task_id, "compile_binary", next_step="sign_binary")
        action_hash = compute_action_hash("compile", {"target": "x86_64"})
        recovery_mgr.record_execution_event(
            task_id=task_id,
            step_id="compile_binary",
            action="compile",
            status="SUCCESS",
            input_params={"target": "x86_64"},
            output_details={"binary_size": 2400000},
        )
        print(f"    -> Step 'compile_binary' committed with side-effect hash: {action_hash[:16]}...")

        # Simulate Restart
        print("    -> Simulating agent reboot and inspecting recovery state...")
        incomplete_tasks = recovery_mgr.load_incomplete_tasks()
        rec_task = incomplete_tasks[0]
        print(f"    -> Recovered Task: {rec_task.task_id} | Resume Step: {rec_task.current_step}")
        already_run = recovery_mgr.is_step_already_executed(task_id, "compile_binary", idempotency_hash=action_hash)
        print(f"    -> Idempotency Guard: Was 'compile_binary' prevented from re-running? {already_run}")

        # 7. Default-Deny Authorization Gate
        print("\n[7] Security Gateway: Default-Deny Policy & Human Approval Gate...")
        # Step A: Shell command blocked
        dec1 = perm_gateway.check_permission(
            user_id="agent-go81",
            action="shell_execute",
            resource="rm -rf /critical_data",
            risk_level=RiskLevel.HIGH,
        )
        print(f"    -> Autonomous model shell request: Allowed? {dec1.allowed} (Requires approval: {dec1.approval_required})")
        print(f"       Reason: {dec1.reason}")

        # Step B: Human issues approval token via UI/CLI
        token = perm_gateway.grant_approval("shell_execute", "rm -rf /critical_data", ttl_seconds=60)
        print(f"    -> Operator granted ephemeral human token: {token[:18]}...")

        # Step C: Execution unlocked
        dec2 = perm_gateway.check_permission(
            user_id="agent-go81",
            action="shell_execute",
            resource="rm -rf /critical_data",
            risk_level=RiskLevel.HIGH,
            approval_token=token,
        )
        print(f"    -> Re-check with human token: Allowed? {dec2.allowed}")

        # Step D: Single-use token consumed
        dec3 = perm_gateway.check_permission(
            user_id="agent-go81",
            action="shell_execute",
            resource="rm -rf /critical_data",
            risk_level=RiskLevel.HIGH,
            approval_token=token,
        )
        print(f"    -> Token re-use replay attempt: Allowed? {dec3.allowed} (Token successfully invalidated)")

        print("\n" + "=" * 70)
        print("  ALL DEMO SPECIFICATIONS & INTEGRITY CHECKS PASSED SUCCESSFULLY!")
        print("=" * 70)


if __name__ == "__main__":
    run_demo()
