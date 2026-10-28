"""
Deterministic, Safe Built-in Skills for Project Go 81.
Integrates directly with SecurityBoundary and Memory Subsystem.
"""

import os
import platform
import sys
import tempfile
from typing import Any, Dict, List
import urllib.parse
import httpx

from app.memory.security_boundary import SecurityBoundary
from app.skills.models import (
    Capability,
    ExecutionContext,
    FilesystemScope,
    NetworkScope,
    ResourceLimits,
    RetryPolicy,
    SkillCategory,
    SkillDefinition,
    SkillParameter,
    SkillRiskLevel,
)
from app.skills.registry import SkillRegistry


# ----------------------------------------------------------------------------
# 1. filesystem.read
# ----------------------------------------------------------------------------

def _filesystem_read_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    project_root = context.project_root or os.getcwd()
    boundary = SecurityBoundary(project_root)
    raw_path = params["path"]
    offset = params.get("offset", 0)
    limit = params.get("limit", 32768)

    safe_path = boundary.resolve_safe_path(raw_path)
    if not os.path.exists(safe_path):
        raise FileNotFoundError(f"File not found: '{raw_path}'")
    if os.path.isdir(safe_path):
        raise IsADirectoryError(f"Target '{raw_path}' is a directory, not a file.")

    file_size = os.path.getsize(safe_path)
    with open(safe_path, "r", encoding="utf-8", errors="replace") as f:
        if offset > 0:
            f.seek(offset)
        content = f.read(limit)

    return {
        "path": raw_path,
        "resolved_path": safe_path,
        "size_bytes": file_size,
        "offset": offset,
        "bytes_read": len(content),
        "content": content,
        "has_more": (offset + len(content)) < file_size,
    }


# ----------------------------------------------------------------------------
# 2. filesystem.write
# ----------------------------------------------------------------------------

def _filesystem_write_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    project_root = context.project_root or os.getcwd()
    boundary = SecurityBoundary(project_root)
    raw_path = params["path"]
    content = params["content"]
    mode = params.get("mode", "write")

    safe_path = boundary.resolve_safe_path(raw_path)
    parent = os.path.dirname(safe_path)
    if parent and not os.path.exists(parent):
        boundary.resolve_safe_path(parent)
        os.makedirs(parent, exist_ok=True)

    if mode == "append" and os.path.exists(safe_path):
        with open(safe_path, "a", encoding="utf-8") as f:
            f.write(content)
        bytes_written = len(content.encode("utf-8"))
    else:
        # Atomic write pattern using temp file in same directory
        temp_dir = parent if parent else project_root
        with tempfile.NamedTemporaryFile("w", dir=temp_dir, delete=False, encoding="utf-8") as tf:
            tf.write(content)
            temp_name = tf.name
        os.replace(temp_name, safe_path)
        bytes_written = len(content.encode("utf-8"))

    return {
        "path": raw_path,
        "resolved_path": safe_path,
        "bytes_written": bytes_written,
        "mode": mode,
        "status": "success",
    }


# ----------------------------------------------------------------------------
# 3. filesystem.list
# ----------------------------------------------------------------------------

def _filesystem_list_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    project_root = context.project_root or os.getcwd()
    boundary = SecurityBoundary(project_root)
    raw_path = params.get("path", ".")
    recursive = params.get("recursive", False)
    max_items = params.get("max_items", 100)

    safe_path = boundary.resolve_safe_path(raw_path)
    if not os.path.exists(safe_path):
        raise FileNotFoundError(f"Path not found: '{raw_path}'")
    if not os.path.isdir(safe_path):
        raise NotADirectoryError(f"Target '{raw_path}' is not a directory.")

    entries = []
    if recursive:
        for root, dirs, files in os.walk(safe_path):
            rel_root = os.path.relpath(root, safe_path)
            for d in dirs:
                if len(entries) >= max_items:
                    break
                p = os.path.join(rel_root, d) if rel_root != "." else d
                entries.append({"name": d, "rel_path": p.replace(os.sep, "/"), "is_dir": True})
            for f in files:
                if len(entries) >= max_items:
                    break
                p = os.path.join(rel_root, f) if rel_root != "." else f
                full = os.path.join(root, f)
                entries.append({
                    "name": f,
                    "rel_path": p.replace(os.sep, "/"),
                    "is_dir": False,
                    "size_bytes": os.path.getsize(full) if os.path.exists(full) else 0,
                })
            if len(entries) >= max_items:
                break
    else:
        for name in os.listdir(safe_path):
            if len(entries) >= max_items:
                break
            full = os.path.join(safe_path, name)
            is_dir = os.path.isdir(full)
            entries.append({
                "name": name,
                "rel_path": name,
                "is_dir": is_dir,
                "size_bytes": os.path.getsize(full) if not is_dir and os.path.exists(full) else 0,
            })

    return {
        "path": raw_path,
        "resolved_path": safe_path,
        "count": len(entries),
        "entries": entries,
        "truncated": len(entries) >= max_items,
    }


