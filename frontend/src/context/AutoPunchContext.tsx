import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { AppState, Platform } from "react-native";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import {
  AUTO_PUNCH_DEBOUNCE_MS,
  GEOFENCE_TASK,
  getLastAutoPunchEvent,
  hasAutoPunchBootstrapRun,
  isAutoPunchEnabled,
  markAutoPunchBootstrapDone,
  setAutoPunchEnabled as persistAutoPunchEnabled,
  setLastAutoPunchEvent,
  startBackgroundGeofence,
  startForegroundGeofenceWatch,
  stopBackgroundGeofence,
} from "@/src/utils/geofence";

// ---------------------------------------------------------------------------
// Background TaskManager registration
// ---------------------------------------------------------------------------
// This block runs once at import time. When the OS fires a geofence event we
// send the auto punch to the backend. We intentionally read the token from
// SecureStore here — do NOT capture any React state, because the JS engine
// context is separate when the OS wakes us in the background.
// ---------------------------------------------------------------------------
if (!TaskManager.isTaskDefined(GEOFENCE_TASK)) {
  TaskManager.defineTask(GEOFENCE_TASK, async (event: any) => {
    try {
      if (event.error) return;
      const { eventType, region } = event.data || {};
      // eventType: 1 = Enter, 2 = Exit  (matches Location.GeofencingEventType)
      const isEnter = eventType === Location.GeofencingEventType.Enter;
      const isExit = eventType === Location.GeofencingEventType.Exit;
      if (!isEnter && !isExit) return;

      // Debounce against a rapid burst from the OS.
      const last = await getLastAutoPunchEvent();
      const now = Date.now();
      if (
        last &&
        (last.kind === (isEnter ? "in" : "out")) &&
        now - last.at < AUTO_PUNCH_DEBOUNCE_MS
      ) {
        return;
      }

      // DOUBLE-CHECK: never trust the OS event alone. Read the phone's
      // ACTUAL current location and confirm it's inside the region radius.
      // On rare OS false-positives (which do happen in Expo Go on
      // emulators), this guard prevents a spurious punch from being
      // recorded server-side.
      let lat: number;
      let lng: number;
      try {
        const pos = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        lat = pos.coords.latitude;
        lng = pos.coords.longitude;
      } catch {
        // If we can't read a real location (permission revoked in the
        // background), skip this punch entirely rather than punching from
        // office coordinates — that would be a false positive.
        return;
      }
      // Verify against the region we registered.
      // For an EXIT event we do NOT gate on distance — an OS exit event
      // is our source of truth that the boundary was just crossed. The
      // employee can walk arbitrarily far after the exit (car, bus,
      // etc.), and we still want the OUT punch to be recorded on the
      // backend. The backend accepts OUT punches from outside the
      // geofence as long as the user has an open IN today.
      if (isEnter) {
        const regionLat = region?.latitude ?? lat;
        const regionLng = region?.longitude ?? lng;
        const regionR = region?.radius ?? 200;
        const R = 6371000;
        const toRad = (v: number) => (v * Math.PI) / 180;
        const dLat = toRad(regionLat - lat);
        const dLng = toRad(regionLng - lng);
        const a =
          Math.sin(dLat / 2) ** 2 +
          Math.cos(toRad(lat)) *
            Math.cos(toRad(regionLat)) *
            Math.sin(dLng / 2) ** 2;
        const distanceM = 2 * R * Math.asin(Math.sqrt(a));
        if (distanceM > regionR) {
          // OS said "enter" but the phone is not actually inside — skip.
          // Do NOT update lastEvent so a legitimate transition later
          // can still fire.
          return;
        }
      }

      await api("/attendance/punch", {
        method: "POST",
        body: {
          kind: isEnter ? "in" : "out",
          latitude: lat,
          longitude: lng,
          biometric_method: "fingerprint",
          source: "geofence-auto",
        },
      });
      await setLastAutoPunchEvent({ kind: isEnter ? "in" : "out", at: now });
    } catch {
      // Non-fatal — the foreground watcher (or the next OS event) will retry.
    }
  });
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------
type Status =
  | { kind: "idle" }
  | { kind: "unavailable"; reason: string }
  | { kind: "watching"; mode: "foreground" | "background"; inside?: boolean }
  | { kind: "error"; msg: string };

interface AutoPunchCtx {
  enabled: boolean;
  supported: boolean;
  toggling: boolean;
  status: Status;
  lastEvent: { kind: "in" | "out"; at: number } | null;
  enable: () => Promise<{ ok: boolean; reason?: string }>;
  disable: () => Promise<void>;
}

const Ctx = createContext<AutoPunchCtx>({
  enabled: false,
  supported: false,
  toggling: false,
  status: { kind: "idle" },
  lastEvent: null,
  enable: async () => ({ ok: false }),
  disable: async () => {},
});

export function useAutoPunch() {
  return useContext(Ctx);
}

export function AutoPunchProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const [toggling, setToggling] = useState(false);
  const [lastEvent, setLastEvent] =
    useState<{ kind: "in" | "out"; at: number } | null>(null);
  const stopFgRef = useRef<null | (() => Promise<void>)>(null);
  // Iter 94 — geofence-exit ALERT watcher (runs when auto punch-out is OFF)
  const stopAlertRef = useRef<null | (() => Promise<void>)>(null);
  const lastAlertAtRef = useRef<number>(0);

  // The feature is only meaningful for employees who have an assigned company
  // with valid office coordinates. Admins don't need it. Live-in staff
  // (resort housekeeping etc.) are always inside the fence, so auto-punch
  // makes no sense for them — the daily roster is used instead.
  const office = user?.company as any;
  const isLiveIn = !!(user as any)?.is_live_in;
  const supported = !!(
    user &&
    user.role === "employee" &&
    !isLiveIn &&
    office &&
    typeof office.office_lat === "number" &&
    typeof office.office_lng === "number" &&
    typeof office.geofence_radius_m === "number"
  );

  // Hydrate persisted pref + last event on mount / user change.
  // Also bootstrap-enable auto-punch ONCE for approved employees so the
  // feature is on by default (user's request: "please check in / punch
  // in when inside geofence, out when outside — subject to approved by
  // company"). We only auto-enable if:
  //   • the user is a company-approved onboarded employee, AND
  //   • the phone has foreground location permission ALREADY granted
  //     (we never trigger the OS prompt from a background effect —
  //     that would be jarring), AND
  //   • we haven't already run the bootstrap flow for this device.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const [en, last, bootstrapped] = await Promise.all([
        isAutoPunchEnabled(),
        getLastAutoPunchEvent(),
        hasAutoPunchBootstrapRun(),
      ]);
      if (cancelled) return;
      setEnabled(en);
      setLastEvent(last);

      const isApprovedEmployee =
        !!user &&
        user.role === "employee" &&
        !!user.onboarded &&
        (user.approval_status ?? "approved") === "approved" &&
        !user.offboarded;
      if (
        !en &&                // not already on
        !bootstrapped &&      // never auto-enabled before
        isApprovedEmployee && // approved by company
        supported             // office coords + geofence radius set
      ) {
        try {
          const perm = await Location.getForegroundPermissionsAsync();
          if (perm.status === "granted") {
            await persistAutoPunchEnabled(true);
            await markAutoPunchBootstrapDone();
            if (!cancelled) setEnabled(true);
          }
        } catch {}
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.user_id, user?.approval_status, user?.onboarded, user?.offboarded, supported]);

  // Start/stop the watcher whenever `enabled` and `supported` change
  useEffect(() => {
    const shouldRun = enabled && supported;
    if (!shouldRun) {
      (async () => {
        if (stopFgRef.current) {
          await stopFgRef.current();
          stopFgRef.current = null;
        }
        await stopBackgroundGeofence();
        setStatus({ kind: "idle" });
      })();
      return;
    }
    if (!office) return;
    let cancelled = false;
    (async () => {
      try {
        // Kick off background geofence best-effort (silent no-op on Expo Go/web).
        const bgStarted = await startBackgroundGeofence({
          officeLat: office.office_lat,
          officeLng: office.office_lng,
          radiusM: office.geofence_radius_m,
        });

        // ALWAYS run the foreground watcher too — it handles the app-open
        // case and any OS that suspends the background task.
        const stop = await startForegroundGeofenceWatch({
          officeLat: office.office_lat,
          officeLng: office.office_lng,
          radiusM: office.geofence_radius_m,
          onEnter: (loc) => onTransition("in", loc),
          onExit: (loc) => onTransition("out", loc),
        });
        if (cancelled) {
          await stop();
          return;
        }
        stopFgRef.current = stop;
        setStatus({
          kind: "watching",
          mode: bgStarted ? "background" : "foreground",
        });
      } catch (e: any) {
        setStatus({
          kind: "unavailable",
          reason:
            e?.message ||
            "Could not start geofence watcher. Please grant location permission.",
        });
      }
    })();
    return () => {
      cancelled = true;
    };
    // We intentionally exclude onTransition (stable closure captures office)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, supported, office?.office_lat, office?.office_lng, office?.geofence_radius_m]);

  const onTransition = useCallback(
    async (kind: "in" | "out", loc: Location.LocationObject) => {
      const now = Date.now();
      // Debounce
      if (
        lastEvent &&
        lastEvent.kind === kind &&
        now - lastEvent.at < AUTO_PUNCH_DEBOUNCE_MS
      ) {
        return;
      }

      // Explicit radius check — the watcher already applies hysteresis
      // but this belt-and-braces guard ensures we never fire a punch when
      // the phone is not physically inside the fence for an "in" event.
      if (
        kind === "in" &&
        office &&
        typeof office.office_lat === "number" &&
        typeof office.office_lng === "number" &&
        typeof office.geofence_radius_m === "number"
      ) {
        const R = 6371000;
        const toRad = (v: number) => (v * Math.PI) / 180;
        const dLat = toRad(office.office_lat - loc.coords.latitude);
        const dLng = toRad(office.office_lng - loc.coords.longitude);
        const a =
          Math.sin(dLat / 2) ** 2 +
          Math.cos(toRad(loc.coords.latitude)) *
            Math.cos(toRad(office.office_lat)) *
            Math.sin(dLng / 2) ** 2;
        const distanceM = 2 * R * Math.asin(Math.sqrt(a));
        if (distanceM > office.geofence_radius_m) {
          // Not actually inside — do not punch. The watcher's hysteresis
          // will correct the internal "inside" flag on the next sample.
          return;
        }
      }
      // Verify against today's records — never double-in or double-out.
      try {
        const t = await api<{ records: any[] }>("/attendance/today");
        const recs = (t.records || []).sort(
          (a, b) => (a.at || "").localeCompare(b.at || ""),
        );
        const last = recs[recs.length - 1];
        if (last && last.kind === kind) {
          // Already in this state — don't double punch. Save the state so the
          // debounce also holds.
          const ev = { kind, at: now };
          await setLastAutoPunchEvent(ev);
          setLastEvent(ev);
          return;
        }
      } catch {
        // If the check fails, still proceed — the backend has its own guards.
      }
      try {
        await api("/attendance/punch", {
          method: "POST",
          body: {
            kind,
            latitude: loc.coords.latitude,
            longitude: loc.coords.longitude,
            biometric_method: "fingerprint",
            source: "geofence-auto",
          },
        });
        const ev = { kind, at: now };
        await setLastAutoPunchEvent(ev);
        setLastEvent(ev);
      } catch (e: any) {
        setStatus({
          kind: "error",
          msg: e?.message || "Auto punch failed. Will retry on next event.",
        });
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [lastEvent, office?.office_lat, office?.office_lng, office?.geofence_radius_m],
  );

  // -------------------------------------------------------------------
  // Iter 94 — Geofence-exit ALERT (no punch). When auto punch-out will
  // NOT fire (device toggle off, or the firm disabled auto punch), we
  // still watch the fence while the app is open. If the employee walks
  // OUT while punched IN, the backend notifies the Employer + Super
  // Admin so they can mark a Half Day or punch the employee OUT.
  // -------------------------------------------------------------------
  const effectiveAutoPunch = (user as any)?.effective_auto_punch !== false;
  const alertWatcherNeeded =
    supported && !(enabled && effectiveAutoPunch);

  const sendExitAlert = useCallback(
    async (loc: Location.LocationObject) => {
      const now = Date.now();
      // Client-side debounce: at most one alert per 30 minutes.
      if (now - lastAlertAtRef.current < 30 * 60 * 1000) return;
      try {
        // Only bother the server when there is an OPEN IN punch today.
        const t = await api<{ records: any[] }>("/attendance/today");
        const recs = (t.records || []).sort(
          (a, b) => (a.at || "").localeCompare(b.at || ""),
        );
        const last = recs[recs.length - 1];
        if (!last || last.kind !== "in") return;
        await api("/attendance/geofence-exit-alert", {
          method: "POST",
          body: {
            latitude: loc.coords.latitude,
            longitude: loc.coords.longitude,
          },
        });
        lastAlertAtRef.current = now;
      } catch {
        // Non-fatal — retried on the next exit sample.
      }
    },
    [],
  );

  useEffect(() => {
    if (Platform.OS === "web") return;
    const stopAlert = async () => {
      if (stopAlertRef.current) {
        await stopAlertRef.current().catch?.(() => {});
        stopAlertRef.current = null;
      }
    };
    if (!alertWatcherNeeded || !office) {
      void stopAlert();
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Never trigger the OS permission prompt from here — only watch
        // if the employee has ALREADY granted foreground location.
        const perm = await Location.getForegroundPermissionsAsync();
        if (perm.status !== "granted") return;
        const stop = await startForegroundGeofenceWatch({
          officeLat: office.office_lat,
          officeLng: office.office_lng,
          radiusM: office.geofence_radius_m,
          onEnter: () => {},
          onExit: (loc) => void sendExitAlert(loc),
        });
        if (cancelled) {
          await stop();
          return;
        }
        stopAlertRef.current = stop;
      } catch {
        // Permission revoked / watcher failed — silently skip.
      }
    })();
    return () => {
      cancelled = true;
      void stopAlert();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alertWatcherNeeded, office?.office_lat, office?.office_lng, office?.geofence_radius_m]);

  const enable = useCallback(async (): Promise<{
    ok: boolean;
    reason?: string;
  }> => {
    if (!supported) {
      return {
        ok: false,
        reason:
          "Auto punch is only available for employees with an assigned office location.",
      };
    }
    setToggling(true);
    try {
      // We only require FOREGROUND permission to enable — background is a
      // best-effort upgrade and won't block the feature on Expo Go.
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") {
        return {
          ok: false,
          reason:
            "Location permission is required for auto punch. Please enable it in Settings.",
        };
      }
      await persistAutoPunchEnabled(true);
      setEnabled(true);
      return { ok: true };
    } finally {
      setToggling(false);
    }
  }, [supported]);

  const disable = useCallback(async () => {
    setToggling(true);
    try {
      await persistAutoPunchEnabled(false);
      setEnabled(false);
    } finally {
      setToggling(false);
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (stopFgRef.current) {
        stopFgRef.current().catch(() => {});
        stopFgRef.current = null;
      }
    };
  }, []);

  // Also react to AppState changes — when the app is backgrounded and there
  // is no background geofence permission, the foreground watch stops. When
  // we come back to the foreground we simply flip enabled off/on to
  // reinitialise if we were watching before.
  useEffect(() => {
    if (Platform.OS === "web") return;
    const sub = AppState.addEventListener("change", (state) => {
      if (state === "active" && enabled && !stopFgRef.current && supported) {
        // Nudge the effect to re-run by toggling internal state.
        // (The effect above depends on `enabled` and `supported`; nothing to
        // do here — expo-location may pause updates transparently.)
        void state;
      }
    });
    return () => sub.remove();
  }, [enabled, supported]);

  const value = useMemo<AutoPunchCtx>(
    () => ({ enabled, supported, toggling, status, lastEvent, enable, disable }),
    [enabled, supported, toggling, status, lastEvent, enable, disable],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
