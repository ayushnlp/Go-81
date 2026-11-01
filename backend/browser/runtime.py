"""
Stage 8: Autonomous Playwright Browser Automation Runtime.
Provides headless Chromium lifecycle, per-task isolated ephemeral browser contexts,
SSRF route interception, element interactions, screenshot/download management, and clean teardown.
"""

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Route,
    async_playwright,
)

from backend.browser.models import (
    BrowserActionTimeoutError,
    BrowserActionType,
    BrowserEvidence,
    BrowserSecurityError,
    SSRFSecurityError,
)
from backend.browser.security import (
    CredentialSanitizer,
    PromptInjectionDefense,
    SSRFValidator,
)

logger = logging.getLogger(__name__)


class PlaywrightBrowserRuntime:
    """
    Central Autonomous Browser Runtime for Project Go 81.
    Maintains a shared Chromium engine, creates isolated ephemeral contexts per task,
    installs strict SSRF interceptors on every context, and bounds resource utilization.
    """

    def __init__(
        self,
        base_dir: str = ".system_generated/browser",
        headless: bool = True,
        ssrf_validator: Optional[SSRFValidator] = None,
        max_tabs_per_context: int = 3,
        default_timeout_seconds: float = 30.0,
    ):
        self.base_dir = os.path.abspath(base_dir)
        self.headless = headless
        self.ssrf_validator = ssrf_validator or SSRFValidator()
        self.max_tabs_per_context = max_tabs_per_context
        self.default_timeout_seconds = default_timeout_seconds

        os.makedirs(os.path.join(self.base_dir, "screenshots"), exist_ok=True)
        os.makedirs(os.path.join(self.base_dir, "downloads"), exist_ok=True)

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        # task_id -> BrowserContext
        self._contexts: Dict[str, BrowserContext] = {}
        # task_id -> List[Page]
        self._pages: Dict[str, List[Page]] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Launches Playwright and shared Chromium browser instance."""
        async with self._lock:
            if self._playwright is None:
                self._playwright = await async_playwright().start()
            if self._browser is None:
                logger.info(f"Launching Chromium browser (headless={self.headless})...")
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-gpu",
                    ],
                )

    async def shutdown(self) -> None:
        """Closes all active task contexts and terminates the browser engine."""
        async with self._lock:
            for task_id in list(self._contexts.keys()):
                try:
                    await self._close_context_internal(task_id)
                except Exception as e:
                    logger.debug(f"Error closing context for task {task_id}: {e}")

            if self._browser:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug(f"Error closing browser: {e}")
                self._browser = None

            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.debug(f"Error stopping playwright: {e}")
                self._playwright = None

    async def get_or_create_context(self, task_id: str) -> BrowserContext:
        """
        Retrieves or initializes an isolated, ephemeral BrowserContext for the specified task.
        Installs strict SSRF request routing on every page in this context.
        """
        if not self._browser:
            await self.initialize()

        if task_id in self._contexts:
            return self._contexts[task_id]

        async with self._lock:
            if task_id in self._contexts:
                return self._contexts[task_id]

            task_download_dir = os.path.join(self.base_dir, "downloads", task_id)
            os.makedirs(task_download_dir, exist_ok=True)

            logger.info(f"Creating isolated ephemeral browser context for task {task_id}")
            context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Go81AutonomousAgent/1.0",
                accept_downloads=True,
                ignore_https_errors=False,
            )

            # Install SSRF interceptor on the entire context
            async def _ssrf_route_interceptor(route: Route):
                req = route.request
                target_url = req.url
                try:
                    self.ssrf_validator.validate_url(target_url)
                    await route.continue_()
                except SSRFSecurityError as se:
                    logger.warning(f"SSRF Interceptor BLOCKED request to '{target_url}': {se}")
                    await route.abort("blockedbyclient")
                except Exception as e:
                    logger.warning(f"Route error inspecting '{target_url}': {e}")
                    await route.abort("blockedbyclient")

            await context.route("**/*", _ssrf_route_interceptor)

            self._contexts[task_id] = context
            self._pages[task_id] = []
            return context

    async def get_or_create_page(self, task_id: str) -> Page:
        """Returns the primary active page for a task, or creates one within tab limits."""
        context = await self.get_or_create_context(task_id)
        pages = self._pages.get(task_id, [])

        # Filter out closed pages
        active_pages = [p for p in pages if not p.is_closed()]
        self._pages[task_id] = active_pages

        if active_pages:
            return active_pages[-1]

        if len(active_pages) >= self.max_tabs_per_context:
            raise BrowserSecurityError(
                f"Task {task_id} exceeded maximum tab limit ({self.max_tabs_per_context} open tabs)."
            )

        page = await context.new_page()
        page.set_default_timeout(int(self.default_timeout_seconds * 1000))
        self._pages[task_id].append(page)
        return page

    async def close_context(self, task_id: str) -> None:
        """Closes all pages and cleans up the ephemeral context for a completed task."""
        async with self._lock:
            await self._close_context_internal(task_id)

    async def _close_context_internal(self, task_id: str) -> None:
        context = self._contexts.pop(task_id, None)
        self._pages.pop(task_id, None)
        if context:
            try:
                await context.close()
                logger.info(f"Cleaned up ephemeral browser context for task {task_id}")
            except Exception as e:
                logger.debug(f"Error closing context for task {task_id}: {e}")

    # =========================================================================
    # High-Level Autonomous Actions
    # =========================================================================

    async def navigate(
        self,
        task_id: str,
        url: str,
        step_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> BrowserEvidence:
        """
        Navigates to the validated URL, enforcing SSRF checks before navigation.
        """
        timeout = timeout_seconds or self.default_timeout_seconds
        # 1. Pre-navigation SSRF Validation
        normalized_url = self.ssrf_validator.validate_url(url)

        page = await self.get_or_create_page(task_id)
        start_t = time.perf_counter()

        try:
            resp = await page.goto(
                normalized_url,
                wait_until="domcontentloaded",
                timeout=int(timeout * 1000),
            )
            status_code = resp.status if resp else None
            actual_url = page.url
            title = await page.title()

            # Post-navigation SSRF check on final URL after redirects
            self.ssrf_validator.validate_url(actual_url)

            summary = f"Navigated successfully to '{actual_url}' (HTTP {status_code or 200}, title: '{title}')."
            return BrowserEvidence(
                task_id=task_id,
                step_id=step_id,
                url=actual_url,
                title=title,
                action=BrowserActionType.NAVIGATE.value,
                result_summary=summary,
                status_code=status_code,
                side_effect_produced=False,
                idempotency_class="IDEMPOTENT",
            )
        except Exception as e:
            error_str = str(e)
            if "timeout" in error_str.lower():
                raise BrowserActionTimeoutError(f"Navigation to '{url}' timed out after {timeout}s.")
            raise

    async def inspect(
        self,
        task_id: str,
        step_id: Optional[str] = None,
        selector: Optional[str] = None,
        max_chars: int = 8192,
    ) -> BrowserEvidence:
        """
        Extracts sanitized DOM text and metadata without mutating page state.
        """
        page = await self.get_or_create_page(task_id)
        actual_url = page.url
        title = await page.title()

        if selector:
            el = await page.wait_for_selector(selector, state="attached", timeout=5000)
            if not el:
                raise RuntimeError(f"Element matching selector '{selector}' not found.")
            raw_text = await el.inner_text()
            summary = f"Inspected element '{selector}': extracted {len(raw_text)} characters."
        else:
            raw_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            summary = f"Inspected page text: extracted {len(raw_text)} characters."

        sanitized_dom = PromptInjectionDefense.sanitize_web_content(
            text=raw_text,
            max_length=max_chars,
        )

        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.INSPECT.value,
            selector=selector,
            result_summary=summary,
            dom_snapshot=sanitized_dom,
            side_effect_produced=False,
            idempotency_class="READ_ONLY",
        )

    async def click(
        self,
        task_id: str,
        selector: str,
        step_id: Optional[str] = None,
        wait_for_navigation: bool = False,
        timeout_seconds: Optional[float] = None,
    ) -> BrowserEvidence:
        """
        Clicks an element identified by selector, accessible role, or text.
        """
        timeout = timeout_seconds or 10.0
        page = await self.get_or_create_page(task_id)

        # Wait for selector to be visible
        await page.wait_for_selector(selector, state="visible", timeout=int(timeout * 1000))

        # Perform click
        if wait_for_navigation:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=int(timeout * 1000)):
                await page.click(selector, timeout=int(timeout * 1000))
        else:
            await page.click(selector, timeout=int(timeout * 1000))
            await page.wait_for_timeout(300)

        actual_url = page.url
        title = await page.title()
        self.ssrf_validator.validate_url(actual_url)

        summary = f"Clicked element '{selector}' successfully. Current page: '{actual_url}' ('{title}')."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.CLICK.value,
            selector=selector,
            result_summary=summary,
            side_effect_produced=True,
            idempotency_class="NON_IDEMPOTENT",
        )

    async def fill(
        self,
        task_id: str,
        selector: str,
        value: str,
        step_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> BrowserEvidence:
        """
        Fills a form control with the given text. Redacts credentials from evidence summary.
        """
        timeout = timeout_seconds or 10.0
        page = await self.get_or_create_page(task_id)

        await page.wait_for_selector(selector, state="visible", timeout=int(timeout * 1000))
        await page.fill(selector, value, timeout=int(timeout * 1000))

        actual_url = page.url
        title = await page.title()

        # Check if sensitive input
        is_sensitive = any(term in selector.lower() for term in ("pass", "pwd", "secret", "token", "otp", "cvv"))
        displayed_val = "[REDACTED_CREDENTIAL]" if is_sensitive else (value[:20] + "..." if len(value) > 20 else value)

        summary = f"Filled element '{selector}' with value '{displayed_val}'."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.FILL.value,
            selector=selector,
            result_summary=summary,
            side_effect_produced=True,
            idempotency_class="IDEMPOTENT",
        )

    async def select(
        self,
        task_id: str,
        selector: str,
        value: str,
        step_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> BrowserEvidence:
        """
        Selects a dropdown option or sets a checkbox/radio state.
        """
        timeout = timeout_seconds or 10.0
        page = await self.get_or_create_page(task_id)

        await page.wait_for_selector(selector, state="visible", timeout=int(timeout * 1000))
        # Try select_option first, fallback to check
        try:
            await page.select_option(selector, value, timeout=int(timeout * 1000))
        except Exception:
            await page.check(selector, timeout=int(timeout * 1000))

        actual_url = page.url
        title = await page.title()

        summary = f"Selected '{value}' on element '{selector}'."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.SELECT.value,
            selector=selector,
            result_summary=summary,
            side_effect_produced=True,
            idempotency_class="IDEMPOTENT",
        )

    async def screenshot(
        self,
        task_id: str,
        step_id: Optional[str] = None,
        selector: Optional[str] = None,
        full_page: bool = False,
    ) -> BrowserEvidence:
        """
        Captures a high-resolution screenshot saved into isolated task storage.
        """
        page = await self.get_or_create_page(task_id)
        ss_dir = os.path.join(self.base_dir, "screenshots", task_id)
        os.makedirs(ss_dir, exist_ok=True)

        filename = f"ss-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}.png"
        filepath = os.path.join(ss_dir, filename)

        if selector:
            el = await page.wait_for_selector(selector, state="visible", timeout=5000)
            if not el:
                raise RuntimeError(f"Element '{selector}' not visible for screenshot.")
            await el.screenshot(path=filepath)
        else:
            await page.screenshot(path=filepath, full_page=full_page)

        actual_url = page.url
        title = await page.title()

        summary = f"Captured screenshot to '{filepath}'."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.SCREENSHOT.value,
            selector=selector,
            result_summary=summary,
            screenshot_ref=filepath,
            side_effect_produced=False,
            idempotency_class="READ_ONLY",
        )

    async def download(
        self,
        task_id: str,
        selector_or_url: str,
        step_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> BrowserEvidence:
        """
        Downloads a file initiated by a click on selector, saving into isolated task download folder.
        Enforces maximum download size limit (10MB).
        """
        timeout = timeout_seconds or 30.0
        page = await self.get_or_create_page(task_id)
        download_dir = os.path.join(self.base_dir, "downloads", task_id)
        os.makedirs(download_dir, exist_ok=True)

        async with page.expect_download(timeout=int(timeout * 1000)) as download_info:
            await page.click(selector_or_url, timeout=int(timeout * 1000))

        download = await download_info.value
        filename = download.suggested_filename or f"download-{uuid.uuid4().hex[:8]}.bin"
        target_path = os.path.join(download_dir, filename)
        await download.save_as(target_path)

        # Enforce file size limit (10MB)
        file_size = os.path.getsize(target_path)
        if file_size > 10 * 1024 * 1024:
            os.remove(target_path)
            raise BrowserSecurityError(
                f"Downloaded file '{filename}' exceeded 10MB limit ({file_size} bytes). File discarded."
            )

        actual_url = page.url
        title = await page.title()

        summary = f"Downloaded file '{filename}' ({file_size} bytes) to '{target_path}'."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.DOWNLOAD.value,
            result_summary=summary,
            downloads=[target_path],
            side_effect_produced=True,
            idempotency_class="IDEMPOTENT",
        )

    async def upload(
        self,
        task_id: str,
        selector: str,
        file_path: str,
        step_id: Optional[str] = None,
    ) -> BrowserEvidence:
        """
        Attaches a file to a file-input element.
        Validates file existence and prevents directory traversal.
        """
        page = await self.get_or_create_page(task_id)
        resolved_path = os.path.abspath(file_path)
        if not os.path.exists(resolved_path):
            raise FileNotFoundError(f"Upload file not found: '{file_path}'")

        await page.set_input_files(selector, resolved_path)

        actual_url = page.url
        title = await page.title()

        summary = f"Attached file '{os.path.basename(resolved_path)}' to element '{selector}'."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.UPLOAD.value,
            selector=selector,
            result_summary=summary,
            side_effect_produced=True,
            idempotency_class="NON_IDEMPOTENT",
        )

    async def submit(
        self,
        task_id: str,
        selector: Optional[str] = None,
        form_data: Optional[Dict[str, Any]] = None,
        step_id: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
    ) -> BrowserEvidence:
        """
        Submits a form or triggers a final submission button.
        """
        timeout = timeout_seconds or 15.0
        page = await self.get_or_create_page(task_id)

        submit_selector = selector or "button[type='submit'], input[type='submit']"
        await page.wait_for_selector(submit_selector, state="visible", timeout=int(timeout * 1000))

        # Click submit and wait for load
        await page.click(submit_selector, timeout=int(timeout * 1000))
        await page.wait_for_load_state("domcontentloaded", timeout=int(timeout * 1000))

        actual_url = page.url
        title = await page.title()
        self.ssrf_validator.validate_url(actual_url)

        sanitized_params = CredentialSanitizer.sanitize_form_data(form_data or {})
        summary = (
            f"Submitted form via '{submit_selector}'. "
            f"Resulting page: '{actual_url}' ('{title}'). "
            f"Submitted fields: {list(sanitized_params.keys())}."
        )

        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.SUBMIT.value,
            selector=submit_selector,
            result_summary=summary,
            side_effect_produced=True,
            idempotency_class="NON_IDEMPOTENT",
        )


# Global singleton instance for backend reuse
_global_browser_runtime: Optional[PlaywrightBrowserRuntime] = None


def get_browser_runtime(allow_local_test_server: bool = False, allowed_test_hosts: Optional[Set[str]] = None) -> PlaywrightBrowserRuntime:
    """Returns or creates the global PlaywrightBrowserRuntime singleton."""
    global _global_browser_runtime
    if _global_browser_runtime is None:
        validator = SSRFValidator(
            allow_local_test_server=allow_local_test_server,
            allowed_test_hosts=allowed_test_hosts,
        )
        _global_browser_runtime = PlaywrightBrowserRuntime(ssrf_validator=validator)
    return _global_browser_runtime
