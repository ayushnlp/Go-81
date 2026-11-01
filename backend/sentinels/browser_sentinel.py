"""
Browser Monitoring Sentinel for Go 81 Stage 9.
Leverages Stage 8 Playwright runtime strictly in read-only mode for approved domains.
Detects web page changes, enforces domain allowlists, and handles redirect/TOCTOU rebinding.
"""

from datetime import datetime, timezone
import hashlib
import logging
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse
import uuid

from backend.browser.runtime import PlaywrightBrowserRuntime as BrowserRuntime
from backend.sentinels.models import (
    SentinelConfig,
    SentinelEvent,
    SentinelStatus,
    SentinelType,
)

logger = logging.getLogger(__name__)


class BrowserMonitoringSentinel:
    """
    Performs periodic, read-only inspection of approved web targets.
    Enforces strict origin restrictions and documents post-navigation redirect rebinding.
    """

    def __init__(
        self,
        config: SentinelConfig,
        browser_runtime: Optional[BrowserRuntime] = None,
        on_event_cb: Optional[Callable[[SentinelEvent], None]] = None,
    ):
        self.config = config
        self.sentinel_id = config.sentinel_id
        self.name = config.name
        self.target_url = config.config_data.get("target_url", "")
        self.allowed_domains: List[str] = config.config_data.get("allowed_domains", [])
        self.selector = config.config_data.get("selector", "body")
        self.status = SentinelStatus.ACTIVE if config.enabled else SentinelStatus.PAUSED
        self.browser_runtime = browser_runtime
        self.on_event_cb = on_event_cb

        self._previous_digest: Optional[str] = None
        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validates the target URL and domain allowlist."""
        if not self.target_url:
            self.status = SentinelStatus.ERROR
            raise ValueError(f"Sentinel {self.name} missing 'target_url'")

        parsed = urlparse(self.target_url)
        if parsed.scheme not in ("http", "https"):
            self.status = SentinelStatus.ERROR
            raise ValueError(f"Target URL scheme must be http or https, got: '{parsed.scheme}'")

        domain = parsed.hostname or ""
        if self.allowed_domains and domain.lower() not in [d.lower() for d in self.allowed_domains]:
            self.status = SentinelStatus.ERROR
            raise PermissionError(f"Target domain '{domain}' is not in allowed domains: {self.allowed_domains}")

    def is_url_allowed(self, url: str) -> bool:
        """Verifies if a URL's domain belongs to the configured allowed domains."""
        try:
            parsed = urlparse(url)
            domain = parsed.hostname or ""
            if not self.allowed_domains:
                return True
            return domain.lower() in [d.lower() for d in self.allowed_domains]
        except Exception:
            return False

    async def check_target(self, runtime: Optional[BrowserRuntime] = None) -> Optional[SentinelEvent]:
        """
        Navigates to the configured URL in read-only mode, captures sanitized DOM content,
        checks for TOCTOU redirect violations, and returns a SentinelEvent if content changed.
        """
        if self.status != SentinelStatus.ACTIVE:
            return None

        active_runtime = runtime or self.browser_runtime
        if not active_runtime:
            logger.warning(f"Browser sentinel {self.name} has no runtime available")
            return None

        # Pre-navigation origin check
        if not self.is_url_allowed(self.target_url):
            logger.error(f"Target URL '{self.target_url}' violates allowed domains")
            return None

        try:
            # 1. Read-only navigation
            nav_result = await active_runtime.navigate(self.target_url)
            final_url = nav_result.get("url", self.target_url)

            # 2. TOCTOU post-navigation redirect check
            if not self.is_url_allowed(final_url):
                logger.error(
                    f"TOCTOU Redirect Violation: Navigation to '{self.target_url}' redirected to forbidden domain '{final_url}'"
                )
                return None

            # 3. Read-only DOM inspection
            dom_data = await active_runtime.inspect_dom(selector=self.selector)
            raw_text = dom_data.get("text", "")

            # 4. Content sanitization (strip script, style, and control sequences)
            sanitized_text = re.sub(r"<script.*?</script>", "", raw_text, flags=re.DOTALL | re.IGNORECASE)
            sanitized_text = re.sub(r"<style.*?</style>", "", sanitized_text, flags=re.DOTALL | re.IGNORECASE)
            sanitized_text = sanitized_text.strip()

            content_digest = hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest()

            if self._previous_digest is None:
                # Initial baseline snapshot
                self._previous_digest = content_digest
                return None

            if content_digest != self._previous_digest:
                now_iso = datetime.now(timezone.utc).isoformat()
                fp_raw = f"{self.sentinel_id}:browser:{final_url}:{content_digest}"
                fingerprint = hashlib.sha256(fp_raw.encode("utf-8")).hexdigest()[:16]

                event = SentinelEvent(
                    event_id=str(uuid.uuid4()),
                    sentinel_id=self.sentinel_id,
                    event_type="browser:content_changed",
                    fingerprint=fingerprint,
                    payload={
                        "target_url": self.target_url,
                        "final_url": final_url,
                        "content_digest": content_digest,
                        "previous_digest": self._previous_digest,
                        "text_excerpt": sanitized_text[:500],
                    },
                    handled=False,
                    task_id=None,
                    created_at=now_iso,
                )

                self._previous_digest = content_digest
                if self.on_event_cb:
                    try:
                        self.on_event_cb(event)
                    except Exception as e:
                        logger.error(f"Error in browser sentinel callback: {e}")

                return event

            return None

        except Exception as e:
            logger.error(f"Error in browser monitoring sentinel {self.name}: {e}")
            return None
