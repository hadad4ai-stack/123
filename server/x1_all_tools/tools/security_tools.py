from __future__ import annotations
from typing import Any
import json, re
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import validate_command, redact_secrets_text, shell_command_args, run_subprocess, safe_join

def security_allowlist(patterns: list[str], replace: bool = False, runtime=None) -> dict[str, Any]:
    perms = runtime.state.setdefault("permissions", {"allowlist": [], "denylist": []})
    if replace:
        perms["allowlist"] = list(patterns)
    else:
        perms.setdefault("allowlist", []).extend(patterns)
    return {"allowlist": perms["allowlist"]}

def security_denylist(patterns: list[str], replace: bool = False, runtime=None) -> dict[str, Any]:
    perms = runtime.state.setdefault("permissions", {"allowlist": [], "denylist": []})
    if replace:
        perms["denylist"] = list(patterns)
    else:
        perms.setdefault("denylist", []).extend(patterns)
    return {"denylist": perms["denylist"]}

def security_scan_command(command: str, runtime=None) -> dict[str, Any]:
    try:
        validate_command(command, runtime, trusted=False)
        return {"command": command, "allowed": True, "reason": None}
    except Exception as exc:
        return {"command": command, "allowed": False, "reason": str(exc), "error_type": type(exc).__name__}

def security_sandbox_run(command: str, cwd: str = ".", timeout_seconds: int | None = None, runtime=None) -> dict[str, Any]:
    # Workspace-scoped command runner with normal validation.
    validate_command(command, runtime, trusted=False)
    workdir = safe_join(runtime.workspace, cwd)
    return run_subprocess(shell_command_args(command), workdir, runtime.merged_env(minimal=True), timeout_seconds or runtime.shell_timeout, runtime.max_output_chars)

def security_audit_log(limit: int = 200, persist: bool = False, runtime=None) -> dict[str, Any]:
    items = runtime.state.get("audit", [])[-limit:]
    path = None
    if persist:
        path_obj = runtime.audit_file()
        path_obj.write_text(json.dumps(runtime.state.get("audit", []), ensure_ascii=False, indent=2), encoding="utf-8")
        path = str(path_obj)
    return {"items": items, "count": len(items), "persisted_to": path}

def security_permissions(action: str = "get", allowlist: list[str] | None = None, denylist: list[str] | None = None, runtime=None) -> dict[str, Any]:
    perms = runtime.state.setdefault("permissions", {"allowlist": [], "denylist": []})
    if action == "get":
        return dict(perms)
    if action == "set":
        perms["allowlist"] = list(allowlist or [])
        perms["denylist"] = list(denylist or [])
    elif action == "clear":
        perms["allowlist"] = []
        perms["denylist"] = []
    else:
        raise ValueError("action must be get, set, or clear")
    return dict(perms)

def security_redact_secrets(text: str, runtime=None) -> dict[str, Any]:
    redacted = redact_secrets_text(text)
    return {"redacted": redacted, "changed": redacted != text}

TOOLS = [
    ToolSpec("security.allowlist", "Add or replace allowed command regex patterns.", object_schema({"patterns": {"type": "array"}, "replace": {"type": "boolean", "default": False}}, ["patterns"]), security_allowlist),
    ToolSpec("security.denylist", "Add or replace denied command regex patterns.", object_schema({"patterns": {"type": "array"}, "replace": {"type": "boolean", "default": False}}, ["patterns"]), security_denylist),
    ToolSpec("security.scan_command", "Scan whether a shell command passes safety checks.", object_schema({"command": {"type": "string"}}, ["command"]), security_scan_command),
    ToolSpec("security.sandbox_run", "Run a command inside workspace with minimal env and validation.", object_schema({"command": {"type": "string"}, "cwd": {"type": "string", "default": "."}, "timeout_seconds": {"type": ["integer", "null"], "default": None}}, ["command"]), security_sandbox_run),
    ToolSpec("security.audit_log", "Read or persist audit log.", object_schema({"limit": {"type": "integer", "default": 200}, "persist": {"type": "boolean", "default": False}}, []), security_audit_log),
    ToolSpec("security.permissions", "Get/set/clear runtime permission patterns.", object_schema({"action": {"type": "string", "default": "get"}, "allowlist": {"type": ["array", "null"], "default": None}, "denylist": {"type": ["array", "null"], "default": None}}, []), security_permissions),
    ToolSpec("security.redact_secrets", "Redact likely secrets from text.", object_schema({"text": {"type": "string"}}, ["text"]), security_redact_secrets),
]
