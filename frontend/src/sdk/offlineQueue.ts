/**
 * Iter 418 — SDK DEVICE SYNC ENGINE (offline punch queue + background sync).
 *
 * The single sync authority for the whole app. Storage is delegated to the
 * proven offlinePunch store — IndexedDB on web (handles large base64
 * selfies) and AsyncStorage on native. Every queued punch carries a
 * client_dedupe_id + client_punch_at, and the backend punch endpoint is
 * idempotent on them, so offline replays never duplicate and always keep
 * the REAL capture time.
 *
 * Sync triggers wired by startAutoSync():
 *   • web PWA: browser `online` event + 60 s foreground interval
 *   • native builds: the same PLUS an expo-background-task job
 *     (WorkManager on Android / BGTaskScheduler on iOS) every ~15 min.
 *     NOTE: background execution needs a real build — not Expo Go / web.
 */
import { Platform } from "react-native";
import { api } from "@/src/api/client";
import {
  enqueuePunch as storeEnqueue,
  flushQueue as storeFlush,
  pendingCount,
  isOnline,
  getOfflinePunchEnabled,
  setLastSync,
} from "@/src/utils/offlinePunch";

export type SyncResult = { synced: number; failed: number; remaining: number };

// ---- Sync-result listeners (UI badges / banners subscribe here) -----------
const listeners = new Set<(r: SyncResult) => void>();

/** Subscribe to sync results (pending-count badges etc). Returns unsubscribe. */
export function onSyncResult(cb: (r: SyncResult) => void): () => void {
  listeners.add(cb);
  return () => { listeners.delete(cb); };
}

function notify(r: SyncResult) {
  listeners.forEach((cb) => { try { cb(r); } catch { /* listener error */ } });
}

/** Firm Master switch — is offline punching allowed for this employee's
 *  firm? TTL-cached and offline-safe (falls back to last-known value). */
export function offlinePunchAllowed(): Promise<boolean> {
  return getOfflinePunchEnabled(api as any);
}

export { isOnline };

export async function queuedPunchCount(): Promise<number> {
  try { return await pendingCount(); } catch { return 0; }
}

/** Cache a punch on-device (dedupe id + REAL capture time attached by the
 *  store). Survives app restarts. Returns the new queue length. */
export async function enqueuePunch(body: Record<string, any>): Promise<number> {
  await storeEnqueue(body);
  return queuedPunchCount();
}

/** Replay every cached punch (idempotent on the server). Successes and
 *  permanent 4xx rejections are removed; network/5xx failures are kept for
 *  the next round. Notifies subscribers with the result. */
export async function flushPunchQueue(): Promise<SyncResult> {
  if (!isOnline()) {
    return { synced: 0, failed: 0, remaining: await queuedPunchCount() };
  }
  const r = await storeFlush(api as any);
  if (r.synced > 0) { try { await setLastSync(Date.now()); } catch {} }
  notify(r);
  return r;
}

// ---- Background job (native builds — WorkManager / BGTaskScheduler) -------
const BG_TASK = "smart-punch-offline-sync";

async function registerBackgroundSync(): Promise<void> {
  if (Platform.OS === "web") return;
  try {
    const TaskManager = await import("expo-task-manager");
    const BackgroundTask = await import("expo-background-task");
    if (!TaskManager.isTaskDefined(BG_TASK)) {
      TaskManager.defineTask(BG_TASK, async () => {
        try {
          await flushPunchQueue();
          return BackgroundTask.BackgroundTaskResult.Success;
        } catch {
          return BackgroundTask.BackgroundTaskResult.Failed;
        }
      });
    }
    await BackgroundTask.registerTaskAsync(BG_TASK, { minimumInterval: 15 });
  } catch {
    /* Expo Go / web preview — foreground triggers still cover sync */
  }
}

// ---- Auto-sync wiring (idempotent — safe to call more than once) ----------
let started = false;

export function startAutoSync(): void {
  if (started) return;
  started = true;
  // 1) Browser back-online event (web PWA).
  if (Platform.OS === "web" && typeof window !== "undefined") {
    window.addEventListener("online", () => { void flushPunchQueue(); });
  }
  // 2) Gentle interval while the app is in the foreground (all platforms).
  setInterval(() => { void flushPunchQueue(); }, 60 * 1000);
  // 3) Native builds: OS-scheduled background job.
  void registerBackgroundSync();
  // 4) Immediate catch-up flush on start.
  void flushPunchQueue();
}
