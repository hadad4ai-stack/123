from __future__ import annotations
from pathlib import Path
import json, shutil, zipfile, hashlib, re
from typing import Any
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, hash_file

def read_text(path: str, max_chars: int = 30000, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    text = target.read_text(encoding="utf-8")
    return {"path": str(target), "content": text[:max_chars], "truncated": len(text) > max_chars}

def write_text(path: str, content: str, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"path": str(target), "bytes": target.stat().st_size}

def append_text(path: str, content: str, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(content)
    return {"path": str(target), "bytes": target.stat().st_size}

def list_files(path: str = ".", recursive: bool = True, runtime=None) -> dict[str, Any]:
    root = safe_join(runtime.workspace, path)
    if not root.exists():
        return {"path": str(root), "items": []}
    pattern = "**/*" if recursive else "*"
    items = []
    for item in sorted(root.glob(pattern)):
        rel = item.relative_to(runtime.workspace)
        items.append({"path": str(rel), "type": "dir" if item.is_dir() else "file", "bytes": item.stat().st_size if item.is_file() else None})
    return {"path": str(root), "items": items}

def mkdir(path: str, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    target.mkdir(parents=True, exist_ok=True)
    return {"path": str(target), "created": True}

def remove(path: str, recursive: bool = False, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    if not target.exists():
        return {"path": str(target), "removed": False}
    if target.is_dir():
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
    else:
        target.unlink()
    return {"path": str(target), "removed": True}

def copy(src: str, dst: str, runtime=None) -> dict[str, Any]:
    s = safe_join(runtime.workspace, src)
    d = safe_join(runtime.workspace, dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    if s.is_dir():
        shutil.copytree(s, d, dirs_exist_ok=True)
    else:
        shutil.copy2(s, d)
    return {"src": str(s), "dst": str(d), "copied": True}

def move(src: str, dst: str, runtime=None) -> dict[str, Any]:
    s = safe_join(runtime.workspace, src)
    d = safe_join(runtime.workspace, dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return {"src": str(s), "dst": str(d), "moved": True}

def search(pattern: str, path: str = ".", regex: bool = False, max_results: int = 100, runtime=None) -> dict[str, Any]:
    root = safe_join(runtime.workspace, path)
    results = []
    compiled = re.compile(pattern) if regex else None
    for file in root.rglob("*"):
        if not file.is_file():
            continue
        try:
            text = file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            matched = compiled.search(line) if compiled else pattern in line
            if matched:
                results.append({"path": str(file.relative_to(runtime.workspace)), "line": lineno, "text": line[:500]})
                if len(results) >= max_results:
                    return {"results": results, "truncated": True}
    return {"results": results, "truncated": False}

def hash(path: str, algorithm: str = "sha256", runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    return {"path": str(target), "algorithm": algorithm, "hash": hash_file(target, algorithm)}

def zip_paths(paths: list[str], output: str, runtime=None) -> dict[str, Any]:
    out = safe_join(runtime.workspace, output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in paths:
            target = safe_join(runtime.workspace, p)
            if target.is_dir():
                for file in target.rglob("*"):
                    if file.is_file():
                        z.write(file, file.relative_to(runtime.workspace))
            else:
                z.write(target, target.relative_to(runtime.workspace))
    return {"path": str(out), "bytes": out.stat().st_size}

def unzip(path: str, output_dir: str = ".", runtime=None) -> dict[str, Any]:
    src = safe_join(runtime.workspace, path)
    out = safe_join(runtime.workspace, output_dir)
    out.mkdir(parents=True, exist_ok=True)
    extracted = []
    with zipfile.ZipFile(src) as z:
        for name in z.namelist():
            dest = safe_join(out, name)
            # safe_join above ensures final destination under output dir.
            z.extract(name, out)
            extracted.append(name)
    return {"source": str(src), "output_dir": str(out), "extracted": extracted}

def write_json(path: str, data: dict[str, Any], runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"path": str(target), "bytes": target.stat().st_size}

def read_json(path: str, runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, path)
    return {"path": str(target), "data": json.loads(target.read_text(encoding="utf-8"))}

TOOLS = [
    ToolSpec("files.read_text", "Read a UTF-8 text file.", object_schema({"path": {"type": "string"}, "max_chars": {"type": "integer", "default": 30000}}, ["path"]), read_text),
    ToolSpec("files.write_text", "Write a UTF-8 text file.", object_schema({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]), write_text),
    ToolSpec("files.append_text", "Append UTF-8 text to a file.", object_schema({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]), append_text),
    ToolSpec("files.list", "List files and folders.", object_schema({"path": {"type": "string", "default": "."}, "recursive": {"type": "boolean", "default": True}}, []), list_files),
    ToolSpec("files.mkdir", "Create a directory.", object_schema({"path": {"type": "string"}}, ["path"]), mkdir),
    ToolSpec("files.remove", "Remove a file or directory.", object_schema({"path": {"type": "string"}, "recursive": {"type": "boolean", "default": False}}, ["path"]), remove),
    ToolSpec("files.copy", "Copy a file or directory.", object_schema({"src": {"type": "string"}, "dst": {"type": "string"}}, ["src", "dst"]), copy),
    ToolSpec("files.move", "Move a file or directory.", object_schema({"src": {"type": "string"}, "dst": {"type": "string"}}, ["src", "dst"]), move),
    ToolSpec("files.search", "Search text inside files.", object_schema({"pattern": {"type": "string"}, "path": {"type": "string", "default": "."}, "regex": {"type": "boolean", "default": False}, "max_results": {"type": "integer", "default": 100}}, ["pattern"]), search),
    ToolSpec("files.hash", "Hash a file.", object_schema({"path": {"type": "string"}, "algorithm": {"type": "string", "default": "sha256"}}, ["path"]), hash),
    ToolSpec("files.zip", "Create a ZIP archive.", object_schema({"paths": {"type": "array"}, "output": {"type": "string"}}, ["paths", "output"]), zip_paths),
    ToolSpec("files.unzip", "Extract a ZIP archive.", object_schema({"path": {"type": "string"}, "output_dir": {"type": "string", "default": "."}}, ["path"]), unzip),
    ToolSpec("files.write_json", "Write JSON file.", object_schema({"path": {"type": "string"}, "data": {"type": "object"}}, ["path", "data"]), write_json),
    ToolSpec("files.read_json", "Read JSON file.", object_schema({"path": {"type": "string"}}, ["path"]), read_json),
]
