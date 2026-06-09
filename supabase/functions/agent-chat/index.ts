import { createClient } from '@supabase/supabase-js';

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
};

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { ...corsHeaders, 'Content-Type': 'application/json' } });
}
function cleanText(value: unknown, max = 16000): string {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/g, ' ').trim().slice(0, max);
}
function safeParseJson(input: string | null | undefined): Record<string, unknown> {
  if (!input) return {};
  try { const p = JSON.parse(input); return p && typeof p === 'object' && !Array.isArray(p) ? p : {}; } catch { return {}; }
}
function chunkText(text: string, size = 1200, overlap = 160): string[] {
  const t = text.replace(/\r/g, '').replace(/\n{3,}/g, '\n\n').trim();
  const chunks: string[] = []; let i = 0;
  while (i < t.length && chunks.length < 24) { const end = Math.min(i + size, t.length); chunks.push(t.slice(i, end)); if (end >= t.length) break; i = Math.max(0, end - overlap); }
  return chunks;
}

async function openaiJson(path: string, body: Record<string, unknown>) {
  const apiKey = Deno.env.get('OPENAI_API_KEY');
  if (!apiKey) throw new Error('OPENAI_API_KEY is not configured in Supabase Edge Function secrets.');
  const baseUrl = (Deno.env.get('OPENAI_BASE_URL') || 'https://api.openai.com/v1').replace(/\/$/, '');
  const res = await fetch(`${baseUrl}${path}`, { method: 'POST', headers: { 'Authorization': `Bearer ${apiKey}`, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  const text = await res.text();
  let json: any = null; try { json = JSON.parse(text); } catch { json = { raw: text }; }
  if (!res.ok) throw new Error(json?.error?.message || json?.message || text || `OpenAI-compatible API error ${res.status}`);
  return json;
}
async function embed(text: string, model: string): Promise<number[] | null> {
  try { const j = await openaiJson('/embeddings', { model, input: text.slice(0, 8000) }); return j?.data?.[0]?.embedding ?? null; } catch { return null; }
}
async function chatCompletion(model: string, messages: any[], tools: any[], temperature: number) {
  return await openaiJson('/chat/completions', { model, messages, tools: tools.length ? tools : undefined, tool_choice: tools.length ? 'auto' : undefined, temperature });
}

const IMPLEMENTED_DB_TOOLS = new Set(['save_memory', 'list_memories', 'knowledge_search', 'create_knowledge_note', 'web_fetch', 'web_search']);

const ARTIFACT_TOOLS = [
  { type: 'function', function: { name: 'artifact_create', description: 'Create a product/artifact (e.g. an HTML app or a document) the user sees instantly in the app. For html pass a complete HTML document.', parameters: { type: 'object', properties: { title: { type: 'string' }, content: { type: 'string' }, artifact_type: { type: 'string', enum: ['html', 'markdown', 'text', 'json'] } }, required: ['title', 'content'] } } },
  { type: 'function', function: { name: 'artifact_list', description: 'List the user saved artifacts.', parameters: { type: 'object', properties: {} } } },
  { type: 'function', function: { name: 'artifact_preview', description: 'Get an artifact preview by id.', parameters: { type: 'object', properties: { id: { type: 'string' }, version: { type: 'number' } }, required: ['id'] } } },
  { type: 'function', function: { name: 'artifact_update', description: 'Update an artifact content and create a new version.', parameters: { type: 'object', properties: { artifact_id: { type: 'string' }, content: { type: 'string' }, change_summary: { type: 'string' } }, required: ['artifact_id', 'content'] } } },
  { type: 'function', function: { name: 'artifact_publish', description: 'Publish or unpublish an artifact.', parameters: { type: 'object', properties: { artifact_id: { type: 'string' }, published: { type: 'boolean' } }, required: ['artifact_id'] } } },
];

async function executeTool(params: { supabase: any; userId: string; conversationId: string; agentRunId: string; name: string; args: Record<string, unknown>; embeddingModel: string; }) {
  const { supabase, userId, conversationId, agentRunId, name, args, embeddingModel } = params;
  const ins = await supabase.from('ai_tool_runs').insert({ user_id: userId, conversation_id: conversationId, agent_run_id: agentRunId, tool_name: name, arguments: args, status: 'running' }).select('id').single();
  const toolRunId = ins.data?.id;
  async function finish(result: unknown, status = 'completed', error: string | null = null) {
    if (toolRunId) await supabase.from('ai_tool_runs').update({ result: result as any, status, error, completed_at: new Date().toISOString() }).eq('id', toolRunId);
    return result;
  }
  try {
    if (name === 'save_memory') {
      const content = cleanText(args.content, 4000); if (!content) throw new Error('content is required');
      const memoryType = typeof args.memory_type === 'string' ? args.memory_type : 'note';
      const importance = typeof args.importance === 'number' ? Math.min(5, Math.max(1, Math.round(args.importance))) : 3;
      const { data, error } = await supabase.from('ai_memories').insert({ user_id: userId, content, memory_type: memoryType, importance }).select('id, memory_type, content, importance, created_at').single();
      if (error) throw error; return await finish({ saved: true, memory: data });
    }
    if (name === 'list_memories') {
      const limit = typeof args.limit === 'number' ? Math.min(50, Math.max(1, Math.round(args.limit))) : 10;
      let q = supabase.from('ai_memories').select('id, memory_type, content, importance, created_at').eq('user_id', userId).order('importance', { ascending: false }).order('created_at', { ascending: false }).limit(limit);
      if (typeof args.memory_type === 'string') q = q.eq('memory_type', args.memory_type);
      const { data, error } = await q; if (error) throw error; return await finish({ memories: data ?? [] });
    }
    if (name === 'knowledge_search') {
      const query = cleanText(args.query, 2000); if (!query) throw new Error('query is required');
      const matchCount = typeof args.match_count === 'number' ? Math.min(20, Math.max(1, Math.round(args.match_count))) : 8;
      const qe = await embed(query, embeddingModel);
      if (qe) { const { data, error } = await supabase.rpc('match_ai_knowledge', { query_embedding: qe, match_count: matchCount, filter_user_id: userId }); if (error) throw error; return await finish({ results: data ?? [], mode: 'semantic' }); }
      const { data, error } = await supabase.from('ai_knowledge_chunks').select('id, source_id, content, metadata, created_at').eq('user_id', userId).ilike('content', `%${query.split(' ').slice(0, 6).join('%')}%`).limit(matchCount);
      if (error) throw error; return await finish({ results: data ?? [], mode: 'text_fallback' });
    }
    if (name === 'create_knowledge_note') {
      const title = cleanText(args.title, 160) || 'Knowledge note';
      const content = cleanText(args.content, 50000); if (!content) throw new Error('content is required');
      const metadata = args.metadata && typeof args.metadata === 'object' ? args.metadata : {};
      const { data: source, error: se } = await supabase.from('ai_knowledge_sources').insert({ user_id: userId, name: title, source_type: 'note', metadata }).select('id, name').single();
      if (se) throw se;
      const chunks = chunkText(content); let n = 0;
      for (const [index, chunk] of chunks.entries()) { const vector = await embed(chunk, embeddingModel); const { error } = await supabase.from('ai_knowledge_chunks').insert({ user_id: userId, source_id: source.id, content: chunk, embedding: vector, metadata: { ...metadata, chunk_index: index, title } }); if (error) throw error; n++; }
      return await finish({ saved: true, source, chunks: n });
    }
    if (name === 'web_fetch') {
      const url = typeof args.url === 'string' ? args.url : '';
      const { data, error } = await supabase.functions.invoke('tool-proxy', { body: { action: 'web_fetch', url } });
      if (error) throw new Error(error.message || 'web_fetch failed'); return await finish(data);
    }
    if (name === 'web_search') {
      const apiKey = Deno.env.get('TAVILY_API_KEY'); if (!apiKey) throw new Error('TAVILY_API_KEY is not configured. Add it as an Edge Function secret to enable web_search.');
      const query = cleanText(args.query, 1000); if (!query) throw new Error('query is required');
      const maxResults = typeof args.max_results === 'number' ? Math.min(10, Math.max(1, Math.round(args.max_results))) : 5;
      const res = await fetch('https://api.tavily.com/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ api_key: apiKey, query, max_results: maxResults, search_depth: 'basic' }) });
      const json = await res.json(); if (!res.ok) throw new Error(json?.error || `Tavily error ${res.status}`); return await finish({ query, results: json?.results ?? [] });
    }
    if (name === 'artifact_create') {
      const { data, error } = await supabase.rpc('create_ai_artifact', { p_title: cleanText(args.title, 140) || 'Untitled', p_artifact_type: typeof args.artifact_type === 'string' ? args.artifact_type : 'html', p_content: typeof args.content === 'string' ? args.content : '', p_content_format: null, p_conversation_id: conversationId, p_agent_run_id: agentRunId, p_metadata: {} });
      if (error) throw error; return await finish({ artifact_id: data });
    }
    if (name === 'artifact_list') {
      const { data, error } = await supabase.rpc('list_ai_artifacts', { p_limit: 50, p_status: null, p_artifact_type: null });
      if (error) throw error; return await finish({ artifacts: data ?? [] });
    }
    if (name === 'artifact_preview') {
      const { data, error } = await supabase.rpc('preview_ai_artifact', { p_artifact_id: String(args.id ?? args.artifact_id ?? ''), p_version: typeof args.version === 'number' ? args.version : null });
      if (error) throw error; return await finish({ preview: data });
    }
    if (name === 'artifact_update') {
      const { data, error } = await supabase.rpc('update_ai_artifact', { p_artifact_id: String(args.artifact_id ?? ''), p_content: typeof args.content === 'string' ? args.content : '', p_change_summary: cleanText(args.change_summary, 400), p_content_format: null, p_status: null, p_metadata: {} });
      if (error) throw error; return await finish({ version: data });
    }
    if (name === 'artifact_publish') {
      const { data, error } = await supabase.rpc('publish_ai_artifact', { p_artifact_id: String(args.artifact_id ?? ''), p_published: args.published !== false });
      if (error) throw error; return await finish({ published: data });
    }
    throw new Error(`Unknown or disabled tool: ${name}`);
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    return await finish({ error }, 'failed', error);
  }
}

Deno.serve(async (req: Request) => {
  if (req.method === 'OPTIONS') return new Response('ok', { headers: corsHeaders });
  if (req.method !== 'POST') return jsonResponse({ error: 'Method not allowed' }, 405);
  const supabaseUrl = Deno.env.get('SUPABASE_URL'); const anonKey = Deno.env.get('SUPABASE_ANON_KEY');
  if (!supabaseUrl || !anonKey) return jsonResponse({ error: 'Supabase environment is not configured.' }, 500);
  const authHeader = req.headers.get('Authorization') || '';
  const supabase = createClient(supabaseUrl, anonKey, { global: { headers: { Authorization: authHeader } }, auth: { persistSession: false } });
  const { data: authData, error: authError } = await supabase.auth.getUser();
  if (authError || !authData?.user) return jsonResponse({ error: 'Unauthorized' }, 401);
  const userId = authData.user.id;
  let body: any = {}; try { body = await req.json(); } catch { return jsonResponse({ error: 'Invalid JSON body' }, 400); }
  const userMessage = cleanText(body.message, 24000); if (!userMessage) return jsonResponse({ error: 'message is required' }, 400);
  const now = new Date().toISOString();
  const defaultPrompt = await supabase.from('ai_system_prompts').select('id, content').eq('slug', 'maximum_cooperative_production_agent').eq('is_enabled', true).maybeSingle();
  let { data: profile } = await supabase.from('ai_profiles').select('*').eq('user_id', userId).maybeSingle();
  if (!profile) { const i = await supabase.from('ai_profiles').insert({ user_id: userId, display_name: authData.user.email ?? 'User', system_prompt: defaultPrompt.data?.content ?? 'You are a practical, cooperative AI agent.' }).select('*').single(); profile = i.data; }
  let { data: modelConfig } = await supabase.from('ai_model_configs').select('*').eq('user_id', userId).eq('is_default', true).maybeSingle();
  if (!modelConfig) { const i = await supabase.from('ai_model_configs').insert({ user_id: userId, system_prompt_id: defaultPrompt.data?.id ?? null, is_default: true }).select('*').single(); modelConfig = i.data; }
  let conversationId = typeof body.conversation_id === 'string' ? body.conversation_id : null;
  if (!conversationId) { const title = userMessage.slice(0, 70) || 'New conversation'; const { data, error } = await supabase.from('ai_conversations').insert({ user_id: userId, title }).select('id').single(); if (error) return jsonResponse({ error: error.message }, 500); conversationId = data.id; }
  const ar = await supabase.from('ai_agent_runs').insert({ user_id: userId, conversation_id: conversationId, status: 'running', model: body.model || modelConfig?.model || profile?.default_model, input_message: userMessage, metadata: { request_time: now } }).select('id').single();
  const agentRunId = ar.data?.id;
  const uimsg = await supabase.from('ai_messages').insert({ user_id: userId, conversation_id: conversationId, role: 'user', content: userMessage });
  if (uimsg.error) return jsonResponse({ error: uimsg.error.message }, 500);
  try {
    const [{ data: skills }, { data: toolsRows }, { data: memories }, { data: recentMessages }] = await Promise.all([
      supabase.from('ai_skills').select('name, slug, description, instruction').eq('is_enabled', true).order('is_system', { ascending: false }).limit(30),
      supabase.from('ai_tools').select('name, slug, description, json_schema, handler, config').eq('is_enabled', true).limit(60),
      supabase.from('ai_memories').select('memory_type, content, importance').eq('user_id', userId).order('importance', { ascending: false }).order('created_at', { ascending: false }).limit(12),
      supabase.from('ai_messages').select('role, content, created_at').eq('conversation_id', conversationId).in('role', ['user', 'assistant']).order('created_at', { ascending: true }).limit(30),
    ]);
    const selectedPromptContent = defaultPrompt.data?.content || profile?.system_prompt || 'You are a cooperative AI agent.';
    const skillText = (skills ?? []).map((s: any) => `- ${s.name} (${s.slug}): ${s.description}`).join('\n');
    const memoryText = (memories ?? []).map((m: any) => `- [${m.memory_type}/importance:${m.importance}] ${m.content}`).join('\n');
    const system = [
      selectedPromptContent,
      profile?.system_prompt ? `\nUser profile/system preference:\n${profile.system_prompt}` : '',
      skillText ? `\nEnabled skills:\n${skillText}` : '',
      memoryText ? `\nLong-term memories available:\n${memoryText}` : '',
      '\nYou can build products with artifact_create (e.g. a complete HTML app) which the user sees instantly. Use function calling when a tool is useful. Reply in the user language.',
    ].filter(Boolean).join('\n');
    const dbTools = (toolsRows ?? []).filter((t: any) => t.handler === 'edge_builtin' && t.json_schema && t.json_schema.function && IMPLEMENTED_DB_TOOLS.has(t.json_schema.function.name)).map((t: any) => t.json_schema);
    const tools = [...dbTools, ...ARTIFACT_TOOLS];
    const model = String(body.model || modelConfig?.model || Deno.env.get('OPENAI_MODEL') || profile?.default_model || 'gpt-4.1-mini');
    const embeddingModel = String(modelConfig?.embedding_model || Deno.env.get('OPENAI_EMBEDDING_MODEL') || 'text-embedding-3-small');
    const temperature = typeof body.temperature === 'number' ? body.temperature : Number(modelConfig?.temperature ?? 0.3);
    const maxToolIterations = Number(modelConfig?.max_tool_iterations ?? 5);
    const messages: any[] = [{ role: 'system', content: system }];
    for (const m of recentMessages ?? []) if (m.role === 'user' || m.role === 'assistant') messages.push({ role: m.role, content: m.content });
    const calledTools: any[] = []; let finalContent = '';
    for (let iteration = 0; iteration <= maxToolIterations; iteration++) {
      const completion = await chatCompletion(model, messages, modelConfig?.tools_enabled === false ? [] : tools, temperature);
      const assistantMessage = completion?.choices?.[0]?.message;
      if (!assistantMessage) throw new Error('Model returned an empty response.');
      const toolCalls = assistantMessage.tool_calls ?? [];
      if (!toolCalls.length) { finalContent = assistantMessage.content || ''; break; }
      messages.push({ role: 'assistant', content: assistantMessage.content ?? '', tool_calls: toolCalls });
      for (const toolCall of toolCalls) {
        const tname = toolCall?.function?.name; const targs = safeParseJson(toolCall?.function?.arguments);
        const result = await executeTool({ supabase, userId, conversationId, agentRunId, name: tname, args: targs, embeddingModel });
        calledTools.push({ name: tname, arguments: targs, result });
        const resultContent = JSON.stringify(result).slice(0, 18000);
        messages.push({ role: 'tool', tool_call_id: toolCall.id, content: resultContent });
        await supabase.from('ai_messages').insert({ user_id: userId, conversation_id: conversationId, role: 'tool', content: resultContent, tool_name: tname, tool_call_id: toolCall.id });
      }
    }
    if (!finalContent) finalContent = 'تم تنفيذ الأدوات، لكن النموذج لم يرجع إجابة نهائية واضحة.';
    await supabase.from('ai_messages').insert({ user_id: userId, conversation_id: conversationId, role: 'assistant', content: finalContent, metadata: { called_tools: calledTools.map((t) => t.name) } });
    if (agentRunId) await supabase.from('ai_agent_runs').update({ status: 'completed', output_message: finalContent, completed_at: new Date().toISOString(), metadata: { called_tools: calledTools } }).eq('id', agentRunId);
    return jsonResponse({ conversation_id: conversationId, message: finalContent, model, tools_called: calledTools.map((t) => t.name), run_id: agentRunId });
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    if (agentRunId) await supabase.from('ai_agent_runs').update({ status: 'failed', error, completed_at: new Date().toISOString() }).eq('id', agentRunId);
    return jsonResponse({ error }, 500);
  }
});
