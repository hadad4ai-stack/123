# Hadad4AI — Hybrid Agent (iPhone / Safari)

تطبيق ويب هجين يعمل من iPhone عبر Safari:
- **نموذج محلي** داخل المتصفح عبر Transformers.js (WebGPU/WASM) — يعمل بدون إنترنت بعد التحميل.
- **وكيل سحابي** عبر Supabase Edge Function `agent-chat` متصل بـ **OpenRouter** (واجهة OpenAI-compatible) مع أدوات وذاكرة وقاعدة معرفة.

## لماذا GitHub Pages؟

لا يمكن تقديم صفحة HTML قابلة للعرض مباشرة من Supabase Edge Function: بوابة Supabase تفرض
`Content-Type: text/plain` و `Content-Security-Policy: sandbox` على نطاق `*.supabase.co`
(إجراء مكافحة إساءة استخدام)، فيظهر الكود كنص ولا تعمل الـ JavaScript.

الحل: **فصل المعمارية**
- الواجهة (`index.html`) تُستضاف على **GitHub Pages** (تقدّم `text/html` صحيح).
- الخادم يبقى Supabase Edge Function `agent-chat` (يرجع JSON، يعمل بشكل سليم).

## البنية

```
index.html   ← الواجهة (تُخدم عبر GitHub Pages)
   │ supabase-js (auth + جداول ai_*)
   │ functions.invoke('agent-chat')
   ▼
Supabase
   ├─ Auth (بريد/كلمة مرور)
   ├─ Postgres: ai_conversations, ai_messages, ai_memories, ...
   └─ Edge Function: agent-chat ──► OpenRouter (OpenAI-compatible)
```

## التشغيل

### 1) تفعيل GitHub Pages
Settings → Pages → Source: **Deploy from a branch** → Branch: `claude/supabase-mcp-JGyJ4` (أو `main` بعد الدمج) → Folder: `/ (root)` → Save.
الرابط الناتج: `https://hadad4ai-stack.github.io/123/`

### 2) أسرار Supabase (للوكيل السحابي عبر OpenRouter)
Dashboard → Edge Functions → Secrets:

| Name | Value |
|------|-------|
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` |
| `OPENAI_API_KEY`  | مفتاح OpenRouter (`sk-or-v1-...`) |

ثم في التطبيق، خانة "نموذج السحابة" اكتب معرّف نموذج OpenRouter صريحاً مثل `openai/gpt-4o-mini`.

### 3) النموذج المحلي
لا يحتاج أي مفتاح — اختر "نموذج محلي" → "تحميل النموذج المحلي".

## ملاحظات
- مفتاح `anon` العام مضمّن في الواجهة (آمن للنشر؛ الحماية عبر RLS).
- OpenRouter لا يوفّر embeddings؛ سيستخدم البحث النصي الاحتياطي تلقائياً في `knowledge_search`.

## الخادم (Supabase) — محفوظ في المستودع
كامل خادم Supabase موثّق ومحفوظ الآن في `supabase/`:
- `supabase/functions/*` — كل دوال الحافة (`agent-chat`, `tool-proxy`, `structural_blocker`, `artifact-api`, `artifact-studio`، + توجيهات قديمة 301).
- `supabase/config.toml` — إعدادات `verify_jwt` لكل دالة.
- `supabase/migrations/README.md` — فهرس الترحيلات (23) وطريقة تصديرها.
- التفاصيل الكاملة (المعمارية، الأدوات، الـ RPCs، الأسرار) في `supabase/README.md`.

## ميزات إضافية في التطبيق
- **Artifacts**: الوكيل (محلي أو سحابي) يبني منتجاً (تطبيق HTML/مستند) ويعرضه فوراً داخل التطبيق في إطار معزول، مع نسخ محفوظة.
- **خادم أدوات HF Space (اختياري)**: ~130 أداة (pdf/docx/xlsx/python/git/data...) عبر ضبط رابط الـ Space ومفتاح API في القائمة.
