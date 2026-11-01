"""
Persistent Scheduler and pure-Python Cron Evaluator for Go 81 Stage 9.
Supports ONE_TIME, INTERVAL, and 5-part CRON schedules with IANA timezone support,
atomic lease claiming, missed-run policies, and deterministic idempotency keys.
"""

from datetime import datetime, timedelta, timezone
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import uuid
import zoneinfo

from app.memory.database import DatabaseManager, utc_now
from backend.sentinels.models import (
    JobRunStatus,
    MissedRunPolicy,
    PersistentSchedule,
    ScheduledJobRun,
    ScheduleState,
    ScheduleType,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Pure-Python Cron Evaluator (Standard 5 Fields)
# ============================================================================

class CronEvaluator:
    """
    Evaluates standard 5-part cron expressions without external dependencies.
    Format: MINUTE (0-59) HOUR (0-23) DAY_OF_MONTH (1-31) MONTH (1-12) DAY_OF_WEEK (0-7, 0 or 7 is Sun)
    Supports wildcards (*), steps (/), ranges (-), and comma-separated lists (,).
    """

    MONTH_NAMES = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12
    }
    DOW_NAMES = {
        "SUN": 0, "MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6
    }

    def __init__(self, expr: str, tz_name: str = "UTC"):
        self.expr = expr.strip()
        self.tz_name = tz_name
        try:
            self.tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            logger.warning(f"Unknown timezone '{tz_name}', falling back to UTC")
            self.tz = timezone.utc

        parts = self.expr.split()
        if len(parts) != 5:
            raise ValueError(f"Cron expression must contain exactly 5 fields, got: '{expr}'")

        self.min_set = self._parse_field(parts[0], 0, 59)
        self.hour_set = self._parse_field(parts[1], 0, 23)
        self.dom_set = self._parse_field(parts[2], 1, 31)
        self.month_set = self._parse_field(parts[3], 1, 12, name_map=self.MONTH_NAMES)
        self.dow_set = self._parse_field(parts[4], 0, 7, name_map=self.DOW_NAMES)
        # Normalize day 7 (Sunday) to 0
        if 7 in self.dow_set:
            self.dow_set.add(0)

    def _parse_field(self, field_str: str, min_val: int, max_val: int, name_map: Optional[Dict[str, int]] = None) -> set:
        """Parses a single cron field into a set of matching integer values."""
        results = set()
        for sub in field_str.split(","):
            sub = sub.strip().upper()
            if not sub:
                continue

            # Replace names if present
            if name_map:
                for name, val in name_map.items():
                    sub = sub.replace(name, str(val))

            if sub == "*":
                results.update(range(min_val, max_val + 1))
            elif "/" in sub:
                parts = sub.split("/")
                step = int(parts[1])
                if parts[0] == "*":
                    start, end = min_val, max_val
                elif "-" in parts[0]:
                    r_parts = parts[0].split("-")
                    start, end = int(r_parts[0]), int(r_parts[1])
                else:
                    start, end = int(parts[0]), max_val
                results.update(range(start, end + 1, step))
            elif "-" in sub:
                r_parts = sub.split("-")
                start, end = int(r_parts[0]), int(r_parts[1])
                results.update(range(start, end + 1))
            else:
                val = int(sub)
                if min_val <= val <= max_val:
                    results.add(val)
                else:
                    raise ValueError(f"Value {val} out of bounds [{min_val}, {max_val}]")
        return results

    def matches(self, dt: datetime) -> bool:
        """Checks if the given localized datetime matches the cron definition."""
        local_dt = dt.astimezone(self.tz)
        if local_dt.minute not in self.min_set:
            return False
        if local_dt.hour not in self.hour_set:
            return False
        if local_dt.day not in self.dom_set:
            return False
        if local_dt.month not in self.month_set:
            return False
        dow = local_dt.weekday()  # Monday=0 ... Sunday=6
        # Convert python weekday (Mon=0..Sun=6) to cron dow (Sun=0..Sat=6)
        cron_dow = (dow + 1) % 7
        if cron_dow not in self.dow_set:
            return False
        return True

    def next_run(self, base_dt: datetime, max_search_minutes: int = 527040) -> datetime:
        """
        Finds the next matching datetime strictly after base_dt.
        Steps minute-by-minute in UTC and tests localized matches, ensuring DST safety.
        """
        if base_dt.tzinfo is None:
            base_dt = base_dt.replace(tzinfo=timezone.utc)
        else:
            base_dt = base_dt.astimezone(timezone.utc)

        # Truncate seconds and microseconds, then advance by 1 minute
        current = base_dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(max_search_minutes):
            if self.matches(current):
                return current
            current += timedelta(minutes=1)

        raise TimeoutError(f"No matching cron execution found within {max_search_minutes} minutes for '{self.expr}'")


