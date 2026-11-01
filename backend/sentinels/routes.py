"""
FastAPI REST API routes for Go 81 Stage 9 Background Sentinels and Persistent Scheduler.
"""

from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.sentinels.models import (
    InternalNotification,
    JobRunStatus,
    MissedRunPolicy,
    NotificationCategory,
    PersistentSchedule,
    ScheduledJobRun,
    ScheduleState,
    ScheduleType,
    SentinelConfig,
    SentinelType,
)

router = APIRouter(tags=["Sentinels & Scheduler"])


# ============================================================================
# Request Models
# ============================================================================

class CreateScheduleRequest(BaseModel):
    name: str
    schedule_type: ScheduleType
    schedule_expr: str
    goal: str
    timezone: str = "UTC"
    parameters: Dict[str, Any] = Field(default_factory=dict)
    missed_run_policy: MissedRunPolicy = MissedRunPolicy.SKIP
    max_runs: Optional[int] = None


class CreateSentinelRequest(BaseModel):
    sentinel_type: SentinelType
    name: str
    config_data: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


# ============================================================================
# Dependency
# ============================================================================

def get_manager():
    """Lazy imports the SentinelManager singleton."""
    from backend.main import get_sentinel_manager
    return get_sentinel_manager()


# ============================================================================
# Schedule Endpoints
# ============================================================================

@router.get("/schedules", response_model=List[PersistentSchedule])
async def list_schedules(
    state: Optional[ScheduleState] = None,
    mgr=Depends(get_manager),
):
    """Lists persistent schedules with optional state filtering."""
    return mgr.scheduler.list_schedules(state=state)


@router.post("/schedules", response_model=PersistentSchedule, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    req: CreateScheduleRequest,
    mgr=Depends(get_manager),
):
    """Creates a new persistent schedule (ONE_TIME, INTERVAL, or CRON)."""
    try:
        schedule = mgr.scheduler.create_schedule(
            name=req.name,
            schedule_type=req.schedule_type,
            schedule_expr=req.schedule_expr,
            goal=req.goal,
            timezone_str=req.timezone,
            parameters=req.parameters,
            missed_run_policy=req.missed_run_policy,
            max_runs=req.max_runs,
        )
        return schedule
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create schedule: {e}")


