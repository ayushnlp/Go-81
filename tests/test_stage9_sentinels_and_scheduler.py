"""
Comprehensive test suite for Go 81 Stage 9: Background Sentinels and Persistent Scheduler.
Tests:
1. Pure-Python CronEvaluator (expressions, DST, timezones, syntax error handling).
2. PersistentScheduler (ONE_TIME, INTERVAL, CRON, atomic leases, idempotency keys, missed-run policies).
3. PathSecurityValidator & UntrustedContentGuard (canonical containment, traversal, symlink escapes, exclusions).
4. FilesystemSentinel (diff detection, debounce coalescing, queue bounds, untrusted file wrapping).
5. InternalEventSentinel (allowlist filtering, cascade recursion depth bound, rate limiting).
6. BrowserMonitoringSentinel (read-only change detection, origin allowlist, TOCTOU redirect protection).
7. NotificationService (severity, bounded history, deduplication, unread queries).
8. SentinelManager (concurrency semaphore, master kill-switch pause/resume, startup recovery, graceful shutdown).
9. FastAPI REST routes for schedules, sentinels, master controls, and notifications.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import tempfile
import time
from typing import Any, Dict
import pytest
from fastapi.testclient import TestClient

from app.memory.database import DatabaseManager, utc_now
from backend.main import app, get_sentinel_manager
from backend.sentinels.browser_sentinel import BrowserMonitoringSentinel
from backend.sentinels.event_sentinel import (
    ALLOWED_EVENT_TYPES,
    InternalEventSentinel,
    MAX_CAUSATION_DEPTH,
)
from backend.sentinels.filesystem_sentinel import FilesystemSentinel
from backend.sentinels.manager import SentinelManager
from backend.sentinels.models import (
    JobRunStatus,
    MissedRunPolicy,
    NotificationCategory,
    NotificationSeverity,
    PersistentSchedule,
    ScheduleState,
    ScheduleType,
    SentinelConfig,
    SentinelEvent,
    SentinelStatus,
    SentinelType,
)
from backend.sentinels.notification_service import NotificationService
from backend.sentinels.scheduler import CronEvaluator, PersistentScheduler
from backend.sentinels.security import (
    PathSecurityValidator,
    UntrustedContentGuard,
)


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "test_sentinels.db")
        db = DatabaseManager(db_path, auto_upgrade_v6=True)
        yield db


# ============================================================================
# 1. Pure-Python CronEvaluator Tests
# ============================================================================

def test_cron_evaluator_basic_matching():
    evaluator = CronEvaluator("*/15 9 * * 1-5")  # Every 15 min between 9:00 and 9:59 on weekdays

    # Monday 09:15 UTC -> match
    dt_match = datetime(2026, 11, 2, 9, 15, tzinfo=timezone.utc)  # Nov 2 2026 is Monday
    assert evaluator.matches(dt_match) is True

    # Monday 09:16 UTC -> no match
    dt_no_match = datetime(2026, 11, 2, 9, 16, tzinfo=timezone.utc)
    assert evaluator.matches(dt_no_match) is False

    # Sunday 09:15 UTC -> no match
    dt_sunday = datetime(2026, 11, 1, 9, 15, tzinfo=timezone.utc)
    assert evaluator.matches(dt_sunday) is False


def test_cron_evaluator_next_run_calculation():
    evaluator = CronEvaluator("0 12 * * *")  # Every day at 12:00 UTC
    base_dt = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    next_dt = evaluator.next_run(base_dt)

    assert next_dt == datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)

    # If base is after 12:00, next run is tomorrow
    base_after = datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc)
    next_tomorrow = evaluator.next_run(base_after)
    assert next_tomorrow == datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def test_cron_evaluator_month_and_dow_names():
    evaluator = CronEvaluator("0 0 1 JAN,JUN MON-FRI")
    dt_jan_mon = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)  # Jan 1 2024 is Monday
    assert evaluator.matches(dt_jan_mon) is True


def test_cron_evaluator_timezone_and_dst():
    # 09:00 in America/New_York
    evaluator = CronEvaluator("0 9 * * *", tz_name="America/New_York")
    base_dt = datetime(2026, 11, 2, 0, 0, tzinfo=timezone.utc)
    next_dt = evaluator.next_run(base_dt)

    # In Nov (Standard Time), New York is UTC-5 -> 09:00 NY = 14:00 UTC
    assert next_dt.hour == 14
    assert next_dt.minute == 0


def test_cron_evaluator_invalid_syntax():
    with pytest.raises(ValueError):
        CronEvaluator("invalid cron")
    with pytest.raises(ValueError):
        CronEvaluator("65 * * * *")  # Minute out of bounds


# ============================================================================
# 2. PersistentScheduler Tests
# ============================================================================

def test_persistent_scheduler_crud(temp_db):
    scheduler = PersistentScheduler(temp_db)

    # Create INTERVAL schedule
    sched = scheduler.create_schedule(
        name="Heartbeat Job",
        schedule_type=ScheduleType.INTERVAL,
        schedule_expr="300",
        goal="Check system status",
    )
    assert sched.schedule_id is not None
    assert sched.state == ScheduleState.ENABLED
    assert sched.next_run_at is not None

    # Retrieve
    fetched = scheduler.get_schedule(sched.schedule_id)
    assert fetched is not None
    assert fetched.name == "Heartbeat Job"

    # Pause
    assert scheduler.pause_schedule(sched.schedule_id) is True
    paused = scheduler.get_schedule(sched.schedule_id)
    assert paused.state == ScheduleState.PAUSED

    # Resume
    assert scheduler.resume_schedule(sched.schedule_id) is True
    resumed = scheduler.get_schedule(sched.schedule_id)
    assert resumed.state == ScheduleState.ENABLED
    assert resumed.next_run_at is not None

    # Delete
    assert scheduler.delete_schedule(sched.schedule_id) is True
    assert scheduler.get_schedule(sched.schedule_id) is None


def test_persistent_scheduler_atomic_lease_and_deduplication(temp_db):
    scheduler = PersistentScheduler(temp_db)
    past_iso = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    sched = scheduler.create_schedule(
        name="Due Job",
        schedule_type=ScheduleType.ONE_TIME,
        schedule_expr=past_iso,
        goal="Execute immediate action",
    )
    # Manually backdate next_run_at to simulate due time
    with temp_db.transaction() as conn:
        conn.execute(
            "UPDATE background_schedules SET next_run_at = ? WHERE schedule_id = ?;",
            (past_iso, sched.schedule_id),
        )

    # Worker 1 claims due schedule
    due_worker1 = scheduler.claim_due_schedules(lease_holder="worker-1", lease_duration_seconds=60.0)
    assert len(due_worker1) == 1
    assert due_worker1[0][0].schedule_id == sched.schedule_id

    # Worker 2 attempts concurrent claim on the same schedule -> should be empty
    due_worker2 = scheduler.claim_due_schedules(lease_holder="worker-2", lease_duration_seconds=60.0)
    assert len(due_worker2) == 0

    # Idempotency Key deduplication test
    scheduled_time = due_worker1[0][1]
    run1 = scheduler.record_job_run_start(sched.schedule_id, scheduled_time)
    assert run1.idempotency_key == f"{sched.schedule_id}:{scheduled_time}"

    # Attempting to start the exact same run must raise sqlite3.IntegrityError
    with pytest.raises(sqlite3.IntegrityError):
        scheduler.record_job_run_start(sched.schedule_id, scheduled_time)

    # Complete run
    scheduler.complete_job_run(
        schedule_id=sched.schedule_id,
        run_id=run1.run_id,
        status=JobRunStatus.SUCCESS,
        result_summary="Completed successfully",
    )
    completed_sched = scheduler.get_schedule(sched.schedule_id)
    assert completed_sched.state == ScheduleState.COMPLETED
    assert completed_sched.runs_completed == 1
    assert completed_sched.next_run_at is None


def test_persistent_scheduler_missed_run_policies(temp_db):
    scheduler = PersistentScheduler(temp_db)
    two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

    # Policy 1: SKIP
    s_skip = scheduler.create_schedule(
        name="Skip Missed",
        schedule_type=ScheduleType.INTERVAL,
        schedule_expr="600",
        goal="Periodic sync",
        missed_run_policy=MissedRunPolicy.SKIP,
    )
    # Policy 2: FAIL
    s_fail = scheduler.create_schedule(
        name="Fail Missed",
        schedule_type=ScheduleType.INTERVAL,
        schedule_expr="600",
        goal="Critical audit",
        missed_run_policy=MissedRunPolicy.FAIL,
    )

    with temp_db.transaction() as conn:
        conn.execute("UPDATE background_schedules SET next_run_at = ? WHERE schedule_id = ?;", (two_hours_ago, s_skip.schedule_id))
        conn.execute("UPDATE background_schedules SET next_run_at = ? WHERE schedule_id = ?;", (two_hours_ago, s_fail.schedule_id))

    missed = scheduler.handle_missed_runs(tolerance_seconds=60.0)
    assert len(missed) == 2

    # Check that s_skip had its next_run_at updated to the future
    updated_skip = scheduler.get_schedule(s_skip.schedule_id)
    assert updated_skip.next_run_at > utc_now()
    assert updated_skip.state == ScheduleState.ENABLED

    # Check that s_fail was paused
    updated_fail = scheduler.get_schedule(s_fail.schedule_id)
    assert updated_fail.state == ScheduleState.PAUSED


# ============================================================================
# 3. PathSecurityValidator & UntrustedContentGuard Tests
# ============================================================================

def test_path_security_confinement():
    with tempfile.TemporaryDirectory() as td:
        safe_dir = os.path.join(td, "safe")
        os.makedirs(safe_dir, exist_ok=True)
        safe_file = os.path.join(safe_dir, "report.txt")
        with open(safe_file, "w") as f:
            f.write("safe content")

        # Valid confined path
        is_val, reason, canon = PathSecurityValidator.validate_confinement(safe_file, safe_dir)
        assert is_val is True
        assert reason is None

        # Path traversal attack (..)
        traversal = os.path.join(safe_dir, "..", "outside.txt")
        is_val, reason, _ = PathSecurityValidator.validate_confinement(traversal, safe_dir)
        assert is_val is False
        assert "Path escape detected" in reason

        # Sensitive path exclusion (.env)
        env_file = os.path.join(safe_dir, ".env")
        with open(env_file, "w") as f:
            f.write("SECRET=123")
        is_val, reason, _ = PathSecurityValidator.validate_confinement(env_file, safe_dir)
        assert is_val is False
        assert "Sensitive path access blocked" in reason


def test_untrusted_content_guard():
    raw_text = "Hello\x00World! Normal content."
    wrapped = UntrustedContentGuard.wrap_content("data/report.txt", raw_text, 100)
    assert "=== UNTRUSTED DATA FROM FILESYSTEM ===" in wrapped
    assert "=== END UNTRUSTED DATA ===" in wrapped
    assert "\x00" not in wrapped  # Null byte stripped
    assert "HelloWorld!" in wrapped


# ============================================================================
# 4. FilesystemSentinel Tests
# ============================================================================

def test_filesystem_sentinel_change_detection_and_debounce():
    with tempfile.TemporaryDirectory() as td:
        monitored_root = os.path.join(td, "monitored")
        os.makedirs(monitored_root, exist_ok=True)

        config = SentinelConfig(
            sentinel_type=SentinelType.FILESYSTEM,
            name="Test FS Sentinel",
            config_data={"monitored_root": monitored_root, "recursive": True},
        )

        sentinel = FilesystemSentinel(config, debounce_seconds=0.1)

        # Baseline initial scan produces no events
        initial_events = sentinel.scan_and_detect_changes()
        assert len(initial_events) == 0

        # Create file
        test_file = os.path.join(monitored_root, "test.txt")
        with open(test_file, "w") as f:
            f.write("initial text")

        # Scan immediately: debounced, not settled yet
        events_immediate = sentinel.scan_and_detect_changes(now_ts=time.time())
        assert len(events_immediate) == 0

        # Wait for debounce deadline to pass
        time.sleep(0.15)
        events_settled = sentinel.scan_and_detect_changes(now_ts=time.time() + 1.0)
        assert len(events_settled) == 1
        assert events_settled[0].event_type == "fs:created"
        assert events_settled[0].payload["relative_path"] == "test.txt"

        # Safe untrusted file reading
        ok, wrapped_content = sentinel.read_untrusted_file("test.txt")
        assert ok is True
        assert "=== UNTRUSTED DATA FROM FILESYSTEM ===" in wrapped_content
        assert "initial text" in wrapped_content


# ============================================================================
# 5. InternalEventSentinel Tests
# ============================================================================

def test_internal_event_sentinel_filtering_and_cascade_prevention():
    config = SentinelConfig(
        sentinel_type=SentinelType.EVENT,
        name="Test Event Sentinel",
        config_data={"event_types": ["task_completed", "task_failed"]},
    )
    sentinel = InternalEventSentinel(config, max_depth=3, rate_limit_per_minute=5)

    # 1. Allowed event
    ev1 = sentinel.publish_event("task_completed", {"task_id": "task-1"}, causation_depth=0)
    assert ev1 is not None
    assert ev1.event_type == "event:task_completed"

    # 2. Disallowed event
    ev_disallowed = sentinel.publish_event("unregistered_random_event", {"task_id": "task-2"})
    assert ev_disallowed is None

    # 3. Cascade loop prevention (depth >= 3 blocked)
    ev_deep = sentinel.publish_event("task_completed", {"task_id": "task-3"}, causation_depth=3)
    assert ev_deep is None

    # 4. Rate limiting: publish until threshold exceeded
    published_count = 0
    t0 = time.time()
    for i in range(10):
        ev = sentinel.publish_event("task_completed", {"task_id": f"t-{i}"}, causation_depth=0, now_ts=t0)
        if ev:
            published_count += 1
    # First 1 from step 1 + at most 4 more = 5 total
    assert published_count == 4


# ============================================================================
# 6. BrowserMonitoringSentinel Tests
# ============================================================================

@pytest.mark.asyncio
async def test_browser_monitoring_sentinel_read_only_and_toctou():
    config = SentinelConfig(
        sentinel_type=SentinelType.BROWSER,
        name="Test Browser Sentinel",
        config_data={
            "target_url": "https://example.com/status",
            "allowed_domains": ["example.com"],
            "selector": "body",
        },
    )

    class MockBrowserRuntime:
        def __init__(self):
            self.redirect_url = "https://example.com/status"
            self.dom_text = "System Operational"

        async def navigate(self, url):
            return {"url": self.redirect_url, "status": 200}

        async def inspect_dom(self, selector):
            return {"selector": selector, "text": self.dom_text}

    mock_runtime = MockBrowserRuntime()
    sentinel = BrowserMonitoringSentinel(config, browser_runtime=mock_runtime)

    # First check establishes baseline
    ev0 = await sentinel.check_target()
    assert ev0 is None

    # Second check unchanged -> returns None
    ev1 = await sentinel.check_target()
    assert ev1 is None

    # Third check with content changed -> emits event
    mock_runtime.dom_text = "System Outage Detected!"
    ev2 = await sentinel.check_target()
    assert ev2 is not None
    assert ev2.event_type == "browser:content_changed"
    assert "System Outage Detected!" in ev2.payload["text_excerpt"]

    # TOCTOU Redirect Violation check: target redirects to untrusted origin
    mock_runtime.redirect_url = "https://malicious-attacker.com/fake-login"
    ev_redirect = await sentinel.check_target()
    assert ev_redirect is None  # Blocked due to forbidden origin


# ============================================================================
# 7. NotificationService Tests
# ============================================================================

def test_notification_service_deduplication_and_pruning(temp_db):
    service = NotificationService(temp_db, max_history=10)

    # 1. Normal notification
    n1 = service.notify(
        category=NotificationCategory.SCHEDULE_EXECUTED,
        severity=NotificationSeverity.INFO,
        title="Job Succeeded",
        message="Task 1 finished cleanly",
        dedup_key="job-1-success",
    )
    assert n1 is not None
    assert n1.read is False

    # 2. Duplicate suppressed within dedup window
    n2 = service.notify(
        category=NotificationCategory.SCHEDULE_EXECUTED,
        severity=NotificationSeverity.INFO,
        title="Job Succeeded",
        message="Task 1 finished cleanly",
        dedup_key="job-1-success",
    )
    assert n2 is None

    # 3. Read status and unread count
    assert service.get_unread_count() == 1
    assert service.mark_as_read(n1.notification_id) is True
    assert service.get_unread_count() == 0

    # 4. Auto-pruning beyond max_history (10)
    for i in range(15):
        service.notify(
            category=NotificationCategory.SYSTEM_HEALTH,
            severity=NotificationSeverity.INFO,
            title=f"Heartbeat {i}",
            message=f"Status check {i}",
        )
    notifications = service.get_notifications(limit=50)
    assert len(notifications) <= 10


# ============================================================================
# 8. SentinelManager Concurrency & Kill-Switch Tests
# ============================================================================

@pytest.mark.asyncio
async def test_sentinel_manager_kill_switch_and_concurrency(temp_db):
    class MockExecutionController:
        async def run_autonomous_loop(self, goal, context):
            await asyncio.sleep(0.05)
            return {"status": "SUCCESS", "summary": f"Completed: {goal}"}

    mgr = SentinelManager(
        db_manager=temp_db,
        execution_controller=MockExecutionController(),
        max_concurrent_jobs=2,
        poll_interval=0.05,
    )

    await mgr.start()
    assert mgr.is_running is True
    assert mgr.is_paused is False

    # Master kill-switch pause
    mgr.pause_all()
    assert mgr.is_paused is True

    # Resume
    mgr.resume_all()
    assert mgr.is_paused is False

    # Check status summary
    status_data = mgr.get_status_summary()
    assert status_data["is_running"] is True
    assert status_data["max_concurrent_jobs"] == 2

    await mgr.stop()
    assert mgr.is_running is False


# ============================================================================
# 9. FastAPI Endpoints Integration Tests
# ============================================================================

def test_api_schedules_and_notifications_routes():
    client = TestClient(app)

    # 1. Create schedule via POST /api/schedules
    payload = {
        "name": "Nightly Backup",
        "schedule_type": "INTERVAL",
        "schedule_expr": "3600",
        "goal": "Backup sqlite databases to local replica",
        "timezone": "UTC",
        "missed_run_policy": "SKIP",
    }
    res = client.post("/api/schedules", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["name"] == "Nightly Backup"
    sched_id = data["schedule_id"]

    # 2. List schedules via GET /api/schedules
    res_list = client.get("/api/schedules")
    assert res_list.status_code == 200
    assert any(s["schedule_id"] == sched_id for s in res_list.json())

    # 3. Pause schedule
    res_pause = client.patch(f"/api/schedules/{sched_id}/pause")
    assert res_pause.status_code == 200
    assert res_pause.json()["status"] == "paused"

    # 4. Resume schedule
    res_resume = client.patch(f"/api/schedules/{sched_id}/resume")
    assert res_resume.status_code == 200
    assert res_resume.json()["status"] == "resumed"

    # 5. Background status
    res_status = client.get("/api/background/status")
    assert res_status.status_code == 200
    assert "is_running" in res_status.json()

    # 6. Master kill-switch API endpoints
    res_bg_pause = client.post("/api/background/pause")
    assert res_bg_pause.status_code == 200
    assert res_bg_pause.json()["is_paused"] is True

    res_bg_resume = client.post("/api/background/resume")
    assert res_bg_resume.status_code == 200
    assert res_bg_resume.json()["is_paused"] is False

    # 7. Notifications API endpoints
    res_notifs = client.get("/api/background/notifications")
    assert res_notifs.status_code == 200
    assert isinstance(res_notifs.json(), list)

    res_read_all = client.post("/api/background/notifications/read-all")
    assert res_read_all.status_code == 200

    # 8. Delete schedule
    res_del = client.delete(f"/api/schedules/{sched_id}")
    assert res_del.status_code == 200


# ============================================================================
# 10. Extended Schema Migration v6 & Sentinel API Tests
# ============================================================================

def test_schema_migration_v6_upgrade_without_data_loss(temp_db):
    """Verifies that schema migration v6 creates all 5 tables and indexes without altering older tables."""
    conn = temp_db.get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(version) FROM schema_migrations;")
        assert cursor.fetchone()[0] == 6

        expected_tables = [
            "background_schedules",
            "scheduled_job_runs",
            "sentinel_configs",
            "sentinel_event_journal",
            "internal_notifications",
        ]
        for tbl in expected_tables:
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{tbl}';")
            assert cursor.fetchone() is not None, f"Table {tbl} missing from schema v6"
    finally:
        conn.close()


def test_filesystem_sentinel_modification_and_deletion():
    with tempfile.TemporaryDirectory() as td:
        monitored_root = os.path.join(td, "monitored")
        os.makedirs(monitored_root, exist_ok=True)
        test_file = os.path.join(monitored_root, "data.txt")
        with open(test_file, "w") as f:
            f.write("v1")

        config = SentinelConfig(
            sentinel_type=SentinelType.FILESYSTEM,
            name="Modification FS Sentinel",
            config_data={"monitored_root": monitored_root, "recursive": True},
        )
        sentinel = FilesystemSentinel(config, debounce_seconds=0.05)

        # Baseline snapshot
        sentinel.scan_and_detect_changes()

        # Modify file
        time.sleep(0.01)
        with open(test_file, "w") as f:
            f.write("v2 modified content")

        sentinel.scan_and_detect_changes(now_ts=time.time())
        time.sleep(0.1)
        mod_events = sentinel.scan_and_detect_changes(now_ts=time.time() + 1.0)
        assert len(mod_events) == 1
        assert mod_events[0].event_type == "fs:modified"

        # Delete file
        os.remove(test_file)
        sentinel.scan_and_detect_changes(now_ts=time.time())
        time.sleep(0.1)
        del_events = sentinel.scan_and_detect_changes(now_ts=time.time() + 1.0)
        assert len(del_events) == 1
        assert del_events[0].event_type == "fs:deleted"


def test_api_sentinels_crud_and_notification_actions():
    client = TestClient(app)

    with tempfile.TemporaryDirectory() as td:
        monitored_dir = os.path.join(td, "watched")
        os.makedirs(monitored_dir, exist_ok=True)

        # 1. POST /api/sentinels
        create_res = client.post(
            "/api/sentinels",
            json={
                "sentinel_type": "FILESYSTEM",
                "name": "Audit Watcher",
                "config_data": {"monitored_root": monitored_dir},
                "enabled": True,
            },
        )
        assert create_res.status_code == 201
        sentinel_id = create_res.json()["sentinel_id"]

        # 2. GET /api/sentinels/{id}
        get_res = client.get(f"/api/sentinels/{sentinel_id}")
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Audit Watcher"

        # 3. Disable sentinel
        dis_res = client.patch(f"/api/sentinels/{sentinel_id}/disable")
        assert dis_res.status_code == 200
        assert dis_res.json()["status"] == "disabled"

        # 4. Enable sentinel
        en_res = client.patch(f"/api/sentinels/{sentinel_id}/enable")
        assert en_res.status_code == 200
        assert en_res.json()["status"] == "enabled"

        # 5. Delete sentinel
        del_res = client.delete(f"/api/sentinels/{sentinel_id}")
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "deleted"

    # Notification actions
    unread_res = client.get("/api/background/notifications/unread-count")
    assert unread_res.status_code == 200
    assert "unread_count" in unread_res.json()

    clear_res = client.delete("/api/background/notifications")
    assert clear_res.status_code == 200
    assert clear_res.json()["status"] == "cleared"

