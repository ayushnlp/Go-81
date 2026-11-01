"""
Autonomous Execution Controller for Project Go 81.
Stage 6 Core Closed-Loop Engine:
GOAL -> PLAN -> VALIDATE -> EXECUTE -> OBSERVE -> EVALUATE -> REPLAN / CONTINUE / COMPLETE
"""

import asyncio
import hashlib
import os
import uuid
from app.memory.journal import ExecutionJournalService
from app.memory.models import DispatchState
from backend.agent_loop.recovery_engine import AutonomousRecoveryEngine, LeaseConflictError
from backend.agent_loop.subprocess_tracker import SubprocessTracker
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.memory.permissions import PermissionGateway
from app.memory.recovery import TaskRecoveryManager
from app.skills.registry import SkillRegistry
from backend.agent_loop.evaluator import GoalEvaluator
from backend.agent_loop.models import (
    GoalEvaluation,
    GoalState,
    IdempotencyClass,
    LoopBudget,
    LoopPhase,
    PlanDiff,
    StepObservation,
)
from backend.agent_loop.replanner import (
    BoundedReplanner,
    CyclicPlanError,
    InvalidReplannedDAGError,
    ReplanBudgetExhaustedError,
)
from app.memory.flight_recorder import FlightRecorderService
from backend.dag_validator import validate_dag_structure
from backend.orchestrator import TaskOrchestrator
from backend.plan_validator import validate_plan_against_security
from backend.planner import DAGStep, TaskDAG, TaskPlanner, utc_now_iso

logger = logging.getLogger(__name__)


