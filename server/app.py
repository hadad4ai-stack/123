"""Secured FastAPI wrapper around the x1_all_tools dispatcher.

Adds API-key authentication, CORS for the browser app, and an optional
tool denylist. Designed to run as a Hugging Face Docker Space on port 7860.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from x1_all_tools.dispatcher import ToolDispatcher
from x1_all_tools.runtime import ToolRuntime
from x1_all_tools.tools import build_registry

API_KEY = os.environ.get("X1_API_KEY", "")
# Comma-separated tool names or namespaces to disable, e.g. "shell,docker,deploy,env.set"
DENY = {d.strip() for d in os.environ.get("X1_DENY", "").split(",") if d.strip()}

registry = build_registry()
runtime = ToolRuntime.create("workspace")
dispatcher = ToolDispatcher(registry, runtime)
WORKSPACE = Path(runtime.workspace).resolve()


def _safe_file(path: str) -> Path:
    p = Path(path)
    full = (p if p.is_absolute() else (WORKSPACE / p)).resolve()
    if full != WORKSPACE and WORKSPACE not in full.parents:
        raise HTTPException(403, "Path is outside the workspace.")
    if not full.is_file():
        raise HTTPException(404, "File not found.")
    return full

app = FastAPI(title="X1 All Tools (secured)", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # the API key is the gate; key is never committed to the repo
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class ToolCall(BaseModel):
    tool: str = Field(..., examples=["pdf.create"])
    arguments: dict[str, Any] = Field(default_factory=dict)


def _auth(key: str | None) -> None:
    if not API_KEY:
        raise HTTPException(500, "Server X1_API_KEY secret is not configured.")
    if key != API_KEY:
        raise HTTPException(401, "Invalid or missing API key.")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/tools")
def tools(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> list[dict[str, Any]]:
    _auth(x_api_key)
    items = dispatcher.manifest()
    if DENY:
        items = [t for t in items if not _denied(t.get("name", ""))]
    return items


@app.post("/call")
def call(req: ToolCall, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    _auth(x_api_key)
    if _denied(req.tool):
        raise HTTPException(403, f"Tool '{req.tool}' is disabled on this server.")
    return dispatcher.call(req.tool, req.arguments).to_dict()


@app.get("/download")
def download(path: str, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> FileResponse:
    _auth(x_api_key)
    full = _safe_file(path)
    return FileResponse(str(full), filename=full.name)


def _denied(tool: str) -> bool:
    if not tool:
        return False
    return tool in DENY or tool.split(".")[0] in DENY
