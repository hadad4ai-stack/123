from __future__ import annotations
from pathlib import Path
from typing import Any
import math, re, json, os
from collections import Counter
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join

def _tokenize(text: str) -> list[str]:
    return re.findall(r"[\w\u0600-\u06FF]+", text.lower())

def agent_plan(goal: str, max_steps: int = 8, runtime=None) -> dict[str, Any]:
    steps = []
    g = goal.lower()
    if any(k in g for k in ["file", "ملف", "read", "write"]):
        steps.append({"step": "inspect_files", "tool": "files.list"})
    if any(k in g for k in ["search", "web", "بحث", "url"]):
        steps.append({"step": "gather_web_info", "tool": "web.search"})
    if any(k in g for k in ["run", "execute", "شغل", "نفذ", "terminal", "shell"]):
        steps.append({"step": "execute_command", "tool": "shell.run"})
    if any(k in g for k in ["data", "csv", "json", "بيانات"]):
        steps.append({"step": "analyze_data", "tool": "data.profile"})
    if any(k in g for k in ["pdf", "docx", "xlsx", "pptx", "document"]):
        steps.append({"step": "create_or_edit_document", "tool": "pdf.create"})
    steps.append({"step": "summarize_result", "tool": None})
    return {"goal": goal, "steps": steps[:max_steps]}

def tool_router(task: str, runtime=None) -> dict[str, Any]:
    t = task.lower()
    mapping = [
        (["shell", "terminal", "command", "bash", "شغل", "نفذ"], "shell.run"),
        (["file", "ملف", "read", "write"], "files.read_text"),
        (["web", "search", "url", "بحث"], "web.search"),
        (["pdf"], "pdf.create"),
        (["excel", "xlsx"], "xlsx.create"),
        (["powerpoint", "pptx"], "pptx.create"),
        (["word", "docx"], "docx.create"),
        (["csv", "data", "بيانات"], "data.profile"),
        (["image", "صورة"], "image.generate_prompt"),
        (["git"], "git.status"),
        (["docker"], "docker.run"),
        (["api", "http"], "http.get"),
    ]
    scores = []
    for keys, tool in mapping:
        score = sum(1 for k in keys if k in t)
        if score:
            scores.append({"tool": tool, "score": score, "matched": keys})
    scores.sort(key=lambda x: x["score"], reverse=True)
    return {"task": task, "recommended": scores[0]["tool"] if scores else "agent.plan", "candidates": scores}

def agent_run(goal: str, auto_execute: bool = False, runtime=None) -> dict[str, Any]:
    plan = agent_plan(goal, runtime=runtime)
    route = tool_router(goal, runtime=runtime)
    result = {"goal": goal, "plan": plan["steps"], "recommended_tool": route["recommended"], "executed": None}
    if auto_execute:
        result["executed"] = "Automatic execution requires a host dispatcher; call the recommended tool explicitly."
    return result

def _memory(runtime) -> dict[str, Any]:
    return runtime.state.setdefault("agent.memory", {})

def memory_write(key: str, value: Any, runtime=None) -> dict[str, Any]:
    _memory(runtime)[key] = value
    return {"key": key, "written": True}

def memory_read(key: str | None = None, runtime=None) -> dict[str, Any]:
    mem = _memory(runtime)
    if key is None:
        return {"memory": mem}
    return {"key": key, "value": mem.get(key)}

def embedding_create(text: str, dimensions: int = 256, runtime=None) -> dict[str, Any]:
    vec = [0.0] * dimensions
    tokens = _tokenize(text)
    for tok in tokens:
        idx = hash(tok) % dimensions
        vec[idx] += 1.0
    norm = math.sqrt(sum(v*v for v in vec)) or 1.0
    vec = [v / norm for v in vec]
    return {"text_length": len(text), "dimensions": dimensions, "embedding": vec}

def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n)) / ((math.sqrt(sum(x*x for x in a[:n])) or 1.0) * (math.sqrt(sum(x*x for x in b[:n])) or 1.0))

