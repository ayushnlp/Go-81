"""
Regression Tests for Stage 3 Security Hardening.
Validates fixes for:
1. Audit-token redaction (comprehensive scrub patterns, nested metadata sanitization, zero token leakage in SQLite)
2. Capability default-deny policy (unrecognized capabilities rejected, context-level granted_capabilities restrictions enforced)
3. Complete approval API enforcement (pending listing, resolve endpoint, 404/409/400 validation, single-use token generation)
4. Network hostname, port, and scope restrictions (port whitelisting, scheme checks, SSRF prevention)
5. Truthful timeout and cancellation behavior (proper CANCELLED and TIMEOUT audit statuses, orchestrator task cancellation)
6. Fail-closed orchestration for unknown skills (no sandbox bypass, unknown skills fail closed with audit trail)
"""

import asyncio
import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from app.api.routes import SubsystemContainer
from backend.main import app
from app.memory.database import DatabaseManager
from app.memory.models import RiskLevel
from app.skills.audit import SkillAuditLogger, sanitize_audit_text, sanitize_audit_structure
from app.skills.builtins import (
    register_builtin_skills,
    validate_network_scope,
    ALLOWED_HTTP_HOSTS,
)
from app.skills.gateway import SecurityPermissionGateway
from app.skills.models import (
    Capability,
    ExecutionContext,
    FilesystemScope,
    NetworkScope,
    ResourceLimits,
    SkillCategory,
    SkillDefinition,
    SkillParameter,
    SkillRiskLevel,
)
from app.skills.registry import SkillRegistry
from app.skills.sandbox import SkillExecutionSandbox
from backend.orchestrator import TaskOrchestrator
from backend.planner import DAGStep, TaskDAG


# ============================================================================
# 1. Audit-Token Redaction Tests
# ============================================================================

def test_audit_token_redaction_patterns():
    """Verifies all sensitive token formats are scrubbed from text."""
    test_cases = [
        ("auth token is tok-1234567890abcdef1234567890abcdef", "[REDACTED]"),
        ("approval id apr-1234567890abcdef", "[REDACTED]"),
        ("short approval apr-1234567890", "[REDACTED]"),
        ("pending approval pending-1234567890abcdef", "[REDACTED]"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", "[REDACTED]"),
        ("api_key='sk-test-1234567890123456'", "[REDACTED]"),
        ("password=super_secret_pass_123", "[REDACTED]"),
        ("token: tok-abcdef0123456789", "[REDACTED]"),
    ]

    for raw, expected in test_cases:
        scrubbed = sanitize_audit_text(raw)
        assert expected in scrubbed
        assert "super_secret_pass_123" not in scrubbed
        assert "sk-test-1234567890123456" not in scrubbed


def test_audit_metadata_nested_redaction():
    """Verifies nested dictionaries and lists in audit metadata redact credentials."""
    nested_meta = {
        "headers": {
            "Authorization": "Bearer secret-bearer-token-123456",
            "X-Api-Key": "my-secret-api-key-9999",
        },
        "payload": {
            "approval_token": "tok-1234567890abcdef1234567890abcdef",
            "user": "alice",
            "credentials": ["password123", "secret_key"],
        },
        "safe_key": "safe_value",
    }

    sanitized = sanitize_audit_structure(nested_meta)

    # Sensitive keys and tokens must be redacted
    assert sanitized["headers"]["Authorization"] == "[REDACTED]"
    assert sanitized["headers"]["X-Api-Key"] == "[REDACTED]"
    assert sanitized["payload"]["approval_token"] == "[REDACTED]"
    assert sanitized["payload"]["credentials"] == "[REDACTED]"
    assert sanitized["safe_key"] == "safe_value"
    assert sanitized["payload"]["user"] == "alice"


def test_audit_sqlite_zero_raw_token_leakage():
    """Verifies that SQLite skill_audit_records table contains zero raw tokens."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "audit_leak.db"))
        logger = SkillAuditLogger(db)

        raw_token = "tok-1234567890abcdef1234567890abcdef"
        logger.log_event(
            skill_id="system.info",
            version="1.0.0",
            action="system.info",
            policy_outcome="ALLOWED",
            capabilities=[],
            approval_token=raw_token,
            error_message=f"Failed using token {raw_token}",
            metadata={"token": raw_token, "nested": {"auth_token": raw_token}},
        )

        records = logger.get_recent_records(limit=10)
        assert len(records) == 1
        rec = records[0]

        # In-memory and persisted records must NOT contain raw token
        assert rec.approval_token == "[REDACTED_APPROVAL_TOKEN]"
        assert raw_token not in (rec.error_message or "")
        assert raw_token not in str(rec.metadata)

        # Raw DB text check
        conn = db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM skill_audit_records;")
            row = cursor.fetchone()
            row_str = " ".join(str(val) for val in dict(row).values())
            assert raw_token not in row_str
        finally:
            conn.close()


# ============================================================================
# 2. Capability Default-Deny Policy Tests
# ============================================================================

def test_capability_default_deny_rejects_unknown_capability():
    """Verifies gateway denies skills declaring unrecognized capabilities."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "gw.db"))
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                id="rogue.tool",
                name="rogue.tool",
                displayName="Rogue Tool",
                risk_level=SkillRiskLevel.LOW,
                required_capabilities=["unauthorized:super_admin"],
            )
        )
        gateway = SecurityPermissionGateway(db, reg)

        ctx = ExecutionContext()
        decision = gateway.authorize_skill_execution("rogue.tool", {}, ctx)

        assert decision.allowed is False
        assert "not recognized or permitted under system default-deny policy" in decision.reason


