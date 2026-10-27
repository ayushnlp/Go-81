"""
Permissions and Security Gateway Subsystem.
Implements a typed authorization interface compatible with Member 1 (Agent Architect).
Strict default-deny policy: prevents the LLM from granting itself execution permissions.
"""

import logging
import time
import uuid
from typing import Dict, Optional, Tuple, Union
from app.memory.database import DatabaseManager
from app.memory.models import (
    PermissionCheckRequest,
    PermissionDecision,
    RiskLevel,
    utc_now_iso,
)
from app.memory.repository import MemoryRepository

logger = logging.getLogger(__name__)


class PermissionGateway:
    """
    Authorization gateway for agent actions.
    Separates model tool suggestions from actual execution permissions.
    """

    def __init__(self, db: DatabaseManager):
        self.db = db
        self.repo = MemoryRepository(db)
        # In-memory registry of explicit human approvals:
        # key = approval_token, value = (action, resource, expiry_timestamp)
        self._approved_tokens: Dict[str, Tuple[str, str, float]] = {}

    def check_permission(
        self,
        user_id: str,
        action: str,
        resource: str,
        risk_level: Union[RiskLevel, str],
        approval_token: Optional[str] = None,
    ) -> PermissionDecision:
        """
        Evaluates whether a requested action on a resource is authorized.
        Default-deny for any high-risk operations or unknown policies unless
        an explicit, unexpired human approval token is provided.
        """
        # Normalize risk level
        if isinstance(risk_level, str):
            try:
                risk = RiskLevel(risk_level.upper())
            except ValueError:
                risk = RiskLevel.HIGH
        else:
            risk = risk_level

        # Check DB permission policy
        policy_row = self.repo.get_permission_policy(action)
        requires_approval = True
        if policy_row:
            requires_approval = bool(policy_row["requires_approval"])
            policy_risk = policy_row["default_risk"]
            # Escalate risk if configured policy is higher
            if policy_risk == "HIGH" or risk == RiskLevel.HIGH:
                risk = RiskLevel.HIGH

        # Safe default-deny logic
        if risk == RiskLevel.LOW and not requires_approval:
            return PermissionDecision(
                allowed=True,
                reason=f"Action '{action}' on '{resource}' authorized under LOW risk policy.",
                approval_required=False,
                approval_id=None,
            )

        # High or Medium risk requiring approval: check approval token
        if approval_token:
            if self._validate_and_consume_token(approval_token, action, resource):
                return PermissionDecision(
                    allowed=True,
                    reason=f"Action '{action}' on '{resource}' authorized by valid human approval token.",
                    approval_required=False,
                    approval_id=approval_token,
                )
            else:
                return PermissionDecision(
                    allowed=False,
                    reason="Provided approval token is invalid, expired, or does not match requested action/resource.",
                    approval_required=True,
                    approval_id=None,
                )

        # No token provided for action requiring approval: DENY & issue approval ID
        pending_id = f"apr-{uuid.uuid4().hex[:12]}"
        return PermissionDecision(
            allowed=False,
            reason=f"Action '{action}' ({risk.value} risk) requires explicit human confirmation. Approval ID issued.",
            approval_required=True,
            approval_id=pending_id,
        )

    def grant_approval(self, action: str, resource: str, ttl_seconds: int = 300, task_id: Optional[str] = None) -> str:
        """
        Human-in-the-loop mechanism:
        Generates an ephemeral, single-use approval token.
        Persisted to SQLite approval_records across application restarts.
        """
        token = f"tok-{uuid.uuid4().hex}"
        approval_id = f"apr-{uuid.uuid4().hex[:12]}"
        expiry = time.time() + ttl_seconds
        now_iso = utc_now_iso()
        self._approved_tokens[token] = (action, resource, expiry)

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
                            action,
                            resource,
                            "*",
                            "{}",
                            "APPROVED",
                            "HIGH",
                            "Granted via PermissionGateway",
                            now_iso,
                            expiry,
                            "{}",
                        ),
                    )
            except Exception as e:
                logger.warning(f"PermissionGateway: failed to persist approval to SQLite: {e}")

        return token

    def _validate_and_consume_token(self, token: str, action: str, resource: str) -> bool:
        """
        Atomically validates and consumes single-use approval token.
        Checks SQLite approval_records first, with in-memory fallback.
        """
        if self.db:
            try:
                with self.db.transaction() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT approval_id, token, action, resource, status, expires_at
                        FROM approval_records
                        WHERE token = ?;
                        """,
                        (token,),
                    )
                    row = cursor.fetchone()
                    if row:
                        status = row["status"]
                        if status != "APPROVED":
                            return False
                        if time.time() > row["expires_at"]:
                            conn.execute("UPDATE approval_records SET status = 'EXPIRED' WHERE token = ?;", (token,))
                            return False
                        if row["action"] != action or (row["resource"] != "*" and row["resource"] != resource):
                            return False

                        now_iso = utc_now_iso()
                        cursor.execute(
                            """
                            UPDATE approval_records
                            SET status = 'CONSUMED', consumed_at = ?
                            WHERE token = ? AND status = 'APPROVED';
                            """,
                            (now_iso, token),
                        )
                        if cursor.rowcount > 0:
                            self._approved_tokens.pop(token, None)
                            return True
                        return False
            except Exception as e:
                logger.warning(f"PermissionGateway SQLite validation error: {e}")

        # In-memory validation
        if token not in self._approved_tokens:
            return False

        t_action, t_resource, expiry = self._approved_tokens[token]
        if time.time() > expiry:
            del self._approved_tokens[token]
            return False

        if t_action != action or (t_resource != "*" and t_resource != resource):
            return False

        del self._approved_tokens[token]
        return True


# Safe Default-Deny Adapter for Member 1 integration
class DefaultDenyAuthorizationAdapter:
    """
    Drop-in adapter ensuring that until Member 1 connects their full auth system,
    every high-risk request defaults to strict denial with requirement for confirmation.
    """

    def __init__(self, gateway: PermissionGateway):
        self.gateway = gateway

    def check(self, req: PermissionCheckRequest) -> PermissionDecision:
        return self.gateway.check_permission(
            user_id=req.user_id,
            action=req.action,
            resource=req.resource,
            risk_level=req.risk_level,
            approval_token=req.approval_token,
        )
