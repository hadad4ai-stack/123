import { createClient } from '@supabase/supabase-js';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { ...corsHeaders, 'Content-Type': 'application/json' },
  });
}

// ---- SSRF guard (hardened) ----
function ipv4ToParts(host: string): number[] | null {
  const m = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  if (!m) return null;
  const parts = m.slice(1).map(Number);
  if (parts.some((n) => n > 255)) return null;
  return parts;
}

function isPrivateIpv4(parts: number[]): boolean {
  const [a, b, c] = parts;
  if (a === 0 || a === 10 || a === 127) return true;
  if (a === 169 && b === 254) return true;
  if (a === 172 && b >= 16 && b <= 31) return true;
  if (a === 192 && b === 168) return true;
  if (a === 192 && b === 0 && c === 0) return true;
  if (a === 100 && b >= 64 && b <= 127) return true;
  if (a === 198 && (b === 18 || b === 19)) return true;
  if (a >= 224) return true;
  return false;
}

function isPrivateIpv6(input: string): boolean {
  let h = input.toLowerCase();
  if (h.startsWith('[') && h.endsWith(']')) h = h.slice(1, -1);
  if (h === '::1' || h === '::') return true;
  const mapped = h.match(/(?:::ffff:|64:ff9b::)([0-9a-f.:]+)$/);
  if (mapped) {
    const tail = mapped[1];
    const v4 = ipv4ToParts(tail);
    if (v4) return isPrivateIpv4(v4);
    const hx = tail.match(/^([0-9a-f]{1,4}):([0-9a-f]{1,4})$/);
    if (hx) {
      const hi = parseInt(hx[1], 16), lo = parseInt(hx[2], 16);
      return isPrivateIpv4([(hi >> 8) & 255, hi & 255, (lo >> 8) & 255, lo & 255]);
    }
  }
  if (h.startsWith('fc') || h.startsWith('fd')) return true;
  if (/^fe[89ab]/.test(h)) return true;
  return false;
}

async function assertPublicUrl(raw: string): Promise<void> {
  let url: URL;
  try { url = new URL(raw); } catch { throw new Error('Invalid URL'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Only public http/https URLs are allowed.');
  const host = url.hostname.toLowerCase();
  if (!host || host === 'localhost' || host.endsWith('.local') || host.endsWith('.internal') || host === 'metadata.google.internal') {
    throw new Error('URL host is blocked.');
  }
  if (host.startsWith('[')) {
    if (isPrivateIpv6(host)) throw new Error('URL resolves to a blocked address.');
    return;
  }
  const literal = ipv4ToParts(host);
  if (literal) {
    if (isPrivateIpv4(literal)) throw new Error('URL resolves to a blocked address.');
    return;
  }
  if (typeof (Deno as any).resolveDns === 'function') {
    const ips: string[] = [];
    try {
      const settled = await Promise.allSettled([
        (Deno as any).resolveDns(host, 'A'),
        (Deno as any).resolveDns(host, 'AAAA'),
      ]);
      for (const s of settled) if (s.status === 'fulfilled' && Array.isArray(s.value)) ips.push(...s.value);
    } catch (_e) { /* resolution unsupported or failed; do not hard-fail */ }
    for (const ip of ips) {
      const bad = ip.includes(':')
        ? isPrivateIpv6(ip)
        : (() => { const p = ipv4ToParts(ip); return !p || isPrivateIpv4(p); })();
      if (bad) throw new Error('URL resolves to a blocked address.');
    }
  }
}

async function guardedFetchText(raw: string, maxBytes = 12000, timeoutMs = 8000) {
  await assertPublicUrl(raw);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(raw, {
      headers: { 'User-Agent': 'Hadad4AI-Agent/1.0' },
      redirect: 'manual',
      signal: ctrl.signal,
    });
    if ((res as any).type === 'opaqueredirect' || (res.status >= 300 && res.status < 400)) {
      throw new Error('Redirects are not followed for safety. Provide the final URL directly.');
    }
    const reader = res.body?.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    const budget = maxBytes * 4;
    if (reader) {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (value) {
          chunks.push(value);
          total += value.length;
          if (total >= budget) { try { await reader.cancel(); } catch (_e) {} break; }
        }
      }
    }
    const merged = new Uint8Array(total);
    let pos = 0;
    for (const c of chunks) { merged.set(c, pos); pos += c.length; }
    const text = new TextDecoder().decode(merged)
      .replace(/<script[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style[\s\S]*?<\/style>/gi, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, maxBytes);
    return { url: raw, status: res.status, ok: res.ok, text };
  } finally {
    clearTimeout(timer);
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });
  if (req.method !== 'POST') return json({ error: 'Method not allowed' }, 405);

  const supabaseUrl = Deno.env.get('SUPABASE_URL');
  const anonKey = Deno.env.get('SUPABASE_ANON_KEY');
  if (!supabaseUrl || !anonKey) return json({ error: 'Supabase env not configured' }, 500);

  const authHeader = req.headers.get('Authorization') || '';
  const supabase = createClient(supabaseUrl, anonKey, {
    global: { headers: { Authorization: authHeader } },
    auth: { persistSession: false },
  });
  const { data: authData, error: authError } = await supabase.auth.getUser();
  if (authError || !authData?.user) return json({ error: 'Unauthorized' }, 401);

  let body: any = {};
  try { body = await req.json(); } catch { return json({ error: 'Invalid JSON' }, 400); }

  const action = String(body.action || 'web_fetch');

  if (action === 'web_fetch') {
    const url = typeof body.url === 'string' ? body.url : '';
    try {
      const out = await guardedFetchText(url, 12000, 8000);
      return json(out);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const blocked = /blocked|invalid|http\/https|redirect|resolve/i.test(msg);
      return json({ error: msg }, blocked ? 400 : 502);
    }
  }

  return json({ error: `Unknown action: ${action}` }, 400);
});
