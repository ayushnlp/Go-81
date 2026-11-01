"""
Stage 8: Browser Skills Registration and Handlers for Project Go 81.
Integrates Playwright browser actions into the existing SkillRegistry and PermissionGateway.
Enforces SSRF validation, risk tiers, and Human Approval Gates on sensitive operations.
"""

import os
from typing import Any, Dict, Optional

from app.skills.models import (
    Capability,
    ExecutionContext,
    FilesystemScope,
    NetworkScope,
    ResourceLimits,
    RetryPolicy,
    SkillCategory,
    SkillDefinition,
    SkillParameter,
    SkillRiskLevel,
)
from app.skills.registry import SkillRegistry
from backend.browser.models import BrowserActionType, BrowserEvidence
from backend.browser.runtime import PlaywrightBrowserRuntime, get_browser_runtime
from backend.browser.security import CredentialSanitizer, SSRFValidator


# ============================================================================
# Skill Handlers
# ============================================================================

async def _browser_navigate_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    url = str(params["url"])
    timeout = params.get("timeout_seconds", 30.0)

    evidence: BrowserEvidence = await runtime.navigate(
        task_id=task_id,
        url=url,
        step_id=context.step_id,
        timeout_seconds=float(timeout),
    )
    return evidence.model_dump()


async def _browser_inspect_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = params.get("selector")
    max_chars = params.get("max_chars", 8192)

    evidence: BrowserEvidence = await runtime.inspect(
        task_id=task_id,
        step_id=context.step_id,
        selector=selector,
        max_chars=int(max_chars),
    )
    return evidence.model_dump()


async def _browser_click_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = str(params["selector"])
    wait_nav = params.get("wait_for_navigation", False)
    timeout = params.get("timeout_seconds", 10.0)

    evidence: BrowserEvidence = await runtime.click(
        task_id=task_id,
        selector=selector,
        step_id=context.step_id,
        wait_for_navigation=bool(wait_nav),
        timeout_seconds=float(timeout),
    )
    return evidence.model_dump()


async def _browser_fill_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = str(params["selector"])
    value = str(params["value"])
    timeout = params.get("timeout_seconds", 10.0)

    evidence: BrowserEvidence = await runtime.fill(
        task_id=task_id,
        selector=selector,
        value=value,
        step_id=context.step_id,
        timeout_seconds=float(timeout),
    )
    return evidence.model_dump()


async def _browser_select_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = str(params["selector"])
    value = str(params["value"])
    timeout = params.get("timeout_seconds", 10.0)

    evidence: BrowserEvidence = await runtime.select(
        task_id=task_id,
        selector=selector,
        value=value,
        step_id=context.step_id,
        timeout_seconds=float(timeout),
    )
    return evidence.model_dump()


async def _browser_screenshot_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = params.get("selector")
    full_page = params.get("full_page", False)

    evidence: BrowserEvidence = await runtime.screenshot(
        task_id=task_id,
        step_id=context.step_id,
        selector=selector,
        full_page=bool(full_page),
    )
    return evidence.model_dump()


async def _browser_download_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = str(params["selector_or_url"])
    timeout = params.get("timeout_seconds", 30.0)

    evidence: BrowserEvidence = await runtime.download(
        task_id=task_id,
        selector_or_url=selector,
        step_id=context.step_id,
        timeout_seconds=float(timeout),
    )
    return evidence.model_dump()


async def _browser_upload_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = str(params["selector"])
    file_path = str(params["file_path"])

    evidence: BrowserEvidence = await runtime.upload(
        task_id=task_id,
        selector=selector,
        file_path=file_path,
        step_id=context.step_id,
    )
    return evidence.model_dump()


async def _browser_submit_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    runtime = get_browser_runtime()
    task_id = context.task_id or "default-browser-task"
    selector = params.get("selector")
    form_data = params.get("form_data", {})
    timeout = params.get("timeout_seconds", 15.0)

    evidence: BrowserEvidence = await runtime.submit(
        task_id=task_id,
        selector=selector,
        form_data=form_data,
        step_id=context.step_id,
        timeout_seconds=float(timeout),
    )
    return evidence.model_dump()


# ============================================================================
# Registration Function
# ============================================================================

