from __future__ import annotations
from dataclasses import dataclass, field
from queue import Queue, Empty
import os, subprocess, threading, time
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, validate_command, shell_executable, trim_output

@dataclass
class TerminalSession:
    session_id: str
    process: subprocess.Popen
    cwd: str
    shell: str
    trusted: bool
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
    finally:
        try:
            pipe.close()
        except Exception:
            pass

def _sessions(runtime) -> dict[str, TerminalSession]:
    return runtime.state.setdefault("terminal.sessions", {})

def start(cwd: str = ".", shell: str | None = None, trusted: bool = False, runtime=None) -> dict[str, Any]:
    workdir = safe_join(runtime.workspace, cwd)
    workdir.mkdir(parents=True, exist_ok=True)
    exe = shell_executable(shell)
    args = [exe] if os.name == "nt" else [exe, "-i"]
    proc = subprocess.Popen(args, cwd=str(workdir), env=runtime.merged_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    sid = runtime.new_id("term")
    session = TerminalSession(sid, proc, str(workdir), exe, trusted, time.time())
    _sessions(runtime)[sid] = session
    threading.Thread(target=_reader, args=(proc.stdout, session.stdout_queue, "stdout"), daemon=True).start()
    threading.Thread(target=_reader, args=(proc.stderr, session.stderr_queue, "stderr"), daemon=True).start()
    return {"session_id": sid, "pid": proc.pid, "cwd": str(workdir), "shell": exe, "alive": True}

def send(session_id: str, command: str, newline: bool = True, runtime=None) -> dict[str, Any]:
    sessions = _sessions(runtime)
    if session_id not in sessions:
        raise KeyError(f"unknown terminal session: {session_id}")
    s = sessions[session_id]
    if not s.alive():
        return {"session_id": session_id, "sent": False, "alive": False, "returncode": s.process.returncode}
    validate_command(command, runtime, trusted=s.trusted)
    assert s.process.stdin is not None
    s.process.stdin.write(command + ("\n" if newline else ""))
    s.process.stdin.flush()
    return {"session_id": session_id, "sent": True, "alive": s.alive()}

def read(session_id: str, wait_seconds: float = 0.2, max_chars: int | None = None, runtime=None) -> dict[str, Any]:
    sessions = _sessions(runtime)
    if session_id not in sessions:
        raise KeyError(f"unknown terminal session: {session_id}")
    s = sessions[session_id]
    deadline = time.time() + wait_seconds
    chunks = []
    while True:
        got = False
        for q in (s.stdout_queue, s.stderr_queue):
            try:
                while True:
                    chunks.append(q.get_nowait())
                    got = True
            except Empty:
                pass
        if time.time() >= deadline:
            break
        if not got:
            time.sleep(0.03)
    stdout = "".join(i["text"] for i in chunks if i["stream"] == "stdout")
    stderr = "".join(i["text"] for i in chunks if i["stream"] == "stderr")
    limit = max_chars or runtime.max_output_chars
    stdout, s1 = trim_output(stdout, limit)
    stderr, s2 = trim_output(stderr, limit)
    return {"session_id": session_id, "alive": s.alive(), "returncode": s.process.poll(), "stdout": stdout, "stderr": stderr, "trimmed": s1 or s2}

def stop(session_id: str, kill: bool = False, runtime=None) -> dict[str, Any]:
    sessions = _sessions(runtime)
    if session_id not in sessions:
        raise KeyError(f"unknown terminal session: {session_id}")
    s = sessions.pop(session_id)
    if s.alive():
        if kill:
            s.process.kill()
        else:
            s.process.terminate()
        try:
            s.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            s.process.kill()
            s.process.wait(timeout=3)
    return {"session_id": session_id, "stopped": True, "returncode": s.process.returncode}

def list_sessions(runtime=None) -> dict[str, Any]:
    return {"sessions": [{
        "session_id": sid, "pid": s.process.pid, "cwd": s.cwd, "shell": s.shell,
        "alive": s.alive(), "returncode": s.process.poll(), "age_seconds": round(time.time() - s.started_at, 3)
    } for sid, s in _sessions(runtime).items()]}

def run_sequence(commands: list[str], cwd: str = ".", wait_seconds: float = 0.2, shell: str | None = None, trusted: bool = False, runtime=None) -> dict[str, Any]:
    created = start(cwd=cwd, shell=shell, trusted=trusted, runtime=runtime)
    sid = created["session_id"]
    outputs = []
    try:
        read(sid, wait_seconds=wait_seconds, runtime=runtime)
        for command in commands:
            marker = "__X1_DONE_" + runtime.new_id("m") + "__"
            send(sid, command, runtime=runtime)
            send(sid, f"echo {marker}", runtime=runtime)
            out = ""
            err = ""
            deadline = time.time() + max(runtime.shell_timeout, 1)
            while time.time() < deadline:
                chunk = read(sid, wait_seconds=wait_seconds, runtime=runtime)
                out += chunk["stdout"]
                err += chunk["stderr"]
                if marker in out or marker in err:
                    break
            outputs.append({"command": command, "stdout": out.replace(marker, ""), "stderr": err.replace(marker, "")})
        return {"session": created, "outputs": outputs}
    finally:
        try:
            stop(sid, runtime=runtime)
        except Exception:
            pass

TOOLS = [
    ToolSpec("terminal.start", "Start a persistent terminal session.", object_schema({"cwd": {"type": "string", "default": "."}, "shell": {"type": ["string", "null"], "default": None}, "trusted": {"type": "boolean", "default": False}}, []), start),
    ToolSpec("terminal.send", "Send command to a terminal session.", object_schema({"session_id": {"type": "string"}, "command": {"type": "string"}, "newline": {"type": "boolean", "default": True}}, ["session_id", "command"]), send),
    ToolSpec("terminal.read", "Read stdout/stderr from a terminal session.", object_schema({"session_id": {"type": "string"}, "wait_seconds": {"type": "number", "default": 0.2}, "max_chars": {"type": ["integer", "null"], "default": None}}, ["session_id"]), read),
    ToolSpec("terminal.stop", "Stop a terminal session.", object_schema({"session_id": {"type": "string"}, "kill": {"type": "boolean", "default": False}}, ["session_id"]), stop),
    ToolSpec("terminal.list", "List terminal sessions.", object_schema({}, []), list_sessions),
    ToolSpec("terminal.run_sequence", "Run multiple commands in one temporary terminal session.", object_schema({"commands": {"type": "array"}, "cwd": {"type": "string", "default": "."}, "wait_seconds": {"type": "number", "default": 0.2}, "shell": {"type": ["string", "null"], "default": None}, "trusted": {"type": "boolean", "default": False}}, ["commands"]), run_sequence),
]
