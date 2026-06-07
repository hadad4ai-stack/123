from __future__ import annotations
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any
import json, subprocess, time
from x1_all_tools.registry import ToolSpec, object_schema
from x1_all_tools.security import safe_join, run_subprocess, shell_command_args, validate_command

def http_get(url: str, headers: dict[str, str] | None = None, timeout_seconds: int = 20, runtime=None) -> dict[str, Any]:
    req = Request(url, headers=headers or {}, method="GET")
    with urlopen(req, timeout=timeout_seconds) as res:
        body = res.read()
        text = body.decode("utf-8", errors="replace")
        return {"url": res.geturl(), "status": getattr(res, "status", None), "headers": dict(res.headers), "text": text[:runtime.max_output_chars], "bytes": len(body)}

def http_post(url: str, data: Any = None, headers: dict[str, str] | None = None, json_body: Any = None, timeout_seconds: int = 20, runtime=None) -> dict[str, Any]:
    final_headers = dict(headers or {})
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/json")
    elif isinstance(data, dict):
        body = urlencode({str(k): str(v) for k, v in data.items()}).encode("utf-8")
        final_headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif isinstance(data, str):
        body = data.encode("utf-8")
    elif data is not None:
        body = bytes(data)
    req = Request(url, data=body, headers=final_headers, method="POST")
    with urlopen(req, timeout=timeout_seconds) as res:
        raw = res.read()
        text = raw.decode("utf-8", errors="replace")
        return {"url": res.geturl(), "status": getattr(res, "status", None), "headers": dict(res.headers), "text": text[:runtime.max_output_chars], "bytes": len(raw)}

def api_call(method: str, url: str, headers: dict[str, str] | None = None, body: Any = None, timeout_seconds: int = 20, runtime=None) -> dict[str, Any]:
    if method.upper() == "GET":
        return http_get(url, headers=headers, timeout_seconds=timeout_seconds, runtime=runtime)
    if method.upper() == "POST":
        return http_post(url, headers=headers, json_body=body if isinstance(body, (dict, list)) else None, data=None if isinstance(body, (dict, list)) else body, timeout_seconds=timeout_seconds, runtime=runtime)
    final_headers = dict(headers or {})
    data = None
    if body is not None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body).encode("utf-8")
            final_headers.setdefault("Content-Type", "application/json")
        else:
            data = str(body).encode("utf-8")
    req = Request(url, data=data, headers=final_headers, method=method.upper())
    with urlopen(req, timeout=timeout_seconds) as res:
        raw = res.read()
        return {"url": res.geturl(), "status": getattr(res, "status", None), "headers": dict(res.headers), "text": raw.decode("utf-8", errors="replace")[:runtime.max_output_chars], "bytes": len(raw)}

def _servers(runtime):
    return runtime.state.setdefault("server.processes", {})

def server_start(command: str, cwd: str = ".", port: int | None = None, trusted: bool = False, runtime=None) -> dict[str, Any]:
    validate_command(command, runtime, trusted=trusted)
    workdir = safe_join(runtime.workspace, cwd)
    workdir.mkdir(parents=True, exist_ok=True)
    log_path = workdir / (runtime.new_id("server") + ".log")
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(shell_command_args(command), cwd=str(workdir), env=runtime.merged_env(), stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT, text=True)
    sid = runtime.new_id("srv")
    _servers(runtime)[sid] = {"pid": proc.pid, "process": proc, "command": command, "cwd": str(workdir), "log": str(log_path), "started_at": time.time(), "port": port}
    return {"server_id": sid, "pid": proc.pid, "command": command, "cwd": str(workdir), "log": str(log_path), "port": port}

def server_stop(server_id: str, kill: bool = False, runtime=None) -> dict[str, Any]:
    servers = _servers(runtime)
    if server_id not in servers:
        raise KeyError(f"unknown server: {server_id}")
    item = servers.pop(server_id)
    proc = item["process"]
    if proc.poll() is None:
        if kill:
            proc.kill()
        else:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
    return {"server_id": server_id, "stopped": True, "returncode": proc.returncode}

def server_logs(server_id: str, max_chars: int | None = None, runtime=None) -> dict[str, Any]:
    servers = _servers(runtime)
    if server_id not in servers:
        raise KeyError(f"unknown server: {server_id}")
    item = servers[server_id]
    path = Path(item["log"])
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    limit = max_chars or runtime.max_output_chars
    return {"server_id": server_id, "log": text[-limit:], "path": str(path), "alive": item["process"].poll() is None}

