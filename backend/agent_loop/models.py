"""
Stage 6 Autonomous Agent Loop Models.
Typed state models, execution budgets, observations, plan diffs, and evaluation outcomes.
"""

from enum import Enum
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from backend.planner import DAGStep, TaskDAG, utc_now_iso


class LoopPhase(str, Enum):
    """Execution lifecycle phase of the Autonomous Agent Loop."""
    PLANNING = "PLANNING"
    VALIDATING = "VALIDATING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    EVALUATING = "EVALUATING"
    REPLANNING = "REPLANNING"
    PAUSED_APPROVAL = "PAUSED_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class IdempotencyClass(str, Enum):
    """
    Classification of skill actions for retry safety and side-effect reconciliation:
    - READ_ONLY: Safe to re-execute at any time without external state changes.
    - IDEMPOTENT: Re-execution produces identical external state (e.g. overwrite exact file).
    - NON_IDEMPOTENT: Re-execution duplicates side effects (e.g. append, send message, commit).
    - IRREVERSIBLE_HIGH_RISK: Cannot be undone safely (e.g. delete, format, privileged shell).
    """
    READ_ONLY = "READ_ONLY"
    IDEMPOTENT = "IDEMPOTENT"
    NON_IDEMPOTENT = "NON_IDEMPOTENT"
    IRREVERSIBLE_HIGH_RISK = "IRREVERSIBLE_HIGH_RISK"


class StepObservation(BaseModel):
    """
    Structured observation captured after every step execution.
    Contains verified output evidence, side-effect flags, and outcome evaluations.
    """
    task_id: str = Field(..., description="Target task identifier")
    step_id: str = Field(..., description="Target step identifier")
    skill_name: str = Field(..., description="Skill executed")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Step parameters")
    status: str = Field(..., description="Step terminal status (COMPLETED, FAILED, BLOCKED, etc.)")
    output_summary: Optional[str] = Field(default=None, description="Concise sanitized summary of output")
    raw_output: Optional[Any] = Field(default=None, description="Raw execution output")
    error_details: Optional[str] = Field(default=None, description="Execution error message or trace")
    evidence_refs: List[str] = Field(default_factory=list, description="IDs of persisted flight recorder evidence")
    started_at: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)
    duration_ms: Optional[float] = Field(default=None)
    produces_side_effect: bool = Field(default=False, description="Whether the step mutates external state")
    idempotency_class: IdempotencyClass = Field(default=IdempotencyClass.READ_ONLY)
    requires_approval: bool = Field(default=False)
    outcome_satisfied: bool = Field(default=False, description="Whether actual evidence satisfies expected outcome")
    reconciliation_required: bool = Field(
        default=False,
        description="True if execution outcome is uncertain (e.g. timeout on side-effect action)"
    )


