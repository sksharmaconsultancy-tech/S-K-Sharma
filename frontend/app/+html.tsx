// @ts-nocheck
import { ScrollViewStyleReset } from "expo-router/html";
import type { PropsWithChildren } from "react";

export default function Root({ children }: PropsWithChildren) {
  return (
    <html lang="en" style={{ height: "100%" }}>
      <head>
        <meta charSet="utf-8" />
        <meta httpEquiv="X-UA-Compatible" content="IE=edge" />
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, shrink-to-fit=no, viewport-fit=cover"
        />
        {/*
          Disable body scrolling on web to make ScrollView components work correctly.
          If you want to enable scrolling, remove `ScrollViewStyleReset` and
          set `overflow: auto` on the body style below.
        */}
        <ScrollViewStyleReset />
        {/* PWA: installable web app (manifest + iOS meta + service worker).
            The manifest is chosen SYNCHRONOUSLY from the URL path so that
            /employee and /employer install as two SEPARATE home-screen apps
            (Chrome reads the manifest at parse time — swapping it later in
            React is too late). */}
        <meta name="theme-color" content="#0F2E3D" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <link rel="apple-touch-icon" href="/icons/icon-192.png" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function () {
                var p = window.location.pathname || "/";
                var q = window.location.search || "";
                var manifest = "/manifest.json";
                var title = "SK Sharma";
                if (p.indexOf("/employee") === 0 || p.indexOf("/pin-login") === 0 ||
                    (p.indexOf("/get-app") === 0 && q.indexOf("type=employer") === -1)) {
                  manifest = "/manifest-employee.json";
                  title = "SKS Employee";
                } else if (p.indexOf("/employer") === 0 || p.indexOf("/admin-pin-login") === 0 ||
                    p.indexOf("/company-login") === 0 || p.indexOf("/company-register") === 0 ||
                    (p.indexOf("/get-app") === 0 && q.indexOf("type=employer") !== -1)) {
                  manifest = "/manifest-employer.json";
                  title = "SKS Employer";
                }
                var link = document.createElement("link");
                link.rel = "manifest";
                link.href = manifest;
                document.head.appendChild(link);
                var meta = document.createElement("meta");
                meta.name = "apple-mobile-web-app-title";
                meta.content = title;
                document.head.appendChild(meta);
              })();
            `,
          }}
        />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              // Capture the PWA install prompt EARLY — Chrome fires
              // 'beforeinstallprompt' before React mounts, so we stash it
              // globally on __pwaInstallEvent (the SAME name promptInstall()
              // in src/utils/pwa.ts reads — a mismatch here silently breaks
              // the Install button). __pwaInstallHooked stops setupPWA()
              // from adding duplicate listeners later.
              window.__pwaInstallHooked = true;
              window.addEventListener('beforeinstallprompt', function (e) {
                e.preventDefault();
                window.__pwaInstallEvent = e;
                window.dispatchEvent(new Event('pwa-installable'));
              });
              window.addEventListener('appinstalled', function () {
                window.__pwaInstallEvent = null;
                window.dispatchEvent(new Event('pwa-installed'));
              });
              // User directive — no pinch/double-tap zoom in the mobile PWA;
              // the app always renders at screen size. (iOS ignores
              // user-scalable=no, so gestures are blocked here too.)
              document.addEventListener('gesturestart', function (e) { e.preventDefault(); }, { passive: false });
              document.addEventListener('gesturechange', function (e) { e.preventDefault(); }, { passive: false });
              var __lastTouchEnd = 0;
              document.addEventListener('touchend', function (e) {
                var now = Date.now();
                if (now - __lastTouchEnd <= 300) { e.preventDefault(); }
                __lastTouchEnd = now;
              }, { passive: false });
              document.addEventListener('wheel', function (e) {
                if (e.ctrlKey) { e.preventDefault(); }
              }, { passive: false });
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function () {
                  navigator.serviceWorker.register('/sw.js').catch(function () {});
                });
              }
              // Iter 511 — BLANK-PAGE SELF-HEAL. If the app fails to boot
              // (stale service-worker shell pointing at a deleted JS bundle,
              // or a half-deployed build), automatically unregister the SW,
              // purge all caches and reload ONCE — no manual cache clearing
              // needed on any device. Max 2 attempts per session to avoid
              // reload loops.
              (function () {
                var KEY = 'sks-selfheal-count';
                var healed = false;
                function heal() {
                  if (healed) return;
                  healed = true;
                  var n = 0;
                  try { n = parseInt(sessionStorage.getItem(KEY) || '0', 10); } catch (e) {}
                  if (n >= 2) return;
                  try { sessionStorage.setItem(KEY, String(n + 1)); } catch (e) {}
                  var reloaded = false;
                  var done = function () {
                    if (reloaded) return;
                    reloaded = true;
                    var u = window.location.pathname + window.location.search;
                    window.location.replace(u + (u.indexOf('?') === -1 ? '?' : '&') + 'skshl=' + Date.now());
                  };
                  var ps = [];
                  try {
                    if ('serviceWorker' in navigator) {
                      ps.push(navigator.serviceWorker.getRegistrations().then(function (rs) {
                        return Promise.all(rs.map(function (r) { return r.unregister(); }));
                      }).catch(function () {}));
                    }
                    if (window.caches && caches.keys) {
                      ps.push(caches.keys().then(function (ks) {
                        return Promise.all(ks.map(function (k) { return caches.delete(k); }));
                      }).catch(function () {}));
                    }
                  } catch (e) {}
                  Promise.all(ps).then(done, done);
                  setTimeout(done, 3000);
                }
                // Entry JS bundle 404/failed → heal immediately.
                window.addEventListener('error', function (e) {
                  var t = e && e.target;
                  if (t && t.tagName === 'SCRIPT' && t.src) heal();
                }, true);
                // App never mounted (splash still up after 15s) → heal.
                window.addEventListener('load', function () {
                  setTimeout(function () {
                    var s = document.getElementById('sks-splash');
                    if (s && s.parentNode) heal();
                  }, 15000);
                });
                // App booted fine → reset the heal counter.
                var okTimer = setInterval(function () {
                  var s = document.getElementById('sks-splash');
                  if (!s || !s.parentNode) {
                    try { sessionStorage.removeItem(KEY); } catch (e) {}
                    clearInterval(okTimer);
                  }
                }, 2000);
              })();
            `,
          }}
        />
        <style
          dangerouslySetInnerHTML={{
            __html: `
              body > div:first-child { position: fixed !important; top: 0; left: 0; right: 0; bottom: 0; }
              [role="tablist"] [role="tab"] * { overflow: visible !important; }
              [role="heading"], [role="heading"] * { overflow: visible !important; }
              /* No pinch-zoom — app renders at screen size (user directive) */
              html, body { touch-action: pan-x pan-y; }
              /* 16px inputs stop iOS Safari auto-zoom on focus (mobile only) */
              @media (pointer: coarse) {
                input, textarea, select { font-size: 16px !important; }
              }
              /* Iter 312 — app-shell splash while the first JS chunk loads */
              #sks-splash {
                position: fixed; inset: 0; z-index: 99999;
                display: flex; flex-direction: column; align-items: center;
                justify-content: center; background: #0F2E3D;
                transition: opacity .3s ease;
              }
              #sks-splash .t { color: #fff; font: 700 22px/1.3 -apple-system, "Segoe UI", Roboto, sans-serif; letter-spacing: .3px; }
              #sks-splash .s { color: #9DB8C6; font: 400 12.5px/1.4 -apple-system, "Segoe UI", Roboto, sans-serif; margin-top: 6px; }
              #sks-splash .bar { width: 180px; height: 4px; border-radius: 999px; background: rgba(255,255,255,.14); overflow: hidden; margin-top: 20px; }
              #sks-splash .fill { width: 40%; height: 100%; border-radius: 999px; background: #4FC3F7; animation: sksload 1.1s ease-in-out infinite; }
              @keyframes sksload { 0% { transform: translateX(-100%); } 100% { transform: translateX(320%); } }
            `,
          }}
        />
      </head>
      <body
        style={{
          margin: 0,
          height: "100%",
          overflow: "hidden",
          display: "flex",
          flexDirection: "column",
        }}
      >
        {/* Iter 312 — app-shell splash: paints INSTANTLY from the cached
            HTML while the first JS chunk downloads/parses on slow
            networks. Removed by RootLayout's mount effect. */}
        <div id="sks-splash">
          <div className="t">S.K. Sharma &amp; Co.</div>
          <div className="s">Loading your workspace…</div>
          <div className="bar"><div className="fill" /></div>
        </div>
        {children}
      </body>
    </html>
  );
}
