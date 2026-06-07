from __future__ import annotations
import ast, json, subprocess, sys, tempfile, time, py_compile
from pathlib import Path
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, trim_output, run_subprocess, require_program

_BLOCKED_CALLS = {"eval", "exec", "compile", "__import__", "open", "input", "breakpoint"}

def _validate(code: str, allow_imports: bool) -> None:
    if allow_imports:
        return
    tree = ast.parse(code, mode="exec")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("imports are disabled by default; pass allow_imports=true for trusted code")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
            raise ValueError(f"blocked call: {node.func.id}")

def run(code: str, timeout_seconds: int = 10, allow_imports: bool = False, cwd: str = ".", runtime=None) -> dict[str, Any]:
    if timeout_seconds < 1 or timeout_seconds > 600:
        raise ValueError("timeout_seconds must be between 1 and 600")
    _validate(code, allow_imports)
    workdir = safe_join(runtime.workspace, cwd)
    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", dir=str(workdir), delete=False) as f:
        path = Path(f.name)
        f.write(code)
    try:
        res = run_subprocess([sys.executable, "-I", str(path)], workdir, runtime.merged_env(minimal=True), timeout_seconds, runtime.max_output_chars)
        return res
    finally:
        try:
            path.unlink()
        except OSError:
            pass

def install_package(package: str, upgrade: bool = False, runtime=None) -> dict[str, Any]:
    args = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"]
    if upgrade:
        args.append("--upgrade")
    args.append(package)
    return run_subprocess(args, runtime.workspace, runtime.merged_env(), runtime.shell_timeout * 10, runtime.max_output_chars)

