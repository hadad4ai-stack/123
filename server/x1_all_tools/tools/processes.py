from __future__ import annotations
from dataclasses import dataclass, field
from queue import Queue, Empty
import subprocess, threading, time
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, validate_command, shell_command_args, trim_output

@dataclass
class ManagedProcess:
    process_id: str
    process: subprocess.Popen
    command: str
    cwd: str
    started_at: float
    stdout_queue: Queue = field(default_factory=Queue)
    stderr_queue: Queue = field(default_factory=Queue)
    def alive(self) -> bool:
        return self.process.poll() is None

def _reader(pipe, q: Queue, stream: str) -> None:
    try:
        for line in iter(pipe.readline, ""):
            if not line:
                break
            q.put({"stream": stream, "text": line, "time": time.time()})
    except Exception as exc:
        q.put({"stream": stream, "text": f"[reader-error] {exc}\n", "time": time.time()})

def _store(runtime) -> dict[str, ManagedProcess]:
    return runtime.state.setdefault("process.managed", {})

def start(command: str, cwd: str = ".", env: dict[str, str] | None = None, trusted: bool = False, runtime=None) -> dict[str, Any]:
    validate_command(command, runtime, trusted=trusted)
    workdir = safe_join(runtime.workspace, cwd)
    workdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(shell_command_args(command), cwd=str(workdir), env=runtime.merged_env(env), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    pid = runtime.new_id("proc")
    managed = ManagedProcess(pid, proc, command, str(workdir), time.time())
    _store(runtime)[pid] = managed
    threading.Thread(target=_reader, args=(proc.stdout, managed.stdout_queue, "stdout"), daemon=True).start()
    threading.Thread(target=_reader, args=(proc.stderr, managed.stderr_queue, "stderr"), daemon=True).start()
    return {"process_id": pid, "pid": proc.pid, "command": command, "cwd": str(workdir), "alive": True}

def read(process_id: str, max_chars: int | None = None, runtime=None) -> dict[str, Any]:
    store = _store(runtime)
    if process_id not in store:
        raise KeyError(f"unknown process: {process_id}")
    p = store[process_id]
    stdout, stderr = [], []
    for q, target in [(p.stdout_queue, stdout), (p.stderr_queue, stderr)]:
        try:
            while True:
                target.append(q.get_nowait()["text"])
        except Empty:
            pass
    limit = max_chars or runtime.max_output_chars
    out, s1 = trim_output("".join(stdout), limit)
    err, s2 = trim_output("".join(stderr), limit)
    return {"process_id": process_id, "alive": p.alive(), "returncode": p.process.poll(), "stdout": out, "stderr": err, "trimmed": s1 or s2}

def list_processes(runtime=None) -> dict[str, Any]:
    return {"processes": [{
        "process_id": pid, "pid": p.process.pid, "command": p.command, "cwd": p.cwd,
        "alive": p.alive(), "returncode": p.process.poll(), "age_seconds": round(time.time() - p.started_at, 3)
    } for pid, p in _store(runtime).items()]}

def stop(process_id: str, kill: bool = False, runtime=None) -> dict[str, Any]:
    store = _store(runtime)
    if process_id not in store:
        raise KeyError(f"unknown process: {process_id}")
    p = store.pop(process_id)
    if p.alive():
        if kill:
            p.process.kill()
        else:
            p.process.terminate()
        try:
            p.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            p.process.kill()
            p.process.wait(timeout=3)
    return {"process_id": process_id, "stopped": True, "returncode": p.process.returncode}

TOOLS = [
    ToolSpec("process.start", "Start a long-running command asynchronously.", object_schema({"command": {"type": "string"}, "cwd": {"type": "string", "default": "."}, "env": {"type": ["object", "null"], "default": None}, "trusted": {"type": "boolean", "default": False}}, ["command"]), start),
    ToolSpec("process.read", "Read buffered stdout/stderr from a managed process.", object_schema({"process_id": {"type": "string"}, "max_chars": {"type": ["integer", "null"], "default": None}}, ["process_id"]), read),
    ToolSpec("process.list", "List managed processes.", object_schema({}, []), list_processes),
    ToolSpec("process.stop", "Stop a managed process.", object_schema({"process_id": {"type": "string"}, "kill": {"type": "boolean", "default": False}}, ["process_id"]), stop),
]
