"""
Stage 8 & 8.1: Autonomous Browser & Web Automation Subsystem for Project Go 81.
"""

from backend.browser.models import (
    ApprovalBindingTamperError,
    BrowserActionTimeoutError,
    BrowserActionType,
    BrowserEvidence,
    BrowserSecurityError,
    ClickTargetInspection,
    ConsequentialActionApprovalRequiredError,
    ConsequentialCategory,
    PromptInjectionAttemptError,
    SSRFSecurityError,
)
from backend.browser.runtime import (
    PlaywrightBrowserRuntime,
    get_browser_runtime,
)
from backend.browser.security import (
    CredentialSanitizer,
    PromptInjectionDefense,
    SSRFValidator,
)

__all__ = [
    "ApprovalBindingTamperError",
    "BrowserActionTimeoutError",
    "BrowserActionType",
    "BrowserEvidence",
    "BrowserSecurityError",
    "ClickTargetInspection",
    "ConsequentialActionApprovalRequiredError",
    "ConsequentialCategory",
    "CredentialSanitizer",
    "PlaywrightBrowserRuntime",
    "PromptInjectionAttemptError",
    "PromptInjectionDefense",
    "SSRFSecurityError",
    "SSRFValidator",
    "get_browser_runtime",
]
