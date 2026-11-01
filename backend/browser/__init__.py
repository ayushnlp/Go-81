"""
Stage 8: Autonomous Browser & Web Automation Subsystem for Project Go 81.
"""

from backend.browser.models import (
    BrowserActionTimeoutError,
    BrowserActionType,
    BrowserEvidence,
    BrowserSecurityError,
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
    "BrowserActionTimeoutError",
    "BrowserActionType",
    "BrowserEvidence",
    "BrowserSecurityError",
    "CredentialSanitizer",
    "PlaywrightBrowserRuntime",
    "PromptInjectionAttemptError",
    "PromptInjectionDefense",
    "SSRFSecurityError",
    "SSRFValidator",
    "get_browser_runtime",
]

