from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
import traceback, json

from .registry import ToolRegistry, validate
from .runtime import ToolRuntime

@dataclass
class ToolResult:
    ok: bool
    tool: str
    result: Any = None
    error: str | None = None
    error_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.ok:
            return {"ok": True, "tool": self.tool, "result": self.result}
        return {"ok": False, "tool": self.tool, "error": self.error, "error_type": self.error_type}

class ToolDispatcher:
    def __init__(self, registry: ToolRegistry, runtime: ToolRuntime | None = None) -> None:
        self.registry = registry
        self.runtime = runtime or ToolRuntime.create()

    def call(self, tool: str, arguments: Mapping[str, Any] | None = None) -> ToolResult:
        args = dict(arguments or {})
        try:
            spec = self.registry.get(tool)
            validate(spec.parameters, args)
            result = spec.handler(**args, runtime=self.runtime)
            self.runtime.audit(tool, args, True)
            return ToolResult(ok=True, tool=tool, result=result)
        except Exception as exc:
            err = traceback.format_exc() if self.runtime.verbose_errors else str(exc)
            self.runtime.audit(tool, args, False, err)
            return ToolResult(ok=False, tool=tool, error=err, error_type=type(exc).__name__)

    def call_json(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        tool = payload.get("tool")
        args = payload.get("arguments", {})
        if not isinstance(tool, str):
            return ToolResult(False, "<missing>", error="payload.tool must be a string", error_type="ValueError").to_dict()
        if not isinstance(args, Mapping):
            return ToolResult(False, tool, error="payload.arguments must be an object", error_type="TypeError").to_dict()
        return self.call(tool, args).to_dict()

    def manifest(self) -> list[dict[str, Any]]:
        return self.registry.manifest()
