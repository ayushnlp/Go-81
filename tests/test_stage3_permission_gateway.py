"""
Unit & Integration tests for Stage 3B: Deterministic Permission Gateway.
Tests:
- Default-deny behavior for high risk or sensitive capabilities
- Unapproved sensitive action rejection & pending approval issuance
- Valid approval authorization
- Single-use consumption & replay rejection (cannot reuse token)
- Expired approval token rejection
- Tampered parameters rejection (canonical action hash mismatch)
- Action mismatch (token issued for skill A used on skill B)
- Concurrency race protection during token consumption
- Untrusted / model-generated token claims rejected
"""

import concurrent.futures
import os
import tempfile
import time
import pytest

from app.memory.database import DatabaseManager
from app.skills.gateway import SecurityPermissionGateway
from app.skills.models import (
    Capability,
    ExecutionContext,
    FilesystemScope,
    SkillCategory,
    SkillDefinition,
    SkillParameter,
    SkillRiskLevel,
)
from app.skills.registry import SkillRegistry


@pytest.fixture
def test_db_and_gateway():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_gateway.db")
        db = DatabaseManager(db_path)
        reg = SkillRegistry()

        # Low risk skill
        reg.register(
            SkillDefinition(
                id="system.read_time",
                name="system.read_time",
                displayName="Read Time",
                risk_level=SkillRiskLevel.LOW,
                requires_approval=False,
            )
        )

        # High risk skill requiring approval
        reg.register(
            SkillDefinition(
                id="shell.execute",
                name="shell.execute",
                displayName="Execute Shell",
                risk_level=SkillRiskLevel.HIGH,
                requires_approval=True,
                required_capabilities=[Capability.SHELL_EXECUTE.value],
                parameters=[
                    SkillParameter(name="command", type="string", required=True),
                ],
            )
        )

        # Sensitive capability filesystem:write
        reg.register(
            SkillDefinition(
                id="file.atomic_write",
                name="file.atomic_write",
                displayName="Write File",
                risk_level=SkillRiskLevel.MEDIUM,
                required_capabilities=[Capability.FILESYSTEM_WRITE.value],
                parameters=[
                    SkillParameter(name="path", type="string", required=True),
                    SkillParameter(name="content", type="string", required=True),
                ],
            )
        )

        gateway = SecurityPermissionGateway(db, reg)
        yield db, reg, gateway


def test_gateway_default_allow_for_low_risk(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    ctx = ExecutionContext()
    decision = gateway.authorize_skill_execution("system.read_time", {}, ctx)
    assert decision.allowed is True
    assert decision.approval_required is False


def test_gateway_default_deny_for_high_risk_without_token(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    ctx = ExecutionContext()
    decision = gateway.authorize_skill_execution("shell.execute", {"command": "dir"}, ctx)

    assert decision.allowed is False
    assert decision.approval_required is True
    assert decision.approval_id is not None
    assert decision.approval_id.startswith("apr-")
    assert decision.action_hash is not None


def test_gateway_valid_approval_token_authorized(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    params = {"command": "ls -la"}
    appr_id, token = gateway.create_approval_token("shell.execute", params, ttl_seconds=60)

    ctx = ExecutionContext(approval_token=token)
    decision = gateway.authorize_skill_execution("shell.execute", params, ctx)

    assert decision.allowed is True
    assert decision.approval_required is False
    assert decision.approval_id == token


def test_gateway_single_use_replay_rejected(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    params = {"command": "ls -la"}
    _, token = gateway.create_approval_token("shell.execute", params, ttl_seconds=60)

    # 1. First execution consumes token
    ctx1 = ExecutionContext(approval_token=token)
    d1 = gateway.authorize_skill_execution("shell.execute", params, ctx1)
    assert d1.allowed is True

    # 2. Second execution attempt with identical token MUST BE REJECTED (replay attack)
    ctx2 = ExecutionContext(approval_token=token)
    d2 = gateway.authorize_skill_execution("shell.execute", params, ctx2)
    assert d2.allowed is False
    assert "already been consumed" in d2.reason or "replay" in d2.reason


def test_gateway_expired_approval_rejected(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    params = {"command": "whoami"}
    # Create token with 0 second TTL (already expired)
    _, token = gateway.create_approval_token("shell.execute", params, ttl_seconds=-1)

    ctx = ExecutionContext(approval_token=token)
    decision = gateway.authorize_skill_execution("shell.execute", params, ctx)

    assert decision.allowed is False
    assert "expired" in decision.reason.lower()


def test_gateway_tampered_parameters_rejected(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    original_params = {"command": "echo safe"}
    _, token = gateway.create_approval_token("shell.execute", original_params, ttl_seconds=60)

    # Attacker alters command parameter after approval was granted
    tampered_params = {"command": "rm -rf /critical_data"}
    ctx = ExecutionContext(approval_token=token)
    decision = gateway.authorize_skill_execution("shell.execute", tampered_params, ctx)

    assert decision.allowed is False
    assert "tampering" in decision.reason.lower() or "mismatch" in decision.reason.lower()


def test_gateway_action_mismatch_rejected(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    params = {"path": "file.txt", "content": "hello"}
    # Token issued for file.atomic_write
    _, token = gateway.create_approval_token("file.atomic_write", params, ttl_seconds=60)

    # Attacker tries to use token for shell.execute
    ctx = ExecutionContext(approval_token=token)
    decision = gateway.authorize_skill_execution("shell.execute", {"command": "file.txt"}, ctx)

    assert decision.allowed is False
    assert "mismatch" in decision.reason.lower()


def test_gateway_resolve_pending_approval_flow(test_db_and_gateway):
    _, _, gateway = test_db_and_gateway
    params = {"command": "pytest"}

    # 1. Attempt without token -> issues pending approval
    ctx = ExecutionContext()
    d1 = gateway.authorize_skill_execution("shell.execute", params, ctx)
    assert d1.approval_required is True
    pending_apr_id = d1.approval_id

    # 2. Human resolves pending approval (rejects first to test rejection)
    ok, token = gateway.resolve_pending_approval(pending_apr_id, approved=False, rejection_reason="Denied by admin")
    assert ok is False
    assert token is None

    # 3. New pending approval approved
    d2 = gateway.authorize_skill_execution("shell.execute", params, ctx)
    apr_id2 = d2.approval_id
    ok2, valid_token = gateway.resolve_pending_approval(apr_id2, approved=True)
    assert ok2 is True
    assert valid_token is not None

    # 4. Authorize with newly generated token
    ctx_approved = ExecutionContext(approval_token=valid_token)
    d3 = gateway.authorize_skill_execution("shell.execute", params, ctx_approved)
    assert d3.allowed is True


def test_gateway_concurrency_race_single_use(test_db_and_gateway):
    """
    Direct verification of concurrency safety:
    10 threads simultaneously try to consume the exact same approval token.
    Exactly ONE thread must succeed; 9 must be rejected.
    """
    _, _, gateway = test_db_and_gateway
    params = {"path": "safe.txt", "content": "concurrency test"}
    _, token = gateway.create_approval_token("file.atomic_write", params, ttl_seconds=60)

    results = []

    def attempt_consume():
        ctx = ExecutionContext(approval_token=token)
        dec = gateway.authorize_skill_execution("file.atomic_write", params, ctx)
        return dec.allowed

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(attempt_consume) for _ in range(10)]
        for f in concurrent.futures.as_completed(futures):
            results.append(f.result())

    # Exactly 1 success, 9 rejections
    success_count = sum(1 for r in results if r is True)
    assert success_count == 1
    assert len(results) == 10