@router.get("/schedules/{schedule_id}")
async def get_schedule_details(
    schedule_id: str,
    limit_runs: int = Query(default=10, ge=1, le=100),
    mgr=Depends(get_manager),
):
    """Retrieves schedule details and recent execution history."""
    schedule = mgr.scheduler.get_schedule(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    recent_runs = mgr.scheduler.get_recent_runs(schedule_id, limit=limit_runs)
    return {
        "schedule": schedule,
        "recent_runs": recent_runs,
    }


@router.patch("/schedules/{schedule_id}/pause")
async def pause_schedule(
    schedule_id: str,
    mgr=Depends(get_manager),
):
    """Pauses an active schedule."""
    success = mgr.scheduler.pause_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Could not pause schedule '{schedule_id}'")
    return {"status": "paused", "schedule_id": schedule_id}


@router.patch("/schedules/{schedule_id}/resume")
async def resume_schedule(
    schedule_id: str,
    mgr=Depends(get_manager),
):
    """Resumes a paused schedule and recalculates the next execution time."""
    success = mgr.scheduler.resume_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=400, detail=f"Could not resume schedule '{schedule_id}'")
    sched = mgr.scheduler.get_schedule(schedule_id)
    return {"status": "resumed", "schedule_id": schedule_id, "next_run_at": sched.next_run_at if sched else None}


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    mgr=Depends(get_manager),
):
    """Deletes a schedule and its historical runs."""
    success = mgr.scheduler.delete_schedule(schedule_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Schedule '{schedule_id}' not found")
    return {"status": "deleted", "schedule_id": schedule_id}


# ============================================================================
# Sentinel Configuration Endpoints
# ============================================================================

@router.get("/sentinels", response_model=List[SentinelConfig])
async def list_sentinels(mgr=Depends(get_manager)):
    """Lists all configured background sentinels."""
    return mgr.list_sentinel_configs()


@router.post("/sentinels", response_model=SentinelConfig, status_code=status.HTTP_201_CREATED)
async def create_sentinel(
    req: CreateSentinelRequest,
    mgr=Depends(get_manager),
):
    """Registers and instantiates a new background sentinel."""
    try:
        config = mgr.register_sentinel_config(
            sentinel_type=req.sentinel_type,
            name=req.name,
            config_data=req.config_data,
            enabled=req.enabled,
        )
        return config
    except (ValueError, PermissionError, FileNotFoundError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to register sentinel: {e}")


@router.get("/sentinels/{sentinel_id}", response_model=SentinelConfig)
async def get_sentinel(sentinel_id: str, mgr=Depends(get_manager)):
    """Retrieves a sentinel configuration by ID."""
    cfg = mgr.get_sentinel_config(sentinel_id)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"Sentinel '{sentinel_id}' not found")
    return cfg


@router.patch("/sentinels/{sentinel_id}/enable")
async def enable_sentinel(sentinel_id: str, mgr=Depends(get_manager)):
    """Enables a background sentinel."""
    success = mgr.set_sentinel_enabled(sentinel_id, True)
    if not success:
        raise HTTPException(status_code=404, detail=f"Sentinel '{sentinel_id}' not found")
    return {"status": "enabled", "sentinel_id": sentinel_id}


@router.patch("/sentinels/{sentinel_id}/disable")
async def disable_sentinel(sentinel_id: str, mgr=Depends(get_manager)):
    """Disables a background sentinel."""
    success = mgr.set_sentinel_enabled(sentinel_id, False)
    if not success:
        raise HTTPException(status_code=404, detail=f"Sentinel '{sentinel_id}' not found")
    return {"status": "disabled", "sentinel_id": sentinel_id}


@router.delete("/sentinels/{sentinel_id}")
async def delete_sentinel(sentinel_id: str, mgr=Depends(get_manager)):
    """Removes a background sentinel configuration."""
    success = mgr.remove_sentinel(sentinel_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Sentinel '{sentinel_id}' not found")
    return {"status": "deleted", "sentinel_id": sentinel_id}


# ============================================================================
# Background Control & Health Endpoints
# ============================================================================

@router.get("/background/status")
async def get_background_status(mgr=Depends(get_manager)):
    """Returns runtime health, active jobs count, and pause status."""
    return mgr.get_status_summary()


@router.post("/background/pause")
async def pause_background_execution(mgr=Depends(get_manager)):
    """Master kill-switch: pauses all background scheduling and sentinel task dispatch."""
    mgr.pause_all()
    return {"status": "paused", "is_paused": True}


@router.post("/background/resume")
async def resume_background_execution(mgr=Depends(get_manager)):
    """Resumes background scheduling and sentinel execution."""
    mgr.resume_all()
    return {"status": "resumed", "is_paused": False}


# ============================================================================
# Internal Notification Endpoints
# ============================================================================

@router.get("/background/notifications", response_model=List[InternalNotification])
async def list_notifications(
    limit: int = Query(default=50, ge=1, le=500),
    unread_only: bool = False,
    category: Optional[NotificationCategory] = None,
    mgr=Depends(get_manager),
):
    """Fetches stored in-app notifications with optional filtering."""
    return mgr.notifications.get_notifications(
        limit=limit,
        unread_only=unread_only,
        category=category,
    )


@router.get("/background/notifications/unread-count")
async def get_unread_notification_count(mgr=Depends(get_manager)):
    """Returns the current count of unread notifications."""
    return {"unread_count": mgr.notifications.get_unread_count()}


@router.post("/background/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str, mgr=Depends(get_manager)):
    """Marks a single notification as read."""
    success = mgr.notifications.mark_as_read(notification_id)
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "marked_read", "notification_id": notification_id}


@router.post("/background/notifications/read-all")
async def mark_all_notifications_read(mgr=Depends(get_manager)):
    """Marks all unread notifications as read."""
    count = mgr.notifications.mark_all_as_read()
    return {"status": "all_marked_read", "updated_count": count}


@router.delete("/background/notifications")
async def clear_notifications(mgr=Depends(get_manager)):
    """Clears all stored notifications."""
    cleared = mgr.notifications.clear_notifications()
    return {"status": "cleared", "deleted_count": cleared}

