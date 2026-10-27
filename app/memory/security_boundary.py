"""
Security Boundary Subsystem for Project Go 81.

Enforces:
1. Canonical project-root scoping with symlink-aware path resolution.
2. Path traversal rejection (no escaping '../' or symlink tricks).
3. Read vs. Write filesystem capability segregation.
4. Command execution constraints and dangerous shell operator rejection.
5. Approval parameter integrity revalidation (action + resource + parameter hash).
6. Localhost loopback binding enforcement.
"""

import hashlib
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.memory.database import DatabaseManager, utc_now
from app.memory.models import utc_now_iso

logger = logging.getLogger(__name__)


class SecurityBoundaryError(Exception):
    """Base exception for security boundary violations."""
    pass


class PathTraversalError(SecurityBoundaryError):
    """Raised when an operation attempts to escape the permitted project root."""
    pass


class DangerousCommandError(SecurityBoundaryError):
    """Raised when an unconstrained or dangerous shell command is proposed."""
    pass


class ApprovalTamperError(SecurityBoundaryError):
    """Raised when action parameters have been altered after approval was issued."""
    pass


# Disallowed dangerous shell operators in automated agent actions
DANGEROUS_SHELL_PATTERNS = [
    re.compile(r"(\||;|&&|\|\||`|\$\()"),  # Chaining, pipes, command substitution
    re.compile(r">\s*/etc/", re.IGNORECASE),
    re.compile(r">\s*/System/", re.IGNORECASE),
    re.compile(r">\s*C:\\Windows\\", re.IGNORECASE),
    re.compile(r"\b(rm\s+-rf\s+[/~]|del\s+/[sfdq]\s+[c-z]:\\)", re.IGNORECASE),
]


