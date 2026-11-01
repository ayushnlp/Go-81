"""
Security controls and validation for Go 81 Stage 9 Background Sentinels.
Enforces strict path confinement, symlink escape prevention, sensitive file exclusion,
and untrusted content tagging.
"""

import os
import re
from typing import List, Optional, Tuple

# Sensitive directory names that sentinels must never monitor or traverse
SENSITIVE_DIR_NAMES = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".azure",
    ".kube",
    ".gemini",
    "AppData\\Local\\Google\\Chrome",
    "AppData\\Roaming\\Mozilla\\Firefox",
    "AppData\\Local\\Microsoft\\Edge",
}

# Sensitive file name patterns or exact matches
SENSITIVE_FILE_PATTERNS = [
    re.compile(r"^\.env(\..+)?$", re.IGNORECASE),
    re.compile(r"^id_(rsa|dsa|ecdsa|ed25519)(.*)$", re.IGNORECASE),
    re.compile(r"^.*(secret|token|credential|password|keyring).*\.(json|ya?ml|key|pem|pfx|p12)$", re.IGNORECASE),
    re.compile(r"^\.git[/\\].*hooks[/\\].*$", re.IGNORECASE),
]

# Sensitive system root prefixes
WINDOWS_SYSTEM_PREFIXES = [
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\ProgramData",
]
UNIX_SYSTEM_PREFIXES = [
    "/etc",
    "/var",
    "/usr",
    "/root",
    "/boot",
    "/sys",
    "/proc",
    "/dev",
]

MAX_INSPECT_FILE_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


class PathSecurityValidator:
    """Validates filesystem paths against canonical containment and security blocklists."""

    @staticmethod
    def canonicalize(path: str) -> str:
        """Resolves symlinks, junctions, and relative segments into a normalized absolute path."""
        abs_p = os.path.abspath(path)
        real_p = os.path.realpath(abs_p)
        return os.path.normcase(os.path.normpath(real_p))

    @classmethod
    def is_system_root_path(cls, path: str) -> bool:
        """Returns True if the path targets a sensitive operating system root directory."""
        canon = cls.canonicalize(path)
        if os.name == "nt":
            for prefix in WINDOWS_SYSTEM_PREFIXES:
                canon_prefix = cls.canonicalize(prefix)
                if canon == canon_prefix or canon.startswith(canon_prefix + os.sep):
                    return True
        else:
            for prefix in UNIX_SYSTEM_PREFIXES:
                canon_prefix = cls.canonicalize(prefix)
                if canon == canon_prefix or canon.startswith(canon_prefix + os.sep):
                    return True
        return False

    @classmethod
    def is_sensitive_path(cls, path: str) -> Tuple[bool, Optional[str]]:
        """
        Checks whether a relative or absolute path contains sensitive directories or files.
        Returns (is_sensitive, reason).
        """
        # 1. System root check
        if cls.is_system_root_path(path):
            return True, "Path is within a protected system directory"

        # 2. Directory names
        parts = re.split(r"[\\/]", path)
        for part in parts:
            if part.lower() in [d.lower() for d in SENSITIVE_DIR_NAMES]:
                return True, f"Path component '{part}' is restricted"

        # 3. File name patterns
        basename = os.path.basename(path)
        for pattern in SENSITIVE_FILE_PATTERNS:
            if pattern.match(basename) or pattern.match(path):
                return True, f"File '{basename}' matches sensitive pattern"

        return False, None

    @classmethod
    def validate_confinement(cls, target_path: str, permitted_root: str) -> Tuple[bool, Optional[str], str]:
        """
        Verifies that target_path is strictly confined within permitted_root.
        Guards against traversal (..) and symlink/junction escape attacks.
        Returns: (is_valid, error_reason, canonical_target_path).
        """
        canon_root = cls.canonicalize(permitted_root)
        canon_target = cls.canonicalize(target_path)

        if not os.path.exists(canon_root):
            return False, f"Permitted root does not exist: {permitted_root}", canon_target

        # Check prefix confinement
        if not (canon_target == canon_root or canon_target.startswith(canon_root + os.sep)):
            return False, f"Path escape detected: '{target_path}' resolves outside '{permitted_root}'", canon_target

        # Check sensitive paths
        is_sens, reason = cls.is_sensitive_path(canon_target)
        if is_sens:
            return False, f"Sensitive path access blocked: {reason}", canon_target

        return True, None, canon_target


class UntrustedContentGuard:
    """Wraps untrusted file or external input with clear delimiter tags to prevent prompt injection."""

    @staticmethod
    def wrap_content(source_ref: str, content: str, size_bytes: int) -> str:
        """Encloses raw content in security boundary delimiters."""
        sanitized = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", content)
        return (
            f"=== UNTRUSTED DATA FROM FILESYSTEM ===\n"
            f"Source: {source_ref}\n"
            f"Size: {size_bytes} bytes\n"
            f"Payload Content:\n"
            f"{sanitized}\n"
            f"=== END UNTRUSTED DATA ==="
        )

