"""Secured FastAPI wrapper around the x1_all_tools dispatcher.

Adds flexible API-key authentication (header, query param, or Bearer token,
all whitespace-tolerant), CORS for the browser app, an optional tool denylist,
and a workspace-scoped file download endpoint. Runs as a Hugging Face Docker
Space on port 7860.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from x1_all_tools.dispatcher import ToolDispatcher
from x1_all_tools.llm import MODEL
from x1_all_tools.runtime import ToolRuntime
from x1_all_tools.tools import build_registry

# .strip() guards against trailing newlines/spaces that some secret stores add.
API_KEY = os.environ.get("X1_API_KEY", "").strip()
DENY = {d.strip() for d in os.environ.get("X1_DENY", "").split(",") if d.strip()}

registry = build_registry()
runtime = ToolRuntime.create("workspace")
dispatcher = ToolDispatcher(registry, runtime)
WORKSPACE = Path(runtime.workspace).resolve()

app = FastAPI(title="X1 All Tools (secured)", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ToolCall(BaseModel):
    tool: str = Field(..., examples=["pdf.create"])
    arguments: dict[str, Any] = Field(default_factory=dict)
    api_key: str | None = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    max_tokens: int = 320
    temperature: float = 0.6
    api_key: str | None = None


def _present_key(request: Request, header_key: str | None, query_key: str | None, body_key: str | None = None) -> str:
    cand = header_key or query_key or body_key
    if not cand:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            cand = auth[7:]
    return (cand or "").strip()


def _auth(key: str) -> None:
    if not API_KEY:
        raise HTTPException(500, "Server X1_API_KEY secret is not configured.")
    if key != API_KEY:
        raise HTTPException(401, "Invalid or missing API key.")


def _denied(tool: str) -> bool:
    if not tool:
        return False
    return tool in DENY or tool.split(".")[0] in DENY


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/debug")
def debug(request: Request,
          x_api_key: str | None = Header(default=None, alias="X-API-Key"),
          key: str | None = Query(default=None)) -> dict[str, Any]:
    got = _present_key(request, x_api_key, key)
    return {
        "server_key_set": bool(API_KEY),
        "server_key_len": len(API_KEY),
        "received_key_len": len(got),
        "match": got == API_KEY,
        "saw_header": x_api_key is not None,
        "saw_query": key is not None,
        "saw_authorization": bool(request.headers.get("authorization")),
    }


@app.get("/tools")
def tools(request: Request,
          x_api_key: str | None = Header(default=None, alias="X-API-Key"),
          key: str | None = Query(default=None)) -> list[dict[str, Any]]:
    _auth(_present_key(request, x_api_key, key))
    items = dispatcher.manifest()
    if DENY:
        items = [t for t in items if not _denied(t.get("name", ""))]
    return items


@app.post("/call")
def call(req: ToolCall,
         request: Request,
         x_api_key: str | None = Header(default=None, alias="X-API-Key"),
         key: str | None = Query(default=None)) -> dict[str, Any]:
    _auth(_present_key(request, x_api_key, key, req.api_key))
    if _denied(req.tool):
        raise HTTPException(403, f"Tool '{req.tool}' is disabled on this server.")
    return dispatcher.call(req.tool, req.arguments).to_dict()


@app.get("/llm/health")
def llm_health(request: Request,
               x_api_key: str | None = Header(default=None, alias="X-API-Key"),
               key: str | None = Query(default=None)) -> dict[str, Any]:
    _auth(_present_key(request, x_api_key, key))
    return MODEL.status()


@app.post("/llm/warm")
def llm_warm(request: Request,
             x_api_key: str | None = Header(default=None, alias="X-API-Key"),
             key: str | None = Query(default=None)) -> dict[str, Any]:
    _auth(_present_key(request, x_api_key, key))
    MODEL.warm_async()
    return MODEL.status()


@app.post("/llm/chat")
def llm_chat(req: ChatRequest,
             request: Request,
             x_api_key: str | None = Header(default=None, alias="X-API-Key"),
             key: str | None = Query(default=None)) -> StreamingResponse:
    _auth(_present_key(request, x_api_key, key, req.api_key))
    msgs = [{"role": m.role, "content": m.content} for m in req.messages if m.content]
    if not msgs:
        raise HTTPException(400, "No messages provided.")

    def gen() -> Any:
        try:
            for piece in MODEL.stream(msgs, req.max_tokens, req.temperature):
                yield piece
        except Exception as exc:  # noqa: BLE001 - stream the error so the client can show it
            yield f"\n[LLM_ERROR] {type(exc).__name__}: {exc}"

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")


@app.get("/download")
def download(path: str,
             request: Request,
             x_api_key: str | None = Header(default=None, alias="X-API-Key"),
             key: str | None = Query(default=None)) -> FileResponse:
    _auth(_present_key(request, x_api_key, key))
    full = _safe_file(path)
    return FileResponse(str(full), filename=full.name)


def _safe_file(path: str) -> Path:
    p = Path(path)
    full = (p if p.is_absolute() else (WORKSPACE / p)).resolve()
    if full != WORKSPACE and WORKSPACE not in full.parents:
        raise HTTPException(403, "Path is outside the workspace.")
    if not full.is_file():
        raise HTTPException(404, "File not found.")
    return full