def run_file(path: str, args: list[str] | None = None, timeout_seconds: int = 30, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    return run_subprocess([sys.executable, str(target)] + [str(a) for a in (args or [])], target.parent, runtime.merged_env(minimal=True), timeout_seconds, runtime.max_output_chars)

def notebook_create(path: str, cells: list[dict[str, Any]] | list[str], runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    nb_cells = []
    for cell in cells:
        if isinstance(cell, str):
            nb_cells.append({"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": cell.splitlines(True)})
        else:
            ctype = cell.get("type", cell.get("cell_type", "code"))
            source = cell.get("source", "")
            nb_cells.append({
                "cell_type": "markdown" if ctype == "markdown" else "code",
                "metadata": cell.get("metadata", {}),
                "source": source.splitlines(True) if isinstance(source, str) else source,
                **({"execution_count": None, "outputs": []} if ctype != "markdown" else {}),
            })
    nb = {"cells": nb_cells, "metadata": {"language_info": {"name": "python"}}, "nbformat": 4, "nbformat_minor": 5}
    target.write_text(json.dumps(nb, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(target), "cells": len(nb_cells), "bytes": target.stat().st_size}

def code_format(path: str, tool: str = "auto", runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    chosen = None
    if tool in ("auto", "black"):
        import shutil
        if shutil.which("black"):
            chosen = "black"
            res = run_subprocess(["black", str(target)], target.parent, runtime.merged_env(), runtime.shell_timeout, runtime.max_output_chars)
            res["tool"] = chosen
            return res
    # Fallback: normalize trailing whitespace and final newline.
    text = target.read_text(encoding="utf-8")
    formatted = "\n".join(line.rstrip() for line in text.splitlines()) + "\n"
    target.write_text(formatted, encoding="utf-8")
    return {"tool": "builtin_trim", "path": str(target), "changed": text != formatted}

def code_lint(path: str, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    if target.suffix == ".py":
        try:
            py_compile.compile(str(target), doraise=True)
            return {"path": str(target), "ok": True, "issues": []}
        except py_compile.PyCompileError as exc:
            return {"path": str(target), "ok": False, "issues": [str(exc)]}
    return {"path": str(target), "ok": True, "issues": ["No builtin linter for this file type."]}

def code_test(path: str = ".", command: str | None = None, runtime=None) -> dict[str, Any]:
    workdir = safe_join(runtime.workspace, path)
    import shutil
    if command:
        from x1_all_tools.security import shell_command_args, validate_command
        validate_command(command, runtime, trusted=False)
        return run_subprocess(shell_command_args(command), workdir, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    if shutil.which("pytest"):
        return run_subprocess(["pytest", "-q"], workdir, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)
    return run_subprocess([sys.executable, "-m", "unittest", "discover"], workdir, runtime.merged_env(), runtime.shell_timeout * 5, runtime.max_output_chars)

def code_explain(path: str, max_chars: int = 20000, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    text = target.read_text(encoding="utf-8")
    summary: dict[str, Any] = {"path": str(target), "bytes": target.stat().st_size, "language_guess": target.suffix.lstrip(".")}
    if target.suffix == ".py":
        tree = ast.parse(text)
        summary["imports"] = []
        summary["functions"] = []
        summary["classes"] = []
        for node in tree.body:
            if isinstance(node, ast.Import):
                summary["imports"].extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                summary["imports"].append(node.module or "")
            elif isinstance(node, ast.FunctionDef):
                summary["functions"].append({"name": node.name, "args": [a.arg for a in node.args.args], "lineno": node.lineno})
            elif isinstance(node, ast.ClassDef):
                summary["classes"].append({"name": node.name, "lineno": node.lineno, "methods": [n.name for n in node.body if isinstance(n, ast.FunctionDef)]})
    summary["preview"] = text[:max_chars]
    return summary

def code_patch(path: str, find: str, replace: str, count: int = -1, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    text = target.read_text(encoding="utf-8")
    if find not in text:
        raise ValueError("find text not found")
    new_text = text.replace(find, replace, count if count >= 0 else text.count(find))
    target.write_text(new_text, encoding="utf-8")
    return {"path": str(target), "replacements": text.count(find) if count < 0 else min(count, text.count(find))}

TOOLS = [
    ToolSpec("python.run", "Run Python code in a subprocess.", object_schema({"code": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 10}, "allow_imports": {"type": "boolean", "default": False}, "cwd": {"type": "string", "default": "."}}, ["code"]), run),
    ToolSpec("python.install_package", "Install a Python package with pip in the current environment.", object_schema({"package": {"type": "string"}, "upgrade": {"type": "boolean", "default": False}}, ["package"]), install_package),
    ToolSpec("python.run_file", "Run a Python file from workspace.", object_schema({"path": {"type": "string"}, "args": {"type": ["array", "null"], "default": None}, "timeout_seconds": {"type": "integer", "default": 30}}, ["path"]), run_file),
    ToolSpec("notebook.create", "Create a Jupyter notebook file.", object_schema({"path": {"type": "string"}, "cells": {"type": "array"}}, ["path", "cells"]), notebook_create),
    ToolSpec("code.format", "Format code using black if installed, else trim whitespace.", object_schema({"path": {"type": "string"}, "tool": {"type": "string", "default": "auto"}}, ["path"]), code_format),
    ToolSpec("code.lint", "Lint/compile-check a code file.", object_schema({"path": {"type": "string"}}, ["path"]), code_lint),
    ToolSpec("code.test", "Run tests using pytest if available, else unittest.", object_schema({"path": {"type": "string", "default": "."}, "command": {"type": ["string", "null"], "default": None}}, []), code_test),
    ToolSpec("code.explain", "Produce a static summary of a code file.", object_schema({"path": {"type": "string"}, "max_chars": {"type": "integer", "default": 20000}}, ["path"]), code_explain),
    ToolSpec("code.patch", "Patch a file with simple find/replace.", object_schema({"path": {"type": "string"}, "find": {"type": "string"}, "replace": {"type": "string"}, "count": {"type": "integer", "default": -1}}, ["path", "find", "replace"]), code_patch),
]
