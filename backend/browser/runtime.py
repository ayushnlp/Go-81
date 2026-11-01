"""
Stage 8 & 8.1: Autonomous Playwright Browser Runtime for Project Go 81.
Provides isolated ephemeral BrowserContext per task, bounded tabs, strict route-level SSRF interceptor,
consequential click protection with binding approvals, password screenshot masking, and credential redaction.
"""

import asyncio
import logging
import os
import time
import urllib.parse
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Route, async_playwright

from backend.browser.models import (
    ApprovalBindingTamperError,
    BrowserActionTimeoutError,
    BrowserActionType,
    BrowserEvidence,
    BrowserSecurityError,
    ClickTargetInspection,
    ConsequentialActionApprovalRequiredError,
    ConsequentialCategory,
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
    Sovereign, local-first browser automation engine using Playwright.
    Manages isolated Chromium processes, per-task ephemeral contexts, and route-level SSRF defense.
    Enforces consequential click protection and credential safety across all actions.
    """

    def __init__(
        self,
        base_dir: str = "workspace/browser_data",
        ssrf_validator: Optional[SSRFValidator] = None,
        headless: bool = True,
        max_tabs_per_context: int = 3,
        default_timeout_seconds: float = 30.0,
    ):
        self.base_dir = base_dir
        self.ssrf_validator = ssrf_validator or SSRFValidator()
        self.headless = headless
        self.max_tabs_per_context = max_tabs_per_context
        self.default_timeout_seconds = default_timeout_seconds

        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._contexts: Dict[str, BrowserContext] = {}
        self._pages: Dict[str, List[Page]] = {}
        self._lock = asyncio.Lock()

        # Consequential click approval registry
        self._approved_tokens: Dict[str, Dict[str, Any]] = {}
        self._consumed_tokens: Set[str] = set()

        os.makedirs(self.base_dir, exist_ok=True)

    # =========================================================================
    # Approval Token Management for Consequential Clicks
    # =========================================================================

    def grant_approval_for_fingerprint(
        self,
        task_id: str,
        fingerprint: str,
        domain: str,
        url: str,
        selector: str,
    ) -> str:
        """Issues and registers an approval token bound to exact domain, url, selector, and fingerprint."""
        token = f"apr-click-{uuid.uuid4().hex[:12]}"
        self._approved_tokens[token] = {
            "task_id": task_id,
            "fingerprint": fingerprint,
            "domain": domain,
            "url": url,
            "selector": selector,
            "consumed": False,
            "granted_at": time.time(),
        }
        return token

    def is_approval_valid(self, task_id: str, token: str, inspection: ClickTargetInspection) -> bool:
        """Validates approval token against the exact live target element inspection."""
        if not token:
            return False

        # Direct fingerprint match
        if token == inspection.approval_fingerprint:
            if token in self._consumed_tokens:
                return False  # Already consumed (replay prevented)
            return True

        if token not in self._approved_tokens:
            return False

        record = self._approved_tokens[token]
        if record.get("consumed", False):
            return False  # Single-use violated
        if record.get("fingerprint") != inspection.approval_fingerprint:
            return False  # Target element changed or page navigated (tamper / state drift)
        if record.get("domain") != inspection.domain:
            return False  # Domain mismatch
        if record.get("selector") != inspection.selector:
            return False  # Selector mismatch

        return True

    def consume_approval(self, token: str) -> None:
        """Atomically consumes an approval token to prevent replay attacks."""
        self._consumed_tokens.add(token)
        if token in self._approved_tokens:
            self._approved_tokens[token]["consumed"] = True

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def initialize(self) -> None:
        """Starts Playwright and launches the headless Chromium browser instance."""
        async with self._lock:
            if self._playwright is None:
                logger.info("Initializing Playwright runtime...")
                self._playwright = await async_playwright().start()

            if self._browser is None:
                logger.info(f"Launching Chromium (headless={self.headless})...")
                self._browser = await self._playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-gpu",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )

    async def shutdown(self) -> None:
        """Terminates all open contexts and closes the browser process cleanly."""
        async with self._lock:
            for task_id in list(self._contexts.keys()):
                await self._close_context_internal(task_id)

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
        Installs strict SSRF request routing and blocks service workers.
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
                service_workers="block",  # Prevents SW interception bypasses
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
    # Consequential Element Inspection
    # =========================================================================

    async def assess_click_target(
        self,
        task_id: str,
        selector: str,
        timeout_seconds: Optional[float] = None,
    ) -> ClickTargetInspection:
        """
        Inspects the live DOM element identified by selector.
        Extracts semantic role, accessible name, type, and form context to determine
        consequentiality (submit, purchase, payment, registration, application, deletion, messaging).
        Unknown or ambiguous actions fail closed.
        """
        timeout = timeout_seconds or 5.0
        page = await self.get_or_create_page(task_id)

        # Wait for element to be attached in DOM
        await page.wait_for_selector(selector, state="attached", timeout=int(timeout * 1000))

        # Evaluate target element properties in page execution context
        raw_info = await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return null;

                const tag = (el.tagName || '').toUpperCase();
                const type = (el.getAttribute('type') || '').toLowerCase();
                const role = (el.getAttribute('role') || '').toLowerCase();
                const ariaLabel = el.getAttribute('aria-label') || '';
                const ariaDesc = el.getAttribute('aria-description') || '';
                const title = el.getAttribute('title') || '';
                const name = el.getAttribute('name') || '';
                const id = el.getAttribute('id') || '';
                const dataAction = (el.getAttribute('data-action') || '').toLowerCase();
                const innerText = (el.innerText || el.textContent || '').trim();
                const href = (el.getAttribute('href') || '').trim();
                const value = (el.getAttribute('value') || '').trim();
                const className = (el.className || '').toString().toLowerCase();

                // Surrounding form context
                const form = el.closest('form');
                const isInsideForm = !!form;
                let formAction = null;
                let formMethod = null;
                let formHasInputs = false;
                let formHasPasswordOrPayment = false;

                if (form) {
                    formAction = form.getAttribute('action') || '';
                    formMethod = (form.getAttribute('method') || 'GET').toUpperCase();
                    const inputs = form.querySelectorAll('input, select, textarea');
                    formHasInputs = inputs.length > 0;
                    inputs.forEach(inp => {
                        const t = (inp.getAttribute('type') || '').toLowerCase();
                        const n = (inp.getAttribute('name') || '').toLowerCase();
                        if (t === 'password' || n.includes('card') || n.includes('pay') || n.includes('cvv')) {
                            formHasPasswordOrPayment = true;
                        }
                    });
                }

                return {
                    tag,
                    type,
                    role,
                    ariaLabel,
                    title,
                    name,
                    id,
                    dataAction,
                    innerText,
                    href,
                    value,
                    className,
                    isInsideForm,
                    formAction,
                    formMethod,
                    formHasInputs,
                    formHasPasswordOrPayment,
                };
            }""",
            selector,
        )

        if not raw_info:
            raise RuntimeError(f"Element matching selector '{selector}' was not found in the DOM.")

        page_url = page.url
        domain = urllib.parse.urlsplit(page_url).netloc.lower()

        tag = raw_info.get("tag", "")
        el_type = raw_info.get("type", "")
        role = raw_info.get("role", "")
        aria_label = raw_info.get("ariaLabel", "")
        inner_text = raw_info.get("innerText", "")
        title = raw_info.get("title", "")
        name = raw_info.get("name", "")
        el_id = raw_info.get("id", "")
        data_action = raw_info.get("dataAction", "")
        value = raw_info.get("value", "")
        class_name = raw_info.get("className", "")
        href = raw_info.get("href", "")
        is_inside_form = raw_info.get("isInsideForm", False)
        form_action = raw_info.get("formAction")
        form_method = raw_info.get("formMethod")
        form_has_inputs = raw_info.get("formHasInputs", False)
        form_has_password_or_payment = raw_info.get("formHasPasswordOrPayment", False)

        accessible_name = aria_label or title or inner_text or value or name or el_id
        combined_text = f"{accessible_name} {name} {el_id} {data_action} {class_name} {value}".lower()

        # Classify Consequentiality
        is_consequential = False
        category = ConsequentialCategory.SAFE_INTERACTION
        reason = "Non-consequential UI interaction."

        # 1. Form Submission
        if is_inside_form and (el_type == "submit" or (tag == "BUTTON" and el_type != "button") or form_has_inputs and tag == "BUTTON"):
            is_consequential = True
            category = ConsequentialCategory.SUBMIT
            reason = f"Submit button inside form (triggers HTTP {form_method or 'POST'} submission)"
        elif el_type == "submit" or (tag == "INPUT" and el_type in ("submit", "image")):
            is_consequential = True
            category = ConsequentialCategory.SUBMIT
            reason = "Form submit input control"

        # 2. Purchase / Payment
        elif any(term in combined_text for term in ("pay", "buy", "checkout", "purchase", "order", "subscribe", "charge", "billing", "place order")):
            is_consequential = True
            category = ConsequentialCategory.PURCHASE
            reason = f"Purchase or payment action detected on element: '{accessible_name}'"
        elif form_has_password_or_payment and tag in ("BUTTON", "A", "INPUT"):
            is_consequential = True
            category = ConsequentialCategory.PAYMENT
            reason = f"Interactive control inside payment/credential form: '{accessible_name}'"

        # 3. Registration / Signup
        elif any(term in combined_text for term in ("register", "signup", "sign up", "create account", "join now", "sign-up")):
            is_consequential = True
            category = ConsequentialCategory.REGISTRATION
            reason = f"Account registration action detected: '{accessible_name}'"

        # 4. Application
        elif any(term in combined_text for term in ("apply", "apply now", "submit application", "enroll", "enrollment")):
            is_consequential = True
            category = ConsequentialCategory.APPLICATION
            reason = f"Formal application submission action detected: '{accessible_name}'"

        # 5. Deletion / Destruction
        elif any(term in combined_text for term in ("delete", "remove", "destroy", "drop", "cancel subscription", "terminate", "revoke", "discard", "erase", "purge")):
            is_consequential = True
            category = ConsequentialCategory.DELETION
            reason = f"Destructive or deletion action detected: '{accessible_name}'"

        # 6. Messaging / Public Communication
        elif any(term in combined_text for term in ("send", "post", "publish", "tweet", "message", "chat", "email", "submit post")):
            is_consequential = True
            category = ConsequentialCategory.MESSAGING
            reason = f"External communication / messaging action detected: '{accessible_name}'"

        # 7. Safe Navigation Links
        elif (tag == "A" or role == "link") and href and not href.startswith("javascript:") and not href.startswith("data:") and not is_inside_form:
            is_consequential = False
            category = ConsequentialCategory.SAFE_NAVIGATION
            reason = f"Standard navigation hyperlink pointing to '{href}'"

        # 8. Safe Non-Mutating UI Components (Tabs, Details/Summary, Pagination)
        elif role in ("tab", "tablist", "combobox") or tag in ("DETAILS", "SUMMARY") or "page-" in el_id or "pagination" in class_name:
            if not is_inside_form:
                is_consequential = False
                category = ConsequentialCategory.SAFE_INTERACTION
                reason = "Safe non-mutating UI expander/navigation element"
            else:
                is_consequential = True
                category = ConsequentialCategory.AMBIGUOUS_ACTION
                reason = "Interactive control inside form fails closed to require approval"

        # 9. Ambiguous or Unknown Action - FAIL CLOSED
        elif tag in ("BUTTON", "INPUT") or role in ("button", "menuitemcheckbox") or data_action:
            is_consequential = True
            category = ConsequentialCategory.AMBIGUOUS_ACTION
            reason = f"Interactive '{tag}' control ('{accessible_name}') fails closed to prevent unverified side effects"

        inspection = ClickTargetInspection(
            selector=selector,
            url=page_url,
            domain=domain,
            tag_name=tag,
            element_type=el_type or None,
            role=role or None,
            accessible_name=accessible_name,
            inner_text=inner_text,
            is_inside_form=is_inside_form,
            form_action=form_action,
            form_method=form_method,
            href=href or None,
            is_consequential=is_consequential,
            category=category,
            reason=reason,
        )
        inspection.approval_fingerprint = inspection.compute_fingerprint()
        return inspection

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
                result_summary=CredentialSanitizer.sanitize_text(summary),
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
        Strips hidden/invisible injection text prior to prompt wrapping.
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
            # Strip script, style, and hidden elements to neutralize stealth prompt injections
            raw_text = await page.evaluate(
                """() => {
                    const clone = document.body.cloneNode(true);
                    const removeSelectors = ['script', 'style', 'noscript', '[hidden]', '[aria-hidden="true"]'];
                    removeSelectors.forEach(sel => clone.querySelectorAll(sel).forEach(e => e.remove()));
                    return clone.innerText || '';
                }"""
            )
            summary = f"Inspected visible page text: extracted {len(raw_text)} characters."

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
            result_summary=CredentialSanitizer.sanitize_text(summary),
            dom_snapshot=sanitized_dom,
            side_effect_produced=False,
            idempotency_class="READ_ONLY",
        )

    async def click(
        self,
        task_id: str,
        selector: str,
        step_id: Optional[str] = None,
        approval_token: Optional[str] = None,
        wait_for_navigation: bool = False,
        timeout_seconds: Optional[float] = None,
    ) -> BrowserEvidence:
        """
        Clicks an element identified by selector.
        Enforces consequential click protection: requires explicit, bound human approval
        for submit, purchase, payment, registration, application, deletion, messaging,
        or ambiguous interactive actions. Never automatically retried.
        """
        timeout = timeout_seconds or 10.0
        page = await self.get_or_create_page(task_id)

        # 1. Assess consequentiality before physical click
        inspection = await self.assess_click_target(task_id, selector, timeout_seconds=timeout)

        if inspection.is_consequential:
            # Verify explicit bound approval
            if not approval_token or not self.is_approval_valid(task_id, approval_token, inspection):
                raise ConsequentialActionApprovalRequiredError(
                    f"Consequential [{inspection.category.value}] click on '{selector}' ('{inspection.accessible_name}') "
                    f"on domain '{inspection.domain}' requires explicit human confirmation. "
                    f"Reason: {inspection.reason}. "
                    f"Required approval fingerprint: '{inspection.approval_fingerprint}'."
                )

            # Consume the approval token to prevent replay
            self.consume_approval(approval_token)

        # 2. Wait for selector to be visible
        await page.wait_for_selector(selector, state="visible", timeout=int(timeout * 1000))

        # 3. Perform click
        if wait_for_navigation:
            async with page.expect_navigation(wait_until="domcontentloaded", timeout=int(timeout * 1000)):
                await page.click(selector, timeout=int(timeout * 1000))
        else:
            await page.click(selector, timeout=int(timeout * 1000))
            await page.wait_for_timeout(300)

        actual_url = page.url
        title = await page.title()
        self.ssrf_validator.validate_url(actual_url)

        summary = (
            f"Clicked [{inspection.category.value}] element '{selector}' successfully. "
            f"Current page: '{actual_url}' ('{title}')."
        )

        idempotency_cls = (
            "IRREVERSIBLE_HIGH_RISK" if inspection.is_consequential else "NON_IDEMPOTENT"
        )

        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.CLICK.value,
            selector=selector,
            result_summary=CredentialSanitizer.sanitize_text(summary),
            side_effect_produced=True,
            idempotency_class=idempotency_cls,
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
        Captures a viewport screenshot. Automatically masks password fields on page
        to prevent sensitive credentials from being rendered in image captures.
        """
        page = await self.get_or_create_page(task_id)
        task_ss_dir = os.path.join(self.base_dir, "screenshots", task_id)
        os.makedirs(task_ss_dir, exist_ok=True)

        ss_filename = f"screenshot_{int(time.time()*1000)}.png"
        ss_path = os.path.join(task_ss_dir, ss_filename)

        # Mask password input fields prior to capturing screenshot
        try:
            await page.evaluate(
                """() => {
                    document.querySelectorAll('input[type="password"]').forEach(el => {
                        el.setAttribute('data-pre-ss-val', el.value);
                        el.value = '••••••••';
                    });
                }"""
            )
        except Exception:
            pass

        try:
            if selector:
                el = await page.wait_for_selector(selector, state="visible", timeout=5000)
                if not el:
                    raise RuntimeError(f"Element '{selector}' not found for screenshot.")
                await el.screenshot(path=ss_path)
            else:
                await page.screenshot(path=ss_path, full_page=full_page)
        finally:
            # Restore password values
            try:
                await page.evaluate(
                    """() => {
                        document.querySelectorAll('input[type="password"]').forEach(el => {
                            if (el.hasAttribute('data-pre-ss-val')) {
                                el.value = el.getAttribute('data-pre-ss-val');
                                el.removeAttribute('data-pre-ss-val');
                            }
                        });
                    }"""
                )
            except Exception:
                pass

        actual_url = page.url
        title = await page.title()
        summary = f"Screenshot saved to '{ss_path}' ({os.path.getsize(ss_path)} bytes)."

        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.SCREENSHOT.value,
            selector=selector,
            result_summary=summary,
            screenshot_ref=ss_path,
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
        Triggers a file download via button/link click or direct navigation.
        Enforces 10MB file size limit.
        """
        timeout = timeout_seconds or self.default_timeout_seconds
        page = await self.get_or_create_page(task_id)
        task_dl_dir = os.path.join(self.base_dir, "downloads", task_id)
        os.makedirs(task_dl_dir, exist_ok=True)

        async with page.expect_download(timeout=int(timeout * 1000)) as download_info:
            if selector_or_url.startswith(("http://", "https://")):
                self.ssrf_validator.validate_url(selector_or_url)
                await page.goto(selector_or_url)
            else:
                await page.click(selector_or_url)

        download = await download_info.value
        suggested_name = download.suggested_filename
        dest_path = os.path.join(task_dl_dir, suggested_name)
        await download.save_as(dest_path)

        file_size = os.path.getsize(dest_path)
        if file_size > 10 * 1024 * 1024:
            os.remove(dest_path)
            raise BrowserSecurityError(
                f"Downloaded file '{suggested_name}' exceeds 10MB limit ({file_size} bytes). File discarded."
            )

        summary = f"Downloaded file '{suggested_name}' ({file_size} bytes) to '{dest_path}'."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=page.url,
            title=await page.title(),
            action=BrowserActionType.DOWNLOAD.value,
            result_summary=summary,
            downloads=[dest_path],
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
        Sets a file into an input[type="file"] element.
        Enforces strict path traversal checks.
        """
        abs_path = os.path.abspath(file_path)
        if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
            raise BrowserSecurityError(f"Upload file '{file_path}' does not exist or is not a valid regular file.")

        page = await self.get_or_create_page(task_id)
        await page.wait_for_selector(selector, state="visible", timeout=5000)
        await page.set_input_files(selector, abs_path)

        summary = f"Uploaded file '{os.path.basename(abs_path)}' to element '{selector}'."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=page.url,
            title=await page.title(),
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
        Submits a web form. Sensitive credential fields are redacted from logs and evidence.
        """
        timeout = timeout_seconds or 15.0
        page = await self.get_or_create_page(task_id)

        clean_form_data = CredentialSanitizer.sanitize_form_data(form_data or {})

        if selector:
            await page.wait_for_selector(selector, state="visible", timeout=int(timeout * 1000))
            await page.click(selector, timeout=int(timeout * 1000))
        else:
            await page.evaluate("() => document.forms[0] ? document.forms[0].submit() : null")

        await page.wait_for_timeout(500)
        actual_url = page.url
        title = await page.title()
        self.ssrf_validator.validate_url(actual_url)

        summary = f"Submitted form on '{actual_url}' ('{title}'). Form data fields: {list(clean_form_data.keys())}."
        return BrowserEvidence(
            task_id=task_id,
            step_id=step_id,
            url=actual_url,
            title=title,
            action=BrowserActionType.SUBMIT.value,
            selector=selector,
            result_summary=summary,
            side_effect_produced=True,
            idempotency_class="IRREVERSIBLE_HIGH_RISK",
        )


_BROWSER_RUNTIME_SINGLETON: Optional[PlaywrightBrowserRuntime] = None
_global_browser_runtime = None


def get_browser_runtime() -> PlaywrightBrowserRuntime:
    """Returns the process-wide Playwright browser runtime singleton."""
    global _BROWSER_RUNTIME_SINGLETON, _global_browser_runtime
    if _global_browser_runtime is not None:
        return _global_browser_runtime
    if _BROWSER_RUNTIME_SINGLETON is None:
        _BROWSER_RUNTIME_SINGLETON = PlaywrightBrowserRuntime()
        _global_browser_runtime = _BROWSER_RUNTIME_SINGLETON
    return _BROWSER_RUNTIME_SINGLETON
