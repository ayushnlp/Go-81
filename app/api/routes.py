"""
FastAPI route handlers for Go 81 Memory & Security Subsystem.
Provides RESTful endpoints for Frontend and Agent Orchestrator.
All payloads are processed locally; plaintext is never transmitted externally.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.memory.consolidation import MemoryConsolidationEngine
from app.memory.crypto import (
    CompositeKeyProvider,
    DecryptionError,
    EncryptionService,
    MissingKeyError,
    TestKeyProvider,
)
from app.memory.database import DatabaseManager
from app.memory.checkpoint_service import CheckpointService
from app.memory.flight_recorder import FlightRecorderService
from app.memory.models import (
    CheckpointCreateRequest,
    CheckpointRestoreRequest,
    CheckpointRestoreResponse,
    EpisodicEvent,
    EventCreate,
    EventQueryFilter,
    EventSourceType,
    EvidenceRecord,
    EvidenceRecordCreate,
    FlightRecorderEvent,
    FlightRecorderEventCreate,
    MemoryExport,
    MemoryRecord,
    MemoryType,
    MemoryUpdate,
    PermissionCheckRequest,
    PermissionDecision,
    ProjectCheckpointManifest,
    SemanticCategory,
    SemanticMemory,
    SemanticMemoryCreate,
    TaskCheckpoint,
    VerificationStatus,
)
from app.memory.permissions import PermissionGateway
from app.memory.recovery import TaskRecoveryManager
from app.memory.security_boundary import (
    ApprovalTamperError,
    DangerousCommandError,
    PathTraversalError,
    SecurityBoundary,
)
from app.memory.service import MemoryService

router = APIRouter(prefix="/api", tags=["Memory & Security"])

# ============================================================================
# Subsystem Dependency Container
# ============================================================================

class SubsystemContainer:
    """Singleton container holding references to initialized subsystem services."""
    db: Optional[DatabaseManager] = None
    crypto: Optional[EncryptionService] = None
    memory_service: Optional[MemoryService] = None
    recovery_manager: Optional[TaskRecoveryManager] = None
    permission_gateway: Optional[PermissionGateway] = None
    consolidation_engine: Optional[MemoryConsolidationEngine] = None
    flight_recorder: Optional[FlightRecorderService] = None
    checkpoint_service: Optional[CheckpointService] = None

    @classmethod
    def initialize(
        cls,
        db_path: str = "go81_memory.db",
        encryption_service: Optional[EncryptionService] = None,
    ) -> None:
        cls.db = DatabaseManager(db_path)
        if encryption_service:
            cls.crypto = encryption_service
        elif cls.crypto is None:
            key_provider = CompositeKeyProvider()
            cls.crypto = EncryptionService(key_provider)

        cls.flight_recorder = FlightRecorderService(cls.db)
        cls.checkpoint_service = CheckpointService(cls.db)
        cls.memory_service = MemoryService(cls.db, cls.crypto, flight_recorder=cls.flight_recorder)
        cls.recovery_manager = TaskRecoveryManager(cls.db, cls.crypto)
        cls.permission_gateway = PermissionGateway(cls.db)
        cls.consolidation_engine = MemoryConsolidationEngine(cls.memory_service)
        SecurityBoundary._db = cls.db


def get_memory_service() -> MemoryService:
    if SubsystemContainer.memory_service is None:
        SubsystemContainer.initialize()
    return SubsystemContainer.memory_service


def get_recovery_manager() -> TaskRecoveryManager:
    if SubsystemContainer.recovery_manager is None:
        SubsystemContainer.initialize()
    return SubsystemContainer.recovery_manager


def get_permission_gateway() -> PermissionGateway:
    if SubsystemContainer.permission_gateway is None:
        SubsystemContainer.initialize()
    return SubsystemContainer.permission_gateway


def get_consolidation_engine() -> MemoryConsolidationEngine:
    if SubsystemContainer.consolidation_engine is None:
        SubsystemContainer.initialize()
    return SubsystemContainer.consolidation_engine


def get_flight_recorder() -> FlightRecorderService:
    if SubsystemContainer.flight_recorder is None:
        SubsystemContainer.initialize()
    return SubsystemContainer.flight_recorder


def get_checkpoint_service() -> CheckpointService:
    if SubsystemContainer.checkpoint_service is None:
        SubsystemContainer.initialize()
    return SubsystemContainer.checkpoint_service


# ============================================================================
# Memory Endpoints (Episodic & Semantic)
# ============================================================================

@router.post("/memory/events", response_model=EpisodicEvent, status_code=status.HTTP_201_CREATED)
def record_episodic_event(
    event: EventCreate,
    service: MemoryService = Depends(get_memory_service),
) -> EpisodicEvent:
    """Stores an episodic event (user message, agent thought, tool execution)."""
    try:
        return service.store_event(
            session_id=event.session_id,
            event_type=event.event_type,
            content=event.content,
            source_ref=event.source_ref,
            ttl_seconds=event.ttl_seconds,
            metadata=event.metadata,
        )
    except (MissingKeyError, DecryptionError) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/memory/semantic", response_model=SemanticMemory, status_code=status.HTTP_201_CREATED)
def record_semantic_memory(
    fact: SemanticMemoryCreate,
    service: MemoryService = Depends(get_memory_service),
) -> SemanticMemory:
    """Stores a structured fact or preference with deterministic deduplication."""
    try:
        return service.store_memory(
            category=fact.category,
            subject=fact.subject,
            predicate=fact.predicate,
            object_value=fact.object_value,
            verification_status=fact.verification_status,
            confidence=fact.confidence,
            source_ref=fact.source_ref,
            ttl_seconds=fact.ttl_seconds,
        )
    except (MissingKeyError, DecryptionError) as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/memory", response_model=List[MemoryRecord])
def list_and_search_memories(
    query: Optional[str] = Query(None, description="In-process deterministic keyword search query"),
    memory_type: Optional[MemoryType] = Query(None, description="Filter by episodic or semantic"),
    category: Optional[str] = Query(None, description="Filter by category or event type"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    include_expired: bool = Query(default=False),
    service: MemoryService = Depends(get_memory_service),
) -> List[MemoryRecord]:
    """Lists and searches memories in process memory with pagination."""
    return service.search_memories(
        query=query,
        memory_type=memory_type,
        category=category,
        limit=limit,
        offset=offset,
        include_expired=include_expired,
    )


@router.get("/memory/{memory_id}", response_model=MemoryRecord)
def inspect_memory(
    memory_id: str,
    include_deleted: bool = Query(default=False),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryRecord:
    """Inspects a single memory by ID, decrypting its payload."""
    record = service.get_memory(memory_id, include_deleted=include_deleted)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory record '{memory_id}' not found.",
        )
    return record


@router.put("/memory/{memory_id}", response_model=MemoryRecord)
def edit_memory(
    memory_id: str,
    update: MemoryUpdate,
    service: MemoryService = Depends(get_memory_service),
) -> MemoryRecord:
    """User-controlled update of memory values, confidence, or verification status."""
    try:
        return service.update_memory(memory_id, update)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory record '{memory_id}' not found.",
        )


@router.delete("/memory/{memory_id}", status_code=status.HTTP_200_OK)
def delete_memory(
    memory_id: str,
    hard: bool = Query(default=False, description="Permanent cryptographic overwrite if true, tombstone if false"),
    service: MemoryService = Depends(get_memory_service),
) -> Dict[str, Any]:
    """Deletes a memory record (soft tombstone or permanent hard erasure)."""
    success = service.delete_memory(memory_id, hard_delete=hard)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory record '{memory_id}' not found or already deleted.",
        )
    return {
        "status": "success",
        "id": memory_id,
        "deletion_type": "hard" if hard else "soft",
    }


# ============================================================================
# Frontend Command Center Endpoints (CONTRACT.md Section 2.5)
# ============================================================================

def _format_for_frontend(record: MemoryRecord) -> Dict[str, Any]:
    """Adapts a MemoryRecord to include frontend-compatible fields while preserving backend structure."""
    base = record.model_dump()
    payload = record.payload or {}
    mem_type = record.memory_type.value if hasattr(record.memory_type, "value") else str(record.memory_type)
    base["type"] = mem_type

    if mem_type == "semantic":
        subject = payload.get("subject", "")
        predicate = payload.get("predicate", "")
        object_val = payload.get("object_value", "")
        statement = f"{subject} {predicate}: {object_val}" if subject else str(object_val)
        base["subject"] = subject
        base["statement"] = statement
        base["updatedAt"] = record.updated_at
        base["accessCount"] = payload.get("access_count", 1)
        base["decayFactor"] = 0.0
    else:
        # episodic
        content = payload.get("content", {})
        if isinstance(content, dict):
            text_content = content.get("message") or content.get("text") or str(content)
        else:
            text_content = str(content)
        base["title"] = payload.get("event_type") or record.category or "Episodic Event"
        base["content"] = text_content
        base["timestamp"] = record.created_at
        base["sourceEvent"] = record.source_ref or payload.get("session_id", "session")
        base["importanceScore"] = record.confidence
        base["tags"] = [record.category] if record.category else ["episodic"]
        base["pinned"] = False
    return base


@router.get("/memories")
def list_memories_frontend(
    type: Optional[str] = Query(None, description="episodic or semantic"),
    project_id: Optional[str] = Query(None, description="Filter by project scope"),
    query: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: MemoryService = Depends(get_memory_service),
) -> List[Dict[str, Any]]:
    """Frontend-compatible alias returning list of memories formatted for UI command center."""
    mem_type = None
    if type:
        try:
            mem_type = MemoryType(type.lower())
        except ValueError:
            pass
    records = service.search_memories(
        query=query,
        project_id=project_id,
        memory_type=mem_type,
        category=category,
        limit=limit,
        offset=offset,
        include_expired=False,
    )
    return [_format_for_frontend(r) for r in records]


@router.delete("/memories/{memory_id}")
def delete_memory_frontend(
    memory_id: str,
    hard: bool = Query(default=False),
    service: MemoryService = Depends(get_memory_service),
) -> Dict[str, Any]:
    """Frontend-compatible deletion endpoint (FR1.3 / NFR4.2)."""
    success = service.delete_memory(memory_id, hard_delete=hard)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Memory record '{memory_id}' not found or already deleted.",
        )
    return {"deleted": True, "success": True, "id": memory_id}


class MemoryPatchRequest(BaseModel):
    statement: Optional[str] = None
    content: Optional[str] = None
    confidence: Optional[float] = None
    verification_status: Optional[VerificationStatus] = None


@router.patch("/memories/{memory_id}")
def patch_memory_frontend(
    memory_id: str,
    patch: MemoryPatchRequest,
    service: MemoryService = Depends(get_memory_service),
) -> Dict[str, Any]:
    """Frontend-compatible patch endpoint for editing memories (NFR4.2)."""
    update = MemoryUpdate(
        object_value=patch.statement,
        content={"message": patch.content} if patch.content else None,
        confidence=patch.confidence,
        verification_status=patch.verification_status,
    )
    try:
        rec = service.update_memory(memory_id, update)
        return _format_for_frontend(rec)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Memory '{memory_id}' not found.")


@router.get("/memory/export/all", response_model=MemoryExport)
def export_memories(
    memory_type: Optional[MemoryType] = Query(None),
    category: Optional[str] = Query(None),
    service: MemoryService = Depends(get_memory_service),
) -> MemoryExport:
    """Exports active memories in decrypted JSON format for user portability."""
    return service.export_memories(memory_type=memory_type, category=category)


@router.post("/memory/consolidate", status_code=status.HTTP_200_OK)
def trigger_consolidation(
    engine: MemoryConsolidationEngine = Depends(get_consolidation_engine),
) -> Dict[str, Any]:
    """Promotes recurring episodic events into semantic facts and prunes expired data."""
    promoted = engine.consolidate_recent_events()
    purged = engine.enforce_retention_and_expiration()
    return {
        "promoted_count": len(promoted),
        "purged_count": purged,
        "promoted_facts": promoted,
    }


# ============================================================================
# Task Recovery Endpoints
# ============================================================================

class ReconcileTaskRequest(BaseModel):
    decision: str = Field(..., description="'resume' to unblock and continue, 'abort' to fail safely")
    notes: Optional[str] = Field(default="", description="Operator explanation or audit notes")
    next_step: Optional[str] = Field(default=None, description="Optional step to jump to if resuming")


@router.get("/tasks/incomplete", response_model=List[TaskCheckpoint])
def list_incomplete_tasks(
    recovery_mgr: TaskRecoveryManager = Depends(get_recovery_manager),
) -> List[TaskCheckpoint]:
    """Returns all unfinished tasks requiring recovery or continuation after reboot."""
    return recovery_mgr.load_incomplete_tasks()


@router.post("/tasks/checkpoints", status_code=status.HTTP_200_OK)
def save_task_checkpoint(
    checkpoint: TaskCheckpoint,
    recovery_mgr: TaskRecoveryManager = Depends(get_recovery_manager),
) -> Dict[str, str]:
    """Saves an encrypted workflow task checkpoint."""
    recovery_mgr.save_task_checkpoint(checkpoint)
    return {"status": "saved", "task_id": checkpoint.task_id}


@router.get("/tasks/checkpoints/{task_id}", response_model=TaskCheckpoint)
def inspect_task_checkpoint(
    task_id: str,
    recovery_mgr: TaskRecoveryManager = Depends(get_recovery_manager),
) -> TaskCheckpoint:
    """Fetches and decrypts an individual task checkpoint by task ID."""
    try:
        chk = recovery_mgr.get_task_checkpoint(task_id.strip())
        if not chk:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task checkpoint '{task_id}' not found.",
            )
        return chk
    except (MissingKeyError, DecryptionError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cryptographic recovery failure: {e}",
        )


@router.post("/tasks/checkpoints/{task_id}/recover", response_model=TaskCheckpoint)
def recover_task_checkpoint(
    task_id: str,
    recovery_mgr: TaskRecoveryManager = Depends(get_recovery_manager),
) -> TaskCheckpoint:
    """
    Restores an incomplete task checkpoint from disk after crash or restart.
    Verifies step state and decrypts saved state variables.
    """
    try:
        return recovery_mgr.recover_task(task_id.strip())
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task checkpoint '{task_id}' not found.",
        )
    except (MissingKeyError, DecryptionError) as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cryptographic recovery failure: {e}",
        )


@router.post("/tasks/checkpoints/{task_id}/reconcile", response_model=TaskCheckpoint)
def reconcile_task(
    task_id: str,
    req: ReconcileTaskRequest,
    recovery_mgr: TaskRecoveryManager = Depends(get_recovery_manager),
) -> TaskCheckpoint:
    """Human-in-the-loop operator resolution for tasks flagged with REQUIRES_RECONCILIATION."""
    try:
        return recovery_mgr.resolve_reconciliation(
            task_id=task_id.strip(),
            resolution=req.decision,
            notes=req.notes or "",
            next_step=req.next_step,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task checkpoint '{task_id}' not found.",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


# ============================================================================
# Permissions Endpoints
# ============================================================================

class GrantApprovalRequest(BaseModel):
    action: str
    resource: str = "*"
    ttl_seconds: int = Field(default=300, ge=10, le=3600)


@router.post("/security/check-permission", response_model=PermissionDecision)
def check_permission(
    req: PermissionCheckRequest,
    gateway: PermissionGateway = Depends(get_permission_gateway),
) -> PermissionDecision:
    """Evaluates whether an agent action is authorized under default-deny policy."""
    return gateway.check_permission(
        user_id=req.user_id,
        action=req.action,
        resource=req.resource,
        risk_level=req.risk_level,
        approval_token=req.approval_token,
    )


@router.post("/security/approve")
def grant_human_approval(
    req: GrantApprovalRequest,
    gateway: PermissionGateway = Depends(get_permission_gateway),
) -> Dict[str, Any]:
    """User-facing endpoint to issue an ephemeral approval token for dangerous tools."""
    token = gateway.grant_approval(
        action=req.action,
        resource=req.resource,
        ttl_seconds=req.ttl_seconds,
    )
    return {"status": "approved", "token": token, "action": req.action, "resource": req.resource}


# ============================================================================
# Project Flight Recorder Endpoints (FORGE Section 2, 3, 4)
# ============================================================================

@router.post("/events", response_model=FlightRecorderEvent, status_code=status.HTTP_201_CREATED, tags=["Flight Recorder"])
def record_flight_event(
    event: FlightRecorderEventCreate,
    recorder: FlightRecorderService = Depends(get_flight_recorder),
) -> FlightRecorderEvent:
    """Durably records an evidence-backed development or agent activity event."""
    return recorder.record_event(event)


@router.get("/events", response_model=List[FlightRecorderEvent], tags=["Flight Recorder"])
def query_flight_events(
    project_id: Optional[str] = Query(None),
    task_id: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    source_type: Optional[EventSourceType] = Query(None),
    start_time: Optional[str] = Query(None),
    end_time: Optional[str] = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    recorder: FlightRecorderService = Depends(get_flight_recorder),
) -> List[FlightRecorderEvent]:
    """Chronologically queries flight recorder events with multi-dimensional filtering."""
    q = EventQueryFilter(
        project_id=project_id,
        task_id=task_id,
        event_type=event_type,
        source_type=source_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        offset=offset,
    )
    return recorder.query_events(q)


@router.get("/events/{event_id}", response_model=FlightRecorderEvent, tags=["Flight Recorder"])
def get_flight_event(
    event_id: str,
    recorder: FlightRecorderService = Depends(get_flight_recorder),
) -> FlightRecorderEvent:
    """Retrieves a single flight recorder event by ID."""
    evt = recorder.get_event(event_id)
    if not evt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found.")
    return evt


@router.get("/events/{event_id}/evidence", tags=["Flight Recorder"])
def get_flight_event_evidence(
    event_id: str,
    recorder: FlightRecorderService = Depends(get_flight_recorder),
) -> Dict[str, Any]:
    """Resolves an event along with all its linked bounded evidence records."""
    data = recorder.get_event_with_evidence(event_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Event '{event_id}' not found.")
    return data


@router.post("/events/evidence", response_model=EvidenceRecord, status_code=status.HTTP_201_CREATED, tags=["Flight Recorder"])
def store_evidence_record(
    evidence: EvidenceRecordCreate,
    recorder: FlightRecorderService = Depends(get_flight_recorder),
) -> EvidenceRecord:
    """Stores a standalone evidence record with automatic digest computation and secret redaction."""
    return recorder.store_evidence(evidence)


@router.get("/evidence/{evidence_id}", response_model=EvidenceRecord, tags=["Flight Recorder"])
def get_evidence_record(
    evidence_id: str,
    recorder: FlightRecorderService = Depends(get_flight_recorder),
) -> EvidenceRecord:
    """Retrieves bounded evidence metadata and redacted excerpt by ID."""
    ev = recorder.get_evidence(evidence_id)
    if not ev:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Evidence '{evidence_id}' not found.")
    return ev


@router.post("/events/prune", tags=["Flight Recorder"])
def prune_flight_events(
    project_id: Optional[str] = Query(None),
    max_events: int = Query(default=5000, ge=100),
    retention_days: Optional[int] = Query(None, ge=1),
    recorder: FlightRecorderService = Depends(get_flight_recorder),
) -> Dict[str, Any]:
    """Enforces bounded retention policy on flight recorder event log."""
    count = recorder.prune_events(project_id=project_id, max_events=max_events, retention_days=retention_days)
    return {"pruned": count, "project_id": project_id, "max_events": max_events}


# ============================================================================
# Project Checkpoints & Safe Recovery Endpoints (FORGE Section 5 & 9)
# ============================================================================

@router.post("/checkpoints", response_model=ProjectCheckpointManifest, status_code=status.HTTP_201_CREATED, tags=["Checkpoints & Recovery"])
def create_checkpoint(
    req: CheckpointCreateRequest,
    checkpoints: CheckpointService = Depends(get_checkpoint_service),
) -> ProjectCheckpointManifest:
    """Captures a new inspectable project checkpoint manifest (status: CREATED)."""
    return checkpoints.create_checkpoint(req)


@router.get("/checkpoints", response_model=List[ProjectCheckpointManifest], tags=["Checkpoints & Recovery"])
def list_checkpoints(
    project_id: Optional[str] = Query(None),
    limit: int = Query(default=50, ge=1, le=200),
    checkpoints: CheckpointService = Depends(get_checkpoint_service),
) -> List[ProjectCheckpointManifest]:
    """Lists project checkpoint manifests ordered chronologically descending."""
    return checkpoints.list_checkpoints(project_id=project_id, limit=limit)


@router.get("/checkpoints/{checkpoint_id}", response_model=ProjectCheckpointManifest, tags=["Checkpoints & Recovery"])
def get_checkpoint(
    checkpoint_id: str,
    checkpoints: CheckpointService = Depends(get_checkpoint_service),
) -> ProjectCheckpointManifest:
    """Retrieves detailed checkpoint manifest, hashes, and validation status."""
    chk = checkpoints.get_checkpoint(checkpoint_id)
    if not chk:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Checkpoint '{checkpoint_id}' not found.")
    return chk


@router.post("/checkpoints/{checkpoint_id}/validate", response_model=ProjectCheckpointManifest, tags=["Checkpoints & Recovery"])
def validate_checkpoint(
    checkpoint_id: str,
    checkpoints: CheckpointService = Depends(get_checkpoint_service),
) -> ProjectCheckpointManifest:
    """Validates manifest integrity hash and disk consistency (transitions to VALIDATED if sound)."""
    try:
        return checkpoints.validate_checkpoint(checkpoint_id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.post("/checkpoints/{checkpoint_id}/validate_restorable", response_model=ProjectCheckpointManifest, tags=["Checkpoints & Recovery"])
def validate_restorable_checkpoint(
    checkpoint_id: str,
    checkpoints: CheckpointService = Depends(get_checkpoint_service),
) -> ProjectCheckpointManifest:
    """Validates recovery procedure against permitted root (transitions to RESTORABLE if sound)."""
    try:
        return checkpoints.validate_restorable(checkpoint_id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/checkpoints/{checkpoint_id}/health", response_model=ProjectCheckpointManifest, tags=["Checkpoints & Recovery"])
def mark_checkpoint_healthy(
    checkpoint_id: str,
    test_evidence_id: str = Query(..., description="ID of passed test evidence proving health"),
    checkpoints: CheckpointService = Depends(get_checkpoint_service),
) -> ProjectCheckpointManifest:
    """Marks checkpoint HEALTHY only when tied to verified test execution evidence."""
    try:
        return checkpoints.mark_healthy(checkpoint_id, test_evidence_id)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/checkpoints/{checkpoint_id}/restore", response_model=CheckpointRestoreResponse, tags=["Checkpoints & Recovery"])
def restore_checkpoint(
    checkpoint_id: str,
    req: CheckpointRestoreRequest,
    checkpoints: CheckpointService = Depends(get_checkpoint_service),
) -> CheckpointRestoreResponse:
    """
    Performs safe, non-destructive restoration.
    Refuses to clobber dirty or untracked developer work without explicit approval token.
    """
    try:
        return checkpoints.restore_checkpoint(checkpoint_id, req)
    except KeyError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PathTraversalError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ApprovalTamperError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
