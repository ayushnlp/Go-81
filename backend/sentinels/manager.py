"""
Sentinel Manager for Go 81 Stage 9.
Coordinates background sentinels, persistent schedules, bounded concurrency execution,
startup recovery, master kill-switch pausing, and notification dispatch.
"""

import asyncio
from datetime import datetime, timezone
import json
import logging
import sqlite3
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

from app.memory.database import DatabaseManager, utc_now
from backend.sentinels.browser_sentinel import BrowserMonitoringSentinel
from backend.sentinels.event_sentinel import InternalEventSentinel
from backend.sentinels.filesystem_sentinel import FilesystemSentinel
from backend.sentinels.models import (
    InternalNotification,
    JobRunStatus,
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
from backend.sentinels.scheduler import PersistentScheduler

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY_LIMIT = 3
DEFAULT_POLL_INTERVAL_SECONDS = 1.0


class SentinelManager:
    """
    Central coordinator for Go 81 background sentinels and persistent scheduler.
    """

    def __init__(
        self,
        db_manager: DatabaseManager,
        scheduler: Optional[PersistentScheduler] = None,
        notification_service: Optional[NotificationService] = None,
        execution_controller: Optional[Any] = None,
        browser_runtime: Optional[Any] = None,
        max_concurrent_jobs: int = DEFAULT_CONCURRENCY_LIMIT,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    ):
        self.db = db_manager
        self.db.apply_migration_v6()

        self.scheduler = scheduler or PersistentScheduler(self.db)
        self.notifications = notification_service or NotificationService(self.db)
        self.execution_controller = execution_controller
        self.browser_runtime = browser_runtime

        self.max_concurrent_jobs = max_concurrent_jobs
        self.poll_interval = poll_interval
        self.worker_id = f"sentinel-worker-{uuid.uuid4().hex[:8]}"

        self._semaphore = asyncio.Semaphore(max_concurrent_jobs)
        self._sentinels: Dict[str, Any] = {}  # sentinel_id -> sentinel instance
        self._is_running = False
        self._is_paused = False
        self._poll_task: Optional[asyncio.Task] = None
        self._active_tasks: Dict[str, asyncio.Task] = {}

    # ========================================================================
    # Lifecycle & Master Controls
    # ========================================================================

    async def start(self) -> None:
        """
        Starts the Sentinel Manager background loop.
        Recovers expired leases, processes missed runs, and loads active sentinels.
        """
        if self._is_running:
            return

        logger.info(f"Starting SentinelManager [{self.worker_id}]")
        self._is_running = True

        # 1. Startup recovery: release expired leases from previous crashes
        recovered_leases = self.scheduler.release_expired_leases()
        if recovered_leases > 0:
            logger.info(f"Recovered {recovered_leases} expired schedule leases")
            self.notifications.notify(
                category=NotificationCategory.SYSTEM_HEALTH,
                severity=NotificationSeverity.WARNING,
                title="Schedule Leases Recovered",
                message=f"Reset {recovered_leases} stale schedule leases following startup recovery.",
            )

        # 2. Process missed runs
        missed = self.scheduler.handle_missed_runs(tolerance_seconds=60.0)
        for sched, missed_time, action in missed:
            logger.info(f"Missed run detected for '{sched.name}' at {missed_time}: action {action}")
            self.notifications.notify(
                category=NotificationCategory.SCHEDULE_MISSED,
                severity=NotificationSeverity.WARNING if action == "SKIPPED" else NotificationSeverity.ERROR,
                title=f"Schedule Missed: {sched.name}",
                message=f"Schedule '{sched.name}' missed its planned run at {missed_time}. Policy applied: {action}",
                metadata={"schedule_id": sched.schedule_id, "action": action},
            )

        # 3. Load sentinels from database
        self._load_sentinels_from_db()

        # 4. Start background polling loop
        self._poll_task = asyncio.create_task(self._main_poll_loop())

    async def stop(self, drain_timeout: float = 5.0) -> None:
        """
        Stops the Sentinel Manager cleanly.
        Cancels polling loop, waits for in-flight tasks to finish (or timeout), and resets state.
        """
        if not self._is_running:
            return

        logger.info(f"Stopping SentinelManager [{self.worker_id}]")
        self._is_running = False

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass

        # Wait for active tasks to drain
        if self._active_tasks:
            logger.info(f"Draining {len(self._active_tasks)} in-flight background jobs...")
            start_drain = time.time()
            while self._active_tasks and (time.time() - start_drain) < drain_timeout:
                await asyncio.sleep(0.1)

            # Cancel remaining tasks that exceeded timeout
            for task_id, t in list(self._active_tasks.items()):
                if not t.done():
                    t.cancel()

        logger.info("SentinelManager stopped cleanly")

    def pause_all(self) -> None:
        """Master kill-switch: immediately halts all dispatch of new background tasks."""
        self._is_paused = True
        logger.warning("SentinelManager MASTER KILL-SWITCH ACTIVATED: all background execution paused")
        self.notifications.notify(
            category=NotificationCategory.SYSTEM_HEALTH,
            severity=NotificationSeverity.WARNING,
            title="Background Execution Paused",
            message="Master kill-switch activated. All background sentinels and schedules are paused.",
        )

    def resume_all(self) -> None:
        """Resumes background execution after pausing."""
        self._is_paused = False
        logger.info("SentinelManager resumed normal background execution")
        self.notifications.notify(
            category=NotificationCategory.SYSTEM_HEALTH,
            severity=NotificationSeverity.INFO,
            title="Background Execution Resumed",
            message="Normal background sentinel and schedule execution resumed.",
        )

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def is_running(self) -> bool:
        return self._is_running

    # ========================================================================
    # Main Polling Loop
    # ========================================================================

    async def _main_poll_loop(self) -> None:
        """Periodic background loop that evaluates schedules and checks active sentinels."""
        while self._is_running:
            try:
                if not self._is_paused:
                    # 1. Claim and dispatch due schedules
                    await self._dispatch_due_schedules()

                    # 2. Poll filesystem sentinels
                    self._poll_filesystem_sentinels()

                await asyncio.sleep(self.poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Unexpected error in SentinelManager main loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval)

    async def _dispatch_due_schedules(self) -> None:
        """Claims due schedules and spawns bounded worker tasks."""
        due = self.scheduler.claim_due_schedules(lease_holder=self.worker_id, lease_duration_seconds=120.0)
        for sched, scheduled_time in due:
            job_task = asyncio.create_task(self._execute_scheduled_job(sched, scheduled_time))
            task_key = f"{sched.schedule_id}:{scheduled_time}"
            self._active_tasks[task_key] = job_task
            job_task.add_done_callback(lambda t, k=task_key: self._active_tasks.pop(k, None))

    async def _execute_scheduled_job(self, sched: PersistentSchedule, scheduled_time_iso: str) -> None:
        """Executes a single scheduled job within the semaphore concurrency boundary."""
        async with self._semaphore:
            # 1. Record job run start (enforces idempotency_key UNIQUE constraint)
            try:
                job_run = self.scheduler.record_job_run_start(sched.schedule_id, scheduled_time_iso)
            except sqlite3.IntegrityError:
                logger.warning(
                    f"Job run for schedule '{sched.name}' at {scheduled_time_iso} already exists. Skipping duplicate dispatch."
                )
                return

            logger.info(f"Executing scheduled job '{sched.name}' (run {job_run.run_id})")
            run_status = JobRunStatus.SUCCESS
            result_summary = ""
            error_message = None

            try:
                if self.execution_controller:
                    # Execute via AutonomousExecutionController
                    if hasattr(self.execution_controller, "run_autonomous_loop"):
                        loop_res = await self.execution_controller.run_autonomous_loop(
                            goal=sched.goal,
                            context=sched.parameters,
                        )
                        result_summary = str(loop_res.get("summary", "Autonomous goal executed"))
                        if loop_res.get("status") in ("FAILED", "BLOCKED"):
                            run_status = JobRunStatus.FAILED
                            error_message = loop_res.get("error")
                    else:
                        result_summary = f"Executed goal: {sched.goal}"
                else:
                    result_summary = f"Scheduled goal '{sched.goal}' executed successfully"

            except Exception as e:
                run_status = JobRunStatus.FAILED
                error_message = str(e)
                logger.error(f"Error executing scheduled job '{sched.name}': {e}", exc_info=True)

            # 2. Complete job run and update schedule state
            self.scheduler.complete_job_run(
                schedule_id=sched.schedule_id,
                run_id=job_run.run_id,
                status=run_status,
                result_summary=result_summary,
                error_message=error_message,
            )

            # 3. Emit notification
            self.notifications.notify(
                category=NotificationCategory.SCHEDULE_EXECUTED,
                severity=NotificationSeverity.INFO if run_status == JobRunStatus.SUCCESS else NotificationSeverity.ERROR,
                title=f"Schedule Executed: {sched.name}",
                message=f"Schedule '{sched.name}' finished with status {run_status.value}. Summary: {result_summary}",
                metadata={"schedule_id": sched.schedule_id, "status": run_status.value},
            )

    def _poll_filesystem_sentinels(self) -> None:
        """Polls registered filesystem sentinels for settled change events."""
        for sentinel in list(self._sentinels.values()):
            if isinstance(sentinel, FilesystemSentinel) and sentinel.status == SentinelStatus.ACTIVE:
                events = sentinel.scan_and_detect_changes()
                for ev in events:
                    self._record_sentinel_event(ev)

    def _record_sentinel_event(self, event: SentinelEvent) -> None:
        """Records a sentinel event into the durable event journal with duplicate prevention."""
        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO sentinel_event_journal (
                        event_id, sentinel_id, event_type, fingerprint,
                        payload, handled, task_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        event.event_id,
                        event.sentinel_id,
                        event.event_type,
                        event.fingerprint,
                        json.dumps(event.payload),
                        1 if event.handled else 0,
                        event.task_id,
                        event.created_at,
                    ),
                )
        except sqlite3.IntegrityError:
            # Duplicate event fingerprint already logged
            return

        # Emit in-app notification for event
        self.notifications.notify(
            category=NotificationCategory.FILE_CHANGE_TRIGGER,
            severity=NotificationSeverity.INFO,
            title=f"Sentinel Triggered: {event.event_type}",
            message=f"Observed event on sentinel {event.sentinel_id}: {json.dumps(event.payload)[:150]}",
            metadata={"event_id": event.event_id, "fingerprint": event.fingerprint},
            dedup_key=f"event:{event.sentinel_id}:{event.event_type}",
        )

    # ========================================================================
    # Sentinel Management CRUD
    # ========================================================================

    def register_sentinel_config(
        self,
        sentinel_type: SentinelType,
        name: str,
        config_data: Dict[str, Any],
        enabled: bool = True,
    ) -> SentinelConfig:
        """Creates and stores a new sentinel configuration."""
        sentinel_id = str(uuid.uuid4())
        now_iso = utc_now()
        config = SentinelConfig(
            sentinel_id=sentinel_id,
            sentinel_type=sentinel_type,
            name=name,
            enabled=enabled,
            config_data=config_data,
            created_at=now_iso,
            updated_at=now_iso,
        )

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO sentinel_configs (
                    sentinel_id, sentinel_type, name, enabled, config_data, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    config.sentinel_id,
                    config.sentinel_type.value,
                    config.name,
                    1 if config.enabled else 0,
                    json.dumps(config.config_data),
                    config.created_at,
                    config.updated_at,
                ),
            )

        self._instantiate_sentinel(config)
        return config

    def get_sentinel_config(self, sentinel_id: str) -> Optional[SentinelConfig]:
        """Retrieves a sentinel config by ID."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sentinel_configs WHERE sentinel_id = ?;", (sentinel_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_sentinel_config(row)
        finally:
            conn.close()

    def list_sentinel_configs(self) -> List[SentinelConfig]:
        """Lists all stored sentinel configurations."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sentinel_configs ORDER BY created_at DESC;")
            rows = cursor.fetchall()
            return [self._row_to_sentinel_config(r) for r in rows]
        finally:
            conn.close()

    def set_sentinel_enabled(self, sentinel_id: str, enabled: bool) -> bool:
        """Enables or disables a sentinel configuration."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sentinel_configs SET enabled = ?, updated_at = ? WHERE sentinel_id = ?;",
                (1 if enabled else 0, utc_now(), sentinel_id),
            )
            updated = cursor.rowcount > 0

        if updated and sentinel_id in self._sentinels:
            instance = self._sentinels[sentinel_id]
            instance.status = SentinelStatus.ACTIVE if enabled else SentinelStatus.PAUSED
        return updated

    def remove_sentinel(self, sentinel_id: str) -> bool:
        """Removes a sentinel and unregisters its runtime instance."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM sentinel_configs WHERE sentinel_id = ?;", (sentinel_id,))
            removed = cursor.rowcount > 0

        self._sentinels.pop(sentinel_id, None)
        return removed

    def get_sentinel_instance(self, sentinel_id: str) -> Optional[Any]:
        """Returns the in-memory active sentinel instance."""
        return self._sentinels.get(sentinel_id)

    def _instantiate_sentinel(self, config: SentinelConfig) -> None:
        """Constructs an active sentinel runtime instance from config."""
        try:
            if config.sentinel_type == SentinelType.FILESYSTEM:
                sentinel = FilesystemSentinel(config, on_event_cb=self._record_sentinel_event)
                self._sentinels[config.sentinel_id] = sentinel
            elif config.sentinel_type == SentinelType.EVENT:
                sentinel = InternalEventSentinel(config, on_event_cb=self._record_sentinel_event)
                self._sentinels[config.sentinel_id] = sentinel
            elif config.sentinel_type == SentinelType.BROWSER:
                sentinel = BrowserMonitoringSentinel(
                    config, browser_runtime=self.browser_runtime, on_event_cb=self._record_sentinel_event
                )
                self._sentinels[config.sentinel_id] = sentinel
        except Exception as e:
            logger.error(f"Failed to instantiate sentinel {config.name}: {e}")

    def _load_sentinels_from_db(self) -> None:
        """Loads and instantiates all enabled sentinels from database."""
        configs = self.list_sentinel_configs()
        for cfg in configs:
            if cfg.enabled:
                self._instantiate_sentinel(cfg)

    def get_status_summary(self) -> Dict[str, Any]:
        """Returns a comprehensive diagnostic status of background execution."""
        schedules = self.scheduler.list_schedules()
        active_schedules = [s for s in schedules if s.state == ScheduleState.ENABLED]
        sentinels = self.list_sentinel_configs()
        active_sentinels = [s for s in sentinels if s.enabled]

        return {
            "worker_id": self.worker_id,
            "is_running": self._is_running,
            "is_paused": self._is_paused,
            "active_tasks_count": len(self._active_tasks),
            "max_concurrent_jobs": self.max_concurrent_jobs,
            "schedules_total": len(schedules),
            "schedules_active": len(active_schedules),
            "sentinels_total": len(sentinels),
            "sentinels_active": len(active_sentinels),
            "unread_notifications": self.notifications.get_unread_count(),
        }

    def _row_to_sentinel_config(self, row: sqlite3.Row) -> SentinelConfig:
        cfg_data = json.loads(row["config_data"]) if row["config_data"] else {}
        return SentinelConfig(
            sentinel_id=row["sentinel_id"],
            sentinel_type=SentinelType(row["sentinel_type"]),
            name=row["name"],
            enabled=bool(row["enabled"]),
            config_data=cfg_data,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

