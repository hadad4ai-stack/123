import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
};

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function pageShell(body: string): string {
  return `<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Artifact Studio</title>
<style>
  :root{color-scheme:dark;--bg:#070b14;--panel:#101827;--panel2:#151f32;--text:#f8fafc;--muted:#a7b0c0;--line:#263244;--green:#20d08a;--blue:#60a5fa;--red:#fb7185;--yellow:#fbbf24}
  *{box-sizing:border-box} body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Tahoma,sans-serif;background:radial-gradient(circle at top,#16223a,#070b14 55%);color:var(--text)}
  .wrap{max-width:1180px;margin:0 auto;padding:22px}.top{display:flex;gap:12px;justify-content:space-between;align-items:center;margin-bottom:18px}.brand{display:flex;gap:12px;align-items:center}.logo{width:44px;height:44px;border-radius:15px;background:linear-gradient(135deg,var(--green),var(--blue));box-shadow:0 10px 35px rgba(32,208,138,.22)} h1{margin:0;font-size:25px}.sub{color:var(--muted);font-size:13px;margin-top:3px}.grid{display:grid;grid-template-columns:330px 1fr;gap:16px}.panel{background:rgba(16,24,39,.86);border:1px solid var(--line);border-radius:22px;overflow:hidden;box-shadow:0 18px 55px rgba(0,0,0,.25)}.panel h2{font-size:16px;margin:0;padding:15px 16px;border-bottom:1px solid var(--line)}.list{padding:10px;display:flex;flex-direction:column;gap:8px;max-height:70vh;overflow:auto}.item{display:block;text-decoration:none;color:var(--text);padding:12px;border-radius:16px;background:var(--panel2);border:1px solid transparent}.item:hover,.item.active{border-color:var(--green)}.item b{display:block;font-size:14px}.meta{font-size:12px;color:var(--muted);margin-top:5px}.previewHead{display:flex;justify-content:space-between;gap:10px;align-items:center;padding:14px 16px;border-bottom:1px solid var(--line)}.badge{font-size:12px;border:1px solid var(--line);border-radius:999px;padding:6px 10px;color:var(--muted)}.actions{display:flex;gap:8px;flex-wrap:wrap}.btn{border:0;border-radius:12px;padding:9px 12px;font-weight:800;background:var(--green);color:#052e1f;text-decoration:none;font-size:13px}.btn.secondary{background:#22304a;color:var(--text)}.btn.warn{background:var(--yellow);color:#332300}.canvas{height:70vh;background:white}.canvas iframe{width:100%;height:100%;border:0;background:white}.empty{padding:44px;text-align:center;color:var(--muted)}.code{direction:ltr;text-align:left;white-space:pre-wrap;background:#050814;color:#d1e7ff;padding:18px;margin:0;min-height:300px;overflow:auto}.create{display:grid;gap:10px;padding:14px;border-top:1px solid var(--line)} input,select,textarea{width:100%;background:#08101f;color:var(--text);border:1px solid var(--line);border-radius:13px;padding:11px;font-family:inherit}textarea{min-height:120px;direction:ltr}.small{font-size:12px;color:var(--muted);line-height:1.6}@media(max-width:880px){.grid{grid-template-columns:1fr}.canvas{height:62vh}.top{align-items:flex-start;flex-direction:column}}
</style>
</head>
<body><div class="wrap">${body}</div></body></html>`;
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: corsHeaders });

  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY")!;
  const auth = req.headers.get("Authorization") ?? "";
  const supabase = createClient(supabaseUrl, anonKey, { global: { headers: { Authorization: auth } } });

  const url = new URL(req.url);
  const selected = url.searchParams.get("id");
  const mode = url.searchParams.get("mode") ?? "studio";

  if (req.method === "POST") {
    const form = await req.formData();
    const title = String(form.get("title") ?? "Untitled Artifact").slice(0, 140);
    const artifactType = String(form.get("artifact_type") ?? "html");
    const content = String(form.get("content") ?? "");
    const { data, error } = await supabase.rpc("create_ai_artifact", {
      p_title: title,
      p_artifact_type: artifactType,
      p_content: content,
      p_content_format: artifactType === "html" ? "html" : artifactType === "markdown" ? "markdown" : "plain",
      p_metadata: { source: "artifact-studio-edge" },
    });
    if (error) return new Response(pageShell(`<div class="empty">فشل الإنشاء: ${escapeHtml(error.message)}</div>`), { status: 400, headers: { ...corsHeaders, "Content-Type": "text/html; charset=utf-8" } });
    return Response.redirect(`${url.origin}${url.pathname}?id=${data}`, 303);
  }

  const { data: artifacts, error: listError } = await supabase.rpc("list_ai_artifacts", { p_limit: 50 });
  if (listError) return new Response(pageShell(`<div class="empty">فشل تحميل artifacts: ${escapeHtml(listError.message)}</div>`), { status: 400, headers: { ...corsHeaders, "Content-Type": "text/html; charset=utf-8" } });

  const chosenId = selected || artifacts?.[0]?.id || null;
  let preview: any = null;
  let previewError = "";
  if (chosenId) {
    const res = await supabase.rpc("preview_ai_artifact", { p_artifact_id: chosenId });
    if (res.error) previewError = res.error.message;
    else preview = res.data;
  }

  if (mode === "preview" && preview) {
    return new Response(preview.content, { headers: { ...corsHeaders, "Content-Type": preview.content_format === "html" ? "text/html; charset=utf-8" : "text/plain; charset=utf-8", "Content-Security-Policy": "default-src 'self' 'unsafe-inline' data: blob:; frame-ancestors *" } });
  }

  const listHtml = (artifacts ?? []).map((a: any) => `
    <a class="item ${a.id === chosenId ? "active" : ""}" href="?id=${a.id}">
      <b>${escapeHtml(a.title)}</b>
      <div class="meta">${escapeHtml(a.artifact_type)} · v${a.current_version} · ${escapeHtml(a.status)}</div>
    </a>`).join("") || `<div class="empty">لا توجد artifacts بعد.</div>`;

  const previewHtml = preview ? `
    <div class="previewHead">
      <div><b>${escapeHtml(preview.title)}</b><div class="meta">${escapeHtml(preview.artifact_type)} · version ${preview.version} · sandboxed preview</div></div>
      <div class="actions">
        <span class="badge">${preview.safe_static_scan ? "Static scan OK" : "Sandbox required"}</span>
        <a class="btn secondary" href="?id=${preview.artifact_id}&mode=preview" target="_blank">فتح منفصل</a>
      </div>
    </div>
    <div class="canvas">${preview.content_format === "html" ? `<iframe sandbox="${escapeHtml(preview.sandbox)}" srcdoc="${escapeHtml(preview.content)}"></iframe>` : `<pre class="code">${escapeHtml(preview.content)}</pre>`}</div>
  ` : `<div class="empty">${previewError ? escapeHtml(previewError) : "اختر artifact أو أنشئ واحدًا."}</div>`;

  const body = `
    <div class="top">
      <div class="brand"><div class="logo"></div><div><h1>Artifact Studio</h1><div class="sub">العميل يصنع منتجًا ويراه فورًا داخل التطبيق، بنسخ محفوظة ومعاينة آمنة.</div></div></div>
      <a class="btn warn" href="/functions/v1/artifact-studio">تحديث</a>
    </div>
    <div class="grid">
      <section class="panel"><h2>منتجات العميل</h2><div class="list">${listHtml}</div>
        <form class="create" method="post">
          <div class="small">إنشاء سريع لاختبار التجربة. في التطبيق النهائي سيستدعي الوكيل هذه العملية تلقائيًا.</div>
          <input name="title" placeholder="اسم المنتج" value="تطبيق صغير جديد" />
          <select name="artifact_type"><option value="html">HTML App</option><option value="markdown">Document</option><option value="text">Text</option><option value="json">JSON</option></select>
          <textarea name="content"><!doctype html><html lang="ar" dir="rtl"><meta charset="utf-8"><style>body{font-family:sans-serif;padding:30px;background:#111827;color:white}button{padding:12px;border-radius:12px}</style><h1>منتجي الجديد</h1><p>هذا artifact تم إنشاؤه داخل التطبيق.</p><button>زر تجربة</button></html></textarea>
          <button class="btn" type="submit">إنشاء Artifact</button>
        </form>
      </section>
      <section class="panel">${previewHtml}</section>
    </div>`;

  return new Response(pageShell(body), { headers: { ...corsHeaders, "Content-Type": "text/html; charset=utf-8" } });
});
