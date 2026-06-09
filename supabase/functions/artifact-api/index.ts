import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

const headers = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Content-Type": "application/json; charset=utf-8",
};

function json(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), { status, headers });
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers });

  const supabaseUrl = Deno.env.get("SUPABASE_URL")!;
  const anonKey = Deno.env.get("SUPABASE_ANON_KEY")!;
  const auth = req.headers.get("Authorization") ?? "";
  const supabase = createClient(supabaseUrl, anonKey, { global: { headers: { Authorization: auth } } });

  const url = new URL(req.url);
  const action = url.searchParams.get("action") ?? "list";

  try {
    if (req.method === "GET" && action === "list") {
      const limit = Number(url.searchParams.get("limit") ?? "50");
      const statusFilter = url.searchParams.get("status");
      const typeFilter = url.searchParams.get("type");
      const { data, error } = await supabase.rpc("list_ai_artifacts", {
        p_limit: limit,
        p_status: statusFilter,
        p_artifact_type: typeFilter,
      });
      if (error) return json({ ok: false, error: error.message }, 400);
      return json({ ok: true, artifacts: data ?? [] });
    }

    if (req.method === "GET" && action === "read") {
      const id = url.searchParams.get("id");
      const versionParam = url.searchParams.get("version");
      if (!id) return json({ ok: false, error: "missing_artifact_id" }, 400);
      const { data, error } = await supabase.rpc("read_ai_artifact", {
        p_artifact_id: id,
        p_version: versionParam ? Number(versionParam) : null,
      });
      if (error) return json({ ok: false, error: error.message }, 400);
      return json({ ok: true, artifact: data?.[0] ?? null });
    }

    if (req.method === "GET" && action === "preview") {
      const id = url.searchParams.get("id");
      const versionParam = url.searchParams.get("version");
      if (!id) return json({ ok: false, error: "missing_artifact_id" }, 400);
      const { data, error } = await supabase.rpc("preview_ai_artifact", {
        p_artifact_id: id,
        p_version: versionParam ? Number(versionParam) : null,
      });
      if (error) return json({ ok: false, error: error.message }, 400);
      return json({ ok: true, preview: data });
    }

    if (req.method === "POST" && action === "create") {
      const body = await req.json();
      const { data, error } = await supabase.rpc("create_ai_artifact", {
        p_title: body.title,
        p_artifact_type: body.artifact_type ?? "html",
        p_content: body.content,
        p_content_format: body.content_format ?? null,
        p_conversation_id: body.conversation_id ?? null,
        p_agent_run_id: body.agent_run_id ?? null,
        p_metadata: body.metadata ?? {},
      });
      if (error) return json({ ok: false, error: error.message }, 400);
      await supabase.rpc("log_ai_tool_run", {
        p_tool_name: "artifact.create",
        p_arguments: body,
        p_result: { artifact_id: data },
        p_status: "completed",
      });
      return json({ ok: true, artifact_id: data });
    }

    if (req.method === "POST" && action === "update") {
      const body = await req.json();
      const { data, error } = await supabase.rpc("update_ai_artifact", {
        p_artifact_id: body.artifact_id,
        p_content: body.content,
        p_change_summary: body.change_summary ?? "",
        p_content_format: body.content_format ?? null,
        p_status: body.status ?? null,
        p_metadata: body.metadata ?? {},
      });
      if (error) return json({ ok: false, error: error.message }, 400);
      await supabase.rpc("log_ai_tool_run", {
        p_tool_name: "artifact.update",
        p_arguments: body,
        p_result: { version: data },
        p_status: "completed",
      });
      return json({ ok: true, version: data });
    }

    if (req.method === "POST" && action === "publish") {
      const body = await req.json();
      const { data, error } = await supabase.rpc("publish_ai_artifact", {
        p_artifact_id: body.artifact_id,
        p_published: body.published ?? true,
      });
      if (error) return json({ ok: false, error: error.message }, 400);
      await supabase.rpc("log_ai_tool_run", {
        p_tool_name: "artifact.publish",
        p_arguments: body,
        p_result: { published: data },
        p_status: "completed",
      });
      return json({ ok: true, published: data });
    }

    return json({ ok: false, error: "unknown_action" }, 404);
  } catch (error) {
    return json({ ok: false, error: error instanceof Error ? error.message : String(error) }, 500);
  }
});
