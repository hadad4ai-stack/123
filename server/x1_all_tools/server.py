from __future__ import annotations
from typing import Any
try:
    from fastapi import FastAPI
    from pydantic import BaseModel, Field
except ImportError as exc:
    raise RuntimeError("Install server dependencies: pip install -e '.[server]'") from exc

from .dispatcher import ToolDispatcher
from .runtime import ToolRuntime
from .tools import build_registry

class ToolCall(BaseModel):
    tool: str = Field(..., examples=["shell.run"])
    arguments: dict[str, Any] = Field(default_factory=dict)

registry = build_registry()
runtime = ToolRuntime.create("workspace")
dispatcher = ToolDispatcher(registry, runtime)
app = FastAPI(title="X1 All Tools", version="1.0.0")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/tools")
def tools() -> list[dict[str, Any]]:
    return dispatcher.manifest()

@app.post("/call")
def call(req: ToolCall) -> dict[str, Any]:
    return dispatcher.call(req.tool, req.arguments).to_dict()