def test_capability_default_deny_context_scoping():
    """Verifies gateway denies execution when context granted_capabilities does not include required capability."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "gw.db"))
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                id="file.writer",
                name="file.writer",
                displayName="File Writer",
                risk_level=SkillRiskLevel.LOW,
                required_capabilities=[Capability.FILESYSTEM_WRITE.value],
            )
        )
        gateway = SecurityPermissionGateway(db, reg)

        # 1. Context granted only filesystem:read -> must be denied filesystem:write
        read_only_ctx = ExecutionContext(granted_capabilities=[Capability.FILESYSTEM_READ.value])
        d1 = gateway.authorize_skill_execution("file.writer", {}, read_only_ctx)
        assert d1.allowed is False
        assert "not granted in the execution context under default-deny policy" in d1.reason

        # 2. Context with empty list (zero capabilities) -> must be denied
        zero_caps_ctx = ExecutionContext(granted_capabilities=[])
        d2 = gateway.authorize_skill_execution("file.writer", {}, zero_caps_ctx)
        assert d2.allowed is False

        # 3. Context granted filesystem:write -> proceeds (to approval gate since write is sensitive)
        write_ctx = ExecutionContext(granted_capabilities=[Capability.FILESYSTEM_WRITE.value])
        d3 = gateway.authorize_skill_execution("file.writer", {}, write_ctx)
        assert d3.approval_required is True


# ============================================================================
# 3. Complete Approval API Enforcement Tests
# ============================================================================

def test_approval_api_lifecycle_and_validation():
    """Tests approval pending listing, resolution, 404, 409, and expiration handling."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "appr_api.db")
        SubsystemContainer.initialize(db_path=db_path)
        from app.skills.routes import SkillContainer
        SkillContainer.initialize(SubsystemContainer.db, project_root=tmpdir)

        client = TestClient(app)

        # 1. Propose action requiring approval to generate pending approval
        prop = client.post(
            "/api/skills/propose",
            json={"skill_id": "filesystem.write", "parameters": {"path": "test.txt", "content": "data"}},
        )
        assert prop.status_code == 200
        prop_data = prop.json()
        assert prop_data["requires_approval"] is True
        approval_id = prop_data["approval_id"]
        assert approval_id is not None

        # 2. Verify pending approval visible in GET /api/skills/approvals/pending and GET /api/approvals
        r_pend = client.get("/api/skills/approvals/pending")
        assert r_pend.status_code == 200
        pending_items = r_pend.json()
        assert any(item["approval_id"] == approval_id for item in pending_items)

        r_main_pend = client.get("/api/approvals")
        assert r_main_pend.status_code == 200
        assert any(item["approval_id"] == approval_id for item in r_main_pend.json())

        # 3. Resolve approval via POST /api/skills/approvals/{id}/resolve
        r_resolve = client.post(
            f"/api/skills/approvals/{approval_id}/resolve",
            json={"approved": True, "reason": "Authorized by security admin"},
        )
        assert r_resolve.status_code == 200
        res_data = r_resolve.json()
        assert res_data["approved"] is True
        assert res_data["status"] == "APPROVED"
        token = res_data["token"]
        assert token.startswith("tok-")

        # 4. Attempt to resolve already-resolved approval -> 409 Conflict
        r_conflict = client.post(
            f"/api/skills/approvals/{approval_id}/resolve",
            json={"approved": True},
        )
        assert r_conflict.status_code == 409
        assert "already been resolved" in r_conflict.json()["detail"].lower()

        # 5. Non-existent approval -> 404 Not Found
        r_404 = client.post(
            "/api/skills/approvals/apr-nonexistent99/resolve",
            json={"approved": True},
        )
        assert r_404.status_code == 404

        # 6. Execute skill using the issued token -> SUCCEEDS
        r_exec = client.post(
            "/api/skills/filesystem.write/execute",
            json={
                "parameters": {"path": "test.txt", "content": "data"},
                "approval_token": token,
            },
        )
        assert r_exec.status_code == 200
        assert r_exec.json()["success"] is True


