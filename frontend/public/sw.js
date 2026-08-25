/* S.K. Sharma & Co. PWA service worker.
 *
 * Strategy (deliberately conservative so fresh deploys always show up):
 *   • /api/* and non-GET requests  → network only, NEVER cached.
 *   • navigations (HTML)           → network first WITH A 3.5s TIMEOUT —
 *     if the network is slow/stalled the cached shell opens instantly
 *     (Iter 291: fixes "PWA sometimes won't open" on weak connections).
 *   • static assets (js/css/img)   → stale-while-revalidate.
 */
const CACHE = "sks-pwa-v35"; // Iter 720 — group/roll live counts

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((c) =>
      c.addAll(["/", "/manifest.json", "/icons/icon-192.png", "/icons/icon-512.png"]).catch(() => {}),
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
  // so new deploys are picked up immediately. Iter 291 — a 3.5 second
  // TIMEOUT races the network: on slow/stalled connections the cached
  // shell opens instantly instead of hanging on a white screen (the
  // network fetch still completes in the background and refreshes the
  // cache for the next open).
  if (req.mode === "navigate") {
    const networkFetch = fetch(req, { cache: "no-store" })
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        return res;
      });
    event.respondWith(
      Promise.race([
        networkFetch.catch(() => null),
        new Promise((resolve) => setTimeout(() => resolve(null), 3500)),
      ]).then((res) => {
        if (res) return res;
        // Slow or offline → serve the cached shell immediately; keep the
        // network fetch alive so the cache refreshes for next time.
        return caches.match(req).then((hit) =>
          hit || caches.match("/").then((root) => root || networkFetch),
        );
      }),
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

/* ------------------------------------------------------------------ */
/* Web Push — punch approvals, leave decisions, joining requests.      */
/* ------------------------------------------------------------------ */
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = { body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "S.K. Sharma & Co.";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: data.tag || undefined,
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((list) => {
        for (const c of list) {
          if ("focus" in c) {
            if ("navigate" in c) c.navigate(url).catch(() => {});
            return c.focus();
          }
        }
        return clients.openWindow(url);
      }),
  );
});
