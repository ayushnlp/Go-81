"""
Pydantic data models and schemas for Go 81 Memory & Security Subsystem.
Strictly local-first, zero-leak design.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field


def utc_now_iso() -> str:
    """Returns current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# Enums
# ============================================================================

class MemoryType(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"


class VerificationStatus(str, Enum):
    USER_PROVIDED = "user_provided"
    VERIFIED = "verified"
    INFERRED = "inferred"
    UNVERIFIED = "unverified"


class SemanticCategory(str, Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    PROJECT_CONTEXT = "project_context"
    HEURISTIC = "heuristic"


class EpisodicEventType(str, Enum):
    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TOOL_EXECUTION = "tool_execution"
    SYSTEM_EVENT = "system_event"
    TASK_OUTCOME = "task_outcome"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REQUIRES_RECONCILIATION = "REQUIRES_RECONCILIATION"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ============================================================================
# Memory Payloads & Records
# ============================================================================

class EpisodicPayload(BaseModel):
    """Payload for episodic memory events."""
    session_id: str = Field(..., description="Active session or conversation ID")
    event_type: str = Field(..., description="Category of event (e.g. user_message, tool_execution)")
    content: Dict[str, Any] = Field(..., description="Detailed event content, thoughts, inputs, outputs")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary contextual metadata")


class SemanticPayload(BaseModel):
    """Payload for semantic structured facts."""
    category: SemanticCategory = Field(..., description="Fact classification")
    subject: str = Field(..., description="Subject / entity")
    predicate: str = Field(..., description="Relation / attribute")
    object_value: Any = Field(..., description="Value (string, number, or JSON object)")
    context: Dict[str, Any] = Field(default_factory=dict, description="Contextual origin details")


class MemoryRecord(BaseModel):
    """
    Decrypted in-memory representation of any memory record (episodic or semantic).
    Plaintext is only materialized in process memory and never written unencrypted to disk.
    """
    id: str = Field(..., description="Stable UUID v4 identifier")
    memory_type: MemoryType = Field(..., description="episodic or semantic")
    category: Optional[str] = Field(None, description="Semantic category or episodic event type")
    verification_status: VerificationStatus = Field(
        default=VerificationStatus.UNVERIFIED,
        description="Provenance confidence rating"
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0,
        description="Confidence score for inferred facts"
    )
    dedup_hash: Optional[str] = Field(
        None, description="Deterministic SHA-256 hash for deduplication"
    )
    source_ref: Optional[str] = Field(
        None, description="Provenance reference (e.g. 'chat', 'tool', 'file')"
    )
    schema_version: int = Field(default=1, description="Payload schema version")
    project_id: Optional[str] = Field(None, description="Project scope reference")
    payload: Dict[str, Any] = Field(..., description="Decrypted payload content")
    created_at: str = Field(default_factory=utc_now_iso, description="UTC ISO-8601 creation timestamp")
    updated_at: str = Field(default_factory=utc_now_iso, description="UTC ISO-8601 update timestamp")
    expires_at: Optional[str] = Field(None, description="UTC ISO-8601 expiration timestamp, if any")
    is_deleted: bool = Field(default=False, description="Tombstone flag")


# Specific convenience views
class EpisodicEvent(BaseModel):
    id: str
    session_id: str
    event_type: str
    content: Dict[str, Any]
    source_ref: Optional[str] = None
    created_at: str
    expires_at: Optional[str] = None
    is_deleted: bool = False


class SemanticMemory(BaseModel):
    id: str
    category: SemanticCategory
    subject: str
    predicate: str
    object_value: Any
    verification_status: VerificationStatus
    confidence: float
    dedup_hash: str
    source_ref: Optional[str] = None
    created_at: str
    updated_at: str
    expires_at: Optional[str] = None
    is_deleted: bool = False


# ============================================================================
# Request / Input Schemas
# ============================================================================

class EventCreate(BaseModel):
    """Input contract for storing an episodic event."""
    session_id: str = Field(..., description="Active session ID")
    event_type: str = Field(default="user_message", description="Event type")
    content: Dict[str, Any] = Field(..., description="Event content dictionary")
    project_id: Optional[str] = Field(None, description="Optional project scope reference")
    source_ref: Optional[str] = Field(None, description="Origin source reference")
    ttl_seconds: Optional[int] = Field(None, description="Retention time-to-live in seconds")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class SemanticMemoryCreate(BaseModel):
    """Input contract for storing a semantic memory."""
    category: SemanticCategory = Field(default=SemanticCategory.FACT)
    subject: str = Field(..., description="Entity or topic the fact describes")
    predicate: str = Field(..., description="Relation or property name")
    object_value: Any = Field(..., description="Target value or structured data")
    project_id: Optional[str] = Field(None, description="Optional project scope reference")
    verification_status: VerificationStatus = Field(default=VerificationStatus.USER_PROVIDED)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_ref: Optional[str] = Field(None, description="Origin source reference")
    ttl_seconds: Optional[int] = Field(None, description="Optional TTL in seconds")


class MemoryUpdate(BaseModel):
    """Input contract for editing an existing semantic or episodic memory."""
    object_value: Optional[Any] = Field(None, description="New object value")
    verification_status: Optional[VerificationStatus] = Field(None)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    content: Optional[Dict[str, Any]] = Field(None, description="New content for episodic record")


class MemorySearchQuery(BaseModel):
    """Request model for memory search."""
    query: Optional[str] = Field(None, description="Keyword search string")
    project_id: Optional[str] = Field(None, description="Filter by project scope")
    memory_type: Optional[MemoryType] = Field(None, description="Filter by episodic or semantic")
    category: Optional[str] = Field(None, description="Filter by category")
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    include_expired: bool = Field(default=False, description="Whether to include expired records")


class MemoryExport(BaseModel):
    """Schema for exported memories."""
    exported_at: str = Field(default_factory=utc_now_iso)
    total_records: int
    records: List[MemoryRecord]


# ============================================================================
# Task Recovery Schemas
# ============================================================================

class DispatchState(str, Enum):
    """
    Two-phase and crash-consistent dispatch states for the Execution Journal.
    Explicitly distinguishes execution boundaries without ambiguous boolean flags.
    """
    PREPARED = "PREPARED"
    DISPATCHING = "DISPATCHING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    UNKNOWN_OUTCOME = "UNKNOWN_OUTCOME"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CANCELLED = "CANCELLED"


class TaskCheckpoint(BaseModel):
    """Persistent task state checkpoint for crash recovery."""
    task_id: str = Field(..., description="Unique task identifier")
    workflow_id: str = Field(..., description="Parent workflow or pipeline ID")
    status: TaskStatus = Field(default=TaskStatus.PENDING)
    current_step: str = Field(..., description="Identifier of current step")
    completed_step_ids: List[str] = Field(default_factory=list, description="List of step IDs already committed")
    pending_step_ids: List[str] = Field(default_factory=list, description="List of step IDs yet to execute")
    approval_references: List[str] = Field(default_factory=list, description="Approved permission token IDs")
    retry_count: int = Field(default=0, ge=0)
    state_data: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary task execution variables")
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
    checkpoint_version: int = Field(default=1, ge=1, description="Optimistic locking version")
    lease_holder: Optional[str] = Field(default=None, description="Worker or node holding the execution lease")
    lease_expires_at: Optional[float] = Field(default=None, description="Epoch timestamp when the lease expires")


class TaskExecutionEvent(BaseModel):
    """Execution event record with idempotency hash for side-effect guard."""
    event_id: str = Field(..., description="Unique event identifier")
    task_id: str = Field(..., description="Associated task ID")
    step_id: str = Field(..., description="Associated step ID")
    action: str = Field(..., description="Action name executed")
    status: str = Field(..., description="SUCCESS, FAILED, PENDING")
    idempotency_hash: str = Field(..., description="SHA-256 hash of action inputs to prevent re-execution")
    details: Dict[str, Any] = Field(default_factory=dict, description="Action outputs or error logs")
    recorded_at: str = Field(default_factory=utc_now_iso)


class ExecutionJournalEntry(BaseModel):
    """
    Relational Execution Journal Record.
    Captures pre-dispatch intent, exact dispatch state, process metadata, and outcomes.
    """
    entry_id: str = Field(..., description="Unique journal record identifier")
    task_id: str = Field(..., description="Associated task identifier")
    step_id: str = Field(..., description="Associated step identifier")
    attempt_id: str = Field(..., description="Unique attempt UUID")
    action: str = Field(..., description="Skill or action identity")
    idempotency_class: str = Field(default="READ_ONLY", description="READ_ONLY, IDEMPOTENT, NON_IDEMPOTENT, IRREVERSIBLE_HIGH_RISK")
    param_hash: str = Field(..., description="Deterministic SHA-256 parameter fingerprint")
    sanitized_params: Dict[str, Any] = Field(default_factory=dict, description="Sanitized arguments with zero plaintext secrets")
    dispatch_state: DispatchState = Field(default=DispatchState.PREPARED)
    approval_ref: Optional[str] = Field(default=None, description="Associated approval token or record ID")
    pid: Optional[int] = Field(default=None, description="Operating system process ID for tracked subprocesses")
    process_creation_time: Optional[float] = Field(default=None, description="Exact 64-bit creation timestamp / FILETIME")
    log_path: Optional[str] = Field(default=None, description="Filesystem path to detached stdout/stderr log")
    exit_code: Optional[int] = Field(default=None, description="Process or action exit code")
    result_digest: Optional[str] = Field(default=None, description="SHA-256 digest of result payload")
    error_message: Optional[str] = Field(default=None, description="Sanitized error message if failed")
    checkpoint_version: int = Field(default=1, ge=1)
    recovery_attempts: int = Field(default=0, ge=0)
    created_at: str = Field(default_factory=utc_now_iso)
    dispatched_at: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)
    updated_at: str = Field(default_factory=utc_now_iso)


class SubprocessTrackRecord(BaseModel):
    """Process identity metadata for safe reattachment and PID reuse rejection."""
    pid: int
    process_creation_time: float
    attempt_id: str
    command_fingerprint: str
    log_path: str
    started_at: str = Field(default_factory=utc_now_iso)
    is_active: bool = True
    exit_code: Optional[int] = None


# ============================================================================
# Permission Schemas
# ============================================================================

class PermissionCheckRequest(BaseModel):
    """Authorization check request compatible with Member 1."""
    user_id: str = Field(..., description="Subject identity or agent identity")
    action: str = Field(..., description="Requested action / tool name")
    resource: str = Field(..., description="Target file, URL, process, or entity")
    risk_level: RiskLevel = Field(default=RiskLevel.MEDIUM)
    approval_token: Optional[str] = Field(None, description="Human approval token if previously granted")


class PermissionDecision(BaseModel):
    """Decision returned by the authorization gateway."""
    allowed: bool = Field(..., description="True if action is permitted to execute")
    reason: str = Field(..., description="Explanation of the authorization decision")
    approval_required: bool = Field(..., description="True if human confirmation is required")
    approval_id: Optional[str] = Field(None, description="Token identifier if approval is pending or granted")


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ApprovalRecord(BaseModel):
    approval_id: str = Field(..., description="Unique approval identifier")
    token: str = Field(..., description="Cryptographically random authorization token")
    task_id: Optional[str] = Field(None, description="Linked task ID if applicable")
    action: str = Field(..., description="Action name (e.g. system.execute, restore_checkpoint)")
    resource: str = Field(..., description="Scoped target resource or path")
    param_hash: str = Field(..., description="SHA-256 hash of bound parameters")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Exact parameters authorized")
    status: ApprovalStatus = Field(default=ApprovalStatus.PENDING)
    risk_level: RiskLevel = Field(default=RiskLevel.HIGH)
    notes: Optional[str] = Field(None)
    created_at: str = Field(default_factory=utc_now_iso)
    expires_at: float = Field(..., description="Epoch seconds when approval expires")
    consumed_at: Optional[str] = Field(None)
    resolved_at: Optional[str] = Field(None)
    rejection_reason: Optional[str] = Field(None)
    audit_evidence_id: Optional[str] = Field(None)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Flight Recorder & Provenance Schemas (FORGE Section 2 & 4)
# ============================================================================

class EventSourceType(str, Enum):
    OBSERVATION = "observation"
    INFERENCE = "inference"
    SYSTEM = "system"
    USER = "user"


class FlightRecorderEventCreate(BaseModel):
    """Input contract for publishing a flight recorder event."""
    project_id: str = Field(..., description="Project identity or scoped root reference")
    event_type: str = Field(..., description="Event classification (e.g. build.failed, test.passed)")
    source_type: EventSourceType = Field(..., description="Strictly 'observation' for real OS/tools or 'inference' for LLM")
    actor: str = Field(..., description="Actor/source name (e.g. subprocess.pytest, developer, agent)")
    summary: str = Field(..., description="Redacted human-readable summary")
    event_id: Optional[str] = Field(None, description="Stable UUID if pre-assigned")
    task_id: Optional[str] = Field(None, description="Associated task ID if applicable")
    phase: Optional[str] = Field(None, description="Lifecycle phase (e.g. triage, diagnosis, repair, verification)")
    evidence_refs: List[str] = Field(default_factory=list, description="IDs of linked evidence records")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Redacted contextual metadata (exit codes, paths, durations)")


class FlightRecorderEvent(BaseModel):
    """Durable development flight recorder event record."""
    event_id: str = Field(..., description="Stable UUID v4 identifier")
    project_id: str = Field(..., description="Scoped project reference")
    task_id: Optional[str] = Field(None, description="Associated task ID")
    timestamp: str = Field(default_factory=utc_now_iso, description="UTC ISO-8601 creation timestamp")
    event_type: str = Field(..., description="Event category")
    source_type: EventSourceType = Field(..., description="observation vs inference")
    actor: str = Field(..., description="Actor or tool source")
    summary: str = Field(..., description="Redacted summary")
    phase: Optional[str] = Field(None)
    evidence_refs: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    schema_version: int = Field(default=1)


class EvidenceRecordCreate(BaseModel):
    """Input contract for storing bounded, redacted evidence."""
    evidence_type: str = Field(..., description="subprocess_result, git_inspection, filesystem_stat, etc.")
    evidence_id: Optional[str] = Field(None, description="Pre-computed content digest or UUID")
    command: Optional[str] = Field(None, description="Command invoked (redacted)")
    exit_code: Optional[int] = Field(None, description="Subprocess return code")
    started_at: Optional[str] = Field(None)
    completed_at: Optional[str] = Field(None)
    duration_ms: Optional[int] = Field(None)
    working_dir: Optional[str] = Field(None)
    raw_stdout: Optional[str] = Field(None, description="Unfiltered stdout (will be digested and redacted into excerpt)")
    raw_stderr: Optional[str] = Field(None, description="Unfiltered stderr (will be digested)")
    redacted_excerpt: Optional[str] = Field(None, description="Pre-redacted bounded excerpt")
    is_agent_hypothesis: bool = Field(default=False, description="True ONLY if model-generated diagnosis")


class EvidenceRecord(BaseModel):
    """Durable evidence record linked to flight recorder events."""
    evidence_id: str
    evidence_type: str
    command: Optional[str] = None
    exit_code: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: Optional[int] = None
    working_dir: Optional[str] = None
    stdout_digest: Optional[str] = None
    stderr_digest: Optional[str] = None
    redacted_excerpt: Optional[str] = None
    is_agent_hypothesis: bool = False
    created_at: str = Field(default_factory=utc_now_iso)


class EventQueryFilter(BaseModel):
    """Query filters for chronological flight recorder search."""
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    event_type: Optional[str] = None
    source_type: Optional[EventSourceType] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# ============================================================================
# Project Checkpoints & Safe Recovery Schemas (FORGE Section 5)
# ============================================================================

class CheckpointLifecycleStatus(str, Enum):
    CREATED = "created"
    VALIDATED = "validated"
    HEALTHY = "healthy"
    RESTORABLE = "restorable"


class TrackedFileChange(BaseModel):
    """Tracks a single file status and hash within a project checkpoint."""
    path: str = Field(..., description="Relative canonical path within project root")
    sha256: str = Field(..., description="SHA-256 digest of file content")
    status: str = Field(default="modified", description="modified, added, deleted")


class GitRevisionInfo(BaseModel):
    """Snapshot of Git revision state."""
    commit_sha: Optional[str] = None
    branch: Optional[str] = None
    is_dirty: bool = False


class ProjectCheckpointManifest(BaseModel):
    """Comprehensive, inspectable project state checkpoint."""
    checkpoint_id: str = Field(..., description="Unique checkpoint identifier")
    project_id: str = Field(..., description="Target project scope")
    permitted_root: str = Field(..., description="Canonical project filesystem root")
    git_revision: GitRevisionInfo = Field(default_factory=GitRevisionInfo)
    tracked_changes: List[TrackedFileChange] = Field(default_factory=list)
    dependency_fingerprints: Dict[str, str] = Field(default_factory=dict)
    toolchain_versions: Dict[str, str] = Field(default_factory=dict)
    status: CheckpointLifecycleStatus = Field(default=CheckpointLifecycleStatus.CREATED)
    integrity_hash: str = Field(..., description="Deterministic SHA-256 manifest hash")
    validation_notes: Optional[str] = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class CheckpointCreateRequest(BaseModel):
    """Request to snapshot project state."""
    project_id: str
    permitted_root: str
    git_revision: Optional[GitRevisionInfo] = None
    tracked_changes: List[TrackedFileChange] = Field(default_factory=list)
    dependency_fingerprints: Dict[str, str] = Field(default_factory=dict)
    toolchain_versions: Dict[str, str] = Field(default_factory=dict)


class CheckpointRestoreRequest(BaseModel):
    """Request to safely recover project state."""
    approval_token: Optional[str] = Field(None, description="Human approval token if modifying/reverting files")
    dry_run: bool = Field(default=True, description="When true, computes preview of changes without disk writes")
    target_files: Optional[List[str]] = Field(None, description="Optional subset of specific files to restore")


class CheckpointRestoreResponse(BaseModel):
    """Result of checkpoint restoration validation or execution."""
    checkpoint_id: str
    project_id: str
    success: bool
    dry_run: bool
    status: str
    restored_files: List[str] = Field(default_factory=list, description="Files successfully restored to target checkpoint state")
    protected_files: List[str] = Field(default_factory=list, description="Untracked or dirty local files that were protected from being overwritten")
    overridden_files: List[str] = Field(default_factory=list, description="Files with local changes that were overwritten under explicit user approval")
    failed_files: List[str] = Field(default_factory=list, description="Files that encountered errors during restoration")
    pre_restoration_snapshot_id: Optional[str] = None
    message: str
