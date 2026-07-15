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
            navigator.serviceWorker.register("/sw.js").catch(function () {});
          });
        }
      })();
    </script>
  </head>`;

html = html.replace("</head>", head);
fs.writeFileSync(file, html);
console.log("inject-pwa-html: PWA tags + install hook injected into dist/index.html");
