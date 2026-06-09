# Hadad4AI — Supabase backend

Version-controlled mirror of the deployed Supabase project (`aiiivwwgtgspkyuvywaz`).
Source of truth for the Edge Functions; the database schema lives in migrations
(see `migrations/` — exportable from `supabase_migrations.schema_migrations`).

## Edge Functions

| Function | JWT | Purpose | Secrets used |
|----------|-----|---------|--------------|
| `agent-chat` | ✅ | Cloud agent loop (OpenAI-compatible / OpenRouter). Tools: memory, knowledge/RAG, `web_fetch` (delegated to `tool-proxy`), `web_search` (Tavily), and **artifacts** (`artifact_*` → RPCs). Only advertises tools it implements. | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL?`, `OPENAI_EMBEDDING_MODEL?`, `TAVILY_API_KEY?` |
| `tool-proxy` | ✅ | `web_fetch` proxy with a hardened SSRF guard (private IPv4/IPv6 + DNS-rebind + redirect blocking, byte budget). | — |
| `structural_blocker` | ✅ | RBAC policy engine (roles in `internal.app_roles`, rules in `internal.policy_rules`, audit in `internal.policy_decisions`). Hard-deny needles + first-match-wins rules. | `SUPABASE_SERVICE_ROLE_KEY`, `STRUCTURAL_BOOTSTRAP_TOKEN?` |
| `artifact-api` | ✅ | Artifacts CRUD over RPCs: `create/update/publish/preview/read/list` (`?action=`). | — |
| `artifact-studio` | ✅ | Server-rendered artifacts studio + sandboxed preview (HTML). Note: Supabase serves edge HTML as `text/plain`+sandbox, so render artifacts client-side in the app instead. | — |
| `ai-mobile-app`, `mobile-ai`, `mobile-ai-config` | ❌ | **Deprecated.** 301-redirect to the GitHub Pages app. | — |

The web app (`/index.html`, GitHub Pages) is the primary client. It runs local
in-browser models and/or the cloud `agent-chat`, executes browser tools, and
renders Artifacts in a sandboxed iframe.

## Key RPCs (public schema)
Artifacts: `create_ai_artifact`, `update_ai_artifact`, `publish_ai_artifact`,
`preview_ai_artifact`, `read_ai_artifact`, `list_ai_artifacts`,
`create_product_artifact`, `iterate_product_artifact`, `infer_artifact_type`.
Retrieval/agent: `match_ai_knowledge`, `match_ai_memory_items`,
`match_ai_tool_guides`, `log_ai_tool_run`, `agent_os_v5_status`,
`agent_os_v5_readiness_report`, `ai_tool_scorecards`.

## Required Edge Function secrets
- `OPENAI_BASE_URL` = `https://openrouter.ai/api/v1`
- `OPENAI_API_KEY`  = OpenRouter key (`sk-or-...`)
- (optional) `TAVILY_API_KEY` for `web_search`, `STRUCTURAL_BOOTSTRAP_TOKEN` for one-time RBAC bootstrap.

`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` are injected by the platform.

## Deploy (Supabase CLI)
```bash
supabase functions deploy agent-chat
supabase functions deploy tool-proxy
# ...etc. JWT settings are in config.toml
supabase db push        # apply migrations
```