# ============================================================================
# Persistent Scheduler
# ============================================================================

class PersistentScheduler:
    """
    Durable, database-backed scheduler supporting ONE_TIME, INTERVAL, and CRON jobs.
    Uses atomic leases to eliminate duplicate runs and supports missed-run catchup.
    """

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        # Ensure migration v6 has been applied
        self.db.apply_migration_v6()

    def calculate_next_run(
        self,
        schedule_type: ScheduleType,
        schedule_expr: str,
        tz_name: str,
        base_time: Optional[datetime] = None,
    ) -> Optional[datetime]:
        """Calculates the next run datetime (in UTC) for a schedule."""
        now_utc = base_time or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

        if schedule_type == ScheduleType.ONE_TIME:
            try:
                target = datetime.fromisoformat(schedule_expr.replace("Z", "+00:00"))
                if target.tzinfo is None:
                    target = target.replace(tzinfo=timezone.utc)
                return target if target > now_utc else None
            except Exception as e:
                logger.error(f"Failed to parse ONE_TIME schedule_expr '{schedule_expr}': {e}")
                return None

        elif schedule_type == ScheduleType.INTERVAL:
            try:
                seconds = int(schedule_expr)
                if seconds <= 0:
                    raise ValueError("Interval must be positive")
                return now_utc + timedelta(seconds=seconds)
            except Exception as e:
                logger.error(f"Failed to parse INTERVAL schedule_expr '{schedule_expr}': {e}")
                return None

        elif schedule_type == ScheduleType.CRON:
            try:
                evaluator = CronEvaluator(schedule_expr, tz_name)
                return evaluator.next_run(now_utc)
            except Exception as e:
                logger.error(f"Failed to evaluate CRON schedule_expr '{schedule_expr}': {e}")
                return None

        return None

    def create_schedule(
        self,
        name: str,
        schedule_type: ScheduleType,
        schedule_expr: str,
        goal: str,
        timezone_str: str = "UTC",
        parameters: Optional[Dict[str, Any]] = None,
        missed_run_policy: MissedRunPolicy = MissedRunPolicy.SKIP,
        max_runs: Optional[int] = None,
    ) -> PersistentSchedule:
        """Creates and stores a new persistent schedule."""
        sched_id = str(uuid.uuid4())
        now_iso = utc_now()
        now_dt = datetime.now(timezone.utc)

        next_dt = self.calculate_next_run(schedule_type, schedule_expr, timezone_str, now_dt)
        next_run_iso = next_dt.isoformat() if next_dt else None

        schedule = PersistentSchedule(
            schedule_id=sched_id,
            name=name,
            schedule_type=schedule_type,
            schedule_expr=schedule_expr,
            timezone=timezone_str,
            goal=goal,
            parameters=parameters or {},
            state=ScheduleState.ENABLED,
            missed_run_policy=missed_run_policy,
            max_runs=max_runs,
            runs_completed=0,
            next_run_at=next_run_iso,
            last_run_at=None,
            lease_holder=None,
            lease_expires_at=None,
            created_at=now_iso,
            updated_at=now_iso,
        )

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO background_schedules (
                    schedule_id, name, schedule_type, schedule_expr, timezone,
                    goal, parameters, state, missed_run_policy, max_runs,
                    runs_completed, next_run_at, last_run_at, lease_holder,
                    lease_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    schedule.schedule_id,
                    schedule.name,
                    schedule.schedule_type.value,
                    schedule.schedule_expr,
                    schedule.timezone,
                    schedule.goal,
                    json.dumps(schedule.parameters),
                    schedule.state.value,
                    schedule.missed_run_policy.value,
                    schedule.max_runs,
                    schedule.runs_completed,
                    schedule.next_run_at,
                    schedule.last_run_at,
                    schedule.lease_holder,
                    schedule.lease_expires_at,
                    schedule.created_at,
                    schedule.updated_at,
                ),
            )

        logger.info(f"Created persistent schedule {sched_id} ({name}), next run: {next_run_iso}")
        return schedule

    def get_schedule(self, schedule_id: str) -> Optional[PersistentSchedule]:
        """Retrieves a persistent schedule by ID."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM background_schedules WHERE schedule_id = ?;", (schedule_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_schedule(row)
        finally:
            conn.close()

    def list_schedules(self, state: Optional[ScheduleState] = None) -> List[PersistentSchedule]:
        """Lists persistent schedules, optionally filtered by state."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            if state:
                cursor.execute("SELECT * FROM background_schedules WHERE state = ? ORDER BY created_at DESC;", (state.value,))
            else:
                cursor.execute("SELECT * FROM background_schedules ORDER BY created_at DESC;")
            rows = cursor.fetchall()
            return [self._row_to_schedule(r) for r in rows]
        finally:
            conn.close()

    def pause_schedule(self, schedule_id: str) -> bool:
        """Pauses an active schedule."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE background_schedules SET state = ?, updated_at = ? WHERE schedule_id = ? AND state != ?;",
                (ScheduleState.PAUSED.value, utc_now(), schedule_id, ScheduleState.CANCELLED.value),
            )
            return cursor.rowcount > 0

    def resume_schedule(self, schedule_id: str) -> bool:
        """Resumes a paused schedule and recalculates next_run_at."""
        sched = self.get_schedule(schedule_id)
        if not sched or sched.state not in (ScheduleState.PAUSED, ScheduleState.ENABLED):
            return False

        now_dt = datetime.now(timezone.utc)
        next_dt = self.calculate_next_run(sched.schedule_type, sched.schedule_expr, sched.timezone, now_dt)
        next_run_iso = next_dt.isoformat() if next_dt else None

        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE background_schedules
                SET state = ?, next_run_at = ?, updated_at = ?
                WHERE schedule_id = ?;
                """,
                (ScheduleState.ENABLED.value, next_run_iso, utc_now(), schedule_id),
            )
            return cursor.rowcount > 0

    def cancel_schedule(self, schedule_id: str) -> bool:
        """Cancels a schedule permanently."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE background_schedules SET state = ?, next_run_at = NULL, updated_at = ? WHERE schedule_id = ?;",
                (ScheduleState.CANCELLED.value, utc_now(), schedule_id),
            )
            return cursor.rowcount > 0

    def delete_schedule(self, schedule_id: str) -> bool:
        """Deletes a schedule and its run records."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM background_schedules WHERE schedule_id = ?;", (schedule_id,))
            return cursor.rowcount > 0

    def claim_due_schedules(
        self,
        lease_holder: str,
        lease_duration_seconds: float = 60.0,
        now_dt: Optional[datetime] = None,
    ) -> List[Tuple[PersistentSchedule, str]]:
        """
        Atomically finds and leases due schedules whose next_run_at <= now.
        Returns list of (schedule, scheduled_time_iso).
        Guarantees that only one worker can lease a given scheduled run.
        """
        current_time = now_dt or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        now_iso = current_time.isoformat()
        current_ts = current_time.timestamp()
        lease_expires_at = current_ts + lease_duration_seconds

        claimed = []
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            # Select eligible schedules: ENABLED, next_run_at <= now, and lease either expired or not held
            cursor.execute(
                """
                SELECT schedule_id, next_run_at FROM background_schedules
                WHERE state = 'ENABLED'
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
                  AND (lease_holder IS NULL OR lease_expires_at < ?)
                ORDER BY next_run_at ASC;
                """,
                (now_iso, current_ts),
            )
            candidates = cursor.fetchall()
        finally:
            conn.close()

        for cand in candidates:
            sched_id = cand["schedule_id"]
            scheduled_time = cand["next_run_at"]
            # Attempt atomic lease claim
            with self.db.transaction() as tx_conn:
                cursor = tx_conn.cursor()
                cursor.execute(
                    """
                    UPDATE background_schedules
                    SET state = 'RUNNING',
                        lease_holder = ?,
                        lease_expires_at = ?,
                        updated_at = ?
                    WHERE schedule_id = ?
                      AND state = 'ENABLED'
                      AND next_run_at = ?
                      AND (lease_holder IS NULL OR lease_expires_at < ?);
                    """,
                    (lease_holder, lease_expires_at, utc_now(), sched_id, scheduled_time, current_ts),
                )
                if cursor.rowcount > 0:
                    sched = self.get_schedule(sched_id)
                    if sched:
                        claimed.append((sched, scheduled_time))

        return claimed

    def record_job_run_start(self, schedule_id: str, scheduled_time_iso: str, task_id: Optional[str] = None) -> ScheduledJobRun:
        """
        Records the start of a job run with a deterministic idempotency key.
        Raises sqlite3.IntegrityError if a run for this (schedule_id, scheduled_time) already exists.
        """
        idempotency_key = f"{schedule_id}:{scheduled_time_iso}"
        run_id = str(uuid.uuid4())
        now_iso = utc_now()

        job_run = ScheduledJobRun(
            run_id=run_id,
            schedule_id=schedule_id,
            idempotency_key=idempotency_key,
            scheduled_time=scheduled_time_iso,
            started_at=now_iso,
            completed_at=None,
            status=JobRunStatus.RUNNING,
            task_id=task_id,
            error_message=None,
            result_summary=None,
            created_at=now_iso,
        )

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_job_runs (
                    run_id, schedule_id, idempotency_key, scheduled_time,
                    started_at, completed_at, status, task_id, error_message,
                    result_summary, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    job_run.run_id,
                    job_run.schedule_id,
                    job_run.idempotency_key,
                    job_run.scheduled_time,
                    job_run.started_at,
                    job_run.completed_at,
                    job_run.status.value,
                    job_run.task_id,
                    job_run.error_message,
                    job_run.result_summary,
                    job_run.created_at,
                ),
            )

        return job_run

    def complete_job_run(
        self,
        schedule_id: str,
        run_id: str,
        status: JobRunStatus,
        result_summary: str = "",
        error_message: Optional[str] = None,
        now_dt: Optional[datetime] = None,
    ) -> None:
        """
        Completes a job run, increments runs_completed, releases lease,
        and calculates next_run_at according to schedule definition and max_runs.
        """
        completion_dt = now_dt or datetime.now(timezone.utc)
        if completion_dt.tzinfo is None:
            completion_dt = completion_dt.replace(tzinfo=timezone.utc)
        completion_iso = completion_dt.isoformat()

        sched = self.get_schedule(schedule_id)
        if not sched:
            logger.warning(f"Schedule {schedule_id} not found when completing run {run_id}")
            return

        new_runs_completed = sched.runs_completed + 1
        is_completed = False

        if sched.schedule_type == ScheduleType.ONE_TIME:
            is_completed = True
            next_run_iso = None
        elif sched.max_runs is not None and new_runs_completed >= sched.max_runs:
            is_completed = True
            next_run_iso = None
        else:
            next_dt = self.calculate_next_run(sched.schedule_type, sched.schedule_expr, sched.timezone, completion_dt)
            next_run_iso = next_dt.isoformat() if next_dt else None
            if next_run_iso is None:
                is_completed = True

        new_state = ScheduleState.COMPLETED if is_completed else ScheduleState.ENABLED

        with self.db.transaction() as conn:
            # 1. Update scheduled_job_runs
            conn.execute(
                """
                UPDATE scheduled_job_runs
                SET completed_at = ?, status = ?, result_summary = ?, error_message = ?
                WHERE run_id = ?;
                """,
                (completion_iso, status.value, result_summary, error_message, run_id),
            )
            # 2. Update background_schedules
            conn.execute(
                """
                UPDATE background_schedules
                SET state = ?,
                    runs_completed = ?,
                    last_run_at = ?,
                    next_run_at = ?,
                    lease_holder = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE schedule_id = ?;
                """,
                (new_state.value, new_runs_completed, completion_iso, next_run_iso, completion_iso, schedule_id),
            )

        logger.info(f"Schedule {schedule_id} run {run_id} finished with {status.value}. Next state: {new_state.value}, next run: {next_run_iso}")

    def handle_missed_runs(
        self,
        tolerance_seconds: float = 60.0,
        now_dt: Optional[datetime] = None,
    ) -> List[Tuple[PersistentSchedule, str, str]]:
        """
        Inspects overdue schedules after downtime.
        Returns list of tuples: (schedule, missed_time_iso, action_taken).
        Action taken: 'RUN_ONCE', 'SKIPPED', 'FAILED'.
        """
        current_time = now_dt or datetime.now(timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        threshold_dt = current_time - timedelta(seconds=tolerance_seconds)
        threshold_iso = threshold_dt.isoformat()
        current_iso = current_time.isoformat()

        results = []
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM background_schedules
                WHERE state = 'ENABLED'
                  AND next_run_at IS NOT NULL
                  AND next_run_at < ?;
                """,
                (threshold_iso,),
            )
            rows = cursor.fetchall()
            overdue_schedules = [self._row_to_schedule(r) for r in rows]
        finally:
            conn.close()

        for sched in overdue_schedules:
            missed_time = sched.next_run_at
            if sched.missed_run_policy == MissedRunPolicy.SKIP:
                # Advance next_run_at to the next future occurrence
                next_dt = self.calculate_next_run(sched.schedule_type, sched.schedule_expr, sched.timezone, current_time)
                next_run_iso = next_dt.isoformat() if next_dt else None
                new_state = ScheduleState.COMPLETED if (next_run_iso is None and sched.schedule_type == ScheduleType.ONE_TIME) else ScheduleState.ENABLED
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE background_schedules SET state = ?, next_run_at = ?, updated_at = ? WHERE schedule_id = ?;",
                        (new_state.value, next_run_iso, current_iso, sched.schedule_id),
                    )
                results.append((sched, missed_time, "SKIPPED"))

            elif sched.missed_run_policy == MissedRunPolicy.FAIL:
                with self.db.transaction() as tx:
                    tx.execute(
                        "UPDATE background_schedules SET state = ?, updated_at = ? WHERE schedule_id = ?;",
                        (ScheduleState.PAUSED.value, current_iso, sched.schedule_id),
                    )
                results.append((sched, missed_time, "FAILED"))

            elif sched.missed_run_policy == MissedRunPolicy.RUN_ONCE:
                # Keep next_run_at as-is so normal claim_due_schedules will pick it up
                results.append((sched, missed_time, "RUN_ONCE"))

        return results

    def release_expired_leases(self, now_ts: Optional[float] = None) -> int:
        """Resets schedules whose leases have expired (e.g. following an unhandled crash)."""
        current_ts = now_ts or datetime.now(timezone.utc).timestamp()
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE background_schedules
                SET state = 'ENABLED',
                    lease_holder = NULL,
                    lease_expires_at = NULL,
                    updated_at = ?
                WHERE state = 'RUNNING'
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at < ?;
                """,
                (utc_now(), current_ts),
            )
            return cursor.rowcount

    def get_recent_runs(self, schedule_id: str, limit: int = 10) -> List[ScheduledJobRun]:
        """Fetches recent job runs for a given schedule."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM scheduled_job_runs
                WHERE schedule_id = ?
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (schedule_id, limit),
            )
            rows = cursor.fetchall()
            return [
                ScheduledJobRun(
                    run_id=r["run_id"],
                    schedule_id=r["schedule_id"],
                    idempotency_key=r["idempotency_key"],
                    scheduled_time=r["scheduled_time"],
                    started_at=r["started_at"],
                    completed_at=r["completed_at"],
                    status=JobRunStatus(r["status"]),
                    task_id=r["task_id"],
                    error_message=r["error_message"],
                    result_summary=r["result_summary"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]
        finally:
            conn.close()

    def _row_to_schedule(self, row: sqlite3.Row) -> PersistentSchedule:
        params = json.loads(row["parameters"]) if row["parameters"] else {}
        return PersistentSchedule(
            schedule_id=row["schedule_id"],
            name=row["name"],
            schedule_type=ScheduleType(row["schedule_type"]),
            schedule_expr=row["schedule_expr"],
            timezone=row["timezone"],
            goal=row["goal"],
            parameters=params,
            state=ScheduleState(row["state"]),
            missed_run_policy=MissedRunPolicy(row["missed_run_policy"]),
            max_runs=row["max_runs"],
            runs_completed=row["runs_completed"],
            next_run_at=row["next_run_at"],
            last_run_at=row["last_run_at"],
            lease_holder=row["lease_holder"],
            lease_expires_at=row["lease_expires_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

