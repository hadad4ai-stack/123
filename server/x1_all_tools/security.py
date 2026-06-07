from __future__ import annotations
from pathlib import Path
from typing import Any
import os, re, shutil, subprocess, hashlib, json

class ToolSecurityError(ValueError):
    pass

DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/(?:\s|$)",
    r"\brm\s+-rf\s+\*",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\bmkfs(?:\.\w+)?\b",
    r"\bdd\s+.*\bof=/dev/",
    r"\bchmod\s+-R\s+777\s+/",
    r"\bchown\s+-R\s+[^ ]+\s+/",
    r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",
    r"\bsudo\b",
    r"\bsu\s+-",
    r"\bcurl\b.*\|\s*(?:sh|bash|python|perl|ruby)",
    r"\bwget\b.*\|\s*(?:sh|bash|python|perl|ruby)",
    r"\bpowershell\b.*-enc",
    r"\bInvoke-Expression\b",
]

SECRET_PATTERNS = [
    (re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd|pwd)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{8,})"), r"\1=***REDACTED***"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "sk-***REDACTED***"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-./+=]{10,}"), "Bearer ***REDACTED***"),
]

def safe_join(workspace: str | Path, path: str | Path = ".") -> Path:
    root = Path(workspace).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = (root / str(path)).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise ToolSecurityError(f"path escapes workspace: {path}") from None
    return target

def trim_output(text: str | bytes | None, max_chars: int) -> tuple[str, bool]:
    if text is None:
        return "", False
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) <= max_chars:
        return text, False
    half = max_chars // 2
    return text[:half] + "\n...[trimmed]...\n" + text[-half:], True

def shell_executable(preferred: str | None = None) -> str:
    if preferred:
        return preferred
    if os.name == "nt":
        return os.environ.get("COMSPEC", "cmd.exe")
    return os.environ.get("SHELL", "/bin/bash")

def shell_command_args(command: str, shell: str | None = None) -> list[str]:
    exe = shell_executable(shell)
    lower = exe.lower()
    if os.name == "nt" and ("cmd" in lower or lower.endswith("cmd.exe")):
        return [exe, "/d", "/s", "/c", command]
    if "powershell" in lower or "pwsh" in lower:
        return [exe, "-NoLogo", "-NoProfile", "-Command", command]
    return [exe, "-lc", command]

def validate_command(command: str, runtime=None, *, trusted: bool = False) -> None:
    if trusted:
        return
    if "\x00" in command:
        raise ToolSecurityError("NUL bytes are not allowed in commands")
    perms = getattr(runtime, "state", {}).get("permissions", {}) if runtime else {}
    allow = perms.get("allowlist", []) or []
    deny = perms.get("denylist", []) or []
    if allow and not any(re.search(p, command, re.I | re.S) for p in allow):
        raise ToolSecurityError("command does not match allowlist")
    if any(re.search(p, command, re.I | re.S) for p in deny):
        raise ToolSecurityError("command matches denylist")
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, flags=re.I | re.S):
            raise ToolSecurityError("blocked potentially dangerous command; pass trusted=true only in a controlled environment")

def require_program(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"Required external program not found: {name}")
    return path

def redact_secrets_text(text: str) -> str:
    redacted = text
    for pat, repl in SECRET_PATTERNS:
        redacted = pat.sub(repl, redacted)
    return redacted

def hash_file(path: Path, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def run_subprocess(args: list[str], cwd: Path, env: dict[str, str], timeout: int, max_chars: int, input_text: str | None = None) -> dict[str, Any]:
    import time
    start = time.time()
    try:
        proc = subprocess.run(args, cwd=str(cwd), env=env, input=input_text, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
        out, s1 = trim_output(proc.stdout, max_chars)
        err, s2 = trim_output(proc.stderr, max_chars)
        return {"returncode": proc.returncode, "stdout": out, "stderr": err, "timed_out": False, "elapsed_seconds": round(time.time() - start, 4), "trimmed": s1 or s2}
    except subprocess.TimeoutExpired as exc:
        out, s1 = trim_output(exc.stdout, max_chars)
        err, s2 = trim_output(exc.stderr, max_chars)
        return {"returncode": None, "stdout": out, "stderr": err, "timed_out": True, "elapsed_seconds": round(time.time() - start, 4), "trimmed": s1 or s2}
