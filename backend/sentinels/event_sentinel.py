"""
Internal Event Sentinel for Go 81 Stage 9.
Listens to internal lifecycle events, enforces strict event allowlists,
caps recursive trigger depth, and applies per-event-type rate limits.
"""

from collections import deque
from datetime import datetime, timezone
import hashlib
import logging
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Set
import uuid

from backend.sentinels.models import (
    SentinelConfig,
    SentinelEvent,
    SentinelStatus,
    SentinelType,
)

logger = logging.getLogger(__name__)

# Strict allowlist of permissible internal event types
ALLOWED_EVENT_TYPES: Set[str] = {
    "task_completed",
    "task_failed",
    "approval_required",
    "approval_resolved",
    "browser_reconciliation",
    "checkpoint_restored",
}

MAX_CAUSATION_DEPTH = 3
DEFAULT_RATE_LIMIT_PER_MINUTE = 10


class InternalEventSentinel:
    """
    Monitors and filters internal Go 81 events with loop prevention and rate limiting.
    """

    def __init__(
        self,
        config: SentinelConfig,
        max_depth: int = MAX_CAUSATION_DEPTH,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
        on_event_cb: Optional[Callable[[SentinelEvent], None]] = None,
    ):
        self.config = config
        self.sentinel_id = config.sentinel_id
        self.name = config.name
        self.status = SentinelStatus.ACTIVE if config.enabled else SentinelStatus.PAUSED
        self.max_depth = max_depth
        self.rate_limit_per_minute = rate_limit_per_minute
        self.on_event_cb = on_event_cb

        # Configured subscriptions (subset of allowed types)
        configured_types = set(config.config_data.get("event_types", list(ALLOWED_EVENT_TYPES)))
        self.subscribed_types = configured_types.intersection(ALLOWED_EVENT_TYPES)

        # Sliding timestamps window for rate limiting: event_type -> Deque[timestamp]
        self._rate_limit_windows: Dict[str, Deque[float]] = {}
        self._event_queue: Deque[SentinelEvent] = deque(maxlen=100)

    def publish_event(
        self,
        event_type: str,
        payload: Dict[str, Any],
        causation_depth: int = 0,
        now_ts: Optional[float] = None,
    ) -> Optional[SentinelEvent]:
        """
        Receives an internal system event, validates against allowlist,
        verifies recursion depth and rate limits, then queues a SentinelEvent.
        """
        if self.status != SentinelStatus.ACTIVE:
            return None

        # 1. Allowlist verification
        if event_type not in self.subscribed_types:
            logger.debug(f"Event '{event_type}' ignored (not in subscribed allowlist)")
            return None

        # 2. Recursion depth bound
        if causation_depth >= self.max_depth:
            logger.warning(
                f"Cascade loop prevented: Event '{event_type}' rejected because causation_depth={causation_depth} >= max={self.max_depth}"
            )
            return None

        # 3. Rate limit enforcement
        current_ts = now_ts or time.time()
        if event_type not in self._rate_limit_windows:
            self._rate_limit_windows[event_type] = deque()

        window = self._rate_limit_windows[event_type]
        one_minute_ago = current_ts - 60.0
        while window and window[0] < one_minute_ago:
            window.popleft()

        if len(window) >= self.rate_limit_per_minute:
            logger.warning(f"Rate limit exceeded for event '{event_type}': {len(window)} in 60s")
            return None

        window.append(current_ts)

        # 4. Create deterministic SentinelEvent
        now_iso = datetime.now(timezone.utc).isoformat()
        payload_with_meta = dict(payload)
        payload_with_meta["causation_depth"] = causation_depth + 1
        fp_raw = f"{self.sentinel_id}:{event_type}:{causation_depth}:{sorted(payload.items())}"
        fingerprint = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:16]

        event = SentinelEvent(
            event_id=str(uuid.uuid4()),
            sentinel_id=self.sentinel_id,
            event_type=f"event:{event_type}",
            fingerprint=fingerprint,
            payload=payload_with_meta,
            handled=False,
            task_id=None,
            created_at=now_iso,
        )

        self._event_queue.append(event)
        if self.on_event_cb:
            try:
                self.on_event_cb(event)
            except Exception as e:
                logger.error(f"Error in event sentinel callback: {e}")

        return event

    def get_queued_events(self) -> List[SentinelEvent]:
        """Drains and returns all queued events."""
        events = list(self._event_queue)
        self._event_queue.clear()
        return events

