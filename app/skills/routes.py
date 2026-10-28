"""
FastAPI Routes for Go 81 Secure Skill Registry & Execution Sandbox.
Exposes endpoints for skill discovery, execution, policy inspection,
and structured audit trail viewing.
"""

import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.memory.database import DatabaseManager
from app.skills.audit import SkillAuditLogger
from app.skills.gateway import SecurityPermissionGateway
from app.skills.models import (
    ExecutionContext,
    ExecutionResult,
    ExecuteSkillRequest,
    ProposeSkillRequest,
    ProposeSkillResponse,
    SkillAuditRecord,
    SkillDefinition,
    SkillRiskLevel,
)
from app.skills.registry import (
    DuplicateSkillError,
    SkillDisabledError,
    SkillNotFoundError,
    SkillRegistry,
    SkillValidationError,
    compute_action_hash,
    get_skill_registry,
)
from app.skills.sandbox import SkillExecutionSandbox

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["Skill Registry & Execution Sandbox"])

# Module-level singletons container for dependency injection
class SkillContainer:
    registry: Optional[SkillRegistry] = None
    gateway: Optional[SecurityPermissionGateway] = None
    sandbox: Optional[SkillExecutionSandbox] = None
    audit_logger: Optional[SkillAuditLogger] = None

    @classmethod
    def initialize(cls, db: DatabaseManager, project_root: str = ".") -> None:
        cls.registry = get_skill_registry()
        cls.audit_logger = SkillAuditLogger(db)
        cls.gateway = SecurityPermissionGateway(db, cls.registry)
        cls.sandbox = SkillExecutionSandbox(
            registry=cls.registry,
            gateway=cls.gateway,
            audit_logger=cls.audit_logger,
            default_project_root=project_root,
        )


def get_sandbox() -> SkillExecutionSandbox:
    if SkillContainer.sandbox is None:
        from app.api.routes import SubsystemContainer
        db = SubsystemContainer.db
        if db is None:
            db = DatabaseManager()
        SkillContainer.initialize(db)
    return SkillContainer.sandbox


def get_registry() -> SkillRegistry:
    if SkillContainer.registry is None:
        get_sandbox()
    return SkillContainer.registry


def get_gateway() -> SecurityPermissionGateway:
    if SkillContainer.gateway is None:
        get_sandbox()
    return SkillContainer.gateway


def get_audit_logger() -> SkillAuditLogger:
    if SkillContainer.audit_logger is None:
        get_sandbox()
    return SkillContainer.audit_logger


# ----------------------------------------------------------------------------
# 1. Skill Discovery & Management
# ----------------------------------------------------------------------------

@router.get("", response_model=List[SkillDefinition])
def list_skills(
    category: Optional[str] = Query(None, description="Filter by category"),
    enabled_only: bool = Query(False, description="Filter enabled skills only"),
) -> List[SkillDefinition]:
    """Lists all registered sovereign skills."""
    registry = get_registry()
    return registry.list(category=category, enabled_only=enabled_only)


@router.get("/{skill_id}", response_model=SkillDefinition)
def get_skill(skill_id: str) -> SkillDefinition:
    """Retrieves full definition and parameters for a specific registered skill."""
    registry = get_registry()
    try:
        return registry.get(skill_id)
    except SkillNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found.")


@router.post("/{skill_id}/enable", response_model=SkillDefinition)
def enable_skill(skill_id: str) -> SkillDefinition:
    """Enables a skill for execution."""
    registry = get_registry()
    try:
        return registry.enable(skill_id)
    except SkillNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found.")


@router.post("/{skill_id}/disable", response_model=SkillDefinition)
def disable_skill(skill_id: str) -> SkillDefinition:
    """Disables a skill from execution."""
    registry = get_registry()
    try:
        return registry.disable(skill_id)
    except SkillNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{skill_id}' not found.")


# ----------------------------------------------------------------------------
# 2. Skill Execution & Proposal
# ----------------------------------------------------------------------------

@router.post("/{skill_id}/execute", response_model=ExecutionResult)
async def execute_skill(skill_id: str, req: ExecuteSkillRequest) -> ExecutionResult:
    """
    Executes a registered skill within the security sandbox.
    Enforces parameter validation, permission gateway authorization, and resource bounding.
    """
    sandbox = get_sandbox()
    ctx = ExecutionContext(
        approval_token=req.approval_token,
        correlation_id=req.correlation_id or f"corr-{uuid.uuid4().hex[:10]}",
        task_id=req.task_id,
    )
    res = await sandbox.execute(skill_id=skill_id, parameters=req.parameters, context=ctx)
    if not res.success and "not registered" in (res.error or ""):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=res.error)
    return res


@router.post("/propose", response_model=ProposeSkillResponse)
def propose_skill(req: ProposeSkillRequest) -> ProposeSkillResponse:
    """
    Evaluates a proposed skill action without executing it.
    Validates arguments and returns the canonical action hash, risk level,
    and whether human approval is required.
    """
    registry = get_registry()
    gateway = get_gateway()

    try:
        skill = registry.get(req.skill_id)
    except SkillNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill '{req.skill_id}' not found.")

    try:
        validated_params = registry.validate_arguments(req.skill_id, req.parameters)
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    ctx = ExecutionContext(task_id=req.task_id)
    decision = gateway.authorize_skill_execution(
        skill_id=req.skill_id,
        validated_params=validated_params,
        context=ctx,
    )

    return ProposeSkillResponse(
        skill_id=req.skill_id,
        action_hash=decision.action_hash or "",
        risk_level=decision.risk_level,
        requires_approval=decision.approval_required,
        approval_id=decision.approval_id,
        allowed=decision.allowed,
        reason=decision.reason,
    )


# ----------------------------------------------------------------------------
# 3. Structured Audit Trail
# ----------------------------------------------------------------------------

@router.get("/audit/records", response_model=List[SkillAuditRecord])
def get_audit_records(
    limit: int = Query(50, ge=1, le=200),
    skill_id: Optional[str] = Query(None),
) -> List[SkillAuditRecord]:
    """Retrieves recent structured audit records for skill execution and authorization."""
    audit_logger = get_audit_logger()
    return audit_logger.get_recent_records(limit=limit, skill_id=skill_id)
