"""
Centralized Validated Skill Registry for Project Go 81.
Manages typed registration, discovery, parameter validation,
and status toggling for trusted sovereign skills.
"""

import hashlib
import json
import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Set

from app.skills.models import (
    Capability,
    ExecutionContext,
    ExecutionResult,
    FilesystemScope,
    NetworkScope,
    ResourceLimits,
    RetryPolicy,
    SkillDefinition,
    SkillParameter,
    SkillRiskLevel,
)

logger = logging.getLogger(__name__)


class SkillRegistryError(Exception):
    """Base exception for skill registry violations."""
    pass


class SkillNotFoundError(SkillRegistryError):
    """Raised when an unregistered skill ID is requested."""
    pass


class SkillDisabledError(SkillRegistryError):
    """Raised when an execution request targets a disabled skill."""
    pass


class DuplicateSkillError(SkillRegistryError):
    """Raised when attempting to register a skill ID that already exists."""
    pass


class SkillValidationError(SkillRegistryError):
    """Raised when skill definition or execution arguments violate schema rules."""
    pass


class UntrustedSkillRegistrationError(SkillRegistryError):
    """Raised when an untrusted caller (e.g. LLM output) attempts to register arbitrary executable code."""
    pass


def canonical_json_dumps(obj: Any) -> str:
    """Serializes an object to deterministic, sorted, whitespace-trimmed JSON string."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_action_hash(
    skill_id: str,
    version: str,
    parameters: Dict[str, Any],
    capabilities: List[str],
    scope: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Computes a deterministic, tamper-evident canonical SHA256 action hash.
    Binds the exact skill ID, version, validated parameters, requested capabilities,
    and applicable filesystem/network scopes.
    """
    canonical_dict = {
        "skill_id": skill_id,
        "version": version,
        "parameters": parameters,
        "capabilities": sorted(list(set(capabilities))),
        "scope": scope or {},
    }
    canonical_repr = canonical_json_dumps(canonical_dict)
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