class AutonomousExecutionController:
    """
    Closed-loop autonomous execution controller that drives:
    GOAL -> PLAN -> VALIDATE -> EXECUTE -> OBSERVE -> EVALUATE -> REPLAN / CONTINUE / COMPLETE
    
    Reuses existing Go 81 architecture:
    - TaskPlanner for structured DAG generation and revision.
    - TaskOrchestrator for step concurrency, permission checks, SSE events, and approval gates.
    - SkillRegistry & PermissionGateway for security enforcement.
    - RecoveryManager & FlightRecorder for state persistence.
    """

    def __init__(
        self,
        planner: TaskPlanner,
        orchestrator: TaskOrchestrator,
        skill_registry: Optional[SkillRegistry] = None,
        permission_gateway: Optional[PermissionGateway] = None,
        recovery_manager: Optional[TaskRecoveryManager] = None,
        flight_recorder: Optional[FlightRecorderService] = None,
        default_budget: Optional[LoopBudget] = None,
        journal_service: Optional[ExecutionJournalService] = None,
        subprocess_tracker: Optional[SubprocessTracker] = None,
        recovery_engine: Optional[AutonomousRecoveryEngine] = None,
        worker_id: Optional[str] = None,
    ):
        self.planner = planner
        self.orchestrator = orchestrator
        self.skill_registry = skill_registry or (
            orchestrator.permission_gateway.registry if hasattr(orchestrator, "permission_gateway") and orchestrator.permission_gateway else None
        )
        self.permission_gateway = permission_gateway or orchestrator.permission_gateway
        self.recovery_manager = recovery_manager or orchestrator.recovery_manager
        self.flight_recorder = flight_recorder or orchestrator.flight_recorder
        self.default_budget = default_budget or LoopBudget()

        # Stage 7 Recovery, Journal & Subprocess Services
        db = getattr(self.recovery_manager, "db", None) or getattr(orchestrator, "db", None)
        self.journal = journal_service or (ExecutionJournalService(db) if db else None)
        self.subprocess_tracker = subprocess_tracker or SubprocessTracker()
        self.recovery_engine = recovery_engine or (
            AutonomousRecoveryEngine(db, self.recovery_manager, self.journal, self.subprocess_tracker)
            if (db and self.recovery_manager) else None
        )
        self.worker_id = worker_id or f"ctrl-{os.getpid()}-{uuid.uuid4().hex[:6]}"

        # Evaluator and Replanner engines
        self.evaluator = GoalEvaluator(
            skill_registry=self.skill_registry,
            ollama_endpoint=getattr(self.planner, "ollama_endpoint", "http://127.0.0.1:11434"),
            model=getattr(self.planner, "model", "llama3.2:3b"),
        )
        self.replanner = BoundedReplanner(skill_registry=self.skill_registry)

        # Active goal states: task_id -> GoalState
        self._states: Dict[str, GoalState] = {}
        self._lock = asyncio.Lock()

    def get_state(self, task_id: str) -> Optional[GoalState]:
        """Retrieves in-memory or persisted loop state."""
        if task_id in self._states:
            return self._states[task_id]

        # Check recovery checkpoint
        if self.recovery_manager:
            try:
                chk = self.recovery_manager.get_task_checkpoint(task_id)
                if chk and isinstance(chk.state_data, dict):
                    loop_data = chk.state_data.get("agent_loop")
                    if loop_data:
                        state = GoalState(**loop_data)
                        self._states[task_id] = state
                        return state
            except Exception as e:
                logger.debug(f"Failed to restore loop state for task {task_id}: {e}")

        return None

    def _persist_state(self, state: GoalState) -> None:
        """Saves current loop state into the existing recovery checkpoint infrastructure."""
        state.updated_at = utc_now_iso()
        self._states[state.task_id] = state

        if self.recovery_manager and state.plan:
            try:
                from app.memory.models import TaskCheckpoint, TaskStatus
                status_mapping = {
                    "PENDING": TaskStatus.PENDING,
                    "RUNNING": TaskStatus.RUNNING,
                    "PAUSED_APPROVAL": TaskStatus.PAUSED,
                    "WAITING_APPROVAL": TaskStatus.PAUSED,
                    "COMPLETED": TaskStatus.COMPLETED,
                    "FAILED": TaskStatus.FAILED,
                    "CANCELLED": TaskStatus.FAILED,
                }
                current_step_id = next(
                    (s.step_id for s in state.plan.steps if s.status in ("RUNNING", "PAUSED_APPROVAL", "WAITING_APPROVAL")),
                    state.plan.steps[0].step_id if state.plan.steps else "start",
                )
                chk = TaskCheckpoint(
                    task_id=state.task_id,
                    workflow_id=state.task_id,
                    status=status_mapping.get(state.status, TaskStatus.RUNNING),
                    current_step=current_step_id,
                    completed_step_ids=[s.step_id for s in state.plan.steps if s.status == "COMPLETED"],
                    pending_step_ids=[
                        s.step_id for s in state.plan.steps if s.status in ("PENDING", "READY", "PAUSED_APPROVAL", "WAITING_APPROVAL")
                    ],
                    state_data={
                        "task_id": state.task_id,
                        "goal": state.goal,
                        "task_status": state.status,
                        "plan_summary": state.plan.plan_summary,
                        "steps": [s.model_dump() for s in state.plan.steps],
                        "completed_at": state.plan.completed_at,
                        "final_report": state.final_report,
                        "agent_loop": state.model_dump(),
                    },
                    created_at=state.created_at,
                    updated_at=state.updated_at,
                    lease_holder=self.worker_id if state.status == "RUNNING" else None,
                    lease_expires_at=(time.time() + 120.0) if state.status == "RUNNING" else None,
                )
                self.recovery_manager.save_task_checkpoint(chk)
            except Exception as e:
                logger.warning(f"Failed to persist agent loop checkpoint for {state.task_id}: {e}")

    async def _emit_loop_event(self, task_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcasts loop state transition via existing orchestrator SSE event system."""
        await self.orchestrator.broadcast_event(
            task_id=task_id,
            event_type=event_type,
            data=data,
        )

    async def run_autonomous_loop(
        self,
        goal: str,
        task_id: Optional[str] = None,
        budget: Optional[LoopBudget] = None,
        initial_dag: Optional[TaskDAG] = None,
    ) -> GoalState:
        """
        Executes the closed-loop autonomous cycle:
        GOAL -> PLAN -> VALIDATE -> EXECUTE -> OBSERVE -> EVALUATE -> REPLAN / CONTINUE / COMPLETE
        """
        active_budget = (budget or self.default_budget).model_copy(deep=True)
        active_budget.start_timer()

        # 1. Initialize GoalState or reuse existing state
        target_tid = task_id or (initial_dag.task_id if initial_dag else f"task-{int(time.time()*1000)}")
        existing_state = self.get_state(target_tid)
        if existing_state:
            state = existing_state
            state.status = "RUNNING"
            state.budget = active_budget
        else:
            state = GoalState(
                goal=goal,
                task_id=target_tid,
                phase=LoopPhase.PLANNING,
                status="RUNNING",
                budget=active_budget,
            )
        self._states[state.task_id] = state

        # Acquire task lease to prevent concurrent recovery or resume
        if self.journal:
            leased = self.journal.acquire_task_lease(state.task_id, self.worker_id, ttl_seconds=120.0)
            if not leased:
                state.phase = LoopPhase.FAILED
                state.status = "FAILED"
                state.terminal_reason = f"Task lease conflict: Task '{state.task_id}' is leased to another active worker."
                if initial_dag:
                    initial_dag.status = "FAILED"
                self._persist_state(state)
                await self._emit_loop_event(state.task_id, "loop_terminated", {
                    "status": "FAILED",
                    "reason": state.terminal_reason,
                })
                return state

        try:
            # 2. Planning Phase
            if initial_dag is None:
                await self._emit_loop_event(state.task_id, "loop_phase_changed", {
                    "phase": LoopPhase.PLANNING.value,
                    "goal": goal,
                    "iteration": active_budget.current_iteration,
                })
                dag = self.planner.generate_dag(user_goal=goal)
                dag.task_id = state.task_id
            else:
                dag = initial_dag
    
            # Avoid instant fail-fast abort on individual steps so the loop can observe and replan
            dag.failure_policy = "autonomous_loop"
            state.plan = dag
            state.pending_steps = [s.step_id for s in dag.steps if s.status not in ("COMPLETED", "SKIPPED")]
            for s in dag.steps:
                if s.status == "COMPLETED" and s.step_id not in state.completed_steps:
                    obs = self.evaluator.create_observation(
                        task_id=state.task_id,
                        step=s,
                        success=True,
                        output=s.output,
                        duration_ms=s.execution_duration_ms,
                    )
                    state.completed_steps[s.step_id] = obs
    
            # 3. Validation Phase
            state.phase = LoopPhase.VALIDATING
            await self._emit_loop_event(state.task_id, "loop_phase_changed", {
                "phase": LoopPhase.VALIDATING.value,
                "step_count": len(dag.steps),
            })
    
            try:
                validate_dag_structure(dag.steps)
                if self.skill_registry:
                    validate_plan_against_security(dag, self.skill_registry)
            except Exception as e:
                state.phase = LoopPhase.FAILED
                state.status = "FAILED"
                state.terminal_reason = f"Plan validation security or structural failure: {e}"
                self._persist_state(state)
                await self._emit_loop_event(state.task_id, "loop_terminated", {
                    "status": "FAILED",
                    "reason": state.terminal_reason,
                })
                return state
    
            # Record initial plan fingerprint
            init_fp = BoundedReplanner.compute_plan_fingerprint(dag.steps)
            state.plan_fingerprints.append(init_fp)
    
            # Register task in orchestrator
            self.orchestrator.register_task(dag)
            self._persist_state(state)
    
            # 4. Main Closed-Loop Execution Cycle
            while True:
                # Check timeout
                if active_budget.is_timed_out():
                    state.phase = LoopPhase.FAILED
                    state.status = "FAILED"
                    state.terminal_reason = (
                        f"Execution exceeded timeout budget of {active_budget.timeout_seconds}s. Terminated safely."
                    )
                    dag.status = "FAILED"
                    self._persist_state(state)
                    await self._emit_loop_event(state.task_id, "loop_terminated", {
                        "status": "FAILED",
                        "reason": state.terminal_reason,
                    })
                    return state
    
                # Check iteration limit
                if not active_budget.increment_iteration():
                    state.phase = LoopPhase.FAILED
                    state.status = "FAILED"
                    state.terminal_reason = (
                        f"Execution exceeded maximum loop iterations ({active_budget.max_iterations}). Terminated safely."
                    )
                    dag.status = "FAILED"
                    self._persist_state(state)
                    await self._emit_loop_event(state.task_id, "loop_terminated", {
                        "status": "FAILED",
                        "reason": state.terminal_reason,
                    })
                    return state
    
                await self._emit_loop_event(state.task_id, "loop_budget_updated", {
                    "iteration": active_budget.current_iteration,
                    "max_iterations": active_budget.max_iterations,
                    "replans": active_budget.current_replans,
                    "max_replans": active_budget.max_replans,
                    "remaining_seconds": round(active_budget.remaining_seconds(), 2),
                })
    
                # Check overall goal completion deterministically
                all_completed = all(s.status == "COMPLETED" for s in dag.steps) and len(dag.steps) > 0
                if all_completed:
                    state.phase = LoopPhase.EVALUATING
                    eval_result = self.evaluator.evaluate_goal_completion(state, use_local_model=False)
                    if eval_result.is_completed:
                        state.phase = LoopPhase.COMPLETED
                        state.status = "COMPLETED"
                        dag.status = "COMPLETED"
                        dag.completed_at = utc_now_iso()
                        state.final_report = self.orchestrator._generate_final_report(dag)
                        dag.final_report = state.final_report
                        self._persist_state(state)
                        await self._emit_loop_event(state.task_id, "task_completed", {
                            "task_id": state.task_id,
                            "status": "COMPLETED",
                            "summary": eval_result.summary,
                            "report": state.final_report,
                        })
                        return state
    
                # Identify ready steps
                completed_step_ids = {s.step_id for s in dag.steps if s.status == "COMPLETED"}
                failed_or_blocked_ids = {s.step_id for s in dag.steps if s.status in ("FAILED", "REJECTED", "BLOCKED")}
    
                ready_steps: List[DAGStep] = []
                for step in dag.steps:
                    if step.status in ("PENDING", "READY"):
                        # Check if any prerequisite failed
                        if any(dep in failed_or_blocked_ids for dep in step.dependencies):
                            step.status = "BLOCKED"
                            step.blocked_reason = "Prerequisite step failed."
                        elif all(dep in completed_step_ids for dep in step.dependencies):
                            step.status = "READY"
                            ready_steps.append(step)
    
                # If no steps ready
                if not ready_steps:
                    # Check if paused for approval
                    paused_step = next((s for s in dag.steps if s.status in ("PAUSED_APPROVAL", "WAITING_APPROVAL")), None)
                    if paused_step:
                        state.phase = LoopPhase.PAUSED_APPROVAL
                        state.awaiting_approval = paused_step.approval_id
                        dag.status = "PAUSED_APPROVAL"
                        self._persist_state(state)
                        await self._emit_loop_event(state.task_id, "loop_phase_changed", {
                            "phase": LoopPhase.PAUSED_APPROVAL.value,
                            "approval_id": paused_step.approval_id,
                            "step_id": paused_step.step_id,
                        })
                        return state
    
                    # Check if unrecoverable deadlock or all steps processed
                    uncompleted = [s for s in dag.steps if s.status not in ("COMPLETED", "SKIPPED")]
                    if uncompleted:
                        state.phase = LoopPhase.FAILED
                        state.status = "FAILED"
                        dag.status = "FAILED"
                        state.terminal_reason = f"No eligible steps ready to execute. {len(uncompleted)} step(s) blocked or incomplete."
                        self._persist_state(state)
                        await self._emit_loop_event(state.task_id, "loop_terminated", {
                            "status": "FAILED",
                            "reason": state.terminal_reason,
                        })
                        return state
                    else:
                        break
    
                # Execute eligible ready steps
                step_to_run = ready_steps[0]
    
                # 5. Check Approval Gate
                if step_to_run.requires_approval and not step_to_run.approval_token:
                    await self.orchestrator._pause_step_for_approval(dag, step_to_run)
                    state.phase = LoopPhase.PAUSED_APPROVAL
                    state.awaiting_approval = step_to_run.approval_id
                    dag.status = "PAUSED_APPROVAL"
                    self._persist_state(state)
                    await self._emit_loop_event(state.task_id, "loop_phase_changed", {
                        "phase": LoopPhase.PAUSED_APPROVAL.value,
                        "approval_id": step_to_run.approval_id,
                        "step_id": step_to_run.step_id,
                    })
                    return state
    
                # Anti-replay guard: Verify if this step has already SUCCEEDED in the durable journal
                if self.journal and self.journal.is_step_already_executed(state.task_id, step_to_run.step_id):
                    logger.info(
                        f"Anti-replay guard: Step '{step_to_run.step_id}' already succeeded in execution journal. "
                        "Skipping duplicate execution and restoring outcome."
                    )
                    step_to_run.status = "COMPLETED"
                    obs = self.evaluator.create_observation(
                        task_id=state.task_id,
                        step=step_to_run,
                        success=True,
                        output=step_to_run.output or "Restored from durable execution journal",
                        duration_ms=0.0,
                    )
                    state.completed_steps[step_to_run.step_id] = obs
                    if step_to_run.step_id in state.pending_steps:
                        state.pending_steps.remove(step_to_run.step_id)
                    continue
    
                # Renew task lease
                if self.journal:
                    self.journal.renew_task_lease(state.task_id, self.worker_id, ttl_seconds=120.0)
    
                # Classify idempotency
                idemp = getattr(step_to_run, "idempotency_class", None) or self.evaluator.classify_step_idempotency(step_to_run.skill_name, step_to_run.parameters or {})
                idemp_val = idemp.value if hasattr(idemp, "value") else str(idemp)
    
                # Two-Phase Intent Registration: PREPARED -> DISPATCHING
                journal_entry = None
                if self.journal:
                    journal_entry = self.journal.prepare_dispatch(
                        task_id=state.task_id,
                        step_id=step_to_run.step_id,
                        action=step_to_run.skill_name,
                        idempotency_class=idemp_val,
                        params=step_to_run.parameters or {},
                        approval_ref=getattr(step_to_run, "approval_token", None),
                    )
                    self.journal.record_dispatching(journal_entry.attempt_id)
    
                # 6. Execute Step
                state.phase = LoopPhase.EXECUTING
                await self._emit_loop_event(state.task_id, "loop_phase_changed", {
                    "phase": LoopPhase.EXECUTING.value,
                    "step_id": step_to_run.step_id,
                    "skill": step_to_run.skill_name,
                })
    
                exec_success = True
                exec_error: Optional[str] = None
                start_t = time.perf_counter()
    
                try:
                    await self.orchestrator._execute_step(dag, step_to_run)
                    if journal_entry and self.journal and step_to_run.status == "COMPLETED":
                        out_str = str(step_to_run.output) if step_to_run.output is not None else ""
                        digest = hashlib.sha256(out_str.encode("utf-8")).hexdigest()
                        self.journal.record_success(journal_entry.attempt_id, result_digest=digest, exit_code=0)
                    elif journal_entry and self.journal and step_to_run.status != "COMPLETED":
                        self.journal.record_failure(
                            journal_entry.attempt_id,
                            error_message=str(step_to_run.error or "Step did not complete"),
                            exit_code=1,
                        )
                except Exception as e:
                    exec_success = False
                    exec_error = str(e)
                    if journal_entry and self.journal:
                        self.journal.record_failure(journal_entry.attempt_id, error_message=exec_error, exit_code=1)
    
                duration_ms = round((time.perf_counter() - start_t) * 1000, 2)
    
                # 7. Observe Phase
                state.phase = LoopPhase.OBSERVING
                observation = self.evaluator.create_observation(
                    task_id=state.task_id,
                    step=step_to_run,
                    success=exec_success and step_to_run.status == "COMPLETED",
                    output=step_to_run.output,
                    error=exec_error or step_to_run.error,
                    duration_ms=duration_ms,
                    was_timeout=("timeout" in (exec_error or "").lower()),
                )
                state.observations.append(observation)
                await self._emit_loop_event(state.task_id, "step_observed", observation.model_dump())
    
                if observation.outcome_satisfied:
                    state.completed_steps[step_to_run.step_id] = observation
                    if step_to_run.step_id in state.pending_steps:
                        state.pending_steps.remove(step_to_run.step_id)
                else:
                    state.failed_steps[step_to_run.step_id] = observation
    
                # 8. Evaluate Phase
                state.phase = LoopPhase.EVALUATING
                evaluation = self.evaluator.evaluate_step_result(observation, active_budget)
                await self._emit_loop_event(state.task_id, "goal_evaluated", evaluation.model_dump())
    
                # Handle evaluation decisions
                if evaluation.terminal_failure:
                    state.phase = LoopPhase.FAILED
                    state.status = "FAILED"
                    dag.status = "FAILED"
                    state.terminal_reason = evaluation.failure_reason
                    self._persist_state(state)
                    await self._emit_loop_event(state.task_id, "loop_terminated", {
                        "status": "FAILED",
                        "reason": state.terminal_reason,
                    })
                    return state
    
                elif evaluation.can_retry_step:
                    # Safe retry scheduled
                    active_budget.record_retry(step_to_run.step_id)
                    step_to_run.status = "PENDING"
                    step_to_run.error = None
                    step_to_run.output = None
                    logger.info(f"Retrying step '{step_to_run.step_id}' (attempt {active_budget.step_retries[step_to_run.step_id]}).")
                    continue
    
                elif evaluation.needs_replanning:
                    # Bounded Replanning Triggered
                    state.phase = LoopPhase.REPLANNING
                    await self._emit_loop_event(state.task_id, "loop_phase_changed", {
                        "phase": LoopPhase.REPLANNING.value,
                        "replan_count": active_budget.current_replans + 1,
                        "reason": evaluation.replan_reason,
                    })
    
                    try:
                        revised_dag, plan_diff = self.replanner.replan(
                            goal_state=state,
                            planner=self.planner,
                            failed_step_id=step_to_run.step_id,
                            failure_reason=evaluation.replan_reason or "Step execution failed.",
                        )
                        revised_dag.failure_policy = "autonomous_loop"
                        state.plan = revised_dag
                        dag = revised_dag
                        self.orchestrator.tasks[state.task_id] = revised_dag
                        self._persist_state(state)
    
                        await self._emit_loop_event(state.task_id, "plan_replanned", plan_diff.model_dump())
                        logger.info(f"Task {state.task_id} replanned successfully to revision {state.plan_revision}.")
                        continue
                    except (ReplanBudgetExhaustedError, CyclicPlanError, InvalidReplannedDAGError, Exception) as e:
                        state.phase = LoopPhase.FAILED
                        state.status = "FAILED"
                        dag.status = "FAILED"
                        state.terminal_reason = f"Replanning failed: {str(e)}"
                        self._persist_state(state)
                        await self._emit_loop_event(state.task_id, "loop_terminated", {
                            "status": "FAILED",
                            "reason": state.terminal_reason,
                        })
                        return state
    
            # Final loop termination check
            state.phase = LoopPhase.COMPLETED
            state.status = "COMPLETED"
            dag.status = "COMPLETED"
            state.final_report = self.orchestrator._generate_final_report(dag)
            self._persist_state(state)
            return state
        finally:
            if self.journal:
                self.journal.release_task_lease(state.task_id, self.worker_id)

    async def resume_approval(
        self,
        approval_id: str,
        decision: str = "approved",
        notes: Optional[str] = None,
    ) -> GoalState:
        """
        Resumes the autonomous agent loop when human authorization is submitted.
        Verifies exact step parameters and approval tokens.
        """
        appr_info = self.orchestrator._pending_approvals.get(approval_id)
        if not appr_info:
            raise KeyError(f"Approval ID '{approval_id}' not found or already processed.")

        task_id = appr_info["task_id"]
        step_id = appr_info["step_id"]

        state = self.get_state(task_id)
        if not state:
            raise KeyError(f"Goal state for task '{task_id}' not found.")

        # Delegate resolution to orchestrator
        res = await self.orchestrator.resume_approval(
            approval_id=approval_id,
            decision=decision,
            notes=notes,
        )

        state.awaiting_approval = None

        if decision.lower() != "approved":
            # Rejection: mark task failed or trigger replan if operator requested
            state.phase = LoopPhase.FAILED
            state.status = "FAILED"
            state.terminal_reason = f"Human operator rejected approval: {notes or 'No reason provided.'}"
            self._persist_state(state)
            return state

        # Step was executed by orchestrator; capture observation
        step = next((s for s in state.plan.steps if s.step_id == step_id), None)
        if step:
            obs = self.evaluator.create_observation(
                task_id=task_id,
                step=step,
                success=(step.status == "COMPLETED"),
                output=step.output,
                error=step.error,
                duration_ms=step.execution_duration_ms,
            )
            state.observations.append(obs)
            if obs.outcome_satisfied:
                state.completed_steps[step_id] = obs
                if step_id in state.pending_steps:
                    state.pending_steps.remove(step_id)

        # Continue autonomous loop from current state
        return await self.run_autonomous_loop(
            goal=state.goal,
            task_id=task_id,
            budget=state.budget,
            initial_dag=state.plan,
        )

    async def cancel_execution(self, task_id: str, reason: str = "Cancelled by user") -> GoalState:
        """
        Safely cancels an autonomous task execution, preventing subsequent steps from starting.
        """
        state = self.get_state(task_id)
        if not state:
            raise KeyError(f"Goal state for task '{task_id}' not found.")

        state.phase = LoopPhase.CANCELLED
        state.status = "CANCELLED"
        state.terminal_reason = reason

        await self.orchestrator.cancel_task(task_id, reason=reason)
        if self.journal:
            active_entries = self.journal.get_incomplete_entries(task_id)
            for ae in active_entries:
                if ae.dispatch_state in (DispatchState.PREPARED, DispatchState.DISPATCHING, DispatchState.RUNNING):
                    self.journal.record_cancelled(ae.attempt_id, reason=reason)
            self.journal.release_task_lease(task_id, self.worker_id)
        self._persist_state(state)

        await self._emit_loop_event(task_id, "loop_terminated", {
            "status": "CANCELLED",
            "reason": reason,
        })
        return state
