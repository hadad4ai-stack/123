# Database migrations

The deployed schema was built by **23 migrations** (~118 KB total), stored live in
`supabase_migrations.schema_migrations`. They are **not exported as files here yet**
(large); this doc is the authoritative index + an export recipe.

## Applied migrations (in order)

| Version | Name |
|---------|------|
| 20260607004338 | create_ai_agent_core |
| 20260607004534 | extend_ai_agent_runtime |
| 20260607121541 | structural_blocker_control_plane |
| 20260607132000 | add_structural_allow_support_20260607 |
| 20260607134214 | create_set_user_role_function_20260607 |
| 20260607135436 | harden_role_function_and_sync_admin_role_20260607 |
| 20260607191132 | harden_set_user_role_admin_only |
| 20260607210201 | ai_agent_performance_indexes |
| 20260607210459 | ai_browser_agent_os_v5_core_compat |
| 20260608053837 | harden_agent_runtime_baseline_20260608_v2 |
| 20260608054001 | fix_agent_os_status_counts_20260608 |
| 20260608054033 | fix_agent_os_status_overload_20260608 |
| 20260608054430 | agent_os_v5_2_seed_runtime_model_tools_from_pack |
| 20260608054446 | agent_os_v5_2_seed_retrieval_memory_tools_from_pack |
| 20260608054501 | agent_os_v5_2_seed_tooling_queue_security_tools_from_pack |
| 20260608054517 | agent_os_v5_2_seed_tool_usage_guides_from_pack |
| 20260608054544 | agent_os_v5_2_seed_core_skills_profile_memory_from_pack |
| 20260608054615 | agent_os_v5_2_audit_functions_from_pack |
| 20260608054705 | add_artifacts_system_20260608 |
| 20260608054952 | complete_artifacts_runtime_rpc_20260608 |
| 20260608055009 | create_artifacts_demo_seed_20260608 |
| 20260608055525 | artifact_centric_product_layer_20260608 |
| 20260609… | harden_security_advisors_20260609 *(search_path + revoke anon on agent_os_v5_status)* |

## Export them to `.sql` files

Run in the Supabase SQL editor and save each row as `migrations/<filename>`:

```sql
select version || '_' || name || '.sql' as filename,
       array_to_string(statements, E'\n;\n')   as sql
from supabase_migrations.schema_migrations
order by version;
```

Or, with the Supabase CLI linked to the project:

```bash
supabase db pull          # regenerates migration files from the live schema
```

## Schema summary (23 tables)
Core agent: `ai_profiles`, `ai_conversations`, `ai_messages`, `ai_agent_runs`,
`ai_tool_runs`, `ai_skills`, `ai_tools`, `ai_system_prompts`, `ai_model_configs`,
`ai_knowledge_sources`, `ai_knowledge_chunks`, `ai_memories`, `ai_memory_items`.
Agent OS: `ai_tool_usage_guides`, `ai_tool_execution_queue`,
`ai_model_runtime_profiles`, `ai_session_context_state`, `ai_security_audit_log`.
Artifacts: `ai_artifacts`, `ai_artifact_versions`, `ai_artifact_events`,
`ai_conversation_artifact_state`, `ai_artifact_product_events`.
Plus an `internal` schema (`app_roles`, `policy_rules`, `policy_decisions`) for `structural_blocker`.
