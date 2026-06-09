create unique index if not exists ai_skills_system_slug_uidx on public.ai_skills (slug) where user_id is null;
create unique index if not exists ai_tools_system_slug_uidx on public.ai_tools (slug) where user_id is null;
create unique index if not exists ai_skills_user_slug_uidx on public.ai_skills (user_id, slug) where user_id is not null;
create unique index if not exists ai_tools_user_slug_uidx on public.ai_tools (user_id, slug) where user_id is not null;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists trg_ai_profiles_updated_at on public.ai_profiles;
create trigger trg_ai_profiles_updated_at before update on public.ai_profiles for each row execute function public.set_updated_at();

drop trigger if exists trg_ai_conversations_updated_at on public.ai_conversations;
create trigger trg_ai_conversations_updated_at before update on public.ai_conversations for each row execute function public.set_updated_at();

drop trigger if exists trg_ai_skills_updated_at on public.ai_skills;
create trigger trg_ai_skills_updated_at before update on public.ai_skills for each row execute function public.set_updated_at();

drop trigger if exists trg_ai_tools_updated_at on public.ai_tools;
create trigger trg_ai_tools_updated_at before update on public.ai_tools for each row execute function public.set_updated_at();

drop trigger if exists trg_ai_knowledge_sources_updated_at on public.ai_knowledge_sources;
create trigger trg_ai_knowledge_sources_updated_at before update on public.ai_knowledge_sources for each row execute function public.set_updated_at();

drop trigger if exists trg_ai_memories_updated_at on public.ai_memories;
create trigger trg_ai_memories_updated_at before update on public.ai_memories for each row execute function public.set_updated_at();

create or replace function public.touch_ai_conversation_on_message()
returns trigger
language plpgsql
as $$
begin
  update public.ai_conversations set updated_at = now() where id = new.conversation_id;
  return new;
end;
$$;

drop trigger if exists trg_touch_ai_conversation_on_message on public.ai_messages;
create trigger trg_touch_ai_conversation_on_message after insert on public.ai_messages for each row execute function public.touch_ai_conversation_on_message();

create table if not exists public.ai_system_prompts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  name text not null,
  slug text not null,
  content text not null,
  priority int not null default 100,
  is_default boolean not null default false,
  is_enabled boolean not null default true,
  is_system boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create unique index if not exists ai_system_prompts_system_slug_uidx on public.ai_system_prompts (slug) where user_id is null;
create unique index if not exists ai_system_prompts_user_slug_uidx on public.ai_system_prompts (user_id, slug) where user_id is not null;
create index if not exists ai_system_prompts_user_enabled_idx on public.ai_system_prompts(user_id, is_enabled, priority);

create table if not exists public.ai_model_configs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  name text not null default 'Default Agent Model',
  provider text not null default 'openai_compatible',
  model text not null default 'gpt-4.1-mini',
  embedding_model text not null default 'text-embedding-3-small',
  temperature numeric not null default 0.3,
  max_tool_iterations int not null default 5 check (max_tool_iterations between 0 and 10),
  system_prompt_id uuid references public.ai_system_prompts(id) on delete set null,
  tools_enabled boolean not null default true,
  knowledge_enabled boolean not null default true,
  memory_enabled boolean not null default true,
  is_default boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ai_model_configs_user_default_idx on public.ai_model_configs(user_id, is_default);

