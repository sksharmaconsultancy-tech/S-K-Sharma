import * as SecureStore from "expo-secure-store";
import { Platform } from "react-native";

const TOKEN_KEY = "llc_session_token";

// Iter 93 — On web the app is served from the SAME domain as the /api
// ingress, so use RELATIVE paths. Same-origin fetches carry the browser's
// Cloudflare clearance cookies and avoid cross-origin bot checks (the
// "Just a moment…" HTML challenge that used to blank out every screen).
// Native (Expo Go / builds) keeps the absolute backend URL.
const ENV_BASE = process.env.EXPO_PUBLIC_BACKEND_URL as string;
const BASE = Platform.OS === "web" ? "" : ENV_BASE;

async function readToken(): Promise<string | null> {
  if (Platform.OS === "web") {
    try {
      return globalThis.localStorage?.getItem(TOKEN_KEY) ?? null;
    } catch {
      return null;
    }
  }
  return await SecureStore.getItemAsync(TOKEN_KEY);
}

export async function saveToken(token: string) {
  if (Platform.OS === "web") {
    globalThis.localStorage?.setItem(TOKEN_KEY, token);
  } else {
    await SecureStore.setItemAsync(TOKEN_KEY, token);
  }
}

export async function clearToken() {
  if (Platform.OS === "web") {
    globalThis.localStorage?.removeItem(TOKEN_KEY);
  } else {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
  }
}

export async function readAuthToken(): Promise<string | null> {
  return await readToken();
}

export function getApiBaseUrl(): string {
  return `${BASE}/api`;
}

/**
 * Fetch a binary payload (PDF / image) from the backend and return it as a
 * base64 string with a data URL prefix suitable for expo-print,
 * expo-sharing, or an <Image src=...>. Also returns the raw mime type.
 *
 * On web we skip the base64 dance and return an object URL that can be
 * assigned to window.location or an <a href> so the browser handles the
 * download natively.
 */
export async function apiBinary(
  path: string,
): Promise<{ mimeType: string; base64: string; webBlobUrl?: string }> {
  const t = await readToken();
  const headers: Record<string, string> = {};
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(`${BASE}/api${path}`, { headers, credentials: "include" });
  if (!res.ok) {
    const txt = await res.text().catch(() => "");
    throw new Error(txt || `HTTP ${res.status}`);
  }
  const mime =
    res.headers.get("content-type")?.split(";")[0]?.trim() ||
    "application/octet-stream";
  if (Platform.OS === "web") {
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    return { mimeType: mime, base64: "", webBlobUrl: url };
  }
  const buf = await res.arrayBuffer();
  const globalBuffer = (globalThis as any).Buffer;
  const bytes = new Uint8Array(buf);
  let base64: string;
  if (globalBuffer) {
    base64 = globalBuffer.from(bytes).toString("base64");
  } else {
    // Fallback for RN environments without Buffer
    let bin = "";
    for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    base64 = (globalThis as any).btoa
      ? (globalThis as any).btoa(bin)
      : "";
  }
  return { mimeType: mime, base64 };
}

export async function api<T = any>(
  path: string,
  opts: { method?: string; body?: any; auth?: boolean } = {},
  _retried = false,
): Promise<T> {
  const { method = "GET", body, auth = true } = opts;
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth) {
    const t = await readToken();
    if (t) headers.Authorization = `Bearer ${t}`;
  }
  const res = await fetch(`${BASE}/api${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
    // Iter 103 — send the browser's Cloudflare clearance cookies so
    // challenged browsers don't receive the HTML challenge page as an
    // API response ("Server returned an unexpected text/html").
    credentials: "include",
  });
  const text = await res.text();
  // Iter 93 — Detect Cloudflare challenge / non-JSON responses BEFORE
  // parsing. Previously an HTML challenge page ("Just a moment…") was
  // returned with HTTP 200, parsed as a string and crashed every caller
  // with an unreadable red error overlay.
  const contentType = res.headers.get("content-type") || "";
  if (text && !contentType.includes("application/json")) {
    const isChallenge =
      text.includes("Just a moment") || text.includes("cf-challenge") ||
      text.includes("challenge-platform");
    // Iter 93/103 — HTML responses (CF challenge, 502/504 gateway pages,
    // rate-limit pages) are usually transient: wait a beat and retry the
    // request ONCE before surfacing anything to the user.
    if (!_retried) {
      await new Promise((r) => setTimeout(r, 2000));
      return api<T>(path, opts, true);
    }
    // Extract the HTML <title> so the user/support can see WHICH page
    // was served (e.g. "502 Bad Gateway", "Just a moment…").
    const title = (/<title[^>]*>([^<]*)<\/title>/i.exec(text)?.[1] || "").trim();
    const err: any = new Error(
      isChallenge
        ? "Security check in progress — please reload the page (Ctrl+R) and try again."
        : `Server is briefly unavailable (${res.status}${title ? ` — ${title}` : ""}). ` +
          "Please wait a few seconds and try again.",
    );
    err.status = res.status;
    err.isChallenge = isChallenge;
    throw err;
  }
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    // Iter 88 — On non-2xx, prefer server-provided detail/message. If the
    // server crashed (no JSON), include any raw text so we don't dead-end
    // on a bare "HTTP 500" like the Company Requests Approve flow used to.
    let detail: any =
      (data && (data.detail || data.message)) ||
      (typeof data === "string" && data.trim() ? data.trim() : "") ||
      `HTTP ${res.status}`;
    if (typeof detail !== "string") detail = JSON.stringify(detail);
    // Attach status to the Error so callers can distinguish transient
    // races (500) from user-fixable errors (400/409).
    const err: any = new Error(detail);
    err.status = res.status;
    throw err;
  }
  return data as T;
}
