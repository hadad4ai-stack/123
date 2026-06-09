import "jsr:@supabase/functions-js/edge-runtime.d.ts";
// Deprecated. Replaced by the GitHub Pages app. Redirect any old links.
const APP = "https://hadad4ai-stack.github.io/123/";
Deno.serve(() => new Response(null, { status: 301, headers: { Location: APP, "Cache-Control": "no-store" } }));