def register_browser_skills(registry: SkillRegistry) -> None:
    """
    Registers the 9 core Stage 8 Autonomous Browser skills into the SkillRegistry.
    Configures strict risk levels, required capabilities, resource limits, and approval gates.
    """

    # 1. browser.navigate
    registry.register(
        SkillDefinition(
            id=BrowserActionType.NAVIGATE.value,
            name=BrowserActionType.NAVIGATE.value,
            displayName="Browser Navigate",
            version="1.0.0",
            description="Navigates to a validated external HTTP/HTTPS URL with strict SSRF protection.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.MEDIUM,
            requires_approval=False,
            parameters=[
                SkillParameter(name="url", type="string", description="Destination web URL (http/https only)", required=True),
                SkillParameter(name="timeout_seconds", type="number", description="Page load timeout in seconds", required=False, default=30.0, min_value=1.0, max_value=60.0),
            ],
            resource_limits=ResourceLimits(timeout_seconds=45.0, max_memory_mb=512),
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=1),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_navigate_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 2. browser.inspect
    registry.register(
        SkillDefinition(
            id=BrowserActionType.INSPECT.value,
            name=BrowserActionType.INSPECT.value,
            displayName="Browser Inspect",
            version="1.0.0",
            description="Extracts sanitized visible text, page title, URL, or specific element DOM.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.LOW,
            requires_approval=False,
            parameters=[
                SkillParameter(name="selector", type="string", description="Optional element selector or accessible name", required=False, default=None),
                SkillParameter(name="max_chars", type="integer", description="Maximum characters to extract", required=False, default=8192, min_value=128, max_value=32768),
            ],
            resource_limits=ResourceLimits(timeout_seconds=15.0, max_memory_mb=256),
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=2),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_inspect_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 3. browser.click
    registry.register(
        SkillDefinition(
            id=BrowserActionType.CLICK.value,
            name=BrowserActionType.CLICK.value,
            displayName="Browser Click",
            version="1.0.0",
            description="Clicks a button, link, or accessible interactive element on the page.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.MEDIUM,
            requires_approval=False,
            parameters=[
                SkillParameter(name="selector", type="string", description="Element selector or accessible name to click", required=True),
                SkillParameter(name="wait_for_navigation", type="boolean", description="Whether to wait for page navigation", required=False, default=False),
                SkillParameter(name="timeout_seconds", type="number", description="Timeout in seconds", required=False, default=10.0),
            ],
            resource_limits=ResourceLimits(timeout_seconds=20.0, max_memory_mb=256),
            retry_policy=RetryPolicy(is_idempotent=False, max_retries=0),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_click_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 4. browser.fill
    registry.register(
        SkillDefinition(
            id=BrowserActionType.FILL.value,
            name=BrowserActionType.FILL.value,
            displayName="Browser Fill Form Control",
            version="1.0.0",
            description="Fills an input or textarea control. Credentials and sensitive values are redacted.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.MEDIUM,
            requires_approval=False,
            parameters=[
                SkillParameter(name="selector", type="string", description="Target input or textarea selector", required=True),
                SkillParameter(name="value", type="string", description="Text content to enter", required=True),
                SkillParameter(name="timeout_seconds", type="number", description="Timeout in seconds", required=False, default=10.0),
            ],
            resource_limits=ResourceLimits(timeout_seconds=20.0, max_memory_mb=256),
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=1),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_fill_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 5. browser.select
    registry.register(
        SkillDefinition(
            id=BrowserActionType.SELECT.value,
            name=BrowserActionType.SELECT.value,
            displayName="Browser Select Option",
            version="1.0.0",
            description="Selects an option from a dropdown or toggles a radio button / checkbox.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.MEDIUM,
            requires_approval=False,
            parameters=[
                SkillParameter(name="selector", type="string", description="Dropdown or checkbox selector", required=True),
                SkillParameter(name="value", type="string", description="Option value or label to select", required=True),
                SkillParameter(name="timeout_seconds", type="number", description="Timeout in seconds", required=False, default=10.0),
            ],
            resource_limits=ResourceLimits(timeout_seconds=20.0, max_memory_mb=256),
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=1),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_select_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 6. browser.screenshot
    registry.register(
        SkillDefinition(
            id=BrowserActionType.SCREENSHOT.value,
            name=BrowserActionType.SCREENSHOT.value,
            displayName="Browser Screenshot",
            version="1.0.0",
            description="Captures a high-resolution screenshot stored into isolated task storage.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.LOW,
            requires_approval=False,
            parameters=[
                SkillParameter(name="selector", type="string", description="Optional element selector to screenshot", required=False, default=None),
                SkillParameter(name="full_page", type="boolean", description="Whether to capture entire scrollable page", required=False, default=False),
            ],
            resource_limits=ResourceLimits(timeout_seconds=20.0, max_memory_mb=256),
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=2),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_screenshot_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 7. browser.download
    registry.register(
        SkillDefinition(
            id=BrowserActionType.DOWNLOAD.value,
            name=BrowserActionType.DOWNLOAD.value,
            displayName="Browser Download File",
            version="1.0.0",
            description="Triggers a file download via button or link click, enforcing a 10MB limit.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.MEDIUM,
            requires_approval=False,
            parameters=[
                SkillParameter(name="selector_or_url", type="string", description="Download button selector or URL", required=True),
                SkillParameter(name="timeout_seconds", type="number", description="Timeout in seconds", required=False, default=30.0),
            ],
            resource_limits=ResourceLimits(timeout_seconds=45.0, max_memory_mb=512),
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=1),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_download_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 8. browser.upload
    registry.register(
        SkillDefinition(
            id=BrowserActionType.UPLOAD.value,
            name=BrowserActionType.UPLOAD.value,
            displayName="Browser Upload File",
            version="1.0.0",
            description="Uploads a local file to a web form input with strict path traversal checks.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.HIGH,
            requires_approval=True,
            parameters=[
                SkillParameter(name="selector", type="string", description="File input selector", required=True),
                SkillParameter(name="file_path", type="string", description="Path to local file to upload", required=True),
            ],
            resource_limits=ResourceLimits(timeout_seconds=30.0, max_memory_mb=256),
            retry_policy=RetryPolicy(is_idempotent=False, max_retries=0),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_upload_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 9. browser.submit
    registry.register(
        SkillDefinition(
            id=BrowserActionType.SUBMIT.value,
            name=BrowserActionType.SUBMIT.value,
            displayName="Browser Form Submit",
            version="1.0.0",
            description="Submits a web form. High-risk operations (registration, payment, job applications, messaging) strictly require explicit human approval.",
            category=SkillCategory.NETWORK,
            required_capabilities=[],
            risk_level=SkillRiskLevel.HIGH,
            requires_approval=True,
            parameters=[
                SkillParameter(name="selector", type="string", description="Submit button selector or form selector", required=False, default=None),
                SkillParameter(name="form_data", type="object", description="Form fields map being submitted", required=False, default={}),
                SkillParameter(name="timeout_seconds", type="number", description="Timeout in seconds", required=False, default=15.0),
            ],
            resource_limits=ResourceLimits(timeout_seconds=30.0, max_memory_mb=512),
            retry_policy=RetryPolicy(is_idempotent=False, max_retries=0),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_browser_submit_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

