"""
Internal Notification Service for Go 81 Stage 9.
Provides bounded in-app notifications with deduplication, severity levels,
and SQLite persistence. Does not rely on external cloud email or SMS services.
"""

from datetime import datetime, timezone
import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional
import uuid

from app.memory.database import DatabaseManager, utc_now
from backend.sentinels.models import (
    InternalNotification,
    NotificationCategory,
    NotificationSeverity,
)

logger = logging.getLogger(__name__)

MAX_NOTIFICATIONS_HISTORY = 500
DEFAULT_DEDUP_WINDOW_SECONDS = 300.0  # 5 minutes


class NotificationService:
    """
    Manages in-app notifications with deduplication, SQLite persistence, and bounded history.
    """

    def __init__(self, db_manager: DatabaseManager, max_history: int = MAX_NOTIFICATIONS_HISTORY):
        self.db = db_manager
        self.max_history = max_history
        self._dedup_cache: Dict[str, float] = {}  # dedup_key -> timestamp
        # Ensure migration v6 has been applied
        self.db.apply_migration_v6()

    def notify(
        self,
        category: NotificationCategory,
        severity: NotificationSeverity,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None,
        dedup_key: Optional[str] = None,
        dedup_window_seconds: float = DEFAULT_DEDUP_WINDOW_SECONDS,
        now_ts: Optional[float] = None,
    ) -> Optional[InternalNotification]:
        """
        Creates and stores a new internal notification.
        If dedup_key is provided, suppresses duplicate notifications within dedup_window_seconds.
        Prunes old notifications beyond max_history.
        """
        current_ts = now_ts or time.time()

        # Deduplication check
        if dedup_key:
            last_sent = self._dedup_cache.get(dedup_key)
            if last_sent is not None and (current_ts - last_sent) < dedup_window_seconds:
                logger.debug(f"Notification suppressed due to dedup_key '{dedup_key}'")
                return None
            self._dedup_cache[dedup_key] = current_ts

        now_iso = utc_now()
        notif_id = str(uuid.uuid4())
        meta = metadata or {}

        notif = InternalNotification(
            notification_id=notif_id,
            category=category,
            severity=severity,
            title=title,
            message=message,
            metadata=meta,
            read=False,
            dedup_key=dedup_key,
            created_at=now_iso,
        )

        with self.db.transaction() as conn:
            conn.execute(
                """
                INSERT INTO internal_notifications (
                    notification_id, category, severity, title, message,
                    metadata, read, dedup_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    notif.notification_id,
                    notif.category.value,
                    notif.severity.value,
                    notif.title,
                    notif.message,
                    json.dumps(notif.metadata),
                    0,
                    notif.dedup_key,
                    notif.created_at,
                ),
            )

            # Auto-prune beyond max_history
            conn.execute(
                """
                DELETE FROM internal_notifications
                WHERE notification_id NOT IN (
                    SELECT notification_id FROM internal_notifications
                    ORDER BY created_at DESC
                    LIMIT ?
                );
                """,
                (self.max_history,),
            )

        logger.info(f"Notification emitted [{severity.value}] {title}")
        return notif

    def get_notifications(
        self,
        limit: int = 50,
        unread_only: bool = False,
        category: Optional[NotificationCategory] = None,
    ) -> List[InternalNotification]:
        """Fetches stored notifications with optional filters."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM internal_notifications"
            params: List[Any] = []
            clauses = []

            if unread_only:
                clauses.append("read = 0")
            if category:
                clauses.append("category = ?")
                params.append(category.value)

            if clauses:
                query += " WHERE " + " AND ".join(clauses)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_notification(r) for r in rows]
        finally:
            conn.close()

    def get_unread_count(self) -> int:
        """Returns the number of unread notifications."""
        conn = self.db.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM internal_notifications WHERE read = 0;")
            row = cursor.fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def mark_as_read(self, notification_id: str) -> bool:
        """Marks a single notification as read."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE internal_notifications SET read = 1 WHERE notification_id = ?;", (notification_id,))
            return cursor.rowcount > 0

    def mark_all_as_read(self) -> int:
        """Marks all notifications as read."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE internal_notifications SET read = 1 WHERE read = 0;")
            return cursor.rowcount

    def clear_notifications(self) -> int:
        """Deletes all notifications from storage."""
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM internal_notifications;")
            self._dedup_cache.clear()
            return cursor.rowcount

    def _row_to_notification(self, row: sqlite3.Row) -> InternalNotification:
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        return InternalNotification(
            notification_id=row["notification_id"],
            category=NotificationCategory(row["category"]),
            severity=NotificationSeverity(row["severity"]),
            title=row["title"],
            message=row["message"],
            metadata=meta,
            read=bool(row["read"]),
            dedup_key=row["dedup_key"],
            created_at=row["created_at"],
        )

