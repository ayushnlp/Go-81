"""
FastAPI route handlers and SubsystemContainer re-exports for Go 81 Memory & Security Subsystem.
Enables imports from either `app.memory.routes` or `app.api.routes`.
"""

from app.api.routes import *
from app.api.routes import (
    ReconcileTaskRequest,
    SubsystemContainer,
    delete_memory,
    edit_memory,
    export_memories,
    get_consolidation_engine,
    get_memory_service,
    get_permission_gateway,
    get_recovery_manager,
    inspect_memory,
    inspect_task_checkpoint,
    list_and_search_memories,
    list_incomplete_tasks,
    reconcile_task,
    record_episodic_event,
    record_semantic_memory,
    recover_task_checkpoint,
    router,
    save_task_checkpoint,
    trigger_consolidation,
)

__all__ = [
    "router",
    "SubsystemContainer",
    "ReconcileTaskRequest",
    "get_memory_service",
    "get_recovery_manager",
    "get_permission_gateway",
    "get_consolidation_engine",
    "record_episodic_event",
    "record_semantic_memory",
    "list_and_search_memories",
    "inspect_memory",
    "edit_memory",
    "delete_memory",
    "export_memories",
    "trigger_consolidation",
    "list_incomplete_tasks",
    "save_task_checkpoint",
    "inspect_task_checkpoint",
    "recover_task_checkpoint",
    "reconcile_task",
]