def vector_search(query: str, vectors: list[dict[str, Any]] | None = None, top_k: int = 5, runtime=None) -> dict[str, Any]:
    q = embedding_create(query, runtime=runtime)["embedding"]
    if vectors is None:
        vectors = runtime.state.get("vector.index", [])
    results = []
    for item in vectors:
        emb = item.get("embedding")
        if not emb and item.get("text"):
            emb = embedding_create(item["text"], runtime=runtime)["embedding"]
        if emb:
            results.append({**{k: v for k, v in item.items() if k != "embedding"}, "score": _cos(q, emb)})
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"query": query, "results": results[:top_k]}

def rag_index_files(paths: list[str] | None = None, root: str = ".", glob: str = "**/*.txt", index_name: str = "default", runtime=None) -> dict[str, Any]:
    files = []
    if paths:
        files = [safe_join(runtime.workspace, p) for p in paths]
    else:
        base = safe_join(runtime.workspace, root)
        files = [p for p in base.glob(glob) if p.is_file()]
    chunks = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        parts = [text[i:i+1200] for i in range(0, len(text), 1000)] or [""]
        for idx, chunk in enumerate(parts):
            emb = embedding_create(chunk, runtime=runtime)["embedding"]
            chunks.append({"id": f"{p.relative_to(runtime.workspace)}:{idx}", "path": str(p.relative_to(runtime.workspace)), "chunk": idx, "text": chunk, "embedding": emb})
    runtime.state.setdefault("rag.indexes", {})[index_name] = chunks
    runtime.state["vector.index"] = chunks
    return {"index_name": index_name, "documents": len(files), "chunks": len(chunks)}

def rag_search(query: str, index_name: str = "default", top_k: int = 5, runtime=None) -> dict[str, Any]:
    index = runtime.state.setdefault("rag.indexes", {}).get(index_name, [])
    return vector_search(query, vectors=index, top_k=top_k, runtime=runtime)

TOOLS = [
    ToolSpec("agent.run", "Run a lightweight planning/router agent. Does not call an external LLM.", object_schema({"goal": {"type": "string"}, "auto_execute": {"type": "boolean", "default": False}}, ["goal"]), agent_run),
    ToolSpec("agent.plan", "Create a simple tool-use plan for a goal.", object_schema({"goal": {"type": "string"}, "max_steps": {"type": "integer", "default": 8}}, ["goal"]), agent_plan),
    ToolSpec("agent.memory_read", "Read runtime agent memory.", object_schema({"key": {"type": ["string", "null"], "default": None}}, []), memory_read),
    ToolSpec("agent.memory_write", "Write runtime agent memory.", object_schema({"key": {"type": "string"}, "value": {}}, ["key", "value"]), memory_write),
    ToolSpec("rag.index_files", "Index text files for local semantic-ish search using hashed embeddings.", object_schema({"paths": {"type": ["array", "null"], "default": None}, "root": {"type": "string", "default": "."}, "glob": {"type": "string", "default": "**/*.txt"}, "index_name": {"type": "string", "default": "default"}}, []), rag_index_files),
    ToolSpec("rag.search", "Search a local RAG index.", object_schema({"query": {"type": "string"}, "index_name": {"type": "string", "default": "default"}, "top_k": {"type": "integer", "default": 5}}, ["query"]), rag_search),
    ToolSpec("embedding.create", "Create a deterministic local hashed embedding vector.", object_schema({"text": {"type": "string"}, "dimensions": {"type": "integer", "default": 256}}, ["text"]), embedding_create),
    ToolSpec("vector.search", "Search vectors by cosine similarity.", object_schema({"query": {"type": "string"}, "vectors": {"type": ["array", "null"], "default": None}, "top_k": {"type": "integer", "default": 5}}, ["query"]), vector_search),
    ToolSpec("tool.router", "Recommend a tool for a task.", object_schema({"task": {"type": "string"}}, ["task"]), tool_router),
]
