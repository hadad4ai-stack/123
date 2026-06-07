---
title: X1 All Tools
emoji: 🛠️
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
---

# X1 All Tools — secured tool server

A FastAPI server exposing the `x1_all_tools` framework (130 tools across 38
namespaces) for the Hadad4AI mobile web app. Runs as a Hugging Face Docker Space.

## Endpoints
- `GET /health` — liveness check (no auth).
- `GET /tools` — tool manifest. Requires header `X-API-Key`.
- `POST /call` — body `{ "tool": "pdf.create", "arguments": { ... } }`. Requires `X-API-Key`.

## Required Space secret
Set in **Space → Settings → Variables and secrets**:
- `X1_API_KEY` — a long random string. The app must send the same value as `X-API-Key`.

## Optional Space secret
- `X1_DENY` — comma-separated tools/namespaces to disable, e.g.
  `shell,docker,deploy,terminal,env,security,process,server,cron`.
  Recommended on a public Space to block remote code execution.

## ⚠️ Security
`/call` can run real code (e.g. `shell.run`, `python.run`). The `X-API-Key`
gate is the only thing protecting it — keep the key secret, and use `X1_DENY`
to disable dangerous namespaces unless you truly need them.
