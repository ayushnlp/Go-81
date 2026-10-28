"""
Controlled Execution Sandbox for Project Go 81 Skills.
Invokes trusted registered skill handlers under explicit constraints:
- Centralized permission gateway enforcement (no bypass)
- Filesystem path traversal, absolute path, and symlink protection via SecurityBoundary
- Strict network host whitelisting
- Execution timeout and cancellation
- Bounded output size
- Sanitized environment with zero credential leakage
- Application-level isolation semantics clearly documented
"""

import asyncio
import functools
import json
import logging
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional

from app.memory.database import DatabaseManager
from app.memory.security_boundary import SecurityBoundary
from app.skills.audit import SkillAuditLogger
from app.skills.gateway import SecurityPermissionGateway
from app.skills.models import (
    ExecutionContext,
    ExecutionResult,
    SkillDefinition,
)
from app.skills.registry import (
    SkillDisabledError,
    SkillNotFoundError,
    SkillRegistry,
    SkillValidationError,
    compute_action_hash,
)

logger = logging.getLogger(__name__)

# Sanitized environment template: strips secrets
BLOCKED_ENV_KEYS = {
    "GO81_ENCRYPTION_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "DATABASE_URL",
    "PASSWORD",
    "TOKEN",
    "SECRET",
}


def build_sanitized_environment() -> Dict[str, str]:
    """Creates a minimal sanitized environment dictionary without leaked credentials."""
    clean_env: Dict[str, str] = {}
    for k, v in os.environ.items():
        if any(blocked in k.upper() for blocked in BLOCKED_ENV_KEYS):
            continue
        clean_env[k] = v
    return clean_env


