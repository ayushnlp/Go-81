"""
Pydantic contracts and data models for Stage 3 Secure Skill Registry,
Execution Sandbox, and Deterministic Permission Gateway.
"""

import enum
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SkillRiskLevel(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SkillCategory(str, enum.Enum):
    SYSTEM = "system"
    FILESYSTEM = "filesystem"
    NETWORK = "network"
    COMMUNICATION = "communication"
    DEVELOPER = "developer"


class Capability(str, enum.Enum):
    FILESYSTEM_READ = "filesystem:read"
    FILESYSTEM_WRITE = "filesystem:write"
    NETWORK_HTTP = "network:http"
    SYSTEM_INFO = "system:info"
    MEMORY_SEARCH = "memory:search"
    SHELL_EXECUTE = "shell:execute"


class SkillParameter(BaseModel):
    name: str = Field(..., description="Parameter name identifier")
    type: str = Field(default="string", description="string, integer, boolean, number, object, array")
    description: str = Field(default="", description="Explanation of parameter purpose")
    required: bool = Field(default=True, description="Whether the parameter must be provided")
    default: Optional[Any] = Field(default=None, description="Default value if omitted")
    enum: Optional[List[Any]] = Field(default=None, description="Permitted enum values")
    min_value: Optional[float] = Field(default=None, description="Minimum numeric value")
    max_value: Optional[float] = Field(default=None, description="Maximum numeric value")
    pattern: Optional[str] = Field(default=None, description="Regex pattern constraint")


class FilesystemScope(BaseModel):
    allowed_roots: List[str] = Field(default_factory=list, description="Permitted root paths")
    allow_read: bool = Field(default=True)
    allow_write: bool = Field(default=False)
    max_file_size_bytes: int = Field(default=10 * 1024 * 1024, description="Max readable/writable file size")


class NetworkScope(BaseModel):
    allowed_hosts: List[str] = Field(default_factory=list, description="Whitelisted hostnames or IP addresses")
    allowed_ports: List[int] = Field(default_factory=lambda: [80, 443, 8000, 11434])
    allow_http: bool = Field(default=True)
    allow_https: bool = Field(default=True)


class ResourceLimits(BaseModel):
    timeout_seconds: float = Field(default=30.0, description="Maximum execution time in seconds")
    max_output_bytes: int = Field(default=64 * 1024, description="Maximum output size in bytes")
    max_memory_mb: int = Field(default=256, description="Memory budget in megabytes")


class RetryPolicy(BaseModel):
    is_idempotent: bool = Field(default=False, description="Whether skill is safe to retry on failure")
    max_retries: int = Field(default=0, description="Maximum retry attempts")
    backoff_seconds: float = Field(default=1.0)


class SkillDefinition(BaseModel):
    id: str = Field(..., description="Stable skill ID, e.g. filesystem.read")
    name: str = Field(..., description="Machine identifier")
    displayName: str = Field(..., description="Human-readable title")
    version: str = Field(default="1.0.0", description="Semantic version string")
    description: str = Field(default="", description="Detailed explanation of skill functionality")
    category: SkillCategory = Field(default=SkillCategory.SYSTEM)
    parameters: List[SkillParameter] = Field(default_factory=list)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    required_capabilities: List[str] = Field(default_factory=list)
    risk_level: SkillRiskLevel = Field(default=SkillRiskLevel.LOW)
    requires_approval: bool = Field(default=False)
    filesystem_scope: Optional[FilesystemScope] = None
    network_scope: Optional[NetworkScope] = None
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    isSandboxed: bool = Field(default=True)
    enabled: bool = Field(default=True)
    is_builtin: bool = Field(default=False)
    executionCount: int = Field(default=0)
    lastExecutedAt: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionContext(BaseModel):
    task_id: Optional[str] = None
    step_id: Optional[str] = None
    user_id: str = Field(default="default_user")
    correlation_id: Optional[str] = Field(default_factory=lambda: f"corr-{uuid.uuid4().hex[:10]}")
    project_root: Optional[str] = Field(default=None)
    approval_token: Optional[str] = None
    action_hash: Optional[str] = None
    caller_identity: str = Field(default="agent")
    environment: Dict[str, str] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    success: bool
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
    truncated: bool = False
    audit_id: Optional[str] = None


class AuthorizationDecision(BaseModel):
    allowed: bool
    reason: str
    approval_required: bool = False
    approval_id: Optional[str] = None
    action_hash: Optional[str] = None
    risk_level: SkillRiskLevel = SkillRiskLevel.LOW


class SkillAuditRecord(BaseModel):
    audit_id: str = Field(default_factory=lambda: f"aud-{uuid.uuid4().hex[:12]}")
    skill_id: str
    version: str
    action: str
    correlation_id: Optional[str] = None
    user_id: Optional[str] = None
    capabilities: List[str] = Field(default_factory=list)
    action_hash: Optional[str] = None
    policy_outcome: str
    approval_token: Optional[str] = None
    execution_status: Optional[str] = None
    duration_ms: Optional[float] = None
    error_message: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecuteSkillRequest(BaseModel):
    parameters: Dict[str, Any] = Field(default_factory=dict)
    approval_token: Optional[str] = None
    correlation_id: Optional[str] = None
    task_id: Optional[str] = None


class ProposeSkillRequest(BaseModel):
    skill_id: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    task_id: Optional[str] = None


class ProposeSkillResponse(BaseModel):
    skill_id: str
    action_hash: str
    risk_level: SkillRiskLevel
    requires_approval: bool
    approval_id: Optional[str] = None
    allowed: bool
    reason: str
