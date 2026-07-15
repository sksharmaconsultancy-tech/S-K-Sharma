#!/usr/bin/env node
/**
 * Post-export PWA injection — `web.output: "single"` ignores app/+html.tsx,
 * so `npx expo export -p web` produces a bare index.html without the
 * manifest link, Apple meta tags or the early beforeinstallprompt capture.
 * Run this AFTER every export:  node scripts/inject-pwa-html.js
 */
const fs = require("fs");
const path = require("path");

const file = path.join(__dirname, "..", "dist", "index.html");
let html = fs.readFileSync(file, "utf8");

if (html.includes("__pwaInstallHooked")) {
  console.log("inject-pwa-html: already injected — skipping");
  process.exit(0);
}

// Lock the viewport (no pinch-zoom) + iOS safe-area support.
html = html.replace(
  /<meta name="viewport"[^>]*\/?>/,
  '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, shrink-to-fit=no, viewport-fit=cover" />',
);

const head = `
    <meta name="theme-color" content="#0F2E3D" />
    <meta name="mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
    <link rel="apple-touch-icon" href="/icons/icon-192.png" />
    <script>
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

        // Capture Chrome's one-time install prompt BEFORE React mounts.
        // Names MUST match src/utils/pwa.ts (promptInstall/canInstallNow).
        window.__pwaInstallHooked = true;
        window.addEventListener("beforeinstallprompt", function (e) {
          e.preventDefault();
          window.__pwaInstallEvent = e;
          window.dispatchEvent(new Event("pwa-installable"));
        });
        window.addEventListener("appinstalled", function () {
          window.__pwaInstallEvent = null;
          window.dispatchEvent(new Event("pwa-installed"));
        });
        if ("serviceWorker" in navigator) {
          window.addEventListener("load", function () {
            navigator.serviceWorker.register("/sw.js").then(function (reg) {
              // Auto-update flow for installed PWAs: check for a new
              // service worker every time the app is opened/resumed,
              // and reload ONCE when the new version takes control.
              function check() { try { reg.update(); } catch (e) {} }
              document.addEventListener("visibilitychange", function () {
                if (document.visibilityState === "visible") check();
              });
              setInterval(check, 15 * 60 * 1000);
              var reloaded = false;
              navigator.serviceWorker.addEventListener("controllerchange", function () {
                if (reloaded) return;
                reloaded = true;
                window.location.reload();
              });
            }).catch(function () {});
          });
        }
      })();
    </script>
  </head>`;

html = html.replace("</head>", head);
fs.writeFileSync(file, html);
console.log("inject-pwa-html: PWA tags + install hook injected into dist/index.html");

// Stamp the exported service worker with a unique build id so EVERY deploy
// produces a byte-different sw.js → browsers install the new SW → the
// controllerchange hook above reloads open/installed PWAs automatically.
const swFile = path.join(__dirname, "..", "dist", "sw.js");
if (fs.existsSync(swFile)) {
  const sw = fs.readFileSync(swFile, "utf8");
  fs.writeFileSync(swFile, "/* build:" + Date.now() + " */\n" + sw);
  console.log("inject-pwa-html: build id stamped into dist/sw.js");
}