class SkillRegistry:
    """
    Thread-safe Centralized Skill Registry.
    Guarantees that only registered, typed, validated skills can be invoked.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._skills: Dict[str, SkillDefinition] = {}
        self._handlers: Dict[str, Callable[[Dict[str, Any], ExecutionContext], Any]] = {}
        self._builtin_ids: Set[str] = set()

    def register(
        self,
        skill: SkillDefinition,
        handler: Optional[Callable[[Dict[str, Any], ExecutionContext], Any]] = None,
        is_builtin: bool = False,
        allow_overwrite: bool = False,
        trusted_system_caller: bool = True,
    ) -> SkillDefinition:
        """
        Registers a typed skill definition and its execution handler.
        Strictly enforces that untrusted callers cannot inject executable code.
        """
        if not trusted_system_caller and handler is not None:
            raise UntrustedSkillRegistrationError(
                f"Untrusted caller attempted to register executable code for skill '{skill.id}'. "
                "Only trusted system modules can provide executable skill handlers."
            )

        with self._lock:
            if skill.id in self._skills and not allow_overwrite:
                raise DuplicateSkillError(
                    f"Skill with ID '{skill.id}' is already registered (version {self._skills[skill.id].version})."
                )

            # Validate parameter definitions
            self._validate_parameter_schemas(skill.parameters)

            # Store definition
            skill_copy = skill.model_copy()
            if is_builtin:
                skill_copy.is_builtin = True
                self._builtin_ids.add(skill.id)

            self._skills[skill.id] = skill_copy
            if handler is not None:
                self._handlers[skill.id] = handler

            logger.info(f"Registered skill '{skill.id}' v{skill.version} (risk: {skill.risk_level.value})")
            return skill_copy

    def unregister(self, skill_id: str) -> None:
        """Removes a skill registration if not protected as a core built-in."""
        with self._lock:
            if skill_id in self._builtin_ids:
                raise SkillRegistryError(f"Cannot unregister core built-in skill '{skill_id}'.")
            if skill_id not in self._skills:
                raise SkillNotFoundError(f"Skill '{skill_id}' not found in registry.")

            del self._skills[skill_id]
            self._handlers.pop(skill_id, None)
            logger.info(f"Unregistered skill '{skill_id}'")

    def get(self, skill_id: str) -> SkillDefinition:
        """Retrieves a skill definition by ID."""
        with self._lock:
            if skill_id not in self._skills:
                raise SkillNotFoundError(f"Skill '{skill_id}' is not registered.")
            return self._skills[skill_id].model_copy()

    def get_handler(self, skill_id: str) -> Optional[Callable]:
        """Retrieves the executable handler for a registered skill."""
        with self._lock:
            if skill_id not in self._skills:
                raise SkillNotFoundError(f"Skill '{skill_id}' is not registered.")
            return self._handlers.get(skill_id)

    def list(
        self,
        category: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[SkillDefinition]:
        """Returns all registered skills, optionally filtered by category and enabled status."""
        with self._lock:
            result = []
            for s in self._skills.values():
                if category and s.category.value != category:
                    continue
                if enabled_only and not s.enabled:
                    continue
                result.append(s.model_copy())
            return result

    def enable(self, skill_id: str) -> SkillDefinition:
        """Enables a registered skill for execution."""
        with self._lock:
            if skill_id not in self._skills:
                raise SkillNotFoundError(f"Skill '{skill_id}' is not registered.")
            self._skills[skill_id].enabled = True
            return self._skills[skill_id].model_copy()

    def disable(self, skill_id: str) -> SkillDefinition:
        """Disables a registered skill from execution."""
        with self._lock:
            if skill_id not in self._skills:
                raise SkillNotFoundError(f"Skill '{skill_id}' is not registered.")
            self._skills[skill_id].enabled = False
            return self._skills[skill_id].model_copy()

    def record_execution(self, skill_id: str, timestamp_iso: str) -> None:
        """Updates invocation telemetry for a skill."""
        with self._lock:
            if skill_id in self._skills:
                self._skills[skill_id].executionCount += 1
                self._skills[skill_id].lastExecutedAt = timestamp_iso

    def validate_arguments(self, skill_id: str, raw_params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates provided execution arguments against the skill's parameter schema.
        Applies defaults, enforces required fields, and checks type and constraint boundaries.
        Returns the sanitized, validated parameter dictionary.
        """
        skill = self.get(skill_id)
        if not skill.enabled:
            raise SkillDisabledError(f"Skill '{skill_id}' is disabled and cannot be executed.")

        validated: Dict[str, Any] = {}
        param_defs = {p.name: p for p in skill.parameters}

        # Check required and defined parameters
        for p_name, p_def in param_defs.items():
            if p_name in raw_params:
                val = raw_params[p_name]
                val = self._validate_param_value(p_def, val)
                validated[p_name] = val
            elif p_def.required:
                if p_def.default is not None:
                    validated[p_name] = p_def.default
                else:
                    raise SkillValidationError(
                        f"Missing required parameter '{p_name}' for skill '{skill_id}'."
                    )
            else:
                if p_def.default is not None:
                    validated[p_name] = p_def.default

        # Disallow unrecognized arguments to prevent parameter injection
        for k in raw_params.keys():
            if k not in param_defs:
                raise SkillValidationError(
                    f"Unexpected parameter '{k}' provided for skill '{skill_id}'. "
                    f"Allowed parameters: {list(param_defs.keys())}"
                )

        return validated

    def _validate_parameter_schemas(self, params: List[SkillParameter]) -> None:
        """Validates that skill parameter definitions are internally consistent."""
        names = set()
        for p in params:
            if not p.name or not p.name.strip():
                raise SkillValidationError("Parameter name cannot be blank.")
            if p.name in names:
                raise SkillValidationError(f"Duplicate parameter name '{p.name}' in skill schema.")
            names.add(p.name)

            valid_types = {"string", "integer", "boolean", "number", "object", "array"}
            if p.type.lower() not in valid_types:
                raise SkillValidationError(
                    f"Invalid type '{p.type}' for parameter '{p.name}'. Must be one of {valid_types}."
                )

    def _validate_param_value(self, p_def: SkillParameter, val: Any) -> Any:
        """Validates a single parameter value against its schema constraint."""
        p_type = p_def.type.lower()
        if p_type == "string":
            if not isinstance(val, str):
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' expected string, got {type(val).__name__}."
                )
            if p_def.pattern:
                import re
                if not re.search(p_def.pattern, val):
                    raise SkillValidationError(
                        f"Parameter '{p_def.name}' value does not match required pattern."
                    )
        elif p_type == "integer":
            if not isinstance(val, int) or isinstance(val, bool):
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' expected integer, got {type(val).__name__}."
                )
            if p_def.min_value is not None and val < p_def.min_value:
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' value {val} is below minimum {p_def.min_value}."
                )
            if p_def.max_value is not None and val > p_def.max_value:
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' value {val} exceeds maximum {p_def.max_value}."
                )
        elif p_type == "number":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' expected number, got {type(val).__name__}."
                )
            if p_def.min_value is not None and val < p_def.min_value:
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' value {val} is below minimum {p_def.min_value}."
                )
            if p_def.max_value is not None and val > p_def.max_value:
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' value {val} exceeds maximum {p_def.max_value}."
                )
        elif p_type == "boolean":
            if not isinstance(val, bool):
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' expected boolean, got {type(val).__name__}."
                )
        elif p_type == "object":
            if not isinstance(val, dict):
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' expected dict/object, got {type(val).__name__}."
                )
        elif p_type == "array":
            if not isinstance(val, list):
                raise SkillValidationError(
                    f"Parameter '{p_def.name}' expected list/array, got {type(val).__name__}."
                )

        if p_def.enum is not None and val not in p_def.enum:
            raise SkillValidationError(
                f"Parameter '{p_def.name}' value '{val}' is not in permitted enum: {p_def.enum}."
            )

        return val


# Global Singleton Registry Instance
_global_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """Returns the shared global SkillRegistry instance."""
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry()
        from app.skills.builtins import register_builtin_skills
        register_builtin_skills(_global_registry)
    return _global_registry
