/**
 * Offline punch queue + background sync (Geofence Phase 2).
 *
 * When the firm has "Offline punching" enabled and the device is offline
 * (or the punch API fails), the punch — including GPS, selfie, distance,
 * device info and the ORIGINAL capture time — is stored on-device and
 * synced automatically when the network returns.
 *
 * Storage: IndexedDB on web (handles large base64 selfies); AsyncStorage
 * fallback on native. Each punch carries a client_dedupe_id so retries and
 * multi-tab syncs never create duplicates (server is idempotent on it).
 */
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

export type QueuedPunch = {
  client_dedupe_id: string;
  client_punch_at: string; // ISO capture time (offline)
  body: Record<string, any>;
  created_at: number;
  attempts: number;
};

const DB_NAME = "sks_offline";
const STORE = "punches";
const AS_KEY = "sks_offline_punches";

function genId(): string {
  return `op_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
}

// ---- IndexedDB (web) -------------------------------------------------------
function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "client_dedupe_id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbAll(): Promise<QueuedPunch[]> {
  const db = await idb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => resolve((req.result as QueuedPunch[]) || []);
    req.onerror = () => reject(req.error);
  });
}

async function idbPut(p: QueuedPunch): Promise<void> {
  const db = await idb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put(p);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

async function idbDel(id: string): Promise<void> {
  const db = await idb();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).delete(id);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

// ---- AsyncStorage (native fallback) ---------------------------------------
async function asAll(): Promise<QueuedPunch[]> {
  const raw = await AsyncStorage.getItem(AS_KEY);
  return raw ? (JSON.parse(raw) as QueuedPunch[]) : [];
}
async function asWrite(list: QueuedPunch[]): Promise<void> {
  await AsyncStorage.setItem(AS_KEY, JSON.stringify(list));
}

const useIdb = Platform.OS === "web" && typeof indexedDB !== "undefined";

// ---- Public API ------------------------------------------------------------
export function isOnline(): boolean {
  if (Platform.OS === "web" && typeof navigator !== "undefined") {
    return navigator.onLine !== false;
  }
  return true; // native online-detection handled by the sync attempt itself
}

export async function enqueuePunch(body: Record<string, any>): Promise<QueuedPunch> {
  const item: QueuedPunch = {
    client_dedupe_id: genId(),
    client_punch_at: new Date().toISOString(),
    body: { ...body, offline: true },
    created_at: Date.now(),
    attempts: 0,
  };
  item.body.client_dedupe_id = item.client_dedupe_id;
  item.body.client_punch_at = item.client_punch_at;
  if (useIdb) await idbPut(item);
  else {
    const list = await asAll();
    list.push(item);
    await asWrite(list);
  }
  return item;
}

export async function pendingCount(): Promise<number> {
  const list = useIdb ? await idbAll() : await asAll();
  return list.length;
}

export async function listQueue(): Promise<QueuedPunch[]> {
  return useIdb ? await idbAll() : await asAll();
}

async function remove(id: string): Promise<void> {
  if (useIdb) await idbDel(id);
  else await asWrite((await asAll()).filter((p) => p.client_dedupe_id !== id));
}

async function bump(item: QueuedPunch): Promise<void> {
  item.attempts += 1;
  if (useIdb) await idbPut(item);
  else {
    const list = await asAll();
    const i = list.findIndex((p) => p.client_dedupe_id === item.client_dedupe_id);
    if (i >= 0) { list[i] = item; await asWrite(list); }
  }
}

let syncing = false;

/**
 * Flush queued punches through the given poster (usually the `api` helper).
 * Returns {synced, failed, remaining}. Safe to call repeatedly.
 */
export async function flushQueue(
  post: (path: string, opts: any) => Promise<any>,
): Promise<{ synced: number; failed: number; remaining: number }> {
  if (syncing || !isOnline()) {
    return { synced: 0, failed: 0, remaining: await pendingCount() };
  }
  syncing = true;
  let synced = 0;
  let failed = 0;
  try {
    const list = await listQueue();
    for (const item of list) {
      try {
        await post("/attendance/punch", { method: "POST", body: item.body });
        await remove(item.client_dedupe_id);
        synced += 1;
      } catch (e: any) {
        // Duplicate / already-accepted → drop it. Other errors → keep & retry.
        const msg = String(e?.message || "").toLowerCase();
        if (msg.includes("duplicate") || e?.status === 409) {
          await remove(item.client_dedupe_id);
          synced += 1;
        } else {
          await bump(item);
          failed += 1;
        }
      }
    }
  } finally {
    syncing = false;
  }
  return { synced, failed, remaining: await pendingCount() };
}

let lastSyncKey = "sks_last_sync";
export async function setLastSync(ts: number): Promise<void> {
  await AsyncStorage.setItem(lastSyncKey, String(ts));
}
export async function getLastSync(): Promise<number | null> {
  const v = await AsyncStorage.getItem(lastSyncKey);
  return v ? Number(v) : null;
}
