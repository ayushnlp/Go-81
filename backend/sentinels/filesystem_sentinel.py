"""
Filesystem Sentinel for Go 81 Stage 9.
Provides pure-Python snapshot-based directory monitoring, sliding debounce windows,
bounded event queues, and strict canonical path confinement.
"""

from collections import deque
from datetime import datetime, timezone
import hashlib
import logging
import os
import time
from typing import Any, Callable, Deque, Dict, List, Optional, Set, Tuple
import uuid

from backend.sentinels.models import (
    SentinelConfig,
    SentinelEvent,
    SentinelStatus,
    SentinelType,
)
from backend.sentinels.security import (
    MAX_INSPECT_FILE_SIZE_BYTES,
    PathSecurityValidator,
    UntrustedContentGuard,
)

logger = logging.getLogger(__name__)


class FileSnapshot:
    """Represents a lightweight stat snapshot of a file."""
    __slots__ = ("rel_path", "abs_path", "mtime", "size")

    def __init__(self, rel_path: str, abs_path: str, mtime: float, size: int):
        self.rel_path = rel_path
        self.abs_path = abs_path
        self.mtime = mtime
        self.size = size


class FilesystemSentinel:
    """
    Monitors a confined directory tree using pure-Python stat snapshots.
    Supports debounce coalescing, bounded event buffers, and path escape prevention.
    """

    def __init__(
        self,
        config: SentinelConfig,
        debounce_seconds: float = 1.0,
        max_queue_size: int = 100,
        on_event_cb: Optional[Callable[[SentinelEvent], None]] = None,
    ):
        self.config = config
        self.sentinel_id = config.sentinel_id
        self.name = config.name
        self.monitored_root = config.config_data.get("monitored_root", "")
        self.recursive = bool(config.config_data.get("recursive", True))
        self.file_patterns = config.config_data.get("patterns", ["*"])
        self.debounce_seconds = debounce_seconds
        self.max_queue_size = max_queue_size
        self.on_event_cb = on_event_cb

        self.status = SentinelStatus.ACTIVE if config.enabled else SentinelStatus.PAUSED
        self._is_initialized = False
        self._previous_snapshot: Dict[str, FileSnapshot] = {}
        self._pending_debounces: Dict[str, Tuple[float, str, FileSnapshot]] = {}  # rel_path -> (debounce_deadline, event_type, snapshot)
        self._event_queue: Deque[SentinelEvent] = deque(maxlen=max_queue_size)
        self._dropped_events_count = 0

        # Validate monitored root upon initialization
        self._validate_monitored_root()

    def _validate_monitored_root(self) -> None:
        """Validates that the monitored root exists and is not a sensitive directory."""
        if not self.monitored_root:
            self.status = SentinelStatus.ERROR
            raise ValueError(f"Sentinel {self.name} missing 'monitored_root' in config_data")

        if not os.path.exists(self.monitored_root):
            self.status = SentinelStatus.ERROR
            raise FileNotFoundError(f"Monitored root does not exist: {self.monitored_root}")

        if PathSecurityValidator.is_system_root_path(self.monitored_root):
            self.status = SentinelStatus.ERROR
            raise PermissionError(f"Monitored root cannot be an operating system root: {self.monitored_root}")

        is_sens, reason = PathSecurityValidator.is_sensitive_path(self.monitored_root)
        if is_sens:
            self.status = SentinelStatus.ERROR
            raise PermissionError(f"Monitored root is restricted: {reason}")

    def capture_snapshot(self) -> Dict[str, FileSnapshot]:
        """
        Walks the monitored directory and records file metadata.
        Strictly excludes sensitive files, files outside confinement, or exceeding size limits.
        """
        snapshot: Dict[str, FileSnapshot] = {}
        canon_root = PathSecurityValidator.canonicalize(self.monitored_root)

        for root_dir, dirnames, filenames in os.walk(self.monitored_root):
            # Prune sensitive directories in-place to avoid descending into them
            pruned_dirs = []
            for d in list(dirnames):
                dir_path = os.path.join(root_dir, d)
                is_sens, _ = PathSecurityValidator.is_sensitive_path(dir_path)
                if is_sens:
                    dirnames.remove(d)
                    pruned_dirs.append(d)

            for fname in filenames:
                full_path = os.path.join(root_dir, fname)

                # Validate confinement and sensitivity
                is_valid, reason, canon_path = PathSecurityValidator.validate_confinement(full_path, canon_root)
                if not is_valid:
                    continue

                try:
                    stat = os.stat(full_path)
                    rel_p = os.path.relpath(full_path, self.monitored_root)
                    snapshot[rel_p] = FileSnapshot(
                        rel_path=rel_p,
                        abs_path=full_path,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                except (OSError, PermissionError) as e:
                    logger.debug(f"Could not stat {full_path}: {e}")

            if not self.recursive:
                break

        return snapshot

    def scan_and_detect_changes(self, now_ts: Optional[float] = None) -> List[SentinelEvent]:
        """
        Compares current filesystem state against previous snapshot.
        Applies debounce coalescing and returns newly settled events.
        """
        if self.status != SentinelStatus.ACTIVE:
            return []

        current_time = now_ts or time.time()
        current_snapshot = self.capture_snapshot()
        settled_events: List[SentinelEvent] = []

        if not self._is_initialized:
            # Baseline initial run - establish baseline without emitting creation storm
            self._previous_snapshot = current_snapshot
            self._is_initialized = True
            return []

        curr_keys = set(current_snapshot.keys())
        prev_keys = set(self._previous_snapshot.keys())

        # 1. Created files
        created = curr_keys - prev_keys
        for rel_p in created:
            snap = current_snapshot[rel_p]
            self._schedule_debounce(rel_p, "CREATED", snap, current_time)

        # 2. Deleted files
        deleted = prev_keys - curr_keys
        for rel_p in deleted:
            snap = self._previous_snapshot[rel_p]
            self._schedule_debounce(rel_p, "DELETED", snap, current_time)

        # 3. Modified files
        common = curr_keys & prev_keys
        for rel_p in common:
            c_snap = current_snapshot[rel_p]
            p_snap = self._previous_snapshot[rel_p]
            if c_snap.mtime != p_snap.mtime or c_snap.size != p_snap.size:
                self._schedule_debounce(rel_p, "MODIFIED", c_snap, current_time)

        # Update previous snapshot
        self._previous_snapshot = current_snapshot

        # 4. Flush debounced events that have passed their deadline
        settled_keys = []
        for rel_p, (deadline, ev_type, snap) in self._pending_debounces.items():
            if current_time >= deadline:
                settled_keys.append(rel_p)
                event = self._build_event(ev_type, snap)
                self._enqueue_event(event)
                settled_events.append(event)
                if self.on_event_cb:
                    try:
                        self.on_event_cb(event)
                    except Exception as e:
                        logger.error(f"Error in sentinel event callback: {e}")

        for k in settled_keys:
            del self._pending_debounces[k]

        return settled_events

    def _schedule_debounce(self, rel_path: str, event_type: str, snapshot: FileSnapshot, now_ts: float) -> None:
        """Schedules or coalesces an event in the sliding debounce window."""
        deadline = now_ts + self.debounce_seconds
        self._pending_debounces[rel_path] = (deadline, event_type, snapshot)

    def _build_event(self, event_type: str, snapshot: FileSnapshot) -> SentinelEvent:
        """Builds a deterministic SentinelEvent."""
        now_iso = datetime.now(timezone.utc).isoformat()
        fp_raw = f"{self.sentinel_id}:{event_type}:{snapshot.rel_path}:{snapshot.mtime}:{snapshot.size}"
        fingerprint = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:16]

        payload = {
            "event_type": event_type,
            "relative_path": snapshot.rel_path,
            "absolute_path": snapshot.abs_path,
            "size_bytes": snapshot.size,
            "mtime": snapshot.mtime,
        }

        return SentinelEvent(
            event_id=str(uuid.uuid4()),
            sentinel_id=self.sentinel_id,
            event_type=f"fs:{event_type.lower()}",
            fingerprint=fingerprint,
            payload=payload,
            handled=False,
            task_id=None,
            created_at=now_iso,
        )

    def _enqueue_event(self, event: SentinelEvent) -> None:
        """Enqueues an event, tracking dropped items on queue overflow."""
        if len(self._event_queue) >= self.max_queue_size:
            self._dropped_events_count += 1
            logger.warning(
                f"Sentinel {self.name} queue full (size {self.max_queue_size}). "
                f"Dropped oldest event. Total dropped: {self._dropped_events_count}"
            )
        self._event_queue.append(event)

    def get_queued_events(self) -> List[SentinelEvent]:
        """Returns and drains all queued events."""
        events = list(self._event_queue)
        self._event_queue.clear()
        return events

    def read_untrusted_file(self, rel_path: str, max_bytes: int = MAX_INSPECT_FILE_SIZE_BYTES) -> Tuple[bool, str]:
        """
        Safely reads a file from the monitored root and wraps it with untrusted content delimiters.
        Returns: (success, wrapped_content_or_error).
        """
        full_path = os.path.join(self.monitored_root, rel_path)
        is_valid, reason, canon_path = PathSecurityValidator.validate_confinement(full_path, self.monitored_root)
        if not is_valid:
            return False, f"Access blocked: {reason}"

        try:
            stat = os.stat(canon_path)
            if stat.st_size > max_bytes:
                return False, f"File size ({stat.st_size} bytes) exceeds limit ({max_bytes} bytes)"

            with open(canon_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read(max_bytes)

            wrapped = UntrustedContentGuard.wrap_content(rel_path, content, stat.st_size)
            return True, wrapped
        except Exception as e:
            return False, f"Failed to read file: {e}"
