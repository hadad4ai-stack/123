from __future__ import annotations
import os, shutil, subprocess, tempfile, time
from pathlib import Path
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, validate_command, shell_command_args, trim_output, run_subprocess

def run(command: str, cwd: str = ".", timeout_seconds: int | None = None, env: dict[str, str] | None = None, trusted: bool = False, shell: str | None = None, runtime=None) -> dict[str, Any]:
    validate_command(command, runtime, trusted=trusted)
    workdir = safe_join(runtime.workspace, cwd)
    workdir.mkdir(parents=True, exist_ok=True)
    timeout = timeout_seconds or runtime.shell_timeout
    result = run_subprocess(shell_command_args(command, shell=shell), workdir, runtime.merged_env(env), timeout, runtime.max_output_chars)
    result.update({"command": command, "cwd": str(workdir)})
    return result

def which(program: str, runtime=None) -> dict[str, Any]:
    path = shutil.which(program, path=runtime.merged_env().get("PATH"))
    return {"program": program, "path": path, "found": bool(path)}

def script(content: str, interpreter: str | None = None, cwd: str = ".", timeout_seconds: int | None = None, trusted: bool = False, runtime=None) -> dict[str, Any]:
    validate_command(content, runtime, trusted=trusted)
    workdir = safe_join(runtime.workspace, cwd)
    workdir.mkdir(parents=True, exist_ok=True)
    suffix = ".bat" if os.name == "nt" else ".sh"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=suffix, dir=str(workdir), delete=False) as f:
        path = Path(f.name)
        if os.name != "nt" and interpreter is None:
            f.write("#!/usr/bin/env bash\nset -e\n")
        f.write(content)
    try:
        if os.name != "nt":
            path.chmod(0o700)
        if interpreter:
            cmd = f'{interpreter} "{path.name}"'
        elif os.name == "nt":
            cmd = f'"{path.name}"'
        else:
            cmd = f'./"{path.name}"'
        res = run(cmd, cwd=cwd, timeout_seconds=timeout_seconds, trusted=True, runtime=runtime)
        res["script_path"] = str(path)
        return res
    finally:
        try:
            path.unlink()
        except OSError:
            pass

def pipeline(commands: list[str], stop_on_error: bool = True, cwd: str = ".", timeout_seconds: int | None = None, trusted: bool = False, runtime=None) -> dict[str, Any]:
    results = []
    for cmd in commands:
        item = run(cmd, cwd=cwd, timeout_seconds=timeout_seconds, trusted=trusted, runtime=runtime)
        results.append(item)
        if stop_on_error and (item.get("timed_out") or item.get("returncode") not in (0, None)):
            break
    return {"results": results, "completed": len(results) == len(commands)}

TOOLS = [
    ToolSpec("shell.run", "Run one shell command inside the workspace and capture stdout/stderr.", object_schema({
        "command": {"type": "string"},
        "cwd": {"type": "string", "default": "."},
        "timeout_seconds": {"type": ["integer", "null"], "default": None},
        "env": {"type": ["object", "null"], "default": None},
        "trusted": {"type": "boolean", "default": False},
        "shell": {"type": ["string", "null"], "default": None},
    }, ["command"]), run, examples=[{"command": "echo hello && pwd"}]),
    ToolSpec("shell.which", "Find an executable in PATH.", object_schema({"program": {"type": "string"}}, ["program"]), which),
    ToolSpec("shell.script", "Run a temporary shell script inside workspace.", object_schema({
        "content": {"type": "string"},
        "interpreter": {"type": ["string", "null"], "default": None},
        "cwd": {"type": "string", "default": "."},
        "timeout_seconds": {"type": ["integer", "null"], "default": None},
        "trusted": {"type": "boolean", "default": False},
    }, ["content"]), script),
    ToolSpec("shell.pipeline", "Run multiple shell commands sequentially.", object_schema({
        "commands": {"type": "array"},
        "stop_on_error": {"type": "boolean", "default": True},
        "cwd": {"type": "string", "default": "."},
        "timeout_seconds": {"type": ["integer", "null"], "default": None},
        "trusted": {"type": "boolean", "default": False},
    }, ["commands"]), pipeline),
]
