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
              // globally for the /get-app screen to use later.
              window.addEventListener('beforeinstallprompt', function (e) {
                e.preventDefault();
                window.__pwaInstallEvt = e;
                window.dispatchEvent(new Event('pwa-install-ready'));
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
        {children}
      </body>
    </html>
  );
}
