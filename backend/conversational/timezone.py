"""
Timezone and Date/Time Utilities for Project Go 81.
Stage 5 Factual Grounding:
- Consistent UTC storage and ISO-8601 formatting
- Configurable IANA user timezone via GO81_TIMEZONE (default: Asia/Kolkata)
- Grounding AI reasoning with real system datetime so it never invents today's date or time
- Defense against double-conversion of timestamps
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Tuple


DEFAULT_TIMEZONE = "Asia/Kolkata"


def get_configured_timezone_name() -> str:
    """Returns the configured IANA timezone name."""
    return os.environ.get("GO81_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE


def get_configured_zoneinfo() -> ZoneInfo:
    """Resolves ZoneInfo object, falling back safely to UTC if invalid."""
    tz_name = get_configured_timezone_name()
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo("UTC")


def get_current_utc_time() -> datetime:
    """Returns current system time in UTC with timezone awareness."""
    return datetime.now(timezone.utc)


def get_current_time(tz: Optional[ZoneInfo] = None) -> datetime:
    """Returns current system time converted to the target timezone (default: configured)."""
    target_tz = tz or get_configured_zoneinfo()
    return datetime.now(timezone.utc).astimezone(target_tz)


def to_utc_iso(dt: Optional[datetime] = None) -> str:
    """Formats datetime as ISO-8601 in UTC."""
    d = dt or get_current_utc_time()
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    else:
        d = d.astimezone(timezone.utc)
    return d.isoformat()


def format_local_timestamp(
    dt_or_iso: Optional[datetime | str] = None,
    include_seconds: bool = False,
    include_date: bool = False,
    tz: Optional[ZoneInfo] = None,
) -> str:
    """
    Formats a datetime or ISO string for user-facing display in the configured local timezone.
    Prevents double-conversion if the datetime is already in local timezone.
    """
    target_tz = tz or get_configured_zoneinfo()
    
    if dt_or_iso is None:
        dt = datetime.now(timezone.utc).astimezone(target_tz)
    elif isinstance(dt_or_iso, str):
        raw_str = dt_or_iso.strip()
        try:
            # Parse ISO string
            parsed = datetime.fromisoformat(raw_str)
            if parsed.tzinfo is None:
                # Assume UTC if naive
                parsed = parsed.replace(tzinfo=timezone.utc)
            dt = parsed.astimezone(target_tz)
        except Exception:
            # If already formatted string like "10:30 PM", return as is to prevent double conversion
            return raw_str
    elif isinstance(dt_or_iso, datetime):
        if dt_or_iso.tzinfo is None:
            dt = dt_or_iso.replace(tzinfo=timezone.utc).astimezone(target_tz)
        else:
            dt = dt_or_iso.astimezone(target_tz)
    else:
        dt = datetime.now(timezone.utc).astimezone(target_tz)

    fmt_parts = []
    if include_date:
        fmt_parts.append("%Y-%m-%d")
    
    if include_seconds:
        fmt_parts.append("%I:%M:%S %p")
    else:
        fmt_parts.append("%I:%M %p")

    fmt_string = " ".join(fmt_parts)
    return dt.strftime(fmt_string)


def get_system_time_context() -> dict[str, str]:
    """
    Returns verified system time information to inject into AI reasoning prompts.
    Grounds the model in real time so it knows current year, date, and time.
    """
    tz = get_configured_zoneinfo()
    local_now = datetime.now(timezone.utc).astimezone(tz)
    utc_now = datetime.now(timezone.utc)
    tz_name = get_configured_timezone_name()

    return {
        "current_local_date": local_now.strftime("%A, %B %d, %Y"),
        "current_local_time": local_now.strftime("%I:%M %p"),
        "current_year": str(local_now.year),
        "timezone": tz_name,
        "current_utc_iso": utc_now.isoformat(),
        "prompt_injection_summary": (
            f"Current System Time: {local_now.strftime('%Y-%m-%d %I:%M %p')} ({tz_name}). "
            f"Today's Year: {local_now.year}."
        ),
    }

