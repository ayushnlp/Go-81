"""
Secure Plan Validation for Project Go 81.
Validates structured task execution plans against the Stage 3 SkillRegistry,
PermissionGateway default-deny policies, argument schemas, and canonical action hashes.
"""

import logging
from typing import Any, Dict, List, Optional, Set

from app.memory.models import RiskLevel
from app.skills.models import (
    Capability,
    FilesystemScope,
    NetworkScope,
    SkillDefinition,
    SkillRiskLevel,
)
from app.skills.registry import (
    SkillDisabledError,
    SkillNotFoundError,
    SkillRegistry,
    SkillValidationError,
    compute_action_hash,
)
from backend.dag_validator import validate_dag_structure

logger = logging.getLogger(__name__)


class PlanSecurityError(Exception):
    """Raised when a generated plan violates security policies or skill constraints."""
    pass


class UnknownSkillPlanError(PlanSecurityError):
    """Raised when a plan references a skill not registered in the SkillRegistry."""
    pass


class DisabledSkillPlanError(PlanSecurityError):
    """Raised when a plan references a disabled skill."""
    pass


class InvalidPlanParameterError(PlanSecurityError):
    """Raised when plan step parameters violate the skill's parameter schema."""
    pass


class MissingSkillHandlerError(PlanSecurityError):
    """Raised when a registered skill lacks an executable handler."""
    pass


def map_skill_risk_to_model_risk(risk: SkillRiskLevel) -> RiskLevel:
    """Maps Stage 3 SkillRiskLevel to memory/planner RiskLevel enum."""
    if risk == SkillRiskLevel.CRITICAL:
        return RiskLevel.CRITICAL
    elif risk == SkillRiskLevel.HIGH:
        return RiskLevel.HIGH
    elif risk == SkillRiskLevel.MEDIUM:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def validate_plan_against_security(
    dag: Any,
    registry: SkillRegistry,
    max_steps: int = 50,
    max_deps_per_step: int = 10,
) -> Any:
    """
    Validates a complete TaskDAG before execution against the system SkillRegistry:
    1. Validates structural DAG integrity (cycles, self-dependencies, unknown dependencies).
    2. Validates that every skill is registered in SkillRegistry.
    3. Validates that every skill is currently enabled.
    4. Validates that an executable handler exists for each skill.
    5. Validates and sanitizes step parameters against parameter schemas.
    6. Verifies declared capabilities.
    7. Enforces approval requirements for high-risk / sensitive skills.
    8. Computes canonical action hashes for each step.
    9. Populates DAG metadata (required_skills, required_capabilities, effective_risk, execution_order).
    """
    steps = getattr(dag, "steps", [])
    if not steps:
        return dag

    # Step 1: Structural DAG validation
    topological_order = validate_dag_structure(
        steps,
        max_steps=max_steps,
        max_deps_per_step=max_deps_per_step,
    )
    if hasattr(dag, "execution_order"):
        dag.execution_order = topological_order

    required_skills: Set[str] = set()
    required_capabilities: Set[str] = set()
    highest_risk_weight = 0
    risk_weights = {
        SkillRiskLevel.LOW: 1,
        SkillRiskLevel.MEDIUM: 2,
        SkillRiskLevel.HIGH: 3,
        SkillRiskLevel.CRITICAL: 4,
    }
    highest_skill_risk = SkillRiskLevel.LOW

    sensitive_caps = {
        Capability.FILESYSTEM_WRITE.value,
        Capability.NETWORK_HTTP.value,
        Capability.SHELL_EXECUTE.value,
    }

    # Step 2-8: Validate each step
    for step in steps:
        skill_id = getattr(step, "skill_name", None) or getattr(step, "skill_id", None)
        if not skill_id or not str(skill_id).strip():
            raise PlanSecurityError(f"Step '{getattr(step, 'step_id', 'unknown')}' does not declare a skill_name.")

        skill_id = str(skill_id).strip()

        # 1. Resolve registered skill definition (public interface only)
        try:
            skill = registry.get(skill_id)
        except SkillNotFoundError:
            raise UnknownSkillPlanError(
                f"Step '{step.step_id}' references unregistered skill '{skill_id}'. "
                "All planned actions must correspond to approved, registered system skills."
            )

        # 2. Check enabled status
        if not skill.enabled:
            raise DisabledSkillPlanError(
                f"Step '{step.step_id}' targets skill '{skill_id}' which is currently disabled."
            )

        # 3. Check handler exists
        handler = registry.get_handler(skill_id)
        if handler is None:
            raise MissingSkillHandlerError(
                f"Step '{step.step_id}' targets skill '{skill_id}' which lacks an executable handler."
            )

        # 4. Validate and sanitize parameters against schema
        raw_params = getattr(step, "parameters", {}) or {}
        try:
            validated_params = registry.validate_arguments(skill_id, raw_params)
            step.parameters = validated_params
        except SkillValidationError as e:
            raise InvalidPlanParameterError(
                f"Step '{step.step_id}' parameter validation failed for skill '{skill_id}': {e}"
            )
        except SkillDisabledError:
            raise DisabledSkillPlanError(f"Skill '{skill_id}' is disabled.")

        # 5. Check declared capabilities
        valid_caps = {c.value for c in Capability}
        for cap in skill.required_capabilities:
            if cap not in valid_caps:
                raise PlanSecurityError(
                    f"Skill '{skill_id}' requires unrecognized capability '{cap}' under default-deny policy."
                )
            required_capabilities.add(cap)

        required_skills.add(skill_id)

        # 6. Evaluate risk level and approval requirement
        needs_approval = (
            skill.requires_approval
            or skill.risk_level in (SkillRiskLevel.HIGH, SkillRiskLevel.CRITICAL)
            or any(c in sensitive_caps for c in skill.required_capabilities)
        )
        step.requires_approval = bool(needs_approval or getattr(step, "requires_approval", False))
        step.risk_level = map_skill_risk_to_model_risk(skill.risk_level)

        if risk_weights.get(skill.risk_level, 1) > highest_risk_weight:
            highest_risk_weight = risk_weights[skill.risk_level]
            highest_skill_risk = skill.risk_level

        # 7. Compute canonical action hash
        scope: Dict[str, Any] = {}
        if skill.filesystem_scope:
            scope["filesystem"] = skill.filesystem_scope.model_dump()
        if skill.network_scope:
            scope["network"] = skill.network_scope.model_dump()

        action_hash = compute_action_hash(
            skill_id=skill.id,
            version=skill.version,
            parameters=step.parameters,
            capabilities=skill.required_capabilities,
            scope=scope,
        )
        if hasattr(step, "action_hash"):
            step.action_hash = action_hash

    # Populate DAG-level security metadata
    if hasattr(dag, "required_skills"):
        dag.required_skills = sorted(list(required_skills))
    if hasattr(dag, "required_capabilities"):
        dag.required_capabilities = sorted(list(required_capabilities))
    if hasattr(dag, "effective_risk"):
        dag.effective_risk = map_skill_risk_to_model_risk(highest_skill_risk)

    return dag

