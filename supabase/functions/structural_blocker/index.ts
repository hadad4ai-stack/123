import 'jsr:@supabase/functions-js/edge-runtime.d.ts';
import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.45.4';

type Decision = {
  allow: boolean;
  decision: 'ALLOW' | 'DENY';
  reason: string;
  rule_id?: number;
  user_role?: string;
};

type ReqBody = {
  action?: string;   // e.g. 'admin.db.sql', 'admin.edge.deploy', 'chat.use'
  path?: string;     // optional routing hint
  meta?: Record<string, unknown>;
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function safeString(x: unknown, max = 200) {
  if (typeof x !== 'string') return '';
  return x.length > max ? x.slice(0, max) : x;
}

function likeMatch(value: string, pattern?: string | null): boolean {
  if (!pattern) return true;
  // Convert SQL-like % wildcard to RegExp
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp('^' + escaped.replace(/%/g, '.*') + '$', 'i');
  return re.test(value);
}

async function getUserIdFromJwt(supabaseAnon: ReturnType<typeof createClient>, req: Request): Promise<string | null> {
  const authHeader = req.headers.get('Authorization') ?? '';
  const { data, error } = await supabaseAnon.auth.getUser(authHeader);
  if (error || !data?.user?.id) return null;
  return data.user.id;
}

Deno.serve(async (req: Request) => {
  const requestId = crypto.randomUUID();

  // Env
  const SUPABASE_URL = Deno.env.get('SUPABASE_URL');
  const SUPABASE_ANON_KEY = Deno.env.get('SUPABASE_ANON_KEY');
  const SUPABASE_SERVICE_ROLE_KEY = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY');
  const BOOTSTRAP_TOKEN = Deno.env.get('STRUCTURAL_BOOTSTRAP_TOKEN');

  if (!SUPABASE_URL || !SUPABASE_ANON_KEY || !SUPABASE_SERVICE_ROLE_KEY) {
    return json(500, {
      request_id: requestId,
      error: 'Missing required environment variables for Structural Blocker',
      required: ['SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY'],
    });
  }

  // Clients
  const supabaseAnon = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
    global: { headers: { Authorization: req.headers.get('Authorization') ?? '' } },
  });
  const supabaseSvc = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);

  // Parse request
  let body: ReqBody = {};
  if (req.method !== 'GET') {
    try {
      body = (await req.json()) as ReqBody;
    } catch {
      body = {};
    }
  }

  const action = safeString(body.action ?? '', 200) || 'unknown';
  const path = safeString(body.path ?? new URL(req.url).pathname, 200);

  // Optional bootstrap endpoint (one-time) to set the caller as ROOT.
  // You MUST set STRUCTURAL_BOOTSTRAP_TOKEN in Edge Function env; otherwise bootstrap is disabled.
  if (path === '/bootstrap_root') {
    if (!BOOTSTRAP_TOKEN) {
      return json(403, { request_id: requestId, allow: false, decision: 'DENY', reason: 'Bootstrap disabled' });
    }
    const token = req.headers.get('X-Bootstrap-Token') ?? '';
    if (token !== BOOTSTRAP_TOKEN) {
      return json(403, { request_id: requestId, allow: false, decision: 'DENY', reason: 'Invalid bootstrap token' });
    }
    const userId = await getUserIdFromJwt(supabaseAnon, req);
    if (!userId) {
      return json(401, { request_id: requestId, allow: false, decision: 'DENY', reason: 'Unauthenticated' });
    }

    const { count } = await supabaseSvc
      .from('internal.app_roles')
      .select('*', { count: 'exact', head: true });

    if ((count ?? 0) > 0) {
      return json(409, { request_id: requestId, allow: false, decision: 'DENY', reason: 'Roles already initialized' });
    }

    await supabaseSvc.from('internal.app_roles').upsert({ user_id: userId, role: 'ROOT' });

    return json(200, { request_id: requestId, allow: true, decision: 'ALLOW', reason: 'BOOTSTRAP_OK', role: 'ROOT' });
  }

  // Determine user
  const userId = await getUserIdFromJwt(supabaseAnon, req);

  // Default role
  let userRole = 'STUDENT';
  if (userId) {
    const { data: roleRow } = await supabaseSvc
      .from('internal.app_roles')
      .select('role')
      .eq('user_id', userId)
      .maybeSingle();
    if (roleRow?.role) userRole = roleRow.role;
  }

  // Hard structural denies (cheap, immediate)
  const hardDenyNeedles = [
    'system prompt', 'system_prompt', 'hidden prompt', 'reveal prompt',
    'service_role', 'anon_key', 'jwt secret', 'apikey', 'api key', 'password',
    'privilege escalation', 'root', 'sudo', 'break sandbox', 'bypass',
  ];
  const hay = (action + ' ' + JSON.stringify(body.meta ?? {})).toLowerCase();
  const hit = hardDenyNeedles.find(n => hay.includes(n));
  if (hit) {
    const decision: Decision = { allow: false, decision: 'DENY', reason: `Hard deny matched: ${hit}`, user_role: userRole };
    await supabaseSvc.from('internal.policy_decisions').insert({
      request_id: requestId,
      user_id: userId,
      user_role: userRole,
      action,
      path,
      decision: decision.decision,
      rule_id: null,
      reason: decision.reason,
      meta: body.meta ?? {},
    });
    return json(403, { request_id: requestId, ...decision });
  }

  // DB-driven rules
  const { data: rules, error: rulesErr } = await supabaseSvc
    .from('internal.policy_rules')
    .select('id,is_enabled,priority,effect,action_like,role_in,path_like,reason')
    .eq('is_enabled', true)
    .order('priority', { ascending: true });

  if (rulesErr) {
    const decision: Decision = { allow: false, decision: 'DENY', reason: 'Policy engine unavailable', user_role: userRole };
    return json(503, { request_id: requestId, ...decision });
  }

  // First-match-wins. Default = DENY.
  let finalDecision: Decision = { allow: false, decision: 'DENY', reason: 'Default deny', user_role: userRole };

  for (const r of rules ?? []) {
    const roleOk = !r.role_in || (Array.isArray(r.role_in) && r.role_in.includes(userRole));
    if (!roleOk) continue;
    if (!likeMatch(action, r.action_like)) continue;
    if (!likeMatch(path, r.path_like)) continue;

    if (r.effect === 'ALLOW') {
      finalDecision = { allow: true, decision: 'ALLOW', reason: r.reason, rule_id: r.id, user_role: userRole };
      break;
    }
    if (r.effect === 'DENY') {
      finalDecision = { allow: false, decision: 'DENY', reason: r.reason, rule_id: r.id, user_role: userRole };
      break;
    }
  }

  // Audit log (best-effort)
  try {
    await supabaseSvc.from('internal.policy_decisions').insert({
      request_id: requestId,
      user_id: userId,
      user_role: userRole,
      action,
      path,
      decision: finalDecision.decision,
      rule_id: finalDecision.rule_id ?? null,
      reason: finalDecision.reason,
      meta: body.meta ?? {},
    });
  } catch {
    // ignore
  }

  if (!finalDecision.allow) {
    return json(403, { request_id: requestId, ...finalDecision });
  }

  return json(200, {
    request_id: requestId,
    ...finalDecision,
    // Return a compact envelope so the caller can route the request
    routing: { action, path, role: userRole },
  });
});
