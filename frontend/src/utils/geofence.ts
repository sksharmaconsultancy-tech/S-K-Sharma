import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { Platform, AppState } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

export const GEOFENCE_TASK = "sks-office-geofence-task";
const PREF_KEY = "sks_autopunch_enabled_v1";
const LAST_EVENT_KEY = "sks_autopunch_last_event_v1";
// Minimum interval between two consecutive auto-punches for the SAME kind.
// Prevents jitter around the boundary from generating a storm of punches.
export const AUTO_PUNCH_DEBOUNCE_MS = 2 * 60 * 1000; // 2 minutes

/**
 * Haversine distance in metres between two coordinates.
 */
export function distanceMeters(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const R = 6371000;
  const toRad = (v: number) => (v * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) *
      Math.cos(toRad(lat2)) *
      Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

export async function isAutoPunchEnabled(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(PREF_KEY);
    return v === "1";
  } catch {
    return false;
  }
}

export async function setAutoPunchEnabled(enabled: boolean): Promise<void> {
  try {
    if (enabled) await AsyncStorage.setItem(PREF_KEY, "1");
    else await AsyncStorage.removeItem(PREF_KEY);
  } catch {}
}

const AUTO_ENABLED_ONCE_KEY = "sks_autopunch_bootstrap_v1";

/**
 * Has this device ever had auto-punch bootstrap-enabled by the app? Used to
 * flip it on ONCE the first time an approved employee opens the app so the
 * feature works out of the box, without overriding a user who later toggled
 * it off explicitly.
 */
export async function hasAutoPunchBootstrapRun(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(AUTO_ENABLED_ONCE_KEY);
    return v === "1";
  } catch {
    return false;
  }
}

export async function markAutoPunchBootstrapDone(): Promise<void> {
  try {
    await AsyncStorage.setItem(AUTO_ENABLED_ONCE_KEY, "1");
  } catch {}
}

export type LastEvent = {
  kind: "in" | "out";
  at: number;
} | null;

export async function getLastAutoPunchEvent(): Promise<LastEvent> {
  try {
    const raw = await AsyncStorage.getItem(LAST_EVENT_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export async function setLastAutoPunchEvent(e: LastEvent): Promise<void> {
  try {
    if (!e) await AsyncStorage.removeItem(LAST_EVENT_KEY);
    else await AsyncStorage.setItem(LAST_EVENT_KEY, JSON.stringify(e));
  } catch {}
}

/**
 * Request foreground location permission — required for both foreground
 * watch and (as a first step) background geofencing. Returns true if the
 * caller can proceed.
 */
export async function ensureForegroundPermission(): Promise<boolean> {
  const { status } = await Location.requestForegroundPermissionsAsync();
  return status === "granted";
}

/**
 * Request BACKGROUND location permission. Only meaningful on native (iOS /
 * Android). Web preview / Expo Go on physical devices will typically return
 * denied — auto-punch will then only work while the app is foregrounded.
 */
export async function ensureBackgroundPermission(): Promise<boolean> {
  if (Platform.OS === "web") return false;
  try {
    const fg = await Location.requestForegroundPermissionsAsync();
    if (fg.status !== "granted") return false;
    const bg = await Location.requestBackgroundPermissionsAsync();
    return bg.status === "granted";
  } catch {
    return false;
  }
}

export type ForegroundWatchOpts = {
  officeLat: number;
  officeLng: number;
  radiusM: number;
  /** Called when the user transitions from OUTSIDE → INSIDE. */
  onEnter: (loc: Location.LocationObject) => Promise<void> | void;
  /** Called when the user transitions from INSIDE → OUTSIDE. */
  onExit: (loc: Location.LocationObject) => Promise<void> | void;
};

/**
 * Foreground geofence watcher. Only fires on TRANSITIONS across the boundary
 * — never on every location update — so callers can safely wire it to their
 * auto-punch API. Uses a small hysteresis (5 m) to avoid boundary jitter.
 *
 * Returns an async `stop()` function to detach the watcher.
 */
export async function startForegroundGeofenceWatch(
  opts: ForegroundWatchOpts,
): Promise<() => Promise<void>> {
  if (Platform.OS === "web") {
    // Web preview: expo-location falls back to browser geolocation; still fine
    // to watch, so we don't early-return here. Only skip if the caller wants
    // to.
  }
  const granted = await ensureForegroundPermission();
  if (!granted) {
    throw new Error("Location permission denied");
  }
  let inside: boolean | null = null; // unknown until first sample
  const HYSTERESIS_M = 5;

  const sub = await Location.watchPositionAsync(
    {
      accuracy: Location.Accuracy.Balanced,
      distanceInterval: 15, // metres — only report if the user has moved 15m
      timeInterval: 15_000, // and no more than once every 15s
    },
    async (loc) => {
      const d = distanceMeters(
        loc.coords.latitude,
        loc.coords.longitude,
        opts.officeLat,
        opts.officeLng,
      );
      // Apply hysteresis relative to the CURRENT state so we don't ping-pong.
      const nowInside =
        inside === null
          ? d <= opts.radiusM
          : inside
            ? d <= opts.radiusM + HYSTERESIS_M
            : d < opts.radiusM - HYSTERESIS_M;

      if (inside === null) {
        inside = nowInside;
        return;
      }
      if (nowInside && !inside) {
        inside = true;
        try {
          await opts.onEnter(loc);
        } catch {}
      } else if (!nowInside && inside) {
        inside = false;
        try {
          await opts.onExit(loc);
        } catch {}
      }
    },
  );
  return async () => {
    try {
      sub.remove();
    } catch {}
  };
}

/**
 * Start the OS-managed geofence (background). Requires background location
 * permission. Only works on native builds — Expo Go's runtime does NOT
 * include the underlying TaskManager task registration for arbitrary
 * background tasks, so this may no-op silently there.
 *
 * The corresponding TaskManager.defineTask must be defined at module load
 * time in App.tsx / _layout.tsx (see registerGeofenceTask in this file).
 */
export async function startBackgroundGeofence(opts: {
  officeLat: number;
  officeLng: number;
  radiusM: number;
}): Promise<boolean> {
  if (Platform.OS === "web") return false;
  const granted = await ensureBackgroundPermission();
  if (!granted) return false;
  try {
    // If a previous session is still running, stop it first.
    const already = await Location.hasStartedGeofencingAsync(GEOFENCE_TASK);
    if (already) {
      try {
        await Location.stopGeofencingAsync(GEOFENCE_TASK);
      } catch {}
    }
    await Location.startGeofencingAsync(GEOFENCE_TASK, [
      {
        identifier: "office",
        latitude: opts.officeLat,
        longitude: opts.officeLng,
        radius: opts.radiusM,
        notifyOnEnter: true,
        notifyOnExit: true,
      },
    ]);
    return true;
  } catch {
    return false;
  }
}

export async function stopBackgroundGeofence(): Promise<void> {
  if (Platform.OS === "web") return;
  try {
    const started = await Location.hasStartedGeofencingAsync(GEOFENCE_TASK);
    if (started) {
      await Location.stopGeofencingAsync(GEOFENCE_TASK);
    }
  } catch {}
}

// Dummy import so ESLint doesn't complain if AppState is unused.
void AppState;
void TaskManager;
