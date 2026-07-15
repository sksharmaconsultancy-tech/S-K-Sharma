/**
 * Iter 145 — Web Push helpers (PWA only; no-op on native).
 *
 * Flow: check support → fetch VAPID public key → request Notification
 * permission (contextually, from a user tap) → pushManager.subscribe →
 * POST the subscription to the backend.
 */
import { Platform } from "react-native";
import { api } from "../api/client";

export function isPushSupported(): boolean {
  return (
    Platform.OS === "web" &&
    typeof window !== "undefined" &&
    typeof navigator !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export function pushPermission(): NotificationPermission | null {
  if (!isPushSupported()) return null;
  return Notification.permission;
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const arr = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) arr[i] = raw.charCodeAt(i);
  return arr;
}

/** The active SW registration, or null (e.g. dev preview without a SW). */
async function getReg(): Promise<ServiceWorkerRegistration | null> {
  try {
    return (await navigator.serviceWorker.getRegistration()) ?? null;
  } catch {
    return null;
  }
}

/** True when the browser already holds an active push subscription. */
export async function isSubscribed(): Promise<boolean> {
  if (!isPushSupported()) return false;
  const reg = await getReg();
  if (!reg) return false;
  try {
    const sub = await reg.pushManager.getSubscription();
    return !!sub;
  } catch {
    return false;
  }
}

/**
 * Subscribe this browser and register the subscription with the backend.
 * Must be called from a user gesture the FIRST time (permission prompt).
 */
export async function subscribeToPush(): Promise<{ ok: boolean; reason?: string }> {
  if (!isPushSupported()) return { ok: false, reason: "unsupported" };
  try {
    const reg = await getReg();
    if (!reg) return { ok: false, reason: "no_sw" };
    if (Notification.permission === "denied") return { ok: false, reason: "denied" };
    if (Notification.permission !== "granted") {
      const perm = await Notification.requestPermission();
      if (perm !== "granted") return { ok: false, reason: perm };
    }
    const { public_key } = await api<{ public_key: string }>("/push/vapid-public-key");
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(public_key) as unknown as BufferSource,
      });
    }
    const json = sub.toJSON();
    await api("/push/subscribe", {
      method: "POST",
      body: {
        endpoint: json.endpoint,
        keys: { p256dh: json.keys?.p256dh, auth: json.keys?.auth },
        ua: navigator.userAgent?.slice(0, 120),
      },
    });
    return { ok: true };
  } catch (e: any) {
    console.log("subscribeToPush failed:", e?.message || e);
    return { ok: false, reason: "error" };
  }
}
