/* S.K. Sharma & Co. PWA service worker.
 *
 * Strategy (deliberately conservative so fresh deploys always show up):
 *   • /api/* and non-GET requests  → network only, NEVER cached.
 *   • navigations (HTML)           → network first, cached copy only when offline.
 *   • static assets (js/css/img)   → stale-while-revalidate.
 */
const CACHE = "sks-pwa-v2";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((c) =>
      c.addAll(["/manifest.json", "/icons/icon-192.png", "/icons/icon-512.png"]).catch(() => {}),
    ),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never touch API calls, non-GET requests, or cross-origin requests.
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api")) {
    return;
  }

  // Navigations: network first (BYPASSING the HTTP cache — mobile PWAs
  // otherwise resurrect a stale index.html pointing at an old JS bundle)
  // so new deploys are picked up immediately.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req, { cache: "no-store" })
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((hit) => hit || caches.match("/"))),
    );
    return;
  }

  // Static assets: stale-while-revalidate.
  const isStatic = /\.(js|css|png|jpg|jpeg|webp|svg|ico|woff2?|ttf|json)$/.test(url.pathname);
  if (isStatic) {
    event.respondWith(
      caches.match(req).then((hit) => {
        const refresh = fetch(req)
          .then((res) => {
            if (res && res.ok) {
              const copy = res.clone();
              caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
            }
            return res;
          })
          .catch(() => hit);
        return hit || refresh;
      }),
    );
  }
});
