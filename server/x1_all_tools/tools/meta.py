from __future__ import annotations
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema

def runtime_info(runtime=None) -> dict[str, Any]:
    return {
        "workspace": str(runtime.workspace),
        "shell_timeout": runtime.shell_timeout,
        "max_output_chars": runtime.max_output_chars,
        "env_keys": sorted(runtime.env.keys()),
        "state_keys": sorted(runtime.state.keys()),
    }

def audit_log(limit: int = 100, runtime=None) -> dict[str, Any]:
    items = runtime.state.get("audit", [])[-limit:]
    return {"items": items, "count": len(items)}

def tools_manifest_note(runtime=None) -> dict[str, Any]:
    return {"note": "Use dispatcher.manifest(), CLI list, or GET /tools for the full manifest."}

TOOLS = [
    ToolSpec("tools.runtime_info", "Return runtime workspace and state details.", object_schema({}, []), runtime_info),
    ToolSpec("tools.audit_log", "Return recent audit log items.", object_schema({"limit": {"type": "integer", "default": 100}}, []), audit_log),
    ToolSpec("tools.manifest_note", "Return a note about obtaining the full manifest.", object_schema({}, []), tools_manifest_note),
]
