from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import os, uuid, time, json

@dataclass
class ToolRuntime:
    workspace: Path
    verbose_errors: bool = False
    shell_timeout: int = 30
    max_output_chars: int = 30000
    env: dict[str, str] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, workspace: str | Path = "workspace", *, verbose_errors: bool = False, shell_timeout: int = 30, max_output_chars: int = 30000) -> "ToolRuntime":
        root = Path(workspace).resolve()
        root.mkdir(parents=True, exist_ok=True)
        rt = cls(root, verbose_errors=verbose_errors, shell_timeout=shell_timeout, max_output_chars=max_output_chars)
        rt.state.setdefault("audit", [])
        rt.state.setdefault("permissions", {"allowlist": [], "denylist": []})
        return rt

    def merged_env(self, extra: dict[str, str] | None = None, *, minimal: bool = False) -> dict[str, str]:
        if minimal:
            keep = {"PATH", "HOME", "TMP", "TEMP", "SYSTEMROOT", "WINDIR", "COMSPEC", "SHELL", "LANG", "LC_ALL"}
            env = {k: v for k, v in os.environ.items() if k.upper() in keep or k in keep}
        else:
            env = dict(os.environ)
        env.update(self.env)
        if extra:
            env.update({str(k): str(v) for k, v in extra.items()})
        return env

    def new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex[:12]}"

    def audit(self, tool: str, arguments: dict[str, Any], ok: bool, error: str | None = None) -> None:
        item = {
            "time": time.time(),
            "tool": tool,
            "ok": ok,
            "arguments_keys": sorted(arguments.keys()),
            "error": error,
        }
        self.state.setdefault("audit", []).append(item)
        if len(self.state["audit"]) > 1000:
            self.state["audit"] = self.state["audit"][-1000:]

    def audit_file(self) -> Path:
        return self.workspace / ".x1_audit.json"
