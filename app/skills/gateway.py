"""
Deterministic Permission Gateway for Project Go 81.
Enforces default-deny, risk-aware escalation, and single-use,
tamper-evident approval tokens bound to canonical action hashes.
"""

import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple, Union

from app.memory.database import DatabaseManager, utc_now
from app.memory.models import utc_now_iso
from app.skills.models import (
    AuthorizationDecision,
    Capability,
    ExecutionContext,
    SkillDefinition,
    SkillRiskLevel,
)
from app.skills.registry import (
    SkillDisabledError,
    SkillNotFoundError,
    SkillRegistry,
    compute_action_hash,
)

logger = logging.getLogger(__name__)


class PermissionGatewayError(Exception):
    """Base exception for permission gateway errors."""
    pass


class ActionDeniedError(PermissionGatewayError):
    """Raised when an action is denied by policy or missing approval."""
    pass


class ApprovalValidationError(PermissionGatewayError):
    """Raised when an approval token fails verification."""
    pass


class ApprovalExpiredError(ApprovalValidationError):
    """Raised when an approval token has passed its expiration window."""
    pass


class ApprovalConsumedError(ApprovalValidationError):
    """Raised when a single-use approval token has already been consumed (replay attempt)."""
    pass


class ApprovalTamperError(ApprovalValidationError):
    """Raised when action parameters, version, or scope do not match the authorized hash."""
    pass


