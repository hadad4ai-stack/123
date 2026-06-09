-- Control plane for Structural Blocker
create schema if not exists internal;

-- Who is admin/root in YOUR app (not Postgres roles)
create table if not exists internal.app_roles (
  user_id uuid primary key,
  role text not null check (role in ('ROOT','ADMIN','DEVELOPER','STUDENT')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Policy rules (deny/allow) stored in DB so you can change without redeploy
create table if not exists internal.policy_rules (
  id bigserial primary key,
  is_enabled boolean not null default true,
  priority int not null default 100,
  effect text not null check (effect in ('DENY','ALLOW')),
  -- simple matching fields
  action_like text,               -- e.g. 'db.%' or 'edge.deploy'
  role_in text[],                 -- e.g. '{ROOT,ADMIN}'
  path_like text,                 -- http path matcher if you use it
  reason text not null,
  created_at timestamptz not null default now()
);

-- Every decision is logged for audit & debugging
create table if not exists internal.policy_decisions (
  id bigserial primary key,
  decided_at timestamptz not null default now(),
  request_id text,
  user_id uuid,
  user_role text,
  action text,
  path text,
  decision text not null check (decision in ('ALLOW','DENY')),
  rule_id bigint,
  reason text,
  meta jsonb
);

-- Utility: keep updated_at fresh
create or replace function internal.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists trg_touch_app_roles on internal.app_roles;
create trigger trg_touch_app_roles
before update on internal.app_roles
for each row execute function internal.touch_updated_at();

-- Seed: ultra-safe default deny rules (you can relax later)
insert into internal.policy_rules (priority,effect,action_like,role_in,reason)
select * from (values
  (10,'DENY','%.system_prompt%', null, 'Block any attempt to access hidden/system prompts'),
  (11,'DENY','%.secrets%',      null, 'Block access to secrets/keys'),
  (12,'DENY','%.privilege%',    null, 'Block privilege escalation attempts'),
  (20,'DENY','admin.%',         array['STUDENT','DEVELOPER'], 'Admin actions require ADMIN/ROOT'),
  (30,'ALLOW','admin.%',        array['ROOT','ADMIN'], 'Admin actions allowed for ADMIN/ROOT'),
  (40,'ALLOW','%.read%',        array['ROOT','ADMIN','DEVELOPER'], 'Read operations allowed for trusted roles')
) v
where not exists (select 1 from internal.policy_rules);

-- RLS: lock down these internal tables from anon users
alter table internal.app_roles enable row level security;
alter table internal.policy_rules enable row level security;
alter table internal.policy_decisions enable row level security;

-- By default: nobody via anon can read/write these.
-- You will access them via service role inside the Edge Function.
create policy "deny_all_app_roles" on internal.app_roles for all using (false) with check (false);
create policy "deny_all_policy_rules" on internal.policy_rules for all using (false) with check (false);
create policy "deny_all_policy_decisions" on internal.policy_decisions for all using (false) with check (false);