# ----------------------------------------------------------------------------
# 4. system.info
# ----------------------------------------------------------------------------

def _system_info_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    # Strictly zero secrets, zero environment tokens, zero host user passwords
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "processor": platform.processor() or "unknown",
        "cpu_count": os.cpu_count() or 1,
        "sovereign_identity": "Go 81 Local Agent Runtime",
    }


# ----------------------------------------------------------------------------
# 5. memory.search
# ----------------------------------------------------------------------------

def _memory_search_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    from app.memory.service import query_relevant_context
    query = params["query"]
    limit = params.get("limit", 5)

    res = query_relevant_context(query)
    facts = res.get("facts", [])[:limit]
    prefs = res.get("preferences", [])[:limit]
    return {
        "query": query,
        "facts": facts,
        "preferences": prefs,
        "cited_ids": res.get("cited_ids", [])[:limit],
        "memory_available": res.get("memory_available", True),
    }


# ----------------------------------------------------------------------------
# 6. network.http_get
# ----------------------------------------------------------------------------

ALLOWED_HTTP_HOSTS = {"127.0.0.1", "localhost", "httpbin.org", "api.github.com"}

def _network_http_get_handler(params: Dict[str, Any], context: ExecutionContext) -> Dict[str, Any]:
    raw_url = params["url"]
    timeout_seconds = min(float(params.get("timeout_seconds", 10.0)), 30.0)

    parsed = urllib.parse.urlparse(raw_url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme '{parsed.scheme}'. Must be http or https.")

    hostname = (parsed.hostname or "").lower()
    if hostname not in ALLOWED_HTTP_HOSTS:
        raise PermissionError(
            f"Outbound network access to host '{hostname}' is not permitted. "
            f"Allowed destinations: {sorted(list(ALLOWED_HTTP_HOSTS))}"
        )

    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        resp = client.get(raw_url)
        # Bounded response content: max 64 KB
        raw_text = resp.text
        max_bytes = 64 * 1024
        truncated = len(raw_text) > max_bytes
        content = raw_text[:max_bytes] if truncated else raw_text

    return {
        "url": raw_url,
        "status_code": resp.status_code,
        "headers": dict(resp.headers),
        "content": content,
        "truncated": truncated,
    }


# ----------------------------------------------------------------------------
# Builtin Registration Factory
# ----------------------------------------------------------------------------

def register_builtin_skills(registry: SkillRegistry) -> None:
    """Registers standard Go 81 built-in skills into the SkillRegistry."""

    # 1. filesystem.read
    registry.register(
        SkillDefinition(
            id="filesystem.read",
            name="filesystem.read",
            displayName="Read Local File",
            version="1.0.0",
            description="Safely reads content from a file within the permitted project root.",
            category=SkillCategory.FILESYSTEM,
            required_capabilities=[Capability.FILESYSTEM_READ.value],
            risk_level=SkillRiskLevel.LOW,
            requires_approval=False,
            filesystem_scope=FilesystemScope(allow_read=True, allow_write=False),
            parameters=[
                SkillParameter(name="path", type="string", description="Relative or safe project path", required=True),
                SkillParameter(name="offset", type="integer", description="Byte offset to begin reading", required=False, default=0, min_value=0),
                SkillParameter(name="limit", type="integer", description="Maximum bytes to read", required=False, default=32768, min_value=1, max_value=1048576),
            ],
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=2),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_filesystem_read_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 2. filesystem.write
    registry.register(
        SkillDefinition(
            id="filesystem.write",
            name="filesystem.write",
            displayName="Write Local File",
            version="1.0.0",
            description="Safely writes or appends content to a file within the permitted project root.",
            category=SkillCategory.FILESYSTEM,
            required_capabilities=[Capability.FILESYSTEM_WRITE.value],
            risk_level=SkillRiskLevel.MEDIUM,
            requires_approval=False,
            filesystem_scope=FilesystemScope(allow_read=True, allow_write=True),
            parameters=[
                SkillParameter(name="path", type="string", description="Relative or safe project path", required=True),
                SkillParameter(name="content", type="string", description="Content to write", required=True),
                SkillParameter(name="mode", type="string", description="Write mode: 'write' or 'append'", required=False, default="write", enum=["write", "append"]),
            ],
            retry_policy=RetryPolicy(is_idempotent=False, max_retries=0),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_filesystem_write_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 3. filesystem.list
    registry.register(
        SkillDefinition(
            id="filesystem.list",
            name="filesystem.list",
            displayName="List Directory",
            version="1.0.0",
            description="Lists files and subdirectories within the permitted project root.",
            category=SkillCategory.FILESYSTEM,
            required_capabilities=[Capability.FILESYSTEM_READ.value],
            risk_level=SkillRiskLevel.LOW,
            requires_approval=False,
            filesystem_scope=FilesystemScope(allow_read=True, allow_write=False),
            parameters=[
                SkillParameter(name="path", type="string", description="Directory path relative to project root", required=False, default="."),
                SkillParameter(name="recursive", type="boolean", description="Whether to recurse into subdirectories", required=False, default=False),
                SkillParameter(name="max_items", type="integer", description="Maximum number of items to return", required=False, default=100, min_value=1, max_value=500),
            ],
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=2),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_filesystem_list_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 4. system.info
    registry.register(
        SkillDefinition(
            id="system.info",
            name="system.info",
            displayName="System Diagnostics",
            version="1.0.0",
            description="Returns safe local operating system and runtime diagnostics with zero secret exposure.",
            category=SkillCategory.SYSTEM,
            required_capabilities=[Capability.SYSTEM_INFO.value],
            risk_level=SkillRiskLevel.LOW,
            requires_approval=False,
            parameters=[
                SkillParameter(name="include_memory_stats", type="boolean", description="Include system memory status", required=False, default=False),
            ],
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=3),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_system_info_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 5. memory.search
    registry.register(
        SkillDefinition(
            id="memory.search",
            name="memory.search",
            displayName="Search Memory Vault",
            version="1.0.0",
            description="Searches verified facts and preferences in the local encrypted memory vault.",
            category=SkillCategory.SYSTEM,
            required_capabilities=[Capability.MEMORY_SEARCH.value],
            risk_level=SkillRiskLevel.LOW,
            requires_approval=False,
            parameters=[
                SkillParameter(name="query", type="string", description="Search query string", required=True),
                SkillParameter(name="limit", type="integer", description="Max records to return", required=False, default=5, min_value=1, max_value=20),
            ],
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=2),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_memory_search_handler,
        is_builtin=True,
        allow_overwrite=True,
    )

    # 6. network.http_get
    registry.register(
        SkillDefinition(
            id="network.http_get",
            name="network.http_get",
            displayName="Restricted HTTP GET",
            version="1.0.0",
            description="Performs an outbound HTTP GET request strictly restricted to whitelisted hostnames.",
            category=SkillCategory.NETWORK,
            required_capabilities=[Capability.NETWORK_HTTP.value],
            risk_level=SkillRiskLevel.HIGH,
            requires_approval=True,
            network_scope=NetworkScope(allowed_hosts=sorted(list(ALLOWED_HTTP_HOSTS))),
            parameters=[
                SkillParameter(name="url", type="string", description="Target HTTP/HTTPS URL", required=True),
                SkillParameter(name="timeout_seconds", type="number", description="Request timeout", required=False, default=10.0, min_value=1.0, max_value=30.0),
            ],
            retry_policy=RetryPolicy(is_idempotent=True, max_retries=1),
            isSandboxed=True,
            enabled=True,
        ),
        handler=_network_http_get_handler,
        is_builtin=True,
        allow_overwrite=True,
    )
