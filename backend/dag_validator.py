"""
DAG Validation and Dependency Resolution Engine for Project Go 81.
Provides structural validation, cycle detection, deterministic topological sorting,
and dependency tracking for autonomous task execution graphs.
"""

from collections import defaultdict, deque
import logging
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)


class DAGValidationError(Exception):
    """Base exception for structural DAG validation errors."""
    pass


class DuplicateStepError(DAGValidationError):
    """Raised when duplicate step IDs are detected in a plan."""
    pass


class UnknownDependencyError(DAGValidationError):
    """Raised when a step references a dependency that does not exist."""
    pass


class SelfDependencyError(DAGValidationError):
    """Raised when a step depends on itself."""
    pass


class CircularDependencyError(DAGValidationError):
    """Raised when circular dependencies (cycles) are detected in a DAG."""
    pass


class PlanSizeLimitExceededError(DAGValidationError):
    """Raised when plan step count or dependency count exceeds system budget."""
    pass


# Default system resource limits for task plans
DEFAULT_MAX_STEPS = 50
DEFAULT_MAX_DEPENDENCIES_PER_STEP = 10


def validate_dag_structure(
    steps: List[Any],
    max_steps: int = DEFAULT_MAX_STEPS,
    max_deps_per_step: int = DEFAULT_MAX_DEPENDENCIES_PER_STEP,
) -> List[str]:
    """
    Validates structural integrity of DAG steps:
    1. Enforces maximum plan step count budget.
    2. Enforces unique step IDs.
    3. Enforces dependency count limits.
    4. Rejects self-dependencies.
    5. Rejects references to non-existent steps (unknown dependencies).
    6. Detects circular dependencies via Kahn's algorithm.
    7. Returns a deterministic topological execution order.
    """
    if len(steps) > max_steps:
        raise PlanSizeLimitExceededError(
            f"Plan step count ({len(steps)}) exceeds maximum permitted budget of {max_steps} steps."
        )

    # Empty plan is trivial
    if not steps:
        return []

    # Map step IDs and verify uniqueness
    step_ids: Set[str] = set()
    for idx, step in enumerate(steps):
        s_id = getattr(step, "step_id", None) or (step.get("step_id") if isinstance(step, dict) else None)
        if not s_id or not str(s_id).strip():
            raise DAGValidationError(f"Step at index {idx} has an empty or invalid step_id.")
        s_id = str(s_id)
        if s_id in step_ids:
            raise DuplicateStepError(f"Duplicate step ID detected in plan: '{s_id}'.")
        step_ids.add(s_id)

    # Build graph and in-degree maps
    in_degree: Dict[str, int] = {s_id: 0 for s_id in step_ids}
    adj_list: Dict[str, List[str]] = {s_id: [] for s_id in step_ids}

    for step in steps:
        s_id = str(getattr(step, "step_id", None) or (step.get("step_id") if isinstance(step, dict) else None))
        deps = getattr(step, "dependencies", None) or (step.get("dependencies", []) if isinstance(step, dict) else [])
        if not isinstance(deps, list):
            raise DAGValidationError(f"Step '{s_id}' dependencies must be a list, got {type(deps).__name__}.")

        if len(deps) > max_deps_per_step:
            raise PlanSizeLimitExceededError(
                f"Step '{s_id}' has {len(deps)} dependencies, exceeding limit of {max_deps_per_step}."
            )

        seen_deps_for_step: Set[str] = set()
        for dep in deps:
            dep_id = str(dep)
            if dep_id == s_id:
                raise SelfDependencyError(f"Step '{s_id}' cannot depend on itself (self-dependency).")
            if dep_id not in step_ids:
                raise UnknownDependencyError(
                    f"Step '{s_id}' references unknown prerequisite dependency '{dep_id}'."
                )
            if dep_id in seen_deps_for_step:
                continue  # ignore duplicate dependency references to same parent
            seen_deps_for_step.add(dep_id)

            adj_list[dep_id].append(s_id)
            in_degree[s_id] += 1

    # Kahn's algorithm for topological sorting and cycle detection
    # Using sorted queue ensures deterministic ordering when multiple steps have in-degree 0
    zero_in_degree = [s_id for s_id in step_ids if in_degree[s_id] == 0]
    zero_in_degree.sort()
    queue = deque(zero_in_degree)

    topological_order: List[str] = []

    while queue:
        curr = queue.popleft()
        topological_order.append(curr)

        # Examine outgoing edges (dependents)
        next_ready = []
        for dependent in adj_list[curr]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                next_ready.append(dependent)

        # Sort next ready steps deterministically
        next_ready.sort()
        for ready_id in next_ready:
            queue.append(ready_id)

    if len(topological_order) != len(step_ids):
        # A cycle exists because not all nodes were visited
        unresolved = [s_id for s_id in step_ids if in_degree[s_id] > 0]
        raise CircularDependencyError(
            f"Circular dependency detected in plan involving steps: {sorted(unresolved)}."
        )

    return topological_order


def find_transitive_dependents(steps: List[Any], root_step_id: str) -> Set[str]:
    """
    Finds all steps in the DAG that depend directly or transitively on `root_step_id`.
    Used for fail-fast dependency cascade blocking.
    """
    adj_list: Dict[str, List[str]] = defaultdict(list)
    for step in steps:
        s_id = str(getattr(step, "step_id", None) or (step.get("step_id") if isinstance(step, dict) else None))
        deps = getattr(step, "dependencies", None) or (step.get("dependencies", []) if isinstance(step, dict) else [])
        for dep in deps:
            adj_list[str(dep)].append(s_id)

    dependents: Set[str] = set()
    queue = deque([root_step_id])

    while queue:
        curr = queue.popleft()
        for child in adj_list.get(curr, []):
            if child not in dependents:
                dependents.add(child)
                queue.append(child)

    return dependents

