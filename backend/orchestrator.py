"""
Task Orchestrator & Execution Engine for Project Go 81.
Stage 4 Autonomous Execution Engine:
- Manages DAG execution lifecycle, bounded concurrency, and step state transitions.
- Evaluates step dependencies and handles fail-fast dependency cascades.
- Emits real-time task progress, approval requirements, and completion events over SSE streams.
- Manages human approval checkpoints and resumes paused DAG branches with verified tokens.
- Persists state checkpoints and canonical Flight Recorder evidence records.
- Produces truthful, evidence-based final task completion summaries.
"""

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from app.memory.models import RiskLevel, TaskCheckpoint, TaskStatus
from app.memory.permissions import PermissionGateway
from app.memory.recovery import TaskRecoveryManager
from backend.dag_validator import find_transitive_dependents, validate_dag_structure
from backend.planner import DAGStep, TaskDAG, utc_now_iso

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    """
    Stateful orchestrator for executing TaskDAGs, enforcing dependencies,
    emitting real-time events, and managing human approval checkpoints.
    """

    def __init__(
        self,
        recovery_manager: Optional[TaskRecoveryManager] = None,
        permission_gateway: Optional[PermissionGateway] = None,
        flight_recorder: Optional[Any] = None,
        max_concurrency: int = 4,
    ):
        self.recovery_manager = recovery_manager
        self.permission_gateway = permission_gateway
        self.flight_recorder = flight_recorder
        self.max_concurrency = max_concurrency

        # Active tasks: task_id -> TaskDAG
        self.tasks: Dict[str, TaskDAG] = {}

        # SSE subscriber queues: task_id -> List[asyncio.Queue]
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}

        # Pending approvals: approval_id -> metadata
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}

        # Concurrency semaphore
        self._semaphore = asyncio.Semaphore(max_concurrency)

        # Mutex for task state updates
        self._lock = asyncio.Lock()

    def register_task(self, dag: TaskDAG) -> None:
        """Registers a newly planned TaskDAG with the orchestrator."""
        self.tasks[dag.task_id] = dag
        self._save_checkpoint(dag)

    def get_task(self, task_id: str) -> Optional[TaskDAG]:
        """Retrieves an active or completed TaskDAG from in-memory cache or SQLite recovery checkpoint."""
        if task_id in self.tasks:
            return self.tasks[task_id]

        # Reconstruct TaskDAG from recovery checkpoint if available across restarts
        if self.recovery_manager:
            try:
                chk = self.recovery_manager.get_task_checkpoint(task_id)
                if chk and isinstance(chk.state_data, dict):
                    raw_steps = chk.state_data.get("steps", [])
                    steps = [DAGStep(**s) for s in raw_steps] if raw_steps else []
                    status_val = chk.state_data.get("task_status") or (
                        chk.status.value if hasattr(chk.status, "value") else str(chk.status)
                    )
                    dag = TaskDAG(
                        task_id=chk.task_id,
                        goal=chk.state_data.get("goal", ""),
                        plan_summary=chk.state_data.get("plan_summary"),
                        model=chk.state_data.get("model", "gemma4:e2b"),
                        system_prompt=chk.state_data.get("system_prompt", ""),
                        injected_context=chk.state_data.get("injected_context", {}),
                        steps=steps,
                        execution_order=chk.state_data.get("execution_order", []),
                        required_skills=chk.state_data.get("required_skills", []),
                        required_capabilities=chk.state_data.get("required_capabilities", []),
                        status=status_val,
                        created_at=chk.created_at,
                        updated_at=chk.updated_at,
                        completed_at=chk.state_data.get("completed_at"),
                        final_report=chk.state_data.get("final_report"),
                    )
                    self.tasks[task_id] = dag
                    return dag
            except Exception as e:
                logger.debug(f"Failed to restore task '{task_id}' from recovery checkpoint: {e}")

        return None

    def list_tasks(self) -> List[TaskDAG]:
        """Lists all registered tasks from memory cache and SQLite checkpoints."""
        if self.recovery_manager:
            try:
                checkpoints = self.recovery_manager.load_incomplete_tasks(raise_on_error=False)
                for chk in checkpoints:
                    if chk.task_id not in self.tasks:
                        self.get_task(chk.task_id)
            except Exception as e:
                logger.debug(f"Failed to sync checkpoints in list_tasks: {e}")
        return list(self.tasks.values())

    def list_pending_approvals(self) -> List[Dict[str, Any]]:
        """Lists all actions currently awaiting human authorization."""
        return list(self._pending_approvals.values())

    # =========================================================================
    # SSE Event Broadcasting & Subscriptions
    # =========================================================================

    def subscribe(self, task_id: str) -> asyncio.Queue:
        """Subscribes an SSE connection to events for a specific task."""
        queue: asyncio.Queue = asyncio.Queue()
        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        self._subscribers[task_id].append(queue)
        return queue

    def unsubscribe(self, task_id: str, queue: asyncio.Queue) -> None:
        """Removes a subscriber queue upon SSE disconnection."""
        if task_id in self._subscribers and queue in self._subscribers[task_id]:
            self._subscribers[task_id].remove(queue)
            if not self._subscribers[task_id]:
                del self._subscribers[task_id]

    async def broadcast_event(self, task_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """Broadcasts an event to all connected SSE clients and persists to Flight Recorder."""
        payload = {
            "task_id": task_id,
            "event": event_type,
            "data": data,
        }
        if task_id in self._subscribers:
            for q in list(self._subscribers[task_id]):
                try:
                    q.put_nowait(payload)
                except Exception as e:
                    logger.debug(f"Failed to queue event for subscriber: {e}")

        # Flight Recorder persistence
        if self.flight_recorder:
            try:
                from app.memory.models import (
                    EventSourceType,
                    EvidenceRecordCreate,
                    FlightRecorderEventCreate,
                )

                task = self.tasks.get(task_id)
                project_id = getattr(task, "project_id", "default") if task else "default"

                source_type = EventSourceType.OBSERVATION
                phase = "execution"
                if "failed" in event_type or "blocked" in event_type:
                    phase = "diagnostic_failure"
                elif "approval" in event_type:
                    phase = "approval"
                elif "completed" in event_type:
                    phase = "completion"

                evidence_refs = []
                out_text = data.get("output")
                err_text = data.get("error") or data.get("blocked_reason")
                if out_text or err_text:
                    ev = self.flight_recorder.store_evidence(
                        EvidenceRecordCreate(
                            evidence_type="command_output" if out_text else "diagnostic_trace",
                            command=data.get("action") or data.get("step_id") or event_type,
                            exit_code=1 if err_text else 0,
                            raw_stdout=out_text,
                            raw_stderr=err_text,
                            is_agent_hypothesis=False,
                        )
                    )
                    evidence_refs.append(ev.evidence_id)

                summary = (
                    data.get("title")
                    or data.get("goal")
                    or (f"Step {data.get('step_id')} {data.get('status', '')}" if data.get("step_id") else None)
                    or data.get("error")
                    or f"Task event: {event_type}"
                )

                self.flight_recorder.record_event(
                    FlightRecorderEventCreate(
                        project_id=project_id,
                        task_id=task_id,
                        event_type=event_type,
                        source_type=source_type,
                        actor="orchestrator",
                        summary=str(summary),
                        phase=phase,
                        evidence_refs=evidence_refs,
                        metadata=data,
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to record event to Flight Recorder: {e}")

    async def event_generator(
        self,
        task_id: str,
        request: Optional[Any] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Asynchronous generator yielding formatted Server-Sent Events (SSE).
        Flushes progress promptly, handles client disconnects, and terminates on terminal states.
        """
        queue = self.subscribe(task_id)
        task = self.get_task(task_id)

        try:
            initial_data = {
                "task_id": task_id,
                "status": task.status if task else "UNKNOWN",
                "goal": task.goal if task else "",
                "step_count": len(task.steps) if task else 0,
            }
            yield f"event: task_connected\ndata: {json.dumps(initial_data)}\n\n"

            # Check if any steps are currently awaiting approval
            if task:
                for step in task.steps:
                    if step.status in ("PAUSED_APPROVAL", "WAITING_APPROVAL") and step.approval_id:
                        appr_evt = {
                            "task_id": task_id,
                            "step_id": step.step_id,
                            "approval_id": step.approval_id,
                            "action": step.skill_name,
                            "title": step.title,
                            "risk_level": step.risk_level.value if hasattr(step.risk_level, "value") else str(step.risk_level),
                            "parameters": step.parameters,
                        }
                        yield f"event: approval_required\ndata: {json.dumps(appr_evt)}\n\n"

                if task.status in ("COMPLETED", "FAILED", "CANCELLED"):
                    terminal_evt = {
                        "task_id": task_id,
                        "status": task.status,
                    }
                    yield f"event: task_{task.status.lower()}\ndata: {json.dumps(terminal_evt)}\n\n"
                    return

            is_testing = "pytest" in sys.modules or os.environ.get("TESTING") == "1"
            max_idle_timeouts = 2 if is_testing else None
            idle_count = 0

            while True:
                if request is not None and hasattr(request, "is_disconnected"):
                    if await request.is_disconnected():
                        logger.debug(f"Client disconnected from SSE stream for task {task_id}")
                        break

                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.05 if is_testing else 15.0)
                    evt_type = event.get("event", "message")
                    evt_data = event.get("data", {})
                    yield f"event: {evt_type}\ndata: {json.dumps(evt_data)}\n\n"
                    idle_count = 0

                    if evt_type in ("task_completed", "task_failed", "task_cancelled"):
                        break
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    if max_idle_timeouts is not None:
                        idle_count += 1
                        if idle_count >= max_idle_timeouts:
                            break
                    current_task = self.get_task(task_id)
                    if current_task and current_task.status in ("COMPLETED", "FAILED", "CANCELLED"):
                        yield f"event: task_{current_task.status.lower()}\ndata: {json.dumps({'task_id': task_id, 'status': current_task.status})}\n\n"
                        break
        finally:
            self.unsubscribe(task_id, queue)

    # =========================================================================
    # Task Execution & Scheduling (Stage 4E)
    # =========================================================================

    async def start_task(self, task_id: str) -> None:
        """Begins DAG execution for a registered task."""
        task = self.get_task(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found.")

        task.status = "RUNNING"
        task.updated_at = utc_now_iso()
        await self.broadcast_event(
            task_id,
            "task_started",
            {"task_id": task_id, "status": "RUNNING", "goal": task.goal},
        )
        self._save_checkpoint(task)

        try:
            await self._advance_dag(task)
        except Exception as e:
            logger.error(f"Error executing task {task_id}: {e}", exc_info=True)
            task.status = "FAILED"
            task.completed_at = utc_now_iso()
            self._save_checkpoint(task)
            await self.broadcast_event(
                task_id,
                "task_failed",
                {"task_id": task_id, "status": "FAILED", "error": str(e)},
            )

    async def _advance_dag(self, task: TaskDAG) -> None:
        """
        Evaluates DAG dependencies and advances eligible steps:
        - Resolves completed steps.
        - Blocks descendants of failed or rejected steps.
        - Identifies ready steps and launches execution with bounded concurrency.
        - Pauses for approval when sensitive steps are ready.
        """
        async with self._lock:
            completed_step_ids = {s.step_id for s in task.steps if s.status == "COMPLETED"}
            failed_or_blocked_ids = {s.step_id for s in task.steps if s.status in ("FAILED", "REJECTED", "BLOCKED")}

            # Cascade blocking to all downstream dependents of failed/blocked steps
            for bad_id in list(failed_or_blocked_ids):
                descendants = find_transitive_dependents(task.steps, bad_id)
                for desc_id in descendants:
                    desc_step = next((s for s in task.steps if s.step_id == desc_id), None)
                    if desc_step and desc_step.status in ("PENDING", "READY"):
                        desc_step.status = "BLOCKED"
                        desc_step.blocked_reason = f"Prerequisite step '{bad_id}' failed or was rejected."
                        await self.broadcast_event(
                            task.task_id,
                            "step_blocked",
                            {
                                "task_id": task.task_id,
                                "step_id": desc_step.step_id,
                                "status": "BLOCKED",
                                "reason": desc_step.blocked_reason,
                            },
                        )

            # Discover ready steps whose prerequisites have all succeeded
            ready_steps: List[DAGStep] = []
            any_waiting_approval = False
            has_running = False

            for step in task.steps:
                if step.status == "RUNNING":
                    has_running = True
                elif step.status in ("PAUSED_APPROVAL", "WAITING_APPROVAL"):
                    any_waiting_approval = True
                elif step.status in ("PENDING", "READY"):
                    # Check if any dependency is failed/blocked
                    if any(dep in failed_or_blocked_ids for dep in step.dependencies):
                        step.status = "BLOCKED"
                        failed_dep = next(dep for dep in step.dependencies if dep in failed_or_blocked_ids)
                        step.blocked_reason = f"Prerequisite step '{failed_dep}' failed or was blocked."
                        await self.broadcast_event(
                            task.task_id,
                            "step_blocked",
                            {"task_id": task.task_id, "step_id": step.step_id, "status": "BLOCKED", "reason": step.blocked_reason},
                        )
                    # Check if all dependencies are satisfied
                    elif all(dep in completed_step_ids for dep in step.dependencies):
                        step.status = "READY"
                        ready_steps.append(step)

        # Process ready steps outside the lock
        steps_to_execute: List[DAGStep] = []

        for step in ready_steps:
            if step.requires_approval and not step.approval_token:
                await self._pause_step_for_approval(task, step)
                any_waiting_approval = True
            else:
                steps_to_execute.append(step)

        # Execute unblocked ready steps
        if steps_to_execute:
            for step in steps_to_execute:
                await self._execute_step(task, step)
            # Recurse to advance downstream newly unblocked steps
            await self._advance_dag(task)
            return

        # Check terminal condition
        all_terminal = all(
            s.status in ("COMPLETED", "FAILED", "BLOCKED", "CANCELLED", "SKIPPED")
            for s in task.steps
        )

        if any_waiting_approval:
            task.status = "PAUSED_APPROVAL"
        elif all_terminal and len(task.steps) > 0:
            failed_steps = [s for s in task.steps if s.status in ("FAILED", "BLOCKED")]
            if failed_steps:
                task.status = "FAILED"
                task.completed_at = utc_now_iso()
                report = self._generate_final_report(task)
                task.final_report = report
                await self.broadcast_event(
                    task.task_id,
                    "task_failed",
                    {
                        "task_id": task.task_id,
                        "status": "FAILED",
                        "error": f"{len(failed_steps)} step(s) failed or were blocked.",
                        "report": report,
                    },
                )
            else:
                task.status = "COMPLETED"
                task.completed_at = utc_now_iso()
                report = self._generate_final_report(task)
                task.final_report = report
                await self.broadcast_event(
                    task.task_id,
                    "task_completed",
                    {
                        "task_id": task.task_id,
                        "status": "COMPLETED",
                        "report": report,
                    },
                )

        task.updated_at = utc_now_iso()
        self._save_checkpoint(task)

    async def _pause_step_for_approval(self, task: TaskDAG, step: DAGStep) -> None:
        """Transitions step into WAITING_APPROVAL / PAUSED_APPROVAL and registers pending approval."""
        approval_id = f"apr-{uuid.uuid4().hex[:10]}"
        step.status = "PAUSED_APPROVAL"  # preserves frontend compatibility
        step.approval_id = approval_id

        # Register pending approval record
        self._pending_approvals[approval_id] = {
            "approval_id": approval_id,
            "task_id": task.task_id,
            "step_id": step.step_id,
            "title": step.title,
            "action": step.skill_name,
            "risk_level": step.risk_level.value if hasattr(step.risk_level, "value") else str(step.risk_level),
            "parameters": step.parameters,
            "created_at": task.updated_at,
        }

        # Flush SSE event for human confirmation
        await self.broadcast_event(
            task.task_id,
            "approval_required",
            {
                "task_id": task.task_id,
                "step_id": step.step_id,
                "approval_id": approval_id,
                "title": step.title,
                "action": step.skill_name,
                "risk_level": step.risk_level.value if hasattr(step.risk_level, "value") else str(step.risk_level),
                "parameters": step.parameters,
            },
        )
        logger.info(f"Task {task.task_id} step {step.step_id} PAUSED for approval: {approval_id}")

    async def _execute_step(self, task: TaskDAG, step: DAGStep) -> None:
        """Executes a single step via SkillExecutionSandbox with bounded concurrency."""
        step.status = "RUNNING"
        step.started_at = utc_now_iso()
        start_time = time.perf_counter()

        await self.broadcast_event(
            task.task_id,
            "step_progress",
            {"task_id": task.task_id, "step_id": step.step_id, "status": "RUNNING", "title": step.title},
        )

        async with self._semaphore:
            try:
                from app.skills.models import ExecutionContext
                from app.skills.routes import get_registry, get_sandbox

                registry = get_registry()
                sandbox = get_sandbox()

                ctx = ExecutionContext(
                    task_id=task.task_id,
                    step_id=step.step_id,
                    project_root=".",
                    approval_token=getattr(step, "approval_token", None),
                )

                # Execute through verified sandbox harness
                res = await sandbox.execute(step.skill_name, step.parameters or {}, ctx)
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                step.execution_duration_ms = duration_ms

                if not res.success:
                    raise RuntimeError(f"Skill execution failed: {res.error}")

                step.output = str(res.output)
                step.status = "COMPLETED"
                step.completed_at = utc_now_iso()

                await self.broadcast_event(
                    task.task_id,
                    "step_completed",
                    {
                        "task_id": task.task_id,
                        "step_id": step.step_id,
                        "status": "COMPLETED",
                        "output": step.output,
                        "duration_ms": duration_ms,
                    },
                )
            except asyncio.CancelledError:
                logger.warning(f"Step {step.step_id} execution was cancelled.")
                step.status = "CANCELLED"
                step.output = "Execution was cancelled."
                step.completed_at = utc_now_iso()
                task.status = "CANCELLED"
                self._save_checkpoint(task)
                await self.broadcast_event(
                    task.task_id,
                    "step_cancelled",
                    {"task_id": task.task_id, "step_id": step.step_id, "status": "CANCELLED"},
                )
                raise
            except Exception as e:
                duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
                step.execution_duration_ms = duration_ms
                logger.error(f"Error executing step {step.step_id} ({step.skill_name}): {e}", exc_info=True)
                step.status = "FAILED"
                step.error = str(e)
                step.output = f"Execution error: {str(e)}"
                step.completed_at = utc_now_iso()

                # Block descendants
                descendants = find_transitive_dependents(task.steps, step.step_id)
                for desc_id in descendants:
                    d_step = next((s for s in task.steps if s.step_id == desc_id), None)
                    if d_step and d_step.status in ("PENDING", "READY"):
                        d_step.status = "BLOCKED"
                        d_step.blocked_reason = f"Prerequisite step '{step.step_id}' failed: {str(e)}"

                await self.broadcast_event(
                    task.task_id,
                    "step_failed",
                    {"task_id": task.task_id, "step_id": step.step_id, "error": str(e)},
                )

                if task.failure_policy == "fail_fast":
                    task.status = "FAILED"
                    task.completed_at = utc_now_iso()
                    self._save_checkpoint(task)
                    await self.broadcast_event(
                        task.task_id,
                        "task_failed",
                        {"task_id": task.task_id, "status": "FAILED", "error": f"Step {step.step_id} failed: {str(e)}"},
                    )
                raise

    # =========================================================================
    # Approval Resumption & Resolution (Stage 4F)
    # =========================================================================

    async def resume_approval(
        self,
        approval_id: str,
        decision: str = "approved",
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Human-in-the-loop endpoint: POST /api/approvals/{approval_id}.
        Resumes the paused DAG branch when approved with a verified single-use token.
        Blocks dependent steps if rejected.
        """
        if approval_id not in self._pending_approvals:
            raise KeyError(f"Approval ID '{approval_id}' not found or already processed.")

        appr_info = self._pending_approvals.pop(approval_id)
        task_id = appr_info["task_id"]
        step_id = appr_info["step_id"]

        task = self.get_task(task_id)
        if not task:
            raise KeyError(f"Associated task '{task_id}' not found.")

        target_step = next((s for s in task.steps if s.step_id == step_id), None)
        if not target_step:
            raise KeyError(f"Associated step '{step_id}' not found in task {task_id}.")

        if decision.lower() == "approved":
            # Grant approval in PermissionGateway
            if self.permission_gateway:
                self.permission_gateway.grant_approval(
                    action=target_step.skill_name,
                    resource=str(target_step.parameters.get("path", "*")),
                )

            await self.broadcast_event(
                task_id,
                "approval_granted",
                {
                    "task_id": task_id,
                    "approval_id": approval_id,
                    "step_id": step_id,
                    "decision": "approved",
                    "notes": notes,
                },
            )

            # Generate single-use approval token via public interface
            from app.skills.routes import get_gateway, get_registry
            sec_gateway = get_gateway()
            registry = get_registry()
            try:
                # Use public registry get to check skill exists
                skill_def = registry.get(target_step.skill_name)
                _, tok = sec_gateway.create_approval_token(
                    skill_id=target_step.skill_name,
                    parameters=target_step.parameters or {},
                    notes=f"Granted via orchestrator approval: {notes}",
                )
                target_step.approval_token = tok
            except Exception as e:
                logger.warning(f"Failed to create approval token for {target_step.skill_name}: {e}")

            target_step.status = "RUNNING"
            await self.broadcast_event(
                task_id,
                "step_resumed",
                {"task_id": task_id, "step_id": step_id, "status": "RUNNING"},
            )

            await self._execute_step(task, target_step)

            if target_step.status == "COMPLETED":
                task.status = "RUNNING"
                await self._advance_dag(task)

            return {
                "success": True,
                "approval_id": approval_id,
                "status": "approved",
                "resumed_task_id": task_id,
                "step_id": step_id,
                "task_status": task.status,
            }
        else:
            # Rejection
            target_step.status = "REJECTED"
            target_step.blocked_reason = notes or "Rejected by human operator."

            # Block all dependent steps
            descendants = find_transitive_dependents(task.steps, target_step.step_id)
            for desc_id in descendants:
                d_step = next((s for s in task.steps if s.step_id == desc_id), None)
                if d_step and d_step.status in ("PENDING", "READY"):
                    d_step.status = "BLOCKED"
                    d_step.blocked_reason = f"Prerequisite step '{target_step.step_id}' was rejected by user."

            task.status = "FAILED"
            task.completed_at = utc_now_iso()

            await self.broadcast_event(
                task_id,
                "approval_rejected",
                {"task_id": task_id, "approval_id": approval_id, "step_id": step_id, "notes": notes},
            )
            self._save_checkpoint(task)
            return {
                "success": True,
                "approval_id": approval_id,
                "status": "rejected",
                "resumed_task_id": task_id,
                "step_id": step_id,
                "task_status": "FAILED",
            }

    async def cancel_task(self, task_id: str, reason: str = "Task cancelled by user") -> Dict[str, Any]:
        """Cancels an active or paused task DAG."""
        task = self.get_task(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found.")

        task.status = "CANCELLED"
        task.completed_at = utc_now_iso()
        for step in task.steps:
            if step.status in ("RUNNING", "PENDING", "READY", "PAUSED_APPROVAL", "WAITING_APPROVAL"):
                step.status = "CANCELLED"
                step.output = f"Execution cancelled: {reason}"

        self._save_checkpoint(task)
        await self.broadcast_event(
            task_id,
            "task_cancelled",
            {"task_id": task_id, "status": "CANCELLED", "reason": reason},
        )
        return {
            "success": True,
            "task_id": task_id,
            "status": "CANCELLED",
            "reason": reason,
        }

    # =========================================================================
    # Checkpointing and Truthful Reporting (Stage 4G & 4I)
    # =========================================================================

    def _generate_final_report(self, task: TaskDAG) -> Dict[str, Any]:
        """Produces a truthful, evidence-based final task execution summary."""
        completed_steps = [s for s in task.steps if s.status == "COMPLETED"]
        failed_steps = [s for s in task.steps if s.status == "FAILED"]
        blocked_steps = [s for s in task.steps if s.status == "BLOCKED"]
        skipped_steps = [s for s in task.steps if s.status == "SKIPPED"]
        waiting_steps = [s for s in task.steps if s.status in ("WAITING_APPROVAL", "PAUSED_APPROVAL")]

        summary = (
            f"Task '{task.goal}' {task.status.lower()}: "
            f"{len(completed_steps)}/{len(task.steps)} steps completed successfully. "
        )
        if failed_steps:
            summary += f"{len(failed_steps)} step(s) failed. "
        if blocked_steps:
            summary += f"{len(blocked_steps)} step(s) blocked by prerequisites. "

        return {
            "task_id": task.task_id,
            "goal": task.goal,
            "status": task.status,
            "total_steps": len(task.steps),
            "completed_steps": len(completed_steps),
            "failed_steps": len(failed_steps),
            "blocked_steps": len(blocked_steps),
            "skipped_steps": len(skipped_steps),
            "waiting_approval_steps": len(waiting_steps),
            "summary": summary.strip(),
            "completed_at": task.completed_at or utc_now_iso(),
            "execution_order": task.execution_order,
        }

    def _save_checkpoint(self, task: TaskDAG) -> None:
        """Persists task checkpoint using TaskRecoveryManager if initialized."""
        if not self.recovery_manager:
            return

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
            (s.step_id for s in task.steps if s.status in ("RUNNING", "PAUSED_APPROVAL", "WAITING_APPROVAL")),
            task.steps[0].step_id if task.steps else "start",
        )

        chk = TaskCheckpoint(
            task_id=task.task_id,
            workflow_id=task.task_id,
            status=status_mapping.get(task.status, TaskStatus.RUNNING),
            current_step=current_step_id,
            completed_step_ids=[s.step_id for s in task.steps if s.status == "COMPLETED"],
            pending_step_ids=[
                s.step_id for s in task.steps if s.status in ("PENDING", "READY", "PAUSED_APPROVAL", "WAITING_APPROVAL")
            ],
            state_data={
                "goal": task.goal,
                "plan_summary": task.plan_summary,
                "model": task.model,
                "system_prompt": task.system_prompt,
                "injected_context": task.injected_context,
                "task_status": task.status,
                "execution_order": task.execution_order,
                "required_skills": task.required_skills,
                "required_capabilities": task.required_capabilities,
                "completed_at": task.completed_at,
                "final_report": task.final_report,
                "steps": [s.model_dump() for s in task.steps],
            },
        )
        try:
            self.recovery_manager.save_task_checkpoint(chk)
        except Exception as e:
            logger.debug(f"Unable to write recovery checkpoint: {e}")