class SecurityPermissionGateway:
    """
    Centralized Permission Enforcement Point for Go 81.
    All skill executions MUST pass through authorize_skill_execution().
    """

    def __init__(self, db: DatabaseManager, registry: SkillRegistry):
        self.db = db
        self.registry = registry
        # Ephemeral memory fallback cache for approvals
        self._in_memory_approvals: Dict[str, Dict[str, Any]] = {}

    def authorize_skill_execution(
        self,
        skill_id: str,
        validated_params: Dict[str, Any],
        context: ExecutionContext,
    ) -> AuthorizationDecision:
        """
        Determines whether a proposed skill execution is authorized.
        Enforces default-deny, single-use approval verification, and parameter integrity.
        """
        # 1. Verify skill exists and is active
        try:
            skill = self.registry.get(skill_id)
        except SkillNotFoundError:
            return AuthorizationDecision(
                allowed=False,
                reason=f"Skill '{skill_id}' is not registered in system registry.",
                risk_level=SkillRiskLevel.CRITICAL,
            )

        if not skill.enabled:
            return AuthorizationDecision(
                allowed=False,
                reason=f"Skill '{skill_id}' is currently disabled.",
                risk_level=skill.risk_level,
            )

        # 1b. Enforce Capability Default-Deny Policy
        valid_system_caps = {c.value for c in Capability}
        for cap in skill.required_capabilities:
            if cap not in valid_system_caps:
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"Capability '{cap}' is not recognized or permitted under system default-deny policy.",
                    action_hash=None,
                    risk_level=SkillRiskLevel.CRITICAL,
                )

        if context.granted_capabilities is not None:
            granted_set = set(context.granted_capabilities)
            for cap in skill.required_capabilities:
                if cap not in granted_set:
                    return AuthorizationDecision(
                        allowed=False,
                        reason=f"Required capability '{cap}' is not granted in the execution context under default-deny policy.",
                        action_hash=None,
                        risk_level=SkillRiskLevel.HIGH,
                    )

        # 2. Determine applicable scope and canonical action hash
        scope: Dict[str, Any] = {}
        if skill.filesystem_scope:
            scope["filesystem"] = skill.filesystem_scope.model_dump()
        if skill.network_scope:
            scope["network"] = skill.network_scope.model_dump()

        action_hash = compute_action_hash(
            skill_id=skill.id,
            version=skill.version,
            parameters=validated_params,
            capabilities=skill.required_capabilities,
            scope=scope,
        )

        # 3. Check effective risk level and approval requirement
        requires_approval = skill.requires_approval or (skill.risk_level in (SkillRiskLevel.HIGH, SkillRiskLevel.CRITICAL))
        
        # Sensitive capabilities escalate to requiring approval
        sensitive_caps = {
            Capability.FILESYSTEM_WRITE.value,
            Capability.NETWORK_HTTP.value,
            Capability.SHELL_EXECUTE.value,
        }
        if any(c in sensitive_caps for c in skill.required_capabilities):
            requires_approval = True

        # 4. If action requires approval, validate the provided token
        if requires_approval:
            approval_token = context.approval_token
            if not approval_token:
                # Issue pending approval request
                pending_id = f"apr-{uuid.uuid4().hex[:12]}"
                self._create_pending_approval(
                    approval_id=pending_id,
                    task_id=context.task_id,
                    skill=skill,
                    action_hash=action_hash,
                    parameters=validated_params,
                )
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"Action '{skill_id}' ({skill.risk_level.value} risk) requires explicit human confirmation.",
                    approval_required=True,
                    approval_id=pending_id,
                    action_hash=action_hash,
                    risk_level=skill.risk_level,
                )

            # Validate and atomically consume the approval token
            is_valid, validation_reason = self._validate_and_consume_approval(
                token=approval_token,
                skill=skill,
                expected_hash=action_hash,
            )
            if not is_valid:
                return AuthorizationDecision(
                    allowed=False,
                    reason=f"Authorization rejected: {validation_reason}",
                    approval_required=True,
                    approval_id=None,
                    action_hash=action_hash,
                    risk_level=skill.risk_level,
                )

            # Successfully authorized by valid approval token
            return AuthorizationDecision(
                allowed=True,
                reason=f"Action '{skill_id}' authorized by verified human approval token.",
                approval_required=False,
                approval_id=approval_token,
                action_hash=action_hash,
                risk_level=skill.risk_level,
            )

        # 5. Low risk actions authorized under standard policy
        return AuthorizationDecision(
            allowed=True,
            reason=f"Action '{skill_id}' authorized under standard LOW/MEDIUM risk policy.",
            approval_required=False,
            approval_id=None,
            action_hash=action_hash,
            risk_level=skill.risk_level,
        )

    def create_approval_token(
        self,
        skill_id: str,
        parameters: Dict[str, Any],
        ttl_seconds: int = 300,
        task_id: Optional[str] = None,
        notes: str = "Granted via SecurityPermissionGateway",
    ) -> Tuple[str, str]:
        """
        Creates a pre-approved, single-use token bound to a specific skill and parameters.
        Returns: (approval_id, token)
        """
        skill = self.registry.get(skill_id)
        try:
            parameters = self.registry.validate_arguments(skill_id, parameters)
        except Exception:
            pass
        scope: Dict[str, Any] = {}
        if skill.filesystem_scope:
            scope["filesystem"] = skill.filesystem_scope.model_dump()
        if skill.network_scope:
            scope["network"] = skill.network_scope.model_dump()

        action_hash = compute_action_hash(
            skill_id=skill.id,
            version=skill.version,
            parameters=parameters,
            capabilities=skill.required_capabilities,
            scope=scope,
        )

        approval_id = f"apr-{uuid.uuid4().hex[:12]}"
        token = f"tok-{uuid.uuid4().hex}"
        now_iso = utc_now_iso()
        expires_at = time.time() + ttl_seconds

        if self.db:
            try:
                with self.db.transaction() as conn:
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
                            skill_id,
                            skill_id,
                            action_hash,
                            json.dumps(parameters, sort_keys=True),
                            "APPROVED",
                            skill.risk_level.value.upper(),
                            notes,
                            now_iso,
                            expires_at,
                            json.dumps({"version": skill.version}),
                        ),
                    )
            except Exception as e:
                logger.warning(f"Failed to record approval token in database: {e}")

        self._in_memory_approvals[token] = {
            "approval_id": approval_id,
            "action": skill_id,
            "param_hash": action_hash,
            "expires_at": expires_at,
            "status": "APPROVED",
        }

        return approval_id, token

    def resolve_pending_approval(
        self,
        approval_id: str,
        approved: bool,
        rejection_reason: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Human-in-the-loop endpoint: resolves a pending approval ID.
        If approved, generates and returns the single-use token.
        """
        now_iso = utc_now_iso()
        with self.db.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT approval_id, token, action, param_hash, status, expires_at FROM approval_records WHERE approval_id = ?;",
                (approval_id,),
            )
            row = cursor.fetchone()
            if not row:
                return False, None

            current_status = row["status"]
            if current_status != "PENDING":
                return False, None

            if approved:
                token = f"tok-{uuid.uuid4().hex}"
                cursor.execute(
                    """
                    UPDATE approval_records
                    SET status = 'APPROVED', token = ?, resolved_at = ?
                    WHERE approval_id = ?;
                    """,
                    (token, now_iso, approval_id),
                )
                self._in_memory_approvals[token] = {
                    "approval_id": approval_id,
                    "action": row["action"],
                    "param_hash": row["param_hash"],
                    "expires_at": row["expires_at"],
                    "status": "APPROVED",
                }
                return True, token
            else:
                cursor.execute(
                    """
                    UPDATE approval_records
                    SET status = 'REJECTED', rejection_reason = ?, resolved_at = ?
                    WHERE approval_id = ?;
                    """,
                    (rejection_reason or "Rejected by user", now_iso, approval_id),
                )
                return False, None

    def get_approval_record(self, approval_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an approval record by ID."""
        if not self.db:
            return None
        try:
            conn = self.db.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT approval_id, token, task_id, action, resource, param_hash, parameters, status, risk_level, notes, created_at, expires_at FROM approval_records WHERE approval_id = ?;",
                    (approval_id,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(row)
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to query approval record {approval_id}: {e}")
            return None

    def list_pending_approvals(self) -> List[Dict[str, Any]]:
        """Retrieves all pending approvals awaiting human authorization."""
        if not self.db:
            return []
        try:
            conn = self.db.get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT approval_id, task_id, action, resource, param_hash,
                           parameters, status, risk_level, notes, created_at, expires_at
                    FROM approval_records
                    WHERE status = 'PENDING'
                    ORDER BY created_at DESC;
                    """
                )
                rows = cursor.fetchall()
                results = []
                for row in rows:
                    results.append({
                        "approval_id": row["approval_id"],
                        "task_id": row["task_id"],
                        "action": row["action"],
                        "resource": row["resource"],
                        "param_hash": row["param_hash"],
                        "parameters": json.loads(row["parameters"]) if row["parameters"] else {},
                        "status": row["status"],
                        "risk_level": row["risk_level"],
                        "notes": row["notes"],
                        "created_at": row["created_at"],
                        "expires_at": row["expires_at"],
                    })
                return results
            finally:
                conn.close()
        except Exception as e:
            logger.warning(f"Failed to query pending approvals from database: {e}")
            return []

    def _create_pending_approval(
        self,
        approval_id: str,
        task_id: Optional[str],
        skill: SkillDefinition,
        action_hash: str,
        parameters: Dict[str, Any],
    ) -> None:
        """Persists a pending approval record awaiting human authorization."""
        now_iso = utc_now_iso()
        expires_at = time.time() + 600.0  # 10 minute window for pending approval
        placeholder_token = f"pending-{uuid.uuid4().hex}"

        try:
            with self.db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO approval_records (
                        approval_id, token, task_id, action, resource,
                        param_hash, parameters, status, risk_level, notes,
                        created_at, expires_at, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        approval_id,
                        placeholder_token,
                        task_id,
                        skill.id,
                        skill.id,
                        action_hash,
                        json.dumps(parameters, sort_keys=True),
                        "PENDING",
                        skill.risk_level.value.upper(),
                        f"Action '{skill.id}' awaiting human confirmation",
                        now_iso,
                        expires_at,
                        json.dumps({"version": skill.version}),
                    ),
                )
        except Exception as e:
            logger.warning(f"Failed to record pending approval in database: {e}")

    def _validate_and_consume_approval(
        self,
        token: str,
        skill: SkillDefinition,
        expected_hash: str,
    ) -> Tuple[bool, str]:
        """
        Atomically verifies and consumes a single-use approval token.
        Guarantees concurrency safety through SQLite transaction locks.
        """
        now_ts = time.time()
        now_iso = utc_now_iso()

        # Database transaction check
        if self.db:
            try:
                with self.db.transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT approval_id, token, action, param_hash, status, expires_at
                        FROM approval_records
                        WHERE token = ?;
                        """,
                        (token,),
                    )
                    row = cursor.fetchone()
                    if not row:
                        return False, "Token not found or unrecognized."

                    status = row["status"]
                    if status == "CONSUMED":
                        return False, "Approval token has already been consumed (single-use replay violation)."
                    if status == "EXPIRED" or now_ts > row["expires_at"]:
                        conn.execute("UPDATE approval_records SET status = 'EXPIRED' WHERE token = ?;", (token,))
                        return False, "Approval token has expired."
                    if status != "APPROVED":
                        return False, f"Approval token is not in APPROVED state (current state: {status})."

                    # Action check
                    if row["action"] != skill.id:
                        return False, f"Token action mismatch (issued for '{row['action']}', presented for '{skill.id}')."

                    # Canonical action hash check
                    stored_hash = row["param_hash"]
                    if stored_hash != "*" and stored_hash != expected_hash:
                        return False, "Parameter tampering detected (action hash mismatch with authorized signature)."

                    # Atomic single-use consumption
                    cursor.execute(
                        """
                        UPDATE approval_records
                        SET status = 'CONSUMED', consumed_at = ?
                        WHERE token = ? AND status = 'APPROVED';
                        """,
                        (now_iso, token),
                    )
                    if cursor.rowcount == 1:
                        self._in_memory_approvals.pop(token, None)
                        return True, "Token consumed successfully."
                    else:
                        return False, "Concurrent token consumption race detected."
            except Exception as e:
                logger.error(f"Approval validation transaction error: {e}")
                return False, f"Database verification error: {str(e)}"

        # In-memory fallback
        if token not in self._in_memory_approvals:
            return False, "Token not found in memory."

        record = self._in_memory_approvals[token]
        if record["status"] != "APPROVED":
            return False, f"Token status is {record['status']}."
        if now_ts > record["expires_at"]:
            record["status"] = "EXPIRED"
            return False, "Token has expired."
        if record["action"] != skill.id:
            return False, f"Action mismatch (issued for '{record['action']}')."
        if record["param_hash"] != "*" and record["param_hash"] != expected_hash:
            return False, "Action hash mismatch with authorized signature."

        del self._in_memory_approvals[token]
        return True, "Token consumed successfully."
