"""
Task Planner for Project Go 81.
Responsible for Memory Handshake:
- Imports and invokes query_relevant_context(user_goal) from the persistence/memory module before generating the DAG.
- Injects verified facts and user preferences into the system prompt passed to Ollama so the planner respects user constraints.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from app.memory.models import RiskLevel, TaskCheckpoint, TaskStatus
from app.memory.service import MemoryService, query_relevant_context

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# DAG Models
# ============================================================================

class DAGStep(BaseModel):
    """Represents a single step within a Task execution DAG."""
    step_id: str = Field(default_factory=lambda: f"step-{uuid.uuid4().hex[:8]}")
    step_number: int = Field(default=1)
    title: str = Field(..., description="Human-readable step title")
    skill_name: str = Field(..., description="Target registered skill or tool")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list, description="IDs of prerequisite steps")
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    requires_approval: bool = Field(default=False)
    status: str = Field(default="PENDING", description="PENDING, RUNNING, PAUSED_APPROVAL, COMPLETED, FAILED")
    output: Optional[Any] = Field(default=None)
    approval_id: Optional[str] = Field(default=None)

    def __getitem__(self, item: str) -> Any:
        if item == "id":
            return self.step_id
        return getattr(self, item)

    def __contains__(self, item: str) -> bool:
        return item in ("id", "step_id") or hasattr(self, item)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, dict):
            for k, v in other.items():
                if k == "id" and self.step_id != v:
                    return False
                elif hasattr(self, k) and getattr(self, k) != v:
                    return False
            return True
        return super().__eq__(other)




class TaskDAG(BaseModel):
    """Execution DAG produced by the TaskPlanner."""
    task_id: str = Field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    goal: str = Field(..., description="Original user prompt or task goal")
    model: str = Field(default="gemma4:e2b", description="Target Ollama model")
    injected_context: Dict[str, Any] = Field(default_factory=dict, description="Retrieved verified facts and preferences")
    system_prompt: str = Field(..., description="System prompt passed to LLM containing injected memory")
    steps: List[DAGStep] = Field(default_factory=list)
    status: str = Field(default="PENDING", description="PENDING, RUNNING, PAUSED_APPROVAL, COMPLETED, FAILED")
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)

    def __getitem__(self, item: str) -> Any:
        if item == "id":
            return self.task_id
        return getattr(self, item)



# ============================================================================
# Task Planner Engine
# ============================================================================

def is_conversational_query(query: str) -> bool:
    """
    Determines if user input is an informational or conversational inquiry
    rather than an imperative action requesting tool side-effects.
    """
    if not query:
        return True
    q = query.strip().lower()

    # Explicit action verbs that signal side-effect execution
    action_keywords = [
        "write file", "create file", "delete file", "delete ", "rm ", "run ", "execute",
        "install", "build", "deploy", "kill", "compile", "clone", "git commit", "push",
        "format disk", "modify file", "update file", "overwrite", "curl", "wget"
    ]
    for act in action_keywords:
        if act in q:
            return False

    # Conversational / question patterns (use word boundaries for short words like 'hi')
    question_prefixes = [
        "what", "who", "why", "how", "when", "where", "which", "is ", "are ",
        "can you", "could you", "tell me", "explain", "describe", "summarize",
        "list my", "show my", "what are my", "what is my", "what was my",
        "do i have", "do you know", "hello", "hey", "help", "thanks", "thank you"
    ]
    for pref in question_prefixes:
        if q.startswith(pref) or f" {pref} " in q:
            return True

    # Standalone greeting check for 'hi'
    if q == "hi" or q.startswith("hi ") or " hi " in q:
        return True

    if q.endswith("?"):
        return True

    return False


class TaskPlanner:
    """
    Sovereign Task Planner that integrates memory context into Ollama (gemma4:e2b)
    to generate execution DAGs respecting user constraints.
    """

    def __init__(
        self,
        model: str = "gemma4:e2b",
        ollama_endpoint: str = "http://127.0.0.1:11434",
        memory_service: Optional[MemoryService] = None,
    ):
        self.model = model
        self.ollama_endpoint = ollama_endpoint.rstrip("/")
        self.memory_service = memory_service

    def build_system_prompt(self, user_goal: str, context: Dict[str, Any]) -> str:
        """
        Injects verified facts, user preferences, and constraints into the system prompt.
        """
        formatted_context = context.get("formatted_context", "No prior preferences found.")
        preferences = context.get("preferences", [])
        verified_facts = context.get("verified_facts", [])
        constraints = context.get("constraints", [])

        prompt = f"""You are Go 81's Sovereign Autonomous Task Planner.
