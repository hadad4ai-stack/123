// Hadad4AI service worker — offline app shell (data calls always go to network).
const CACHE = 'hadad4ai-v1';
const SHELL = [
  './', './index.html', './manifest.json', './icon.svg',
  'https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2',
  'https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js',
  'https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js'
];

self.addEventListener('install', (e) => {
  self.skipWaiting();
  e.waitUntil(caches.open(CACHE).then((c) => Promise.allSettled(SHELL.map((u) => c.add(u)))));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // Never intercept Supabase or HF Space calls — auth/data must stay live.
  if (url.hostname.endsWith('supabase.co') || url.hostname.endsWith('hf.space')) return;
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      // Cache only same-origin assets (avoid bloating storage with huge model files).
      if (res && res.ok && url.origin === location.origin) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      }
      return res;
    }).catch(() => caches.match('./index.html')))
  );
});