class LoopBudget(BaseModel):
    """
    Execution budget policies enforcing deterministic termination limits.
    Model reasoning has zero authority to override these limits.
    """
    max_iterations: int = Field(default=20, description="Absolute ceiling on loop cycle iterations")
    max_replans: int = Field(default=2, description="Maximum number of DAG revisions per task")
    max_retries_per_step: int = Field(default=1, description="Maximum retries per individual step")
    max_repeated_fingerprints: int = Field(default=2, description="Maximum identical plan occurrences before cycle stop")
    timeout_seconds: float = Field(default=300.0, description="Overall execution deadline in seconds")

    # Dynamic tracking counters
    current_iteration: int = Field(default=0)
    current_replans: int = Field(default=0)
    step_retries: Dict[str, int] = Field(default_factory=dict)
    started_at_timestamp: Optional[float] = Field(default=None)

    def start_timer(self) -> None:
        """Initializes loop start timestamp."""
        if self.started_at_timestamp is None:
            self.started_at_timestamp = time.time()

    def is_timed_out(self, now: Optional[float] = None) -> bool:
        """Checks if execution has exceeded timeout deadline."""
        if self.started_at_timestamp is None:
            return False
        current_now = now if now is not None else time.time()
        return (current_now - self.started_at_timestamp) > self.timeout_seconds

    def remaining_seconds(self, now: Optional[float] = None) -> float:
        """Calculates remaining execution seconds before deadline."""
        if self.started_at_timestamp is None:
            return self.timeout_seconds
        current_now = now if now is not None else time.time()
        elapsed = current_now - self.started_at_timestamp
        return max(0.0, self.timeout_seconds - elapsed)

    def can_retry_step(self, step_id: str, idempotency_class: IdempotencyClass) -> bool:
        """
        Determines if a step is safe to retry:
        - Only READ_ONLY or IDEMPOTENT steps may be retried.
        - Must not have exceeded max_retries_per_step.
        """
        if idempotency_class not in (IdempotencyClass.READ_ONLY, IdempotencyClass.IDEMPOTENT):
            return False
        retries_done = self.step_retries.get(step_id, 0)
        return retries_done < self.max_retries_per_step

    def record_retry(self, step_id: str) -> None:
        """Records a retry attempt for a step."""
        self.step_retries[step_id] = self.step_retries.get(step_id, 0) + 1

    def can_replan(self) -> bool:
        """Checks if replan budget is available."""
        return self.current_replans < self.max_replans

    def record_replan(self) -> None:
        """Increments replan count."""
        self.current_replans += 1

    def increment_iteration(self) -> bool:
        """
        Increments loop iteration counter.
        Returns True if within budget, False if iteration limit exceeded.
        """
        self.current_iteration += 1
        return self.current_iteration <= self.max_iterations


class PlanDiff(BaseModel):
    """Structured plan revision diff comparing old and new DAGs."""
    previous_revision: int
    new_revision: int
    added_step_ids: List[str] = Field(default_factory=list)
    removed_step_ids: List[str] = Field(default_factory=list)
    modified_step_ids: List[str] = Field(default_factory=list)
    preserved_step_ids: List[str] = Field(default_factory=list)
    reason: str
    created_at: str = Field(default_factory=utc_now_iso)


class GoalEvaluation(BaseModel):
    """
    Truthful assessment of whether the goal has been achieved or requires intervention.
    Combines deterministic rules with local model reasoning.
    """
    is_completed: bool = Field(default=False)
    needs_replanning: bool = Field(default=False)
    replan_reason: Optional[str] = Field(default=None)
    can_retry_step: Optional[str] = Field(default=None)
    requires_approval: bool = Field(default=False)
    terminal_failure: bool = Field(default=False)
    failure_reason: Optional[str] = Field(default=None)
    summary: str = Field(default="")
    evidence: List[Dict[str, Any]] = Field(default_factory=list)


class GoalState(BaseModel):
    """
    Complete state of the autonomous execution loop.
    Persisted through WAL checkpoints and queryable via APIs.
    """
    goal: str = Field(..., description="Original immutable user goal")
    task_id: str = Field(..., description="Canonical task identifier")
    phase: LoopPhase = Field(default=LoopPhase.PLANNING)
    status: str = Field(default="PENDING")
    plan_revision: int = Field(default=1)
    plan: Optional[TaskDAG] = Field(default=None)
    completed_steps: Dict[str, StepObservation] = Field(default_factory=dict)
    pending_steps: List[str] = Field(default_factory=list)
    failed_steps: Dict[str, StepObservation] = Field(default_factory=dict)
    awaiting_approval: Optional[str] = Field(default=None, description="Approval ID if paused")
    observations: List[StepObservation] = Field(default_factory=list)
    budget: LoopBudget = Field(default_factory=LoopBudget)
    replan_history: List[PlanDiff] = Field(default_factory=list)
    plan_fingerprints: List[str] = Field(default_factory=list)
    terminal_reason: Optional[str] = Field(default=None)
    final_report: Optional[Any] = Field(default=None)
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)
