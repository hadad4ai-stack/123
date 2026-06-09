create extension if not exists vector;
create extension if not exists pgcrypto;

create table if not exists public.ai_profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  display_name text,
  default_model text not null default 'gpt-4.1-mini',
  system_prompt text not null default 'You are a practical AI agent. Use tools only when useful. Be accurate, safe, and concise.',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id)
);

create table if not exists public.ai_conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  title text not null default 'New conversation',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ai_messages (
  id uuid primary key default gen_random_uuid(),
  conversation_id uuid not null references public.ai_conversations(id) on delete cascade,
  user_id uuid not null,
  role text not null check (role in ('system','user','assistant','tool')),
  content text not null,
  tool_name text,
  tool_call_id text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.ai_skills (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  name text not null,
  slug text not null,
  description text not null,
  instruction text not null,
  input_schema jsonb not null default '{}'::jsonb,
  is_enabled boolean not null default true,
  is_system boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, slug)
);

create table if not exists public.ai_tools (
  id uuid primary key default gen_random_uuid(),
  user_id uuid,
  name text not null,
  slug text not null,
  description text not null,
  json_schema jsonb not null,
  handler text not null check (handler in ('edge_builtin','http_webhook','sql_rpc')),
  config jsonb not null default '{}'::jsonb,
  is_enabled boolean not null default true,
  is_system boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(user_id, slug)
);

create table if not exists public.ai_knowledge_sources (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  name text not null,
  source_type text not null default 'manual' check (source_type in ('manual','file','url','note')),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.ai_knowledge_chunks (
  id uuid primary key default gen_random_uuid(),
  source_id uuid not null references public.ai_knowledge_sources(id) on delete cascade,
  user_id uuid not null,
  content text not null,
  embedding vector(1536),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.ai_memories (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null,
  memory_type text not null default 'fact' check (memory_type in ('fact','preference','project','task','note')),
  content text not null,
  importance int not null default 3 check (importance between 1 and 5),
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists ai_messages_conversation_created_idx on public.ai_messages(conversation_id, created_at);
create index if not exists ai_conversations_user_updated_idx on public.ai_conversations(user_id, updated_at desc);
create index if not exists ai_memories_user_type_idx on public.ai_memories(user_id, memory_type);
create index if not exists ai_knowledge_chunks_user_idx on public.ai_knowledge_chunks(user_id);
create index if not exists ai_knowledge_chunks_embedding_idx on public.ai_knowledge_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

alter table public.ai_profiles enable row level security;
alter table public.ai_conversations enable row level security;
alter table public.ai_messages enable row level security;
alter table public.ai_skills enable row level security;
alter table public.ai_tools enable row level security;
alter table public.ai_knowledge_sources enable row level security;
alter table public.ai_knowledge_chunks enable row level security;
alter table public.ai_memories enable row level security;

create policy ai_profiles_owner_all on public.ai_profiles for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ai_conversations_owner_all on public.ai_conversations for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ai_messages_owner_all on public.ai_messages for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ai_skills_read on public.ai_skills for select using (is_system = true or auth.uid() = user_id);
create policy ai_skills_owner_write on public.ai_skills for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ai_tools_read on public.ai_tools for select using (is_system = true or auth.uid() = user_id);
create policy ai_tools_owner_write on public.ai_tools for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ai_knowledge_sources_owner_all on public.ai_knowledge_sources for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ai_knowledge_chunks_owner_all on public.ai_knowledge_chunks for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy ai_memories_owner_all on public.ai_memories for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create or replace function public.match_ai_knowledge(
  query_embedding vector(1536),
  match_count int default 8,
  filter_user_id uuid default auth.uid()
)
returns table (
  id uuid,
  source_id uuid,
  content text,
  metadata jsonb,
  similarity float
)
language sql stable security invoker as $$
  select
    kc.id,
    kc.source_id,
    kc.content,
    kc.metadata,
    1 - (kc.embedding <=> query_embedding) as similarity
  from public.ai_knowledge_chunks kc
  where kc.user_id = filter_user_id and kc.embedding is not null
  order by kc.embedding <=> query_embedding
  limit match_count;
$$;

insert into public.ai_skills (user_id, name, slug, description, instruction, input_schema, is_system)
values
(null, 'Planning', 'planning', 'Break complex goals into safe executable steps.', 'Analyze the user goal, identify missing context, choose tools, execute step by step, and summarize results.', '{"type":"object","properties":{"goal":{"type":"string"}},"required":["goal"]}', true),
(null, 'Knowledge Retrieval', 'knowledge_retrieval', 'Search private knowledge before answering project-specific questions.', 'Use the knowledge_search tool when the answer may exist in user documents or saved notes.', '{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}', true),
(null, 'Memory', 'memory', 'Store and use durable user/project memories.', 'Save stable preferences, project facts, and important decisions. Do not save sensitive secrets.', '{"type":"object","properties":{"content":{"type":"string"},"memory_type":{"type":"string"}}}', true),
(null, 'File Analysis', 'file_analysis', 'Analyze uploaded files and extract structured knowledge.', 'Extract clean text, split into chunks, summarize, and store useful knowledge with source metadata.', '{"type":"object","properties":{"file_id":{"type":"string"}}}', true),
(null, 'Function Calling', 'function_calling', 'Select and call tools using JSON schemas.', 'When a tool is needed, emit a valid function call matching the tool schema. Never invent tool results.', '{"type":"object","properties":{"tool":{"type":"string"},"arguments":{"type":"object"}}}', true)
on conflict (user_id, slug) do nothing;

insert into public.ai_tools (user_id, name, slug, description, json_schema, handler, config, is_system)
values
(null, 'knowledge_search', 'knowledge_search', 'Search user knowledge chunks using semantic embeddings.', '{"type":"function","function":{"name":"knowledge_search","description":"Search saved private knowledge for relevant context.","parameters":{"type":"object","properties":{"query":{"type":"string"},"match_count":{"type":"integer","minimum":1,"maximum":20}},"required":["query"]}}}', 'edge_builtin', '{"requires_embedding":true}', true),
(null, 'save_memory', 'save_memory', 'Save a stable user or project memory.', '{"type":"function","function":{"name":"save_memory","description":"Save a durable memory. Do not store passwords, tokens, or secrets.","parameters":{"type":"object","properties":{"content":{"type":"string"},"memory_type":{"type":"string","enum":["fact","preference","project","task","note"]},"importance":{"type":"integer","minimum":1,"maximum":5}},"required":["content"]}}}', 'edge_builtin', '{}', true),
(null, 'list_memories', 'list_memories', 'List saved memories for context.', '{"type":"function","function":{"name":"list_memories","description":"List relevant saved memories.","parameters":{"type":"object","properties":{"memory_type":{"type":"string","enum":["fact","preference","project","task","note"]},"limit":{"type":"integer","minimum":1,"maximum":50}}}}}', 'edge_builtin', '{}', true),
(null, 'web_fetch', 'web_fetch', 'Fetch a public URL for browsing or extraction.', '{"type":"function","function":{"name":"web_fetch","description":"Fetch a public URL and return text. Use only for URLs provided by the user or allowed public pages.","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}}', 'edge_builtin', '{}', true)
on conflict (user_id, slug) do nothing;
