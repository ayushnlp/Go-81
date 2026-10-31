"""
Bounded Replanning Engine for Project Go 81.
Manages DAG revisions, computes plan diffs, enforces cycle detection via plan fingerprints,
and guarantees the preservation of completed steps and non-idempotent side effects.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from app.skills.registry import SkillRegistry
from backend.agent_loop.models import (
    GoalState,
    IdempotencyClass,
    PlanDiff,
    StepObservation,
)
from backend.dag_validator import validate_dag_structure
from backend.plan_validator import validate_plan_against_security
from backend.planner import DAGStep, TaskDAG, TaskPlanner, utc_now_iso

logger = logging.getLogger(__name__)


class ReplanError(Exception):
    """Base error for replanning failures."""
    pass


class ReplanBudgetExhaustedError(ReplanError):
    """Raised when the maximum allowed replan revisions have been reached."""
    pass


class CyclicPlanError(ReplanError):
    """Raised when an identical or cyclic plan fingerprint is generated."""
    pass


class InvalidReplannedDAGError(ReplanError):
    """Raised when a revised DAG fails structural or security validation."""
    pass


class BoundedReplanner:
    """
    Coordinates bounded plan revisions:
    - Enforces max replans (default 2).
    - Detects cyclic plans using canonical fingerprints.
    - Preserves completed steps to prevent re-execution of irreversible side effects.
    - Revalidates revised DAGs against SkillRegistry and PermissionGateway.
    - Retains original user goal without drift.
    """

    def __init__(self, skill_registry: Optional[SkillRegistry] = None):
        self.skill_registry = skill_registry

    @staticmethod
    def compute_plan_fingerprint(steps: List[DAGStep]) -> str:
        """
        Computes a deterministic canonical SHA256 fingerprint for a sequence of steps.
        Considers skill name, sorted parameters, and dependencies.
        """
        canonical_items = []
        for s in steps:
            # Exclude transient fields like step_id, status, error, output from fingerprint
            clean_params = json.dumps(s.parameters or {}, sort_keys=True)
            canonical_items.append((
                s.skill_name,
                clean_params,
                sorted(s.dependencies or []),
                s.risk_level.value if hasattr(s.risk_level, "value") else str(s.risk_level),
            ))
        canonical_bytes = json.dumps(canonical_items, sort_keys=True).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()

    @staticmethod
    def compute_plan_diff(
        old_steps: List[DAGStep],
        new_steps: List[DAGStep],
        previous_revision: int,
        new_revision: int,
        preserved_ids: List[str],
        reason: str,
    ) -> PlanDiff:
        """Computes a structured diff between old and revised plan steps."""
        old_ids = {s.step_id for s in old_steps}
        new_ids = {s.step_id for s in new_steps}

        added = [sid for sid in new_ids if sid not in old_ids]
        removed = [sid for sid in old_ids if sid not in new_ids and sid not in preserved_ids]

        old_map = {s.step_id: s for s in old_steps}
        modified = []
        for s in new_steps:
            if s.step_id in old_map and s.step_id not in preserved_ids:
                old_s = old_map[s.step_id]
                if (
                    old_s.skill_name != s.skill_name
                    or old_s.parameters != s.parameters
                    or old_s.dependencies != s.dependencies
                ):
                    modified.append(s.step_id)

        return PlanDiff(
            previous_revision=previous_revision,
            new_revision=new_revision,
            added_step_ids=added,
            removed_step_ids=removed,
            modified_step_ids=modified,
            preserved_step_ids=preserved_ids,
            reason=reason,
            created_at=utc_now_iso(),
        )

    def replan(
        self,
        goal_state: GoalState,
        planner: TaskPlanner,
        failed_step_id: str,
        failure_reason: str,
    ) -> Tuple[TaskDAG, PlanDiff]:
        """
        Generates a validated revised DAG:
        1. Checks replan budget.
        2. Preserves completed steps (ensuring completed side effects are NOT re-executed).
        3. Generates alternative steps for the remainder of the plan.
        4. Detects cyclic plan generation via fingerprint checks.
        5. Validates structural and security properties.
        6. Updates goal state tracking.
        """
        # 1. Budget enforcement
        if not goal_state.budget.can_replan():
            raise ReplanBudgetExhaustedError(
                f"Replan budget exhausted: maximum {goal_state.budget.max_replans} replans allowed. "
                f"Task execution terminated."
            )

        old_dag = goal_state.plan
        if not old_dag:
            raise ReplanError("Cannot replan without an existing TaskDAG.")

        # 2. Identify preserved completed steps
        completed_obs: Dict[str, StepObservation] = goal_state.completed_steps
        preserved_steps: List[DAGStep] = []
        preserved_step_ids: Set[str] = set()

        for s in old_dag.steps:
            if s.step_id in completed_obs and completed_obs[s.step_id].outcome_satisfied:
                # Clone preserved step with its verified completion status
                preserved_copy = s.model_copy(deep=True)
                preserved_copy.status = "COMPLETED"
                preserved_steps.append(preserved_copy)
                preserved_step_ids.add(s.step_id)

        # 3. Formulate replan prompt for TaskPlanner
        # Preserve original user goal strictly
        original_goal = goal_state.goal

        replan_context = {
            "failed_step_id": failed_step_id,
            "failure_reason": failure_reason,
            "completed_steps": [
                {
                    "step_id": s.step_id,
                    "title": s.title,
                    "skill": s.skill_name,
                    "output_summary": completed_obs[s.step_id].output_summary,
                }
                for s in preserved_steps
            ],
            "original_goal": original_goal,
        }

        # Build modified goal instruction for planner that incorporates the failed context
        # while keeping the original user goal immutable
        completed_summary = ", ".join(f"'{s.step_id}' ({s.skill_name})" for s in preserved_steps) or "None"
        revised_instruction = (
            f"Original user goal: {original_goal}\n"
            f"Note: The following step(s) have ALREADY COMPLETED successfully and MUST NOT be repeated: {completed_summary}.\n"
            f"Step '{failed_step_id}' failed with error: {failure_reason}.\n"
            f"Design an alternative plan to complete the original goal without repeating completed actions."
        )

        # Synthesize replacement steps
        replacement_dag = planner.generate_dag(user_goal=revised_instruction)

        # Merge preserved completed steps with new replacement steps
        combined_steps: List[DAGStep] = []
        # Add preserved steps first
        for ps in preserved_steps:
            combined_steps.append(ps)

        # Add replacement steps, adjusting dependencies if needed
        for rs in replacement_dag.steps:
            # If replacement planner duplicated a preserved step ID or skill, adjust or include
            if rs.step_id in preserved_step_ids:
                continue
            # Ensure replacement step depends on the last preserved step if it has no dependencies
            if not rs.dependencies and preserved_steps:
                rs.dependencies = [preserved_steps[-1].step_id]
            rs.status = "PENDING"
            combined_steps.append(rs)

        # 4. Fingerprint cycle detection
        new_fingerprint = self.compute_plan_fingerprint(combined_steps)
        repeated_count = goal_state.plan_fingerprints.count(new_fingerprint)
        if repeated_count >= goal_state.budget.max_repeated_fingerprints:
            raise CyclicPlanError(
                f"Cyclic plan detected: revised plan matches earlier fingerprint '{new_fingerprint[:8]}' "
                f"which has already occurred {repeated_count} time(s). Terminating to prevent infinite loop."
            )

        # 5. Validation of revised DAG
        try:
            validate_dag_structure(combined_steps)
        except Exception as e:
            raise InvalidReplannedDAGError(f"Revised DAG failed structural validation: {e}")

        new_dag = TaskDAG(
            task_id=old_dag.task_id,
            goal=original_goal,  # Retain original goal strictly
            plan_summary=f"Revised plan (revision {goal_state.plan_revision + 1}): {replacement_dag.plan_summary}",
            model=old_dag.model,
            system_prompt=old_dag.system_prompt,
            injected_context=old_dag.injected_context,
            steps=combined_steps,
            execution_order=[s.step_id for s in combined_steps],
            required_skills=list({s.skill_name for s in combined_steps}),
            required_capabilities=list({
                cap for s in combined_steps
                for cap in (s.parameters.get("capabilities", []) if isinstance(s.parameters, dict) else [])
            }),
            status="RUNNING",
            created_at=old_dag.created_at,
            updated_at=utc_now_iso(),
        )

        if self.skill_registry:
            try:
                validate_plan_against_security(new_dag, self.skill_registry)
            except Exception as e:
                raise InvalidReplannedDAGError(f"Revised DAG failed security validation: {e}")

        # 6. Compute diff and update goal state
        old_revision = goal_state.plan_revision
        new_revision = old_revision + 1

        plan_diff = self.compute_plan_diff(
            old_steps=old_dag.steps,
            new_steps=combined_steps,
            previous_revision=old_revision,
            new_revision=new_revision,
            preserved_ids=list(preserved_step_ids),
            reason=failure_reason,
        )

        # Record replan in budget and history
        goal_state.budget.record_replan()
        goal_state.plan_revision = new_revision
        goal_state.plan = new_dag
        goal_state.plan_fingerprints.append(new_fingerprint)
        goal_state.replan_history.append(plan_diff)
        goal_state.updated_at = utc_now_iso()

        logger.info(
            f"Replanning completed for task {goal_state.task_id}: revision {new_revision}, "
            f"preserved {len(preserved_step_ids)} step(s), added {len(plan_diff.added_step_ids)} step(s)."
        )

        return new_dag, plan_diff