class SecurityBoundary:
    """
    Validates and constrains local project operations.
    Acts as the defensive gate between agent proposals and host OS execution.
    Supports durable SQLite-backed approval tokens surviving application restarts.
    """
    _db: Optional[DatabaseManager] = None

    def __init__(self, permitted_root: str, db: Optional[DatabaseManager] = None):
        self.permitted_root = os.path.abspath(os.path.realpath(permitted_root))
        self.db = db or SecurityBoundary._db

    # ------------------------------------------------------------------------
    # Filesystem Scoping & Traversal Rejection
    # ------------------------------------------------------------------------

    def resolve_safe_path(self, target_path: str, allow_symlinks_outside: bool = False) -> str:
        """
        Resolves a target path against the permitted project root.
        Rejects:
        - Relative traversal attempts (e.g. '../../etc/passwd')
        - Escaping symlinks (points outside permitted_root)
        - Absolute paths outside the permitted root.
        """
        if not target_path or not target_path.strip():
            raise PathTraversalError("Empty or blank path provided.")

        # If relative, join with permitted root
        if not os.path.isabs(target_path):
            combined = os.path.join(self.permitted_root, target_path)
        else:
            combined = target_path

        # Canonical normalization
        normalized = os.path.abspath(combined)

        # Symlink-aware canonical resolution
        if not allow_symlinks_outside:
            real = os.path.realpath(normalized)
        else:
            real = normalized

        # Strict root containment verification
        # Must be either identical to root, or within root with separator
        is_subpath = (
            real == self.permitted_root
            or real.startswith(self.permitted_root + os.sep)
            or real.startswith(self.permitted_root + "/")
        )

        if not is_subpath:
            logger.warning(
                f"SecurityBoundary: Blocked path traversal attempt '{target_path}'. "
                f"Resolved to '{real}' outside permitted root '{self.permitted_root}'."
            )
            raise PathTraversalError(
                f"Path '{target_path}' escapes permitted project root '{self.permitted_root}'."
            )

        return real

    def validate_file_access(self, target_path: str, mode: str = "read") -> str:
        """
        Validates path traversal safety and enforces read vs write capabilities.
        """
        safe_path = self.resolve_safe_path(target_path)

        if mode == "read":
            if not os.path.exists(safe_path):
                raise FileNotFoundError(f"File not found: '{target_path}'")
        elif mode == "write":
            parent = os.path.dirname(safe_path)
            if parent and not os.path.exists(parent):
                # Ensure parent is within root as well
                self.resolve_safe_path(parent)
        else:
            raise ValueError(f"Unsupported access mode: '{mode}'. Must be 'read' or 'write'.")

        return safe_path

    # ------------------------------------------------------------------------
    # Command Execution Scoping
    # ------------------------------------------------------------------------

    def validate_command_safety(self, command: str) -> None:
        """
        Validates that a proposed shell command does not contain dangerous operators,
        arbitrary shell chains, or root-directory wipe instructions.
        """
        if not command or not command.strip():
            raise DangerousCommandError("Empty command string provided.")

        for pattern in DANGEROUS_SHELL_PATTERNS:
            if pattern.search(command):
                raise DangerousCommandError(
                    f"Command contains restricted shell operators or unsafe patterns: '{command}'"
                )

    # In-memory approval token tracking (token -> metadata) and consumed replay set
    _approval_registry: Dict[str, Dict[str, Any]] = {}
    _consumed_tokens: set = set()

    def safe_open(self, target_path: str, mode: str = "r", **kwargs):
        """
        Opens a file while verifying that symlink replacement between check and open
        cannot escape the permitted root (TOCTOU defense).
        """
        safe_path = self.resolve_safe_path(target_path, allow_symlinks_outside=False)
        f = open(safe_path, mode, **kwargs)
        try:
            # Re-verify realpath of opened path to guard against post-check symlink swapping
            rechecked = os.path.realpath(safe_path)
            is_subpath = (
                rechecked == self.permitted_root
                or rechecked.startswith(self.permitted_root + os.sep)
                or rechecked.startswith(self.permitted_root + "/")
            )
            if not is_subpath:
                f.close()
                raise PathTraversalError(f"TOCTOU violation: symlink swapped during file access '{target_path}'.")
            return f
        except Exception:
            f.close()
            raise

    # ------------------------------------------------------------------------
    # Approval Revalidation & Replay Prevention (Anti-Tampering)
    # ------------------------------------------------------------------------

    @staticmethod
    def compute_action_hash(action: str, resource: str, parameters: Dict[str, Any]) -> str:
        """
        Computes deterministic SHA-256 hash of an approved action and its parameters.
        """
        serialized_params = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        canonical_str = f"{action}|{resource}|{serialized_params}"
        return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()

    def create_approval_token(
        self,
        action: str,
        resource: str,
        parameters: Dict[str, Any],
        ttl_seconds: int = 300,
        task_id: Optional[str] = None,
        risk_level: str = "HIGH",
        notes: Optional[str] = None,
    ) -> str:
        """
        Generates an ephemeral, parameter-bound approval token.
        Cannot be reused or repurposed for other actions or modified parameters.
        Persisted durably to SQLite approval_records when database is available.
        """
        token = f"tok-{uuid.uuid4().hex}"
        approval_id = f"apr-{uuid.uuid4().hex[:12]}"
        param_hash = self.compute_action_hash(action, resource, parameters)
        expires_at = time.time() + ttl_seconds
        now_iso = utc_now_iso()

        # In-memory registry for rapid synchronous lookup
        SecurityBoundary._approval_registry[token] = {
            "approval_id": approval_id,
            "token": token,
            "task_id": task_id,
            "action": action,
            "resource": resource,
            "param_hash": param_hash,
            "parameters": parameters,
            "status": "APPROVED",
            "expires_at": expires_at,
            "created_at": now_iso,
        }

        # Persistent SQLite storage
        db = self.db or SecurityBoundary._db
        if db:
            try:
                with db.transaction() as conn:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO approval_records (
                            approval_id, token, task_id, action, resource,
                            param_hash, parameters, status, risk_level, notes,
                            created_at, expires_at, metadata
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            approval_id,
                            token,
                            task_id,
                            action,
                            resource,
                            param_hash,
                            json.dumps(parameters, sort_keys=True),
                            "APPROVED",
                            risk_level,
                            notes,
                            now_iso,
                            expires_at,
                            "{}",
                        ),
                    )
            except Exception as e:
                logger.warning(f"Failed to persist approval token to SQLite: {e}")

        return token

    def consume_approval_token(
        self,
        approval_token: Optional[str] = None,
        action: str = "",
        resource: str = "",
        parameters: Optional[Dict[str, Any]] = None,
        *,
        token: Optional[str] = None,
        expected_action: Optional[str] = None,
        expected_resource: Optional[str] = None,
    ) -> bool:
        """
        Validates and consumes a single-use approval token.
        Enforces:
        1. Single-use: rejects replay attempts atomically.
        2. Expiration: rejects expired tokens.
        3. Parameter integrity: rejects tokens if parameters, action, or resource were altered.
        Atomically transitions the token status to CONSUMED in SQLite.
        Returns True on success.
        """
        tok = approval_token or token
        act = action or expected_action or ""
        res = resource or expected_resource or ""
        params = parameters if parameters is not None else {}

        if not tok:
            raise ApprovalTamperError("Operation requires human approval token, but none was provided.")

        db = self.db or SecurityBoundary._db
        if db:
            try:
                with db.transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT approval_id, token, task_id, action, resource,
                               param_hash, parameters, status, expires_at
                        FROM approval_records
                        WHERE token = ?;
                        """,
                        (tok,),
                    )
                    row = cursor.fetchone()
                    if row:
                        status = row["status"]
                        if status == "CONSUMED" or tok in SecurityBoundary._consumed_tokens:
                            raise ApprovalTamperError(
                                f"Replay detected: approval token '{tok}' has already been consumed and cannot be reused."
                            )
                        if status == "REJECTED":
                            raise ApprovalTamperError(f"Approval token '{tok}' has been rejected.")
                        if status == "REVOKED":
                            raise ApprovalTamperError(f"Approval token '{tok}' has been revoked.")
                        if status != "APPROVED":
                            raise ApprovalTamperError(
                                f"Approval token '{tok}' is not in APPROVED state (currently '{status}')."
                            )

                        if time.time() > row["expires_at"]:
                            conn.execute("UPDATE approval_records SET status = 'EXPIRED' WHERE token = ?;", (tok,))
                            raise ApprovalTamperError(f"Approval token '{tok}' has expired.")

                        if row["action"] != act or (row["resource"] != "*" and row["resource"] != res):
                            raise ApprovalTamperError(
                                f"Approval token was issued for {row['action']} on {row['resource']}, "
                                f"cannot be repurposed for {act} on {res}."
                            )

                        current_hash = self.compute_action_hash(act, res, params)
                        if row["param_hash"] != "*" and row["param_hash"] != current_hash:
                            raise ApprovalTamperError(
                                "Action parameters were modified after human approval was granted! "
                                f"Expected hash '{row['param_hash']}', computed '{current_hash}'."
                            )

                        # Atomic single-use consumption with conditional write
                        now_iso = utc_now_iso()
                        cursor.execute(
                            """
                            UPDATE approval_records
                            SET status = 'CONSUMED', consumed_at = ?
                            WHERE token = ? AND status = 'APPROVED';
                            """,
                            (now_iso, tok),
                        )
                        if cursor.rowcount == 0:
                            raise ApprovalTamperError(
                                f"Replay detected: approval token '{tok}' has already been consumed and cannot be reused."
                            )

                        SecurityBoundary._consumed_tokens.add(tok)
                        SecurityBoundary._approval_registry.pop(tok, None)
                        return True
            except ApprovalTamperError:
                raise
            except Exception as e:
                logger.warning(f"SQLite consumption check encountered error, checking in-memory: {e}")

        # In-memory validation fallback (when database is offline or token exists only in memory)
        if tok in SecurityBoundary._consumed_tokens:
            raise ApprovalTamperError(
                f"Replay detected: approval token '{tok}' has already been consumed and cannot be reused."
            )

        if tok not in SecurityBoundary._approval_registry:
            raise ApprovalTamperError(
                f"Approval token '{tok}' is invalid, unrecognized, or already expired."
            )

        token_data = SecurityBoundary._approval_registry[tok]

        # Check expiration
        if time.time() > token_data["expires_at"]:
            del SecurityBoundary._approval_registry[tok]
            raise ApprovalTamperError(f"Approval token '{tok}' has expired.")

        # Check action & resource binding
        if token_data["action"] != act or (token_data["resource"] != "*" and token_data["resource"] != res):
            raise ApprovalTamperError(
                f"Approval token was issued for {token_data['action']} on {token_data['resource']}, "
                f"cannot be repurposed for {act} on {res}."
            )

        # Check parameter hash integrity
        current_hash = self.compute_action_hash(act, res, params)
        if token_data["param_hash"] != "*" and token_data["param_hash"] != current_hash:
            raise ApprovalTamperError(
                "Action parameters were modified after human approval was granted! "
                f"Expected hash '{token_data['param_hash']}', computed '{current_hash}'."
            )

        # Mark consumed (single use)
        del SecurityBoundary._approval_registry[tok]
        SecurityBoundary._consumed_tokens.add(tok)
        return True

    def revalidate_approved_operation(
        self,
        approval_token: Optional[str],
        action: str,
        resource: str,
        parameters: Dict[str, Any],
        expected_token: Optional[str],
        expected_hash: Optional[str],
    ) -> None:
        """
        Revalidates that an action being executed exactly matches the action, resource,
        and parameter payload that the human user authorized.
        """
        if not approval_token:
            raise ApprovalTamperError("Operation requires human approval token, but none was provided.")

        if expected_token and approval_token != expected_token:
            raise ApprovalTamperError(
                f"Mismatched approval token: received '{approval_token}', expected '{expected_token}'."
            )

        if expected_hash:
            current_hash = self.compute_action_hash(action, resource, parameters)
            if current_hash != expected_hash:
                raise ApprovalTamperError(
                    "Action parameters were modified after human approval was granted! "
                    f"Expected hash '{expected_hash}', but computed '{current_hash}'."
                )

    # ------------------------------------------------------------------------
    # Loopback Verification
    # ------------------------------------------------------------------------

    @staticmethod
    def verify_loopback_binding(host: str) -> bool:
        """Verifies that the network listener is restricted to loopback."""
        loopback_hosts = {"127.0.0.1", "localhost", "::1"}
        return host.lower() in loopback_hosts

