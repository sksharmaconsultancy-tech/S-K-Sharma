import { Platform } from "react-native";

/**
 * PWA helpers (web only).
 *
 * setupPWA(): injects the base manifest + iOS meta + registers the service
 * worker, and captures the Chrome/Android `beforeinstallprompt` event so we
 * can offer a one-tap install button later.
 *
 * The /employer and /employee entry screens call setManifestHref() to swap
 * to their own manifest (so each installs as a SEPARATE home-screen app),
 * and usePwaInstall() to drive the install button.
 */
export function setupPWA(): void {
  if (Platform.OS !== "web" || typeof document === "undefined") return;
  const w = window as any;

  // Capture the install prompt as early as possible (before user reaches
  // /employer or /employee). Chrome/Edge/Android only.
  if (!w.__pwaInstallHooked) {
    w.__pwaInstallHooked = true;
    window.addEventListener("beforeinstallprompt", (e: any) => {
      e.preventDefault();
      w.__pwaInstallEvent = e;
      window.dispatchEvent(new Event("pwa-installable"));
    });
    window.addEventListener("appinstalled", () => {
      w.__pwaInstallEvent = null;
      window.dispatchEvent(new Event("pwa-installed"));
    });
  }

  const head = document.head;
  if (!head) return;

  // User directive — no pinch/double-tap zoom in the mobile PWA; the app
  // always renders at screen size. (Done at runtime because web.output is
  // "single" — +html.tsx is not served.)
  if (!w.__noZoomHooked) {
    w.__noZoomHooked = true;
    const vp = head.querySelector('meta[name="viewport"]') as HTMLMetaElement | null;
    const content = "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, shrink-to-fit=no, viewport-fit=cover";
    if (vp) vp.content = content;
    else {
      const el = document.createElement("meta");
      el.name = "viewport";
      el.content = content;
      head.appendChild(el);
    }
    // iOS Safari ignores user-scalable=no — block gestures too.
    document.addEventListener("gesturestart", (e: any) => e.preventDefault(), { passive: false } as any);
    document.addEventListener("gesturechange", (e: any) => e.preventDefault(), { passive: false } as any);
    let lastTouchEnd = 0;
    document.addEventListener("touchend", (e: any) => {
      const now = Date.now();
      if (now - lastTouchEnd <= 300) e.preventDefault();
      lastTouchEnd = now;
    }, { passive: false } as any);
    const style = document.createElement("style");
    style.textContent =
      "html, body { touch-action: pan-x pan-y; } " +
      "@media (pointer: coarse) { input, textarea, select { font-size: 16px !important; } }";
    head.appendChild(style);
  }

  const meta = (name: string, content: string) => {
    if (head.querySelector(`meta[name="${name}"]`)) return;
    const el = document.createElement("meta");
    el.name = name;
    el.content = content;
    head.appendChild(el);
  };

  // Pick the manifest from the URL path SYNCHRONOUSLY so /employee and
  // /employer install as two SEPARATE home-screen apps (the browser may
  // read the manifest before React mounts the entry screen).
  const path = window.location.pathname || "/";
  const query = window.location.search || "";
  let manifestHref = "/manifest.json";
  let appTitle = "SK Sharma";
  if (path.startsWith("/employee") || path.startsWith("/pin-login") ||
      (path.startsWith("/get-app") && !query.includes("type=employer"))) {
    manifestHref = "/manifest-employee.json";
    appTitle = "SKS Employee";
  } else if (path.startsWith("/employer") || path.startsWith("/admin-pin-login") ||
      path.startsWith("/company-login") || path.startsWith("/company-register") ||
      (path.startsWith("/get-app") && query.includes("type=employer"))) {
    manifestHref = "/manifest-employer.json";
    appTitle = "SKS Employer";
  }

  if (!head.querySelector('link[rel="manifest"]')) {
    const link = document.createElement("link");
    link.rel = "manifest";
    link.href = manifestHref;
    head.appendChild(link);
  }
  if (!head.querySelector('link[rel="apple-touch-icon"]')) {
    const icon = document.createElement("link");
    icon.rel = "apple-touch-icon";
    icon.href = "/icons/icon-192.png";
    head.appendChild(icon);
  }
  meta("theme-color", "#0F2E3D");
  meta("mobile-web-app-capable", "yes");
  meta("apple-mobile-web-app-capable", "yes");
  meta("apple-mobile-web-app-status-bar-style", "black-translucent");
  meta("apple-mobile-web-app-title", appTitle);

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}

/** Swap the linked manifest (so /employer & /employee install separately). */
export function setManifestHref(href: string): void {
  if (Platform.OS !== "web" || typeof document === "undefined") return;
  let link = document.querySelector('link[rel="manifest"]') as HTMLLinkElement | null;
  if (!link) {
    link = document.createElement("link");
    link.rel = "manifest";
    document.head.appendChild(link);
  }
  if (link.href.endsWith(href)) return;
  link.href = href;
}

/** True when running as an installed standalone PWA. */
export function isStandalonePWA(): boolean {
  if (Platform.OS !== "web" || typeof window === "undefined") return false;
  const w = window as any;
  return (
    (w.matchMedia && w.matchMedia("(display-mode: standalone)").matches) ||
    w.navigator?.standalone === true
  );
}

/** True on any iOS/iPadOS device (any browser). */
export function isIOS(): boolean {
  if (Platform.OS !== "web" || typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  return /iPad|iPhone|iPod/.test(ua) ||
    (navigator.platform === "MacIntel" && (navigator as any).maxTouchPoints > 1);
}

/** True on iOS Safari (no beforeinstallprompt → manual Add-to-Home-Screen). */
export function isIOSWeb(): boolean {
  if (Platform.OS !== "web" || typeof navigator === "undefined") return false;
  const ua = navigator.userAgent || "";
  const webkit = /WebKit/.test(ua) && !/CriOS|FxiOS|EdgiOS/.test(ua);
  return isIOS() && webkit;
}

/** Set the iOS home-screen app name for the current entry link. */
export function setAppleWebAppTitle(title: string): void {
  if (Platform.OS !== "web" || typeof document === "undefined") return;
  let meta = document.querySelector('meta[name="apple-mobile-web-app-title"]') as HTMLMetaElement | null;
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "apple-mobile-web-app-title";
    document.head.appendChild(meta);
  }
  meta.content = title;
}

/** Fire the captured install prompt. Returns 'accepted' | 'dismissed' | 'unavailable'. */
export async function promptInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
  if (Platform.OS !== "web") return "unavailable";
  const w = window as any;
  const evt = w.__pwaInstallEvent;
  if (!evt) return "unavailable";
  evt.prompt();
  try {
    const choice = await evt.userChoice;
    w.__pwaInstallEvent = null;
    return choice?.outcome === "accepted" ? "accepted" : "dismissed";
  } catch {
    return "dismissed";
  }
}

export function canInstallNow(): boolean {
  if (Platform.OS !== "web" || typeof window === "undefined") return false;
  return !!(window as any).__pwaInstallEvent;
}
