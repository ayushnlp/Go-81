"""
Data models and enumerations for Go 81 Stage 9 Background Sentinels and Persistent Scheduler.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SentinelType(str, Enum):
    FILESYSTEM = "FILESYSTEM"
    EVENT = "EVENT"
    BROWSER = "BROWSER"


class SentinelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ERROR = "ERROR"
    STOPPED = "STOPPED"


class ScheduleType(str, Enum):
    ONE_TIME = "ONE_TIME"
    INTERVAL = "INTERVAL"
    CRON = "CRON"


class ScheduleState(str, Enum):
    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    RUNNING = "RUNNING"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class MissedRunPolicy(str, Enum):
    SKIP = "SKIP"
    RUN_ONCE = "RUN_ONCE"
    FAIL = "FAIL"


class NotificationSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class NotificationCategory(str, Enum):
    SCHEDULE_EXECUTED = "SCHEDULE_EXECUTED"
    SCHEDULE_MISSED = "SCHEDULE_MISSED"
    FILE_CHANGE_TRIGGER = "FILE_CHANGE_TRIGGER"
    EVENT_TRIGGER = "EVENT_TRIGGER"
    SECURITY_ALERT = "SECURITY_ALERT"
    SYSTEM_HEALTH = "SYSTEM_HEALTH"


class JobRunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class PersistentSchedule(BaseModel):
    schedule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    schedule_type: ScheduleType
    schedule_expr: str  # ISO timestamp, interval seconds, or 5-part cron
    timezone: str = "UTC"
    goal: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    state: ScheduleState = ScheduleState.ENABLED
    missed_run_policy: MissedRunPolicy = MissedRunPolicy.SKIP
    max_runs: Optional[int] = None
    runs_completed: int = 0
    next_run_at: Optional[str] = None
    last_run_at: Optional[str] = None
    lease_holder: Optional[str] = None
    lease_expires_at: Optional[float] = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ScheduledJobRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    schedule_id: str
    idempotency_key: str
    scheduled_time: str
    started_at: str = Field(default_factory=utc_now)
    completed_at: Optional[str] = None
    status: JobRunStatus = JobRunStatus.PENDING
    task_id: Optional[str] = None
    error_message: Optional[str] = None
    result_summary: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)


class SentinelConfig(BaseModel):
    sentinel_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sentinel_type: SentinelType
    name: str
    enabled: bool = True
    config_data: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class SentinelEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sentinel_id: str
    event_type: str
    fingerprint: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    handled: bool = False
    task_id: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)


class InternalNotification(BaseModel):
    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    category: NotificationCategory
    severity: NotificationSeverity
    title: str
    message: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    read: bool = False
    dedup_key: Optional[str] = None
    created_at: str = Field(default_factory=utc_now)