create table if not exists public.ai_agent_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  conversation_id uuid references public.ai_conversations(id) on delete set null,
  status text not null default 'running' check (status in ('running','completed','failed')),
  model text,
  input_message text,
  output_message text,
  error text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table if not exists public.ai_tool_runs (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  agent_run_id uuid references public.ai_agent_runs(id) on delete cascade,
  conversation_id uuid references public.ai_conversations(id) on delete set null,
  tool_name text not null,
  arguments jsonb not null default '{}'::jsonb,
  result jsonb,
  status text not null default 'running' check (status in ('running','completed','failed')),
  error text,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create index if not exists ai_agent_runs_user_created_idx on public.ai_agent_runs(user_id, created_at desc);
create index if not exists ai_tool_runs_user_created_idx on public.ai_tool_runs(user_id, created_at desc);

alter table public.ai_system_prompts enable row level security;
alter table public.ai_model_configs enable row level security;
alter table public.ai_agent_runs enable row level security;
alter table public.ai_tool_runs enable row level security;

drop policy if exists ai_system_prompts_read on public.ai_system_prompts;
create policy ai_system_prompts_read on public.ai_system_prompts for select using (is_system = true or auth.uid() = user_id);

drop policy if exists ai_system_prompts_owner_write on public.ai_system_prompts;
create policy ai_system_prompts_owner_write on public.ai_system_prompts for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists ai_model_configs_owner_all on public.ai_model_configs;
create policy ai_model_configs_owner_all on public.ai_model_configs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists ai_agent_runs_owner_all on public.ai_agent_runs;
create policy ai_agent_runs_owner_all on public.ai_agent_runs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop policy if exists ai_tool_runs_owner_all on public.ai_tool_runs;
create policy ai_tool_runs_owner_all on public.ai_tool_runs for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

drop trigger if exists trg_ai_system_prompts_updated_at on public.ai_system_prompts;
create trigger trg_ai_system_prompts_updated_at before update on public.ai_system_prompts for each row execute function public.set_updated_at();

drop trigger if exists trg_ai_model_configs_updated_at on public.ai_model_configs;
create trigger trg_ai_model_configs_updated_at before update on public.ai_model_configs for each row execute function public.set_updated_at();

insert into public.ai_system_prompts (user_id, name, slug, content, priority, is_default, is_system, metadata)
values (
  null,
  'Maximum Cooperative Production Agent',
  'maximum_cooperative_production_agent',
  'You are a highly cooperative production-grade AI agent. Your job is to help the user accomplish real tasks with maximum practical usefulness. Be direct, precise, and action-oriented. When a task can be done safely, do it rather than merely describing it. Use available tools when they improve correctness, retrieval, execution, persistence, or automation. Break complex tasks into steps internally, then present clear results. Ask for clarification only when required to avoid a harmful or materially wrong action; otherwise make a reasonable assumption and state it briefly. Preserve user privacy and secrets. Do not store passwords, tokens, private keys, or sensitive credentials in memory. Do not invent tool outputs. Never claim that a tool was used unless it was actually used. When using function calling, call tools with valid JSON only and respect each tool schema. For knowledge-heavy questions, search saved knowledge before finalizing if relevant. For durable preferences or project facts, save memory only when stable and useful. Refuse only when a request is unsafe, illegal, privacy-invasive, or technically impossible; when refusing, provide the safest useful alternative. Arabic preference: when the user writes Arabic, answer in Arabic unless they request another language.',
  100,
  true,
  true,
  '{"purpose":"default_system_prompt","cooperation_level":"maximum_safe","language":"ar_en"}'::jsonb
)
on conflict do nothing;

insert into public.ai_tools (user_id, name, slug, description, json_schema, handler, config, is_system)
values
(null, 'web_search', 'web_search', 'Search the public web using a configured search provider such as Tavily.', '{"type":"function","function":{"name":"web_search","description":"Search the public web for current or external information. Requires TAVILY_API_KEY in Edge Function secrets.","parameters":{"type":"object","properties":{"query":{"type":"string"},"max_results":{"type":"integer","minimum":1,"maximum":10}},"required":["query"]}}}', 'edge_builtin', '{"provider":"tavily"}', true),
(null, 'create_knowledge_note', 'create_knowledge_note', 'Save user-provided text as a knowledge source and chunk.', '{"type":"function","function":{"name":"create_knowledge_note","description":"Save useful user-provided information into the private knowledge base.","parameters":{"type":"object","properties":{"title":{"type":"string"},"content":{"type":"string"},"metadata":{"type":"object"}},"required":["title","content"]}}}', 'edge_builtin', '{}', true)
on conflict do nothing;

insert into public.ai_skills (user_id, name, slug, description, instruction, input_schema, is_system)
values
(null, 'Internet Research', 'internet_research', 'Use web search/fetch for current external information.', 'Use web_search for current, niche, or external public facts. Use web_fetch when the user provides a specific URL. Cite or summarize sources in the final answer when available.', '{"type":"object","properties":{"query":{"type":"string"}}}', true),
(null, 'Production Builder', 'production_builder', 'Design and implement production-ready application components.', 'Prefer complete runnable implementations, clear database schemas, secure defaults, and deployment-aware architecture. Avoid placeholders when a real implementation can be provided.', '{"type":"object","properties":{"component":{"type":"string"}}}', true)
on conflict do nothing;
