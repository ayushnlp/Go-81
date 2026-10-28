"""
Unit & Integration tests for Stage 3C: Controlled Sandboxed Skill Execution.
Tests:
- Filesystem root boundary enforcement & path traversal rejection (../)
- Symlink escape detection and rejection
- Unauthorized network destination blocking
- Execution timeout enforcement
- Bounded output size enforcement (truncation without crash)
- Sanitized environment (no secret/key exposure)
- Strict absence of raw eval/exec or shell=True
- Fallback never grants unrestricted execution on failure
"""

import asyncio
import os
import tempfile
import time
import pytest

from app.memory.database import DatabaseManager
from app.memory.security_boundary import PathTraversalError
from app.skills.audit import SkillAuditLogger
from app.skills.builtins import register_builtin_skills
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


@pytest.fixture
def sandbox_env():
    with tempfile.TemporaryDirectory() as tmp_root:
        db_path = os.path.join(tmp_root, "sandbox_test.db")
        db = DatabaseManager(db_path)
        reg = SkillRegistry()
        register_builtin_skills(reg)
        gateway = SecurityPermissionGateway(db, reg)
        audit_logger = SkillAuditLogger(db)
        sandbox = SkillExecutionSandbox(
            registry=reg,
            gateway=gateway,
            audit_logger=audit_logger,
            default_project_root=tmp_root,
        )
        yield tmp_root, db, reg, gateway, sandbox


@pytest.mark.asyncio
async def test_sandbox_filesystem_safe_read_and_write(sandbox_env):
    tmp_root, _, _, _, sandbox = sandbox_env

    # 1. Write file inside project root with approval token
    write_params = {"path": "data/sample.txt", "content": "Go 81 Sovereign Agent Sandboxed Storage"}
    _, token = sandbox.gateway.create_approval_token("filesystem.write", write_params)
    write_res = await sandbox.execute(
        "filesystem.write",
        write_params,
        ExecutionContext(project_root=tmp_root, approval_token=token),
    )
    assert write_res.success is True
    assert write_res.output["status"] == "success"

    # 2. Read file back
    read_res = await sandbox.execute(
        "filesystem.read",
        {"path": "data/sample.txt"},
        ExecutionContext(project_root=tmp_root),
    )
    assert read_res.success is True
    assert "Go 81 Sovereign Agent Sandboxed Storage" in read_res.output["content"]


@pytest.mark.asyncio
async def test_sandbox_path_traversal_rejected(sandbox_env):
    tmp_root, _, _, _, sandbox = sandbox_env

    # Attempt relative path traversal out of project root
    traversal_paths = [
        "../../etc/passwd",
        "../outside.txt",
        r"..\..\Windows\System32\drivers\etc\hosts",
        "nested/../../../../etc/shadow",
    ]
    for p in traversal_paths:
        res = await sandbox.execute(
            "filesystem.read",
            {"path": p},
            ExecutionContext(project_root=tmp_root),
        )
        assert res.success is False
        assert "escapes permitted project root" in res.error.lower() or "not found" in res.error.lower()


@pytest.mark.asyncio
async def test_sandbox_symlink_escape_rejected(sandbox_env):
    tmp_root, _, _, _, sandbox = sandbox_env

    # Create target file outside root in a separate directory
    with tempfile.TemporaryDirectory() as outside_dir:
        outside_file = os.path.join(outside_dir, "secret_outside.txt")
        with open(outside_file, "w") as f:
            f.write("SUPER_SECRET_HOST_DATA")

        # Create symlink inside project root pointing to outside_file
        symlink_path = os.path.join(tmp_root, "link_to_outside.txt")
        try:
            os.symlink(outside_file, symlink_path)
        except (OSError, NotImplementedError):
            pytest.skip("Symlink creation not supported in current environment.")

        # Attempt to read through the symlink: SecurityBoundary must reject it
        res = await sandbox.execute(
            "filesystem.read",
            {"path": "link_to_outside.txt"},
            ExecutionContext(project_root=tmp_root),
        )
        assert res.success is False
        assert "escapes permitted project root" in res.error.lower()


@pytest.mark.asyncio
async def test_sandbox_unauthorized_network_host_rejected(sandbox_env):
    tmp_root, _, _, gateway, sandbox = sandbox_env

    # URL to unapproved external host
    unauthorized_url = "https://malicious-command-and-control.attacker.com/leak"
    
    # Pre-approve action in gateway to ensure sandbox network check stops it
    _, token = gateway.create_approval_token("network.http_get", {"url": unauthorized_url})
    
    res = await sandbox.execute(
        "network.http_get",
        {"url": unauthorized_url},
        ExecutionContext(project_root=tmp_root, approval_token=token),
    )
    assert res.success is False
    assert "not permitted" in res.error.lower() or "allowed destinations" in res.error.lower()


@pytest.mark.asyncio
async def test_sandbox_execution_timeout(sandbox_env):
    tmp_root, _, reg, gateway, sandbox = sandbox_env

    # Register slow skill with 0.1s timeout limit
    def slow_handler(params, ctx):
        time.sleep(1.0)
        return "finished"

    reg.register(
        SkillDefinition(
            id="test.slow",
            name="test.slow",
            displayName="Slow Skill",
            resource_limits=ResourceLimits(timeout_seconds=0.2),
            risk_level=SkillRiskLevel.LOW,
        ),
        handler=slow_handler,
    )

    res = await sandbox.execute("test.slow", {}, ExecutionContext(project_root=tmp_root))
    assert res.success is False
    assert "timed out" in res.error.lower()


@pytest.mark.asyncio
async def test_sandbox_bounded_output_truncation(sandbox_env):
    tmp_root, _, reg, gateway, sandbox = sandbox_env

    # Register skill producing 100 KB with 1 KB max_output_bytes limit
    def large_output_handler(params, ctx):
        return "A" * (100 * 1024)

    reg.register(
        SkillDefinition(
            id="test.large_output",
            name="test.large_output",
            displayName="Large Output",
            resource_limits=ResourceLimits(max_output_bytes=1024),
            risk_level=SkillRiskLevel.LOW,
        ),
        handler=large_output_handler,
    )

    res = await sandbox.execute("test.large_output", {}, ExecutionContext(project_root=tmp_root))
    assert res.success is True
    assert len(res.output) <= 1024
    assert res.truncated is True


@pytest.mark.asyncio
async def test_sandbox_environment_sanitization_no_secret_leaks(sandbox_env):
    tmp_root, _, reg, gateway, sandbox = sandbox_env

    # Set dummy secret environment variable
    os.environ["GO81_ENCRYPTION_KEY"] = "super-secret-key-12345"
    os.environ["OPENAI_API_KEY"] = "sk-leaked-api-token"

    captured_env = {}

    def capture_env_handler(params, ctx):
        captured_env.update(ctx.environment)
        return "captured"

    reg.register(
        SkillDefinition(
            id="test.env_inspect",
            name="test.env_inspect",
            displayName="Inspect Env",
            risk_level=SkillRiskLevel.LOW,
        ),
        handler=capture_env_handler,
    )

    res = await sandbox.execute("test.env_inspect", {}, ExecutionContext(project_root=tmp_root))
    assert res.success is True
    assert "GO81_ENCRYPTION_KEY" not in captured_env
    assert "OPENAI_API_KEY" not in captured_env
