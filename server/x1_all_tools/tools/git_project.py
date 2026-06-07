from __future__ import annotations
from pathlib import Path
from typing import Any
import os, json, subprocess
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, require_program, run_subprocess, shell_command_args, validate_command

def _git(args: list[str], cwd: Path, runtime=None, timeout: int | None = None) -> dict[str, Any]:
    require_program("git")
    return run_subprocess(["git"] + args, cwd, runtime.merged_env(), timeout or runtime.shell_timeout, runtime.max_output_chars)

def git_status(path: str = ".", runtime=None) -> dict[str, Any]:
    cwd = safe_join(runtime.workspace, path)
    return _git(["status", "--short", "--branch"], cwd, runtime)

def git_diff(path: str = ".", staged: bool = False, runtime=None) -> dict[str, Any]:
    cwd = safe_join(runtime.workspace, path)
    args = ["diff"]
    if staged:
        args.append("--staged")
    return _git(args, cwd, runtime)

def git_commit(message: str, path: str = ".", add_all: bool = True, runtime=None) -> dict[str, Any]:
    cwd = safe_join(runtime.workspace, path)
    results = []
    if add_all:
        results.append(_git(["add", "-A"], cwd, runtime))
    results.append(_git(["commit", "-m", message], cwd, runtime))
    return {"results": results}

def git_branch(name: str | None = None, checkout: bool = False, path: str = ".", runtime=None) -> dict[str, Any]:
    cwd = safe_join(runtime.workspace, path)
    if name and checkout:
        return _git(["checkout", "-B", name], cwd, runtime)
    if name:
        return _git(["branch", name], cwd, runtime)
    return _git(["branch", "--show-current"], cwd, runtime)

def git_clone(url: str, path: str, runtime=None) -> dict[str, Any]:
    require_program("git")
    dest = safe_join(runtime.workspace, path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    return run_subprocess(["git", "clone", url, str(dest)], runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 10, runtime.max_output_chars)

def project_scan(path: str = ".", max_files: int = 500, runtime=None) -> dict[str, Any]:
    root = safe_join(runtime.workspace, path)
    files = []
    dirs = set()
    for p in root.rglob("*"):
        if len(files) >= max_files:
            break
        if any(part in {".git", "__pycache__", "node_modules", ".venv", "venv"} for part in p.parts):
            continue
        if p.is_dir():
            dirs.add(str(p.relative_to(root)))
        else:
            files.append({
                "path": str(p.relative_to(root)),
                "bytes": p.stat().st_size,
                "suffix": p.suffix,
            })
    markers = {}
    for marker in ["pyproject.toml", "package.json", "requirements.txt", "Dockerfile", "README.md", "Makefile"]:
        markers[marker] = (root / marker).exists()
    return {"root": str(root), "files": files, "file_count": len(files), "markers": markers}

def project_init(path: str, kind: str = "python", name: str = "app", runtime=None) -> dict[str, Any]:
    root = safe_join(runtime.workspace, path)
    root.mkdir(parents=True, exist_ok=True)
    created = []
    if kind == "python":
        (root / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        pyproject = f"""[project]
name = "{name}"
version = "0.1.0"
requires-python = ">=3.10"
"""
        (root / "pyproject.toml").write_text(pyproject, encoding="utf-8")
        (root / "src").mkdir(exist_ok=True)
        module_name = name.replace("-", "_")
        code = 'def main():\n    print("hello")\n\nif __name__ == "__main__":\n    main()\n'
        (root / "src" / (module_name + ".py")).write_text(code, encoding="utf-8")
        created = ["README.md", "pyproject.toml", "src/"]
    elif kind == "node":
        (root / "package.json").write_text(json.dumps({"name": name, "version": "0.1.0", "scripts": {"start": "node index.js", "test": "node index.js"}}, indent=2), encoding="utf-8")
        (root / "index.js").write_text('console.log("hello");\n', encoding="utf-8")
        created = ["package.json", "index.js"]
    elif kind == "static":
        (root / "index.html").write_text(f"<!doctype html><title>{name}</title><h1>{name}</h1>\n", encoding="utf-8")
        created = ["index.html"]
    else:
        raise ValueError("kind must be python, node, or static")
    return {"path": str(root), "kind": kind, "created": created}

def project_run(path: str = ".", command: str | None = None, runtime=None) -> dict[str, Any]:
    root = safe_join(runtime.workspace, path)
    if command:
        validate_command(command, runtime)
        return run_subprocess(shell_command_args(command), root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    if (root / "package.json").exists():
        return run_subprocess(shell_command_args("npm start"), root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists():
        if (root / "main.py").exists():
            return run_subprocess(["python", "main.py"], root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
        return run_subprocess(["python", "-m", "unittest", "discover"], root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    raise RuntimeError("No runnable project type detected; provide command.")

def project_test(path: str = ".", command: str | None = None, runtime=None) -> dict[str, Any]:
    root = safe_join(runtime.workspace, path)
    if command:
        validate_command(command, runtime)
        return run_subprocess(shell_command_args(command), root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    if (root / "package.json").exists():
        return run_subprocess(shell_command_args("npm test"), root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    import shutil
    if shutil.which("pytest"):
        return run_subprocess(["pytest", "-q"], root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    return run_subprocess(["python", "-m", "unittest", "discover"], root, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)

TOOLS = [
    ToolSpec("git.status", "Run git status.", object_schema({"path": {"type": "string", "default": "."}}, []), git_status),
    ToolSpec("git.diff", "Run git diff.", object_schema({"path": {"type": "string", "default": "."}, "staged": {"type": "boolean", "default": False}}, []), git_diff),
    ToolSpec("git.commit", "Create a git commit.", object_schema({"message": {"type": "string"}, "path": {"type": "string", "default": "."}, "add_all": {"type": "boolean", "default": True}}, ["message"]), git_commit),
    ToolSpec("git.branch", "Create/list/switch branch.", object_schema({"name": {"type": ["string", "null"], "default": None}, "checkout": {"type": "boolean", "default": False}, "path": {"type": "string", "default": "."}}, []), git_branch),
    ToolSpec("git.clone", "Clone a git repository.", object_schema({"url": {"type": "string"}, "path": {"type": "string"}}, ["url", "path"]), git_clone),
    ToolSpec("project.scan", "Scan a project tree.", object_schema({"path": {"type": "string", "default": "."}, "max_files": {"type": "integer", "default": 500}}, []), project_scan),
    ToolSpec("project.init", "Initialize a project skeleton.", object_schema({"path": {"type": "string"}, "kind": {"type": "string", "default": "python"}, "name": {"type": "string", "default": "app"}}, ["path"]), project_init),
    ToolSpec("project.run", "Run a project or command.", object_schema({"path": {"type": "string", "default": "."}, "command": {"type": ["string", "null"], "default": None}}, []), project_run),
    ToolSpec("project.test", "Run project tests.", object_schema({"path": {"type": "string", "default": "."}, "command": {"type": ["string", "null"], "default": None}}, []), project_test),
]