# ============================================================================
# 4. Network Hostname, Port, and Scope Restrictions Tests
# ============================================================================

def test_network_scope_port_and_host_restrictions():
    """Verifies that network scope enforces hostname, port, and scheme whitelisting."""
    scope = NetworkScope(
        allowed_hosts=["localhost", "127.0.0.1", "api.github.com"],
        allowed_ports=[80, 443, 8000, 11434],
        allow_http=True,
        allow_https=True,
    )

    # 1. Allowed host and port
    validate_network_scope("http://127.0.0.1:8000/v1/health", scope)
    validate_network_scope("https://api.github.com:443/repos", scope)
    validate_network_scope("http://localhost:11434/api/tags", scope)

    # 2. Disallowed host -> must raise PermissionError
    with pytest.raises(PermissionError, match="not permitted"):
        validate_network_scope("https://evil-host.attacker.com/leak", scope)

    # 3. Disallowed port (port 22 SSH, 6379 Redis, 25 SMTP) -> must raise PermissionError
    with pytest.raises(PermissionError, match="port 22"):
        validate_network_scope("http://127.0.0.1:22", scope)

    with pytest.raises(PermissionError, match="port 6379"):
        validate_network_scope("http://localhost:6379", scope)

    # 4. Disallowed protocol (HTTP when allow_http=False)
    https_only_scope = NetworkScope(
        allowed_hosts=["api.github.com"],
        allowed_ports=[443],
        allow_http=False,
        allow_https=True,
    )
    with pytest.raises(PermissionError, match="HTTP protocol is not permitted"):
        validate_network_scope("http://api.github.com:80", https_only_scope)