Target Local Inference Engine: Ollama
Active Model: {self.model}
Telemetry Policy: Zero outbound telemetry, local-first execution.

=== INJECTED VERIFIED USER MEMORY & CONSTRAINTS (MEMBER 2 HANDSHAKE) ===
{formatted_context}
===================================================

USER TASK GOAL:
{user_goal}

CRITICAL PLANNING RULES:
1. All user preferences and verified facts shown above MUST be strictly respected.
2. If a user preference or constraint conflicts with a generic strategy, user preference WINS.
3. Classify each step by risk level (LOW, MEDIUM, HIGH).
4. High-risk actions (writing files, executing shell commands, modifying network states, sending data) MUST have requires_approval=True.
5. Deconstruct into a Directed Acyclic Graph (DAG) with explicit step dependencies.
"""
        return prompt

    def generate_dag(self, user_goal: str) -> TaskDAG:
        """
        Executes Milestone 5 handshake:
        1. Queries relevant context via query_relevant_context(user_goal).
        2. Injects verified facts and preferences into the prompt for gemma4:e2b.
        3. Calls local Ollama or deterministic sovereign planner to produce the DAG.
        """
        # Step 1: Handshake with Member 2 persistence/memory module
        context = query_relevant_context(user_goal, memory_service=self.memory_service)

        # Step 2: Inject into system prompt for gemma4:e2b
        system_prompt = self.build_system_prompt(user_goal, context)

        # Step 3: Attempt Ollama generation or use deterministic heuristic DAG
        steps = self._synthesize_dag_steps(user_goal, context, system_prompt)

        dag = TaskDAG(
            goal=user_goal,
            model=self.model,
            injected_context=context,
            system_prompt=system_prompt,
            steps=steps,
            status="PENDING",
        )

        return dag

    def _synthesize_dag_steps(
        self,
        user_goal: str,
        context: Dict[str, Any],
        system_prompt: str,
    ) -> List[DAGStep]:
        """
        Attempts to call Ollama gemma4:e2b. If Ollama is offline or doesn't return JSON,
        uses the deterministic sovereign planner that adheres to the user constraints.
        """
        # Safety gate: conversational questions never run mutating tools
        if is_conversational_query(user_goal):
            return self._generate_deterministic_dag(user_goal, context)

        ollama_response = self._call_ollama(system_prompt, user_goal)
        if ollama_response:
            parsed_steps = self._parse_llm_dag(ollama_response)
            if parsed_steps:
                return parsed_steps

        # Deterministic sovereign fallback that respects user constraints
        return self._generate_deterministic_dag(user_goal, context)

    def _call_ollama(self, system_prompt: str, user_goal: str) -> Optional[str]:
        """Queries local Ollama chat endpoint with bounded timeout using OllamaClient."""
        try:
            from backend.ollama_client import (
                OllamaClient,
                OllamaConfig,
                OllamaConnectionError,
                OllamaTimeoutError,
                OllamaModelNotFoundError,
            )
            config = OllamaConfig(
                base_url=self.ollama_endpoint,
                chat_model=self.model,
                connect_timeout=1.5,
                request_timeout=2.5,
            )
            client = OllamaClient(config=config)
            chat_resp = client.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Produce DAG JSON for goal: {user_goal}"},
                ],
                format="json",
                timeout=2.5,
            )
            return chat_resp.content
        except (OllamaConnectionError, httpx.ConnectError):
            logger.warning(
                f"Ollama local endpoint '{self.ollama_endpoint}' is unreachable. "
                "Ensure Ollama is installed (https://ollama.com) and running via 'ollama serve'. "
                "Falling back to sovereign deterministic planner."
            )
        except (OllamaTimeoutError, httpx.TimeoutException):
            logger.warning(
                f"Ollama request to '{self.ollama_endpoint}' timed out after 2.5s. "
                "Falling back to sovereign deterministic planner."
            )
        except OllamaModelNotFoundError as e:
            logger.warning(f"{e} Falling back to sovereign deterministic planner.")
        except Exception as e:
            logger.warning(
                f"Ollama local endpoint error ({e}); using sovereign deterministic engine."
            )
        return None

    def _parse_llm_dag(self, response_text: str) -> Optional[List[DAGStep]]:
        """Parses structured JSON response from Ollama."""
        try:
            match = re.search(r"(\[.*\]|\{.*\})", response_text, re.DOTALL)
            if not match:
                return None
            data = json.loads(match.group(1))
            if isinstance(data, dict):
                data = data.get("steps", [])
            if not isinstance(data, list):
                return None

            steps: List[DAGStep] = []
            for idx, item in enumerate(data, start=1):
                risk = item.get("risk_level", "LOW").upper()
                risk_enum = RiskLevel.HIGH if risk == "HIGH" else (RiskLevel.MEDIUM if risk == "MEDIUM" else RiskLevel.LOW)
                req_appr = bool(item.get("requires_approval", risk_enum == RiskLevel.HIGH))

                steps.append(
                    DAGStep(
                        step_id=item.get("step_id") or item.get("id") or f"step-{uuid.uuid4().hex[:6]}",
                        step_number=idx,
                        title=item.get("title", f"Step {idx}"),
                        skill_name=item.get("skill_name", "system.execute"),
                        parameters=item.get("parameters", {}),
                        dependencies=item.get("dependencies", []),
                        risk_level=risk_enum,
                        requires_approval=req_appr,
                    )
                )
            return steps if steps else None
        except Exception:
            return None

    def _generate_deterministic_dag(self, user_goal: str, context: Dict[str, Any]) -> List[DAGStep]:
        """
        Sovereign rule-based DAG synthesis that strictly incorporates
        retrieved user preferences and verified facts into parameters.
        Conversational inquiries return read-only response steps and never trigger tools.
        """
        steps: List[DAGStep] = []
        preferences = context.get("preferences", [])
        verified_facts = context.get("verified_facts", [])

        # Extract preference parameters (e.g. preferred language, formatting style, output path)
        pref_params: Dict[str, Any] = {}
        for p in preferences:
            key = f"{p['subject']}_{p['predicate']}".lower().replace(" ", "_")
            pref_params[key] = p["object_value"]

        # Conversational / Informational check
        if is_conversational_query(user_goal):
            step_1_id = f"step-recall-{uuid.uuid4().hex[:6]}"
            steps.append(
                DAGStep(
                    step_id=step_1_id,
                    step_number=1,
                    title="Verify Context and Ingest User Preferences",
                    skill_name="memory.recall_context",
                    parameters={"query": user_goal, "preferences": pref_params, "verified_count": len(verified_facts)},
                    dependencies=[],
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                )
            )

            step_2_id = f"step-respond-{uuid.uuid4().hex[:6]}"
            steps.append(
                DAGStep(
                    step_id=step_2_id,
                    step_number=2,
                    title=f"Formulate Response for: {user_goal[:40]}",
                    skill_name="conversation.respond",
                    parameters={"goal": user_goal, "formatted_context": context.get("formatted_context", "")},
                    dependencies=[step_1_id],
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                )
            )
            return steps

        # Task Action DAG
        # Step 1: Memory & Context Verification (Low risk, no approval required)
        step_1_id = f"step-recall-{uuid.uuid4().hex[:6]}"
        steps.append(
            DAGStep(
                step_id=step_1_id,
                step_number=1,
                title="Verify Context and Ingest User Preferences",
                skill_name="memory.recall_context",
                parameters={"query": user_goal, "preferences": pref_params, "verified_count": len(verified_facts)},
                dependencies=[],
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            )
        )

        # Step 2: Synthesis and Analysis
        step_2_id = f"step-analyze-{uuid.uuid4().hex[:6]}"
        steps.append(
            DAGStep(
                step_id=step_2_id,
                step_number=2,
                title=f"Analyze Goal: {user_goal[:40]}...",
                skill_name="reasoning.synthesize",
                parameters={"goal": user_goal, "constraints_applied": len(context.get("constraints", []))},
                dependencies=[step_1_id],
                risk_level=RiskLevel.LOW,
                requires_approval=False,
            )
        )

        # Step 3: Execution Action (High-risk gate requiring explicit user authorization)
        step_3_id = f"step-exec-{uuid.uuid4().hex[:6]}"
        steps.append(
            DAGStep(
                step_id=step_3_id,
                step_number=3,
                title=f"Execute Side-Effect for Goal: {user_goal[:30]}",
                skill_name="filesystem.write_file" if "file" in user_goal.lower() else "shell.execute",
                parameters={"goal": user_goal, "user_preferences": pref_params},
                dependencies=[step_2_id],
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
            )
        )

        return steps