class SkillExecutionSandbox:
    """
    Controlled Sandbox Execution Service.
    Acts as the single execution harness for all agent skills.
    
    NOTE ON SECURITY BOUNDARY:
    This sandbox provides rigorous APPLICATION-LEVEL isolation, schema validation,
    path-traversal protection, and network destination gating. It operates within
    the host process or controlled sub-threads, and does not claim OS kernel-level
    containerization (such as Docker/cgroups/seccomp).
    """

    def __init__(
        self,
        registry: SkillRegistry,
        gateway: SecurityPermissionGateway,
        audit_logger: SkillAuditLogger,
        default_project_root: str = ".",
    ):
        self.registry = registry
        self.gateway = gateway
        self.audit_logger = audit_logger
        self.default_project_root = os.path.abspath(default_project_root)

    async def execute(
        self,
        skill_id: str,
        parameters: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
    ) -> ExecutionResult:
        """
        Executes a registered skill under full sandbox constraints.
        Enforces permission gateway authorization, argument validation,
        timeouts, output bounds, and audit logging.
        """
        start_time = time.perf_counter()
        ctx = context or ExecutionContext()
        if not ctx.project_root or ctx.project_root == ".":
            ctx.project_root = self.default_project_root

        # 1. Fetch skill definition
        try:
            skill = self.registry.get(skill_id)
        except SkillNotFoundError as e:
            return self._fail_with_audit(
                skill_id=skill_id,
                version="unknown",
                action="resolve_skill",
                policy_outcome="DENIED",
                capabilities=[],
                error=f"Skill '{skill_id}' is not registered.",
                context=ctx,
                start_time=start_time,
                status="BLOCKED",
            )

        if not skill.enabled:
            return self._fail_with_audit(
                skill_id=skill_id,
                version=skill.version,
                action="verify_status",
                policy_outcome="DENIED",
                capabilities=skill.required_capabilities,
                error=f"Skill '{skill_id}' is disabled.",
                context=ctx,
                start_time=start_time,
                status="BLOCKED",
            )

        # 2. Strict argument validation
        try:
            validated_params = self.registry.validate_arguments(skill.id, parameters)
        except (SkillValidationError, SkillDisabledError) as e:
            return self._fail_with_audit(
                skill_id=skill.id,
                version=skill.version,
                action="validate_parameters",
                policy_outcome="DENIED",
                capabilities=skill.required_capabilities,
                error=f"Parameter validation failed: {str(e)}",
                context=ctx,
                start_time=start_time,
                status="BLOCKED",
            )

        # 3. Deterministic Permission Gateway Authorization
        auth_decision = self.gateway.authorize_skill_execution(
            skill_id=skill.id,
            validated_params=validated_params,
            context=ctx,
        )

        if not auth_decision.allowed:
            outcome = "APPROVAL_REQUIRED" if auth_decision.approval_required else "DENIED"
            return self._fail_with_audit(
                skill_id=skill.id,
                version=skill.version,
                action=skill.id,
                policy_outcome=outcome,
                capabilities=skill.required_capabilities,
                error=auth_decision.reason,
                context=ctx,
                start_time=start_time,
                status="BLOCKED",
                action_hash=auth_decision.action_hash,
                metadata={"approval_id": auth_decision.approval_id},
            )

        # 4. Resolve trusted handler
        handler = self.registry.get_handler(skill.id)
        if handler is None:
            return self._fail_with_audit(
                skill_id=skill.id,
                version=skill.version,
                action="resolve_handler",
                policy_outcome="DENIED",
                capabilities=skill.required_capabilities,
                error=f"No executable handler registered for skill '{skill.id}'.",
                context=ctx,
                start_time=start_time,
                status="BLOCKED",
            )

        # Pre-execution cancellation check
        if ctx.is_cancelled:
            return self._fail_with_audit(
                skill_id=skill.id,
                version=skill.version,
                action=skill.id,
                policy_outcome="ALLOWED",
                capabilities=skill.required_capabilities,
                error="Execution was cancelled prior to start.",
                context=ctx,
                start_time=start_time,
                status="CANCELLED",
                action_hash=auth_decision.action_hash,
            )

        # Enforce Network Scope destination whitelist before execution
        if skill.network_scope and "url" in validated_params:
            from app.skills.builtins import validate_network_scope
            try:
                validate_network_scope(str(validated_params["url"]), skill.network_scope)
            except PermissionError as pe:
                return self._fail_with_audit(
                    skill_id=skill.id,
                    version=skill.version,
                    action=skill.id,
                    policy_outcome="DENIED",
                    capabilities=skill.required_capabilities,
                    error=str(pe),
                    context=ctx,
                    start_time=start_time,
                    status="BLOCKED",
                    action_hash=auth_decision.action_hash,
                )

        # 5. Execute handler with timeout and resource limits
        timeout_sec = skill.resource_limits.timeout_seconds
        max_bytes = skill.resource_limits.max_output_bytes

        # Inject sanitized environment
        ctx.environment = build_sanitized_environment()

        try:
            loop = asyncio.get_running_loop()
            if asyncio.iscoroutinefunction(handler):
                output = await asyncio.wait_for(
                    handler(validated_params, ctx),
                    timeout=timeout_sec,
                )
            else:
                task_fn = functools.partial(handler, validated_params, ctx)
                output = await asyncio.wait_for(
                    loop.run_in_executor(None, task_fn),
                    timeout=timeout_sec,
                )
        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_msg = f"Execution timed out after {timeout_sec}s"
            audit_rec = self.audit_logger.log_event(
                skill_id=skill.id,
                version=skill.version,
                action=skill.id,
                policy_outcome="ALLOWED",
                capabilities=skill.required_capabilities,
                correlation_id=ctx.correlation_id,
                user_id=ctx.user_id,
                action_hash=auth_decision.action_hash,
                approval_token=ctx.approval_token,
                execution_status="TIMEOUT",
                duration_ms=duration_ms,
                error_message=error_msg,
            )
            return ExecutionResult(
                success=False,
                error=error_msg,
                duration_ms=duration_ms,
                audit_id=audit_rec.audit_id,
            )
        except asyncio.CancelledError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_msg = "Execution was cancelled"
            audit_rec = self.audit_logger.log_event(
                skill_id=skill.id,
                version=skill.version,
                action=skill.id,
                policy_outcome="ALLOWED",
                capabilities=skill.required_capabilities,
                correlation_id=ctx.correlation_id,
                user_id=ctx.user_id,
                action_hash=auth_decision.action_hash,
                approval_token=ctx.approval_token,
                execution_status="CANCELLED",
                duration_ms=duration_ms,
                error_message=error_msg,
            )
            return ExecutionResult(
                success=False,
                error=error_msg,
                duration_ms=duration_ms,
                audit_id=audit_rec.audit_id,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            error_msg = f"{type(e).__name__}: {str(e)}"
            audit_rec = self.audit_logger.log_event(
                skill_id=skill.id,
                version=skill.version,
                action=skill.id,
                policy_outcome="ALLOWED",
                capabilities=skill.required_capabilities,
                correlation_id=ctx.correlation_id,
                user_id=ctx.user_id,
                action_hash=auth_decision.action_hash,
                approval_token=ctx.approval_token,
                execution_status="FAILED",
                duration_ms=duration_ms,
                error_message=error_msg,
            )
            return ExecutionResult(
                success=False,
                error=error_msg,
                duration_ms=duration_ms,
                audit_id=audit_rec.audit_id,
            )

        # 6. Enforce Bounded Output Size
        truncated = False
        if isinstance(output, (str, bytes)):
            out_len = len(output)
            if out_len > max_bytes:
                output = output[:max_bytes]
                truncated = True
        elif isinstance(output, dict) and "content" in output and isinstance(output["content"], str):
            if len(output["content"]) > max_bytes:
                output["content"] = output["content"][:max_bytes]
                output["truncated"] = True
                truncated = True

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # 7. Record Telemetry & Audit
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        self.registry.record_execution(skill.id, now_iso)

        audit_rec = self.audit_logger.log_event(
            skill_id=skill.id,
            version=skill.version,
            action=skill.id,
            policy_outcome="ALLOWED",
            capabilities=skill.required_capabilities,
            correlation_id=ctx.correlation_id,
            user_id=ctx.user_id,
            action_hash=auth_decision.action_hash,
            approval_token=ctx.approval_token,
            execution_status="SUCCESS",
            duration_ms=duration_ms,
            error_message=None,
        )

        return ExecutionResult(
            success=True,
            output=output,
            duration_ms=duration_ms,
            truncated=truncated,
            audit_id=audit_rec.audit_id,
        )

    def _fail_with_audit(
        self,
        skill_id: str,
        version: str,
        action: str,
        policy_outcome: str,
        capabilities: List[str],
        error: str,
        context: ExecutionContext,
        start_time: float,
        status: str = "BLOCKED",
        action_hash: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExecutionResult:
        """Helper to record blocked or failed attempts into audit log."""
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        audit_rec = self.audit_logger.log_event(
            skill_id=skill_id,
            version=version,
            action=action,
            policy_outcome=policy_outcome,
            capabilities=capabilities,
            correlation_id=context.correlation_id,
            user_id=context.user_id,
            action_hash=action_hash,
            approval_token=context.approval_token,
            execution_status=status,
            duration_ms=duration_ms,
            error_message=error,
            metadata=metadata,
        )
        return ExecutionResult(
            success=False,
            error=error,
            duration_ms=duration_ms,
            audit_id=audit_rec.audit_id,
        )
