from __future__ import annotations
from typing import Any
import os
from x1_all_tools.registry import ToolSpec, object_schema

SENSITIVE = ("TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "CREDENTIAL", "AUTH")

def _redact(key: str, value: str, reveal_sensitive: bool) -> str:
    if reveal_sensitive:
        return value
    if any(x in key.upper() for x in SENSITIVE):
        if len(value) <= 6:
            return "***"
        return value[:2] + "..." + value[-2:]
    return value

def env_list(prefix: str = "", include_runtime: bool = True, reveal_sensitive: bool = False, runtime=None) -> dict[str, Any]:
    data = dict(os.environ)
    if include_runtime:
        data.update(runtime.env)
    out = {}
    for k in sorted(data):
        if prefix and not k.startswith(prefix):
            continue
        out[k] = _redact(k, str(data[k]), reveal_sensitive)
    return {"env": out, "redacted": not reveal_sensitive}

def env_get(name: str, default: str = "", reveal_sensitive: bool = False, runtime=None) -> dict[str, Any]:
    value = runtime.env.get(name, os.environ.get(name, default))
    return {"name": name, "value": _redact(name, str(value), reveal_sensitive), "redacted": not reveal_sensitive}

def env_set(name: str, value: str, runtime=None) -> dict[str, Any]:
    runtime.env[str(name)] = str(value)
    return {"name": name, "set": True}

def env_unset(name: str, runtime=None) -> dict[str, Any]:
    existed = name in runtime.env
    runtime.env.pop(name, None)
    return {"name": name, "removed_from_runtime": existed}

TOOLS = [
    ToolSpec("env.list", "List environment variables with redaction by default.", object_schema({"prefix": {"type": "string", "default": ""}, "include_runtime": {"type": "boolean", "default": True}, "reveal_sensitive": {"type": "boolean", "default": False}}, []), env_list),
    ToolSpec("env.get", "Get one environment variable with redaction by default.", object_schema({"name": {"type": "string"}, "default": {"type": "string", "default": ""}, "reveal_sensitive": {"type": "boolean", "default": False}}, ["name"]), env_get),
    ToolSpec("env.set", "Set a runtime-only environment variable.", object_schema({"name": {"type": "string"}, "value": {"type": "string"}}, ["name", "value"]), env_set),
    ToolSpec("env.unset", "Unset a runtime-only environment variable.", object_schema({"name": {"type": "string"}}, ["name"]), env_unset),
]