def webhook_create(path: str = "/webhook", response: dict[str, Any] | None = None, output: str = "webhook_app.py", runtime=None) -> dict[str, Any]:
    target = safe_join(runtime.workspace, output)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = response or {"ok": True}
    code = (
        "from fastapi import FastAPI, Request\n"
        "app = FastAPI()\n\n"
        "@app.post(" + repr(path) + ")\n"
        "async def webhook(request: Request):\n"
        "    body = await request.json()\n"
        "    print('WEBHOOK', body, flush=True)\n"
        "    return " + repr(payload) + "\n"
    )
    target.write_text(code, encoding="utf-8")
    return {"path": str(target), "route": path, "run": "uvicorn " + target.stem + ":app --host 0.0.0.0 --port 8000"}

def openapi_load(path_or_url: str, runtime=None) -> dict[str, Any]:
    if path_or_url.startswith(("http://", "https://")):
        text = http_get(path_or_url, runtime=runtime)["text"]
    else:
        text = safe_join(runtime.workspace, path_or_url).read_text(encoding="utf-8")
    try:
        spec = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError("YAML OpenAPI requires PyYAML: pip install PyYAML") from exc
        spec = yaml.safe_load(text)
    endpoints = []
    for p, methods in spec.get("paths", {}).items():
        for method in methods.keys():
            endpoints.append({"method": method.upper(), "path": p})
    runtime.state["openapi.last"] = spec
    return {"title": spec.get("info", {}).get("title"), "version": spec.get("info", {}).get("version"), "endpoints": endpoints, "spec": spec}

def openapi_call(base_url: str, path: str, method: str = "GET", params: dict[str, Any] | None = None, body: Any = None, headers: dict[str, str] | None = None, runtime=None) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/" + path.lstrip("/")
    if params:
        sep = "&" if "?" in url else "?"
        url += sep + urlencode({str(k): str(v) for k, v in params.items()})
    return api_call(method, url, headers=headers, body=body, runtime=runtime)

TOOLS = [
    ToolSpec("http.get", "Send HTTP GET.", object_schema({"url": {"type": "string"}, "headers": {"type": ["object", "null"], "default": None}, "timeout_seconds": {"type": "integer", "default": 20}}, ["url"]), http_get),
    ToolSpec("http.post", "Send HTTP POST.", object_schema({"url": {"type": "string"}, "data": {}, "headers": {"type": ["object", "null"], "default": None}, "json_body": {}, "timeout_seconds": {"type": "integer", "default": 20}}, ["url"], additional=True), http_post),
    ToolSpec("api.call", "Call an HTTP API with arbitrary method.", object_schema({"method": {"type": "string"}, "url": {"type": "string"}, "headers": {"type": ["object", "null"], "default": None}, "body": {}, "timeout_seconds": {"type": "integer", "default": 20}}, ["method", "url"], additional=True), api_call),
    ToolSpec("server.start", "Start a local server process.", object_schema({"command": {"type": "string"}, "cwd": {"type": "string", "default": "."}, "port": {"type": ["integer", "null"], "default": None}, "trusted": {"type": "boolean", "default": False}}, ["command"]), server_start),
    ToolSpec("server.stop", "Stop a local server process.", object_schema({"server_id": {"type": "string"}, "kill": {"type": "boolean", "default": False}}, ["server_id"]), server_stop),
    ToolSpec("server.logs", "Read server logs.", object_schema({"server_id": {"type": "string"}, "max_chars": {"type": ["integer", "null"], "default": None}}, ["server_id"]), server_logs),
    ToolSpec("webhook.create", "Create a simple FastAPI webhook app file.", object_schema({"path": {"type": "string", "default": "/webhook"}, "response": {"type": ["object", "null"], "default": None}, "output": {"type": "string", "default": "webhook_app.py"}}, []), webhook_create),
    ToolSpec("openapi.load", "Load an OpenAPI JSON/YAML spec.", object_schema({"path_or_url": {"type": "string"}}, ["path_or_url"]), openapi_load),
    ToolSpec("openapi.call", "Call an endpoint described by an OpenAPI base URL/path.", object_schema({"base_url": {"type": "string"}, "path": {"type": "string"}, "method": {"type": "string", "default": "GET"}, "params": {"type": ["object", "null"], "default": None}, "body": {}, "headers": {"type": ["object", "null"], "default": None}}, ["base_url", "path"], additional=True), openapi_call),
]
