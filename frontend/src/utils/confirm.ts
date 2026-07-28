/**
 * Cross-platform Yes/No confirmation (Iter 129e).
 * Iter 345 (user bug — "No Message Only Refresh the Page"): the web build
 * used window.confirm / window.alert. Browsers SUPPRESS those after the
 * user ticks "Prevent this page from creating additional dialogs" — every
 * confirm then instantly returns FALSE with nothing on screen, which made
 * Salary Process/Save look like a silent page refresh. Web now renders an
 * IN-APP modal + toast that can never be suppressed.
 */
import { Alert, Platform } from "react-native";

const BTN_BASE =
  "border-radius:10px;padding:9px 22px;font-size:13px;font-weight:800;" +
  "cursor:pointer;font-family:inherit;";

export function confirmYesNo(message: string, title = "Please confirm"): Promise<boolean> {
  if (Platform.OS === "web") {
    if (typeof document === "undefined") return Promise.resolve(true);
    return new Promise((resolve) => {
      const ov = document.createElement("div");
      ov.style.cssText =
        "position:fixed;inset:0;background:rgba(15,23,42,.55);z-index:999999;" +
        "display:flex;align-items:center;justify-content:center;padding:16px;";
      const box = document.createElement("div");
      box.style.cssText =
        "background:#fff;border-radius:14px;max-width:460px;width:100%;padding:20px;" +
        "box-shadow:0 20px 60px rgba(0,0,0,.35);font-family:system-ui,-apple-system,sans-serif;";
      const h = document.createElement("div");
      h.textContent = title;
      h.style.cssText = "font-weight:800;font-size:15px;color:#0F172A;margin-bottom:8px;";
      const p = document.createElement("div");
      p.textContent = message;
      p.style.cssText =
        "font-size:13px;color:#334155;white-space:pre-wrap;line-height:1.55;margin-bottom:18px;";
      const row = document.createElement("div");
      row.style.cssText = "display:flex;gap:10px;justify-content:flex-end;";
      const done = (v: boolean) => { ov.remove(); resolve(v); };
      const no = document.createElement("button");
      no.textContent = "No";
      no.style.cssText = BTN_BASE + "background:#F1F5F9;color:#334155;border:1px solid #CBD5E1;";
      no.onclick = () => done(false);
      const yes = document.createElement("button");
      yes.textContent = "Yes";
      yes.style.cssText = BTN_BASE + "background:#2563EB;color:#fff;border:1px solid #2563EB;";
      yes.onclick = () => done(true);
      ov.onclick = (e) => { if (e.target === ov) done(false); };
      row.append(no, yes);
      box.append(h, p, row);
      ov.append(box);
      document.body.append(ov);
      yes.focus();
    });
  }
  return new Promise((resolve) => {
    Alert.alert(title, message, [
      { text: "No", style: "cancel", onPress: () => resolve(false) },
      { text: "Yes", onPress: () => resolve(true) },
    ]);
  });
}

/**
 * Iter 345 — non-blocking toast (web) / Alert (native). Unlike
 * window.alert this can NEVER be suppressed by the browser, so users
 * always see "Saved ✓" / error feedback.
 */
export function showToast(message: string, title = "") {
  if (Platform.OS !== "web") {
    Alert.alert(title || "Info", message);
    return;
  }
  if (typeof document === "undefined") return;
  const id = "app-toast-host";
  let host = document.getElementById(id);
  if (!host) {
    host = document.createElement("div");
    host.id = id;
    host.style.cssText =
      "position:fixed;top:14px;left:50%;transform:translateX(-50%);z-index:9999999;" +
      "display:flex;flex-direction:column;gap:8px;align-items:center;max-width:92vw;";
    document.body.append(host);
  }
  const t = document.createElement("div");
  t.style.cssText =
    "background:#0F172A;color:#fff;border-radius:12px;padding:12px 18px;font-size:13px;" +
    "font-weight:600;font-family:system-ui,-apple-system,sans-serif;line-height:1.5;" +
    "box-shadow:0 12px 32px rgba(0,0,0,.35);max-width:560px;white-space:pre-wrap;cursor:pointer;";
  t.textContent = message;
  t.onclick = () => t.remove();
  host.append(t);
  const life = Math.min(12000, Math.max(4500, message.length * 55));
  setTimeout(() => t.remove(), life);
}