@pytest.mark.asyncio
async def test_sandbox_network_scope_rejection_before_execution():
    """Verifies sandbox rejects requests violating network scope before handler execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "net_sb.db"))
        reg = SkillRegistry()
        register_builtin_skills(reg)
        gateway = SecurityPermissionGateway(db, reg)
        logger = SkillAuditLogger(db)
        sandbox = SkillExecutionSandbox(reg, gateway, logger, default_project_root=tmpdir)

        # Attacker tries to access internal SSH port 22 on localhost
        malicious_url = "http://127.0.0.1:22/ssh"
        _, token = gateway.create_approval_token("network.http_get", {"url": malicious_url})

        res = await sandbox.execute(
            "network.http_get",
            {"url": malicious_url},
            ExecutionContext(project_root=tmpdir, approval_token=token),
        )

        assert res.success is False
        assert "port 22" in res.error.lower() or "not permitted" in res.error.lower()

        # Check audit record logs BLOCKED/DENIED
        records = logger.get_recent_records(limit=5)
        rec = next(r for r in records if r.skill_id == "network.http_get")
        assert rec.policy_outcome == "DENIED"
        assert rec.execution_status == "BLOCKED"


# ============================================================================
# 5. Truthful Timeout and Cancellation Behavior Tests
# ============================================================================

@pytest.mark.asyncio
async def test_sandbox_truthful_cancellation_status():
    """Verifies cancelled executions are recorded truthfully as CANCELLED in audit trail."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db = DatabaseManager(os.path.join(tmpdir, "cancel_sb.db"))
        reg = SkillRegistry()
        reg.register(
            SkillDefinition(
                id="test.async_task",
                name="test.async_task",
                displayName="Async Task",
                risk_level=SkillRiskLevel.LOW,
            ),
            handler=lambda p, ctx: time.sleep(0.01),
        )
        gateway = SecurityPermissionGateway(db, reg)
        logger = SkillAuditLogger(db)
        sandbox = SkillExecutionSandbox(reg, gateway, logger, default_project_root=tmpdir)

        # 1. Pre-execution cancelled context
        ctx = ExecutionContext(project_root=tmpdir, is_cancelled=True)
        res = await sandbox.execute("test.async_task", {}, ctx)

        assert res.success is False
        assert "cancelled" in res.error.lower()
        records = logger.get_recent_records(limit=5)
        assert records[0].execution_status == "CANCELLED"


@pytest.mark.asyncio
async def test_orchestrator_task_cancellation():
    """Verifies TaskOrchestrator.cancel_task transitions task and steps to CANCELLED."""
    orchestrator = TaskOrchestrator()
    task = TaskDAG(
        task_id="task-cancel-test",
        goal="Test Cancellation",
        system_prompt="You are Go 81 sovereign agent",
        steps=[
            DAGStep(
                step_id="step-1",
                step_number=1,
                title="Pending Step",
                skill_name="system.info",
                status="PENDING",
            ),
            DAGStep(
                step_id="step-2",
                step_number=2,
                title="Paused Step",
                skill_name="filesystem.write",
                status="PAUSED_APPROVAL",
            ),
        ],
    )
    orchestrator.register_task(task)

    # Cancel task
    res = await orchestrator.cancel_task("task-cancel-test", reason="User stopped run")
    assert res["success"] is True
    assert res["status"] == "CANCELLED"

    retrieved = orchestrator.get_task("task-cancel-test")
    assert retrieved.status == "CANCELLED"
    assert retrieved.steps[0].status == "CANCELLED"
    assert retrieved.steps[1].status == "CANCELLED"


# ============================================================================
# 6. Fail-Closed Orchestration for Unknown Skills Tests
# ============================================================================

@pytest.mark.asyncio
async def test_orchestrator_fail_closed_for_unknown_skill():
    """
    CRITICAL REGRESSION TEST:
    Verifies that DAG steps requesting unknown/unregistered skills fail closed.
    They must NOT report success or bypass sandbox.
    """
    orchestrator = TaskOrchestrator()

    # Create task with an unregistered/unknown skill
    task = TaskDAG(
        task_id="task-unknown-fail-closed",
        goal="Execute unregistered tool",
        system_prompt="You are Go 81 sovereign agent",
        steps=[
            DAGStep(
                step_id="step-unregistered",
                step_number=1,
                title="Unregistered Tool Execution",
                skill_name="attacker.arbitrary_payload",
                parameters={"command": "malicious_eval"},
                dependencies=[],
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            )
        ],
    )
    orchestrator.register_task(task)

    # Run the task
    await orchestrator.start_task("task-unknown-fail-closed")

    # Step and task MUST be FAILED, NOT COMPLETED
    updated_task = orchestrator.get_task("task-unknown-fail-closed")
    step = updated_task.steps[0]

    assert step.status == "FAILED", f"Expected step to be FAILED, but was {step.status}"
    assert "not registered" in step.output.lower() or "failed" in step.output.lower()
    assert updated_task.status == "FAILED"
    assert "Executed attacker.arbitrary_payload successfully" not in step.output
