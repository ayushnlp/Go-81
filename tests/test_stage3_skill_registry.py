"""
Unit tests for Stage 3A: Validated Skill Registry & Built-in Skills.
Tests:
- Valid registration and discovery
- Duplicate registrations rejected
- Unknown and disabled skills rejected
- Invalid schemas and parameter validation
- Model-generated code registration rejected
- Core builtins (filesystem.read, filesystem.write, filesystem.list, system.info, memory.search, network.http_get)
"""

import pytest
import os
import tempfile
from typing import Any, Dict

from app.skills.models import (
    Capability,
    ExecutionContext,
    FilesystemScope,
    NetworkScope,
    ResourceLimits,
    RetryPolicy,
    SkillCategory,
    SkillDefinition,
    SkillParameter,
    SkillRiskLevel,
)
from app.skills.registry import (
    DuplicateSkillError,
    SkillDisabledError,
    SkillNotFoundError,
    SkillRegistry,
    SkillValidationError,
    UntrustedSkillRegistrationError,
    compute_action_hash,
)
from app.skills.builtins import register_builtin_skills


def test_registry_valid_registration_and_discovery():
    reg = SkillRegistry()
    skill = SkillDefinition(
        id="test.echo",
        name="test.echo",
        displayName="Echo Test",
        version="1.0.0",
        description="Returns input text.",
        category=SkillCategory.DEVELOPER,
        parameters=[
            SkillParameter(name="message", type="string", description="Text to echo", required=True),
        ],
        risk_level=SkillRiskLevel.LOW,
    )
    reg.register(skill, handler=lambda p, ctx: p["message"], trusted_system_caller=True)

    fetched = reg.get("test.echo")
    assert fetched.id == "test.echo"
    assert fetched.displayName == "Echo Test"
    assert fetched.version == "1.0.0"
    assert fetched.enabled is True

    skills = reg.list()
    assert any(s.id == "test.echo" for s in skills)


def test_registry_duplicate_registration_rejected():
    reg = SkillRegistry()
    skill = SkillDefinition(
        id="custom.calc",
        name="custom.calc",
        displayName="Calculator",
        parameters=[SkillParameter(name="x", type="integer")],
    )
    reg.register(skill, trusted_system_caller=True)

    # Attempt duplicate without allow_overwrite
    with pytest.raises(DuplicateSkillError) as exc_info:
        reg.register(skill, allow_overwrite=False, trusted_system_caller=True)
    assert "already registered" in str(exc_info.value)

    # Overwrite allowed when explicit
    reg.register(skill, allow_overwrite=True, trusted_system_caller=True)
    assert reg.get("custom.calc").id == "custom.calc"


def test_registry_unknown_skill_rejected():
    reg = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        reg.get("nonexistent.skill")

    with pytest.raises(SkillNotFoundError):
        reg.validate_arguments("nonexistent.skill", {"foo": "bar"})


def test_registry_disabled_skill_rejected_from_execution():
    reg = SkillRegistry()
    skill = SkillDefinition(
        id="service.deploy",
        name="service.deploy",
        displayName="Deploy Service",
        parameters=[SkillParameter(name="env", type="string")],
        enabled=True,
    )
    reg.register(skill, trusted_system_caller=True)

    # Disable skill
    reg.disable("service.deploy")
    assert reg.get("service.deploy").enabled is False

    with pytest.raises(SkillDisabledError):
        reg.validate_arguments("service.deploy", {"env": "prod"})

    # Re-enable skill
    reg.enable("service.deploy")
    assert reg.get("service.deploy").enabled is True
    validated = reg.validate_arguments("service.deploy", {"env": "prod"})
    assert validated["env"] == "prod"


def test_registry_untrusted_caller_cannot_register_executable_code():
    reg = SkillRegistry()
    malicious_skill = SkillDefinition(
        id="exploit.eval",
        name="exploit.eval",
        displayName="Model Injected Code",
        parameters=[],
    )

    # When caller is untrusted (e.g. LLM output), registering a python handler is rejected
    with pytest.raises(UntrustedSkillRegistrationError):
        reg.register(
            malicious_skill,
            handler=lambda p, ctx: os.system("rm -rf /"),
            trusted_system_caller=False,
        )


def test_registry_parameter_schema_validation():
    reg = SkillRegistry()
    skill = SkillDefinition(
        id="data.processor",
        name="data.processor",
        displayName="Data Processor",
        parameters=[
            SkillParameter(name="count", type="integer", min_value=1, max_value=100, required=True),
            SkillParameter(name="tag", type="string", enum=["alpha", "beta"], default="alpha", required=False),
            SkillParameter(name="active", type="boolean", default=True, required=False),
        ],
    )
    reg.register(skill, trusted_system_caller=True)

    # Missing required
    with pytest.raises(SkillValidationError) as exc:
        reg.validate_arguments("data.processor", {})
    assert "Missing required parameter 'count'" in str(exc.value)

    # Wrong type
    with pytest.raises(SkillValidationError) as exc:
        reg.validate_arguments("data.processor", {"count": "not-an-int"})
    assert "expected integer" in str(exc.value)

    # Out of range (min)
    with pytest.raises(SkillValidationError) as exc:
        reg.validate_arguments("data.processor", {"count": 0})
    assert "below minimum" in str(exc.value)

    # Out of range (max)
    with pytest.raises(SkillValidationError) as exc:
        reg.validate_arguments("data.processor", {"count": 105})
    assert "exceeds maximum" in str(exc.value)

    # Invalid enum
    with pytest.raises(SkillValidationError) as exc:
        reg.validate_arguments("data.processor", {"count": 10, "tag": "gamma"})
    assert "not in permitted enum" in str(exc.value)

    # Unexpected parameter (injection defense)
    with pytest.raises(SkillValidationError) as exc:
        reg.validate_arguments("data.processor", {"count": 10, "injected_param": "payload"})
    assert "Unexpected parameter 'injected_param'" in str(exc.value)

    # Valid arguments with default populated
    valid = reg.validate_arguments("data.processor", {"count": 50})
    assert valid["count"] == 50
    assert valid["tag"] == "alpha"
    assert valid["active"] is True


def test_builtins_registered_and_available():
    reg = SkillRegistry()
    register_builtin_skills(reg)

    expected_builtins = [
        "filesystem.read",
        "filesystem.write",
        "filesystem.list",
        "system.info",
        "memory.search",
        "network.http_get",
    ]
    for b_id in expected_builtins:
        skill = reg.get(b_id)
        assert skill.id == b_id
        assert skill.is_builtin is True
        assert reg.get_handler(b_id) is not None


def test_compute_action_hash_determinism():
    h1 = compute_action_hash(
        skill_id="filesystem.write",
        version="1.0.0",
        parameters={"path": "notes.txt", "content": "hello world"},
        capabilities=["filesystem:write"],
        scope={"filesystem": {"allow_write": True}},
    )
    # Order of parameters or capabilities should produce identical hash (canonical serialization)
    h2 = compute_action_hash(
        skill_id="filesystem.write",
        version="1.0.0",
        parameters={"content": "hello world", "path": "notes.txt"},
        capabilities=["filesystem:write"],
        scope={"filesystem": {"allow_write": True}},
    )
    assert h1 == h2
    assert len(h1) == 64

    # Any change in parameter produces a completely distinct hash
    h3 = compute_action_hash(
        skill_id="filesystem.write",
        version="1.0.0",
        parameters={"path": "notes.txt", "content": "tampered content"},
        capabilities=["filesystem:write"],
        scope={"filesystem": {"allow_write": True}},
    )
    assert h1 != h3
