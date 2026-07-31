/**
 * Iter 417 — SMART GPS ENGINE (Smart Punch PWA GPS Verification revamp).
 *
 * Goals (user spec): 99%+ GPS success without changing the punch workflow.
 *  • Warm-up + background refresh (every 5 s) from the moment the punch
 *    screen opens, so a fix is usually ready before the button is pressed.
 *  • Automatic retry engine: up to 4 attempts with 5 s waits — the
 *    employee never has to hammer a Retry button.
 *  • Accuracy tiers: ≤30 m proceed · 30–100 m keep improving · >100 m retry.
 *  • Pre-flight checks: permission, device location services, network.
 *  • Smart failure diagnosis with exact corrective action.
 *  • Diagnostic logging of every attempt to /api/gps-diagnostics.
 *
 * The single-attempt worker is the battle-tested getAccurateFix()
 * (parallel seed + BestForNavigation watcher + last-known fallback).
 */
import { Platform } from "react-native";
import * as Location from "expo-location";
import { api } from "@/src/api/client";
import { getAccurateFix, GpsFix } from "@/src/utils/accurateLocation";

export type GpsProgress = {
  phase: "preflight" | "searching" | "improving" | "waiting_retry" | "done" | "failed";
  message: string;
  attempt: number;
  maxAttempts: number;
  accuracy: number | null;
  etaSeconds?: number;
};

export type GpsOutcome = {
  ok: boolean;
  fix?: GpsFix;
  reason?: string;       // machine-readable failure reason
  guidance?: string;     // human corrective action
  retryCount: number;
};

const MAX_ATTEMPTS = 4;
const RETRY_WAIT_MS = 5000;
const GOOD_ACCURACY_M = 30;
const USABLE_ACCURACY_M = 100;
const ATTEMPT_TIMEOUT_MS = 30000; // spec: timeout = 30000
const WARM_FIX_MAX_AGE_MS = 5000; // background fix usable for punch if this fresh

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ---------------------------------------------------------------------------
// Failure diagnosis — map the situation to an exact corrective action.
// ---------------------------------------------------------------------------
export function diagnoseGpsFailure(ctx: {
  permission?: Location.PermissionStatus | "unknown";
  canAskAgain?: boolean;
  servicesEnabled?: boolean;
  online?: boolean;
  lastAccuracy?: number | null;
}): { reason: string; guidance: string } {
  if (ctx.online === false) {
    return {
      reason: "network_unavailable",
      guidance: "No internet connection. Switch on mobile data or Wi-Fi and the punch will continue automatically.",
    };
  }
  if (ctx.permission && ctx.permission !== "granted") {
    return ctx.canAskAgain === false
      ? {
          reason: "permission_blocked",
          guidance: Platform.OS === "web"
            ? "Location is blocked for this site. Tap the lock icon in the address bar → Site settings → Location → Allow, then reload."
            : "Location permission is blocked. Open phone Settings → Apps → this app → Permissions → Location → Allow.",
        }
      : {
          reason: "permission_denied",
          guidance: "Please tap Allow on the location popup so your punch can be verified.",
        };
  }
  if (ctx.servicesEnabled === false) {
    return {
      reason: "gps_disabled",
      guidance: "Device GPS is switched OFF. Pull down the quick-settings panel, turn ON Location (High accuracy), then punching continues automatically.",
    };
  }
  if (ctx.lastAccuracy != null && ctx.lastAccuracy > USABLE_ACCURACY_M) {
    return {
      reason: "weak_gps_signal",
      guidance: "GPS signal is weak (probably indoors). Move near a window or step outside for a few seconds — we keep retrying automatically.",
    };
  }
  return {
    reason: "gps_timeout",
    guidance: "Satellites are taking longer than usual (10–30 s is normal). Keep Location ON, move near a window, and we'll keep trying automatically.",
  };
}

// ---------------------------------------------------------------------------
// Diagnostic logging — fire-and-forget, never blocks the punch.
// ---------------------------------------------------------------------------
export function logGpsDiagnostic(payload: {
  outcome: "success" | "weak" | "failed";
  latitude?: number | null;
  longitude?: number | null;
  accuracy?: number | null;
  retry_count?: number;
  failure_reason?: string | null;
  permission_status?: string;
  gps_enabled?: boolean | null;
  mock_location?: boolean;
  context?: string; // "punch" | "warmup" | ...
}) {
  const device =
    Platform.OS === "web"
      ? (typeof navigator !== "undefined" ? navigator.userAgent : "web")
      : `${Platform.OS} ${Platform.Version}`;
  const network_status =
    typeof navigator !== "undefined" && "onLine" in navigator
      ? (navigator.onLine ? "online" : "offline")
      : "unknown";
  api("/gps-diagnostics", {
    method: "POST",
    body: {
      ...payload,
      device,
      platform: Platform.OS,
      network_status,
      gps_time: new Date().toISOString(),
    },
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// SmartGpsEngine — one instance per punch screen/session.
// ---------------------------------------------------------------------------
export class SmartGpsEngine {
  private warmFix: GpsFix | null = null;
  private warmFixAt = 0;
  private warmTimer: ReturnType<typeof setInterval> | null = null;
  private warming = false;
  private disposed = false;

  /** Latest background fix (may be stale — check freshness before use). */
  get latest(): { fix: GpsFix; ageMs: number } | null {
    if (!this.warmFix) return null;
    return { fix: this.warmFix, ageMs: Date.now() - this.warmFixAt };
  }

  /** Start GPS warm-up + 5-second background refresh. Safe to call twice. */
  async warmUp() {
    if (this.warmTimer || this.disposed) return;
    const tick = async () => {
      if (this.warming || this.disposed) return;
      this.warming = true;
      try {
        const perm = await Location.getForegroundPermissionsAsync();
        if (perm.status !== "granted") return;
        const l = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.Balanced,
        });
        this.warmFix = {
          latitude: l.coords.latitude,
          longitude: l.coords.longitude,
          accuracy:
            typeof l.coords.accuracy === "number"
              ? Math.round(l.coords.accuracy)
              : null,
          mocked:
            (l as any)?.mocked === true || (l.coords as any)?.mocked === true,
        };
        this.warmFixAt = Date.now();
      } catch {
        /* warm-up is best-effort */
      } finally {
        this.warming = false;
      }
    };
    tick(); // immediate warm-up
    this.warmTimer = setInterval(tick, 5000);
  }

  /** Stop all background work + release listeners (battery friendly). */
  dispose() {
    this.disposed = true;
    if (this.warmTimer) {
      clearInterval(this.warmTimer);
      this.warmTimer = null;
    }
  }

  /** Pre-flight: permission / device GPS / network. Requests permission
   *  when possible so a single Allow unblocks everything. */
  async preflight(): Promise<{
    ok: boolean;
    permission: Location.PermissionStatus;
    canAskAgain: boolean;
    servicesEnabled: boolean;
    online: boolean;
  }> {
    let perm = await Location.getForegroundPermissionsAsync();
    if (perm.status !== "granted" && perm.canAskAgain) {
      perm = await Location.requestForegroundPermissionsAsync();
    }
    let servicesEnabled = true;
    try {
      servicesEnabled = await Location.hasServicesEnabledAsync();
    } catch {
      /* web: assume enabled */
    }
    const online =
      typeof navigator !== "undefined" && "onLine" in navigator
        ? navigator.onLine
        : true;
    return {
      ok: perm.status === "granted" && servicesEnabled,
      permission: perm.status,
      canAskAgain: perm.canAskAgain,
      servicesEnabled,
      online,
    };
  }

  /**
   * Punch-grade fix with the automatic retry engine.
   * Resolves with the best fresh fix, or a diagnosed failure after
   * MAX_ATTEMPTS. Progress is streamed via onProgress (never blocks UI).
   */
  async getPunchFix(
    onProgress?: (p: GpsProgress) => void,
    isCancelled?: () => boolean,
  ): Promise<GpsOutcome> {
    const report = (p: GpsProgress) => {
      try { onProgress?.(p); } catch { /* noop */ }
    };

    report({
      phase: "preflight", attempt: 0, maxAttempts: MAX_ATTEMPTS,
      accuracy: null, message: "Checking location permission…",
    });
    const pf = await this.preflight();
    if (!pf.ok) {
      const d = diagnoseGpsFailure({
        permission: pf.permission, canAskAgain: pf.canAskAgain,
        servicesEnabled: pf.servicesEnabled, online: pf.online,
      });
      logGpsDiagnostic({
        outcome: "failed", retry_count: 0, failure_reason: d.reason,
        permission_status: pf.permission, gps_enabled: pf.servicesEnabled,
        context: "punch",
      });
      report({ phase: "failed", attempt: 0, maxAttempts: MAX_ATTEMPTS,
        accuracy: null, message: d.guidance });
      return { ok: false, reason: d.reason, guidance: d.guidance, retryCount: 0 };
    }

    // Background monitoring often has a punch-grade fix already.
    const warm = this.latest;
    if (warm && warm.ageMs <= WARM_FIX_MAX_AGE_MS &&
        warm.fix.accuracy != null && warm.fix.accuracy <= GOOD_ACCURACY_M) {
      report({ phase: "done", attempt: 0, maxAttempts: MAX_ATTEMPTS,
        accuracy: warm.fix.accuracy, message: `GPS locked · ±${warm.fix.accuracy}m` });
      logGpsDiagnostic({
        outcome: "success", latitude: warm.fix.latitude,
        longitude: warm.fix.longitude, accuracy: warm.fix.accuracy,
        retry_count: 0, mock_location: warm.fix.mocked,
        permission_status: "granted", gps_enabled: true, context: "punch_warm",
      });
      return { ok: true, fix: warm.fix, retryCount: 0 };
    }

    let best: GpsFix | null = null;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
      if (isCancelled?.()) {
        return { ok: false, reason: "cancelled", guidance: "Cancelled", retryCount: attempt - 1 };
      }
      report({
        phase: "searching", attempt, maxAttempts: MAX_ATTEMPTS,
        accuracy: best?.accuracy ?? null,
        message: attempt === 1
          ? "Getting GPS… searching satellites (10–30 s is normal)"
          : `Retrying GPS automatically… attempt ${attempt}/${MAX_ATTEMPTS}`,
      });
      try {
        const fix = await getAccurateFix({
          targetAccuracyM: GOOD_ACCURACY_M,
          // First attempts fail fast so retries kick in sooner; the final
          // attempt gets the full 30 s budget from the spec.
          timeoutMs: attempt < MAX_ATTEMPTS ? 15000 : ATTEMPT_TIMEOUT_MS,
        });
        if (!best || (fix.accuracy ?? 9e9) < (best.accuracy ?? 9e9)) best = fix;
        if (fix.accuracy != null && fix.accuracy <= GOOD_ACCURACY_M) {
          report({ phase: "done", attempt, maxAttempts: MAX_ATTEMPTS,
            accuracy: fix.accuracy, message: `GPS locked · ±${fix.accuracy}m` });
          logGpsDiagnostic({
            outcome: "success", latitude: fix.latitude, longitude: fix.longitude,
            accuracy: fix.accuracy, retry_count: attempt - 1,
            mock_location: fix.mocked, permission_status: "granted",
            gps_enabled: true, context: "punch",
          });
          return { ok: true, fix, retryCount: attempt - 1 };
        }
        // 30–100 m: usable for geofence (buffered) — accept after attempt 2
        // rather than blocking honest punches on mid-range phones.
        if (fix.accuracy != null && fix.accuracy <= USABLE_ACCURACY_M && attempt >= 2) {
          report({ phase: "done", attempt, maxAttempts: MAX_ATTEMPTS,
            accuracy: fix.accuracy, message: `GPS ready · ±${fix.accuracy}m` });
          logGpsDiagnostic({
            outcome: "weak", latitude: fix.latitude, longitude: fix.longitude,
            accuracy: fix.accuracy, retry_count: attempt - 1,
            mock_location: fix.mocked, permission_status: "granted",
            gps_enabled: true, context: "punch",
          });
          return { ok: true, fix, retryCount: attempt - 1 };
        }
        report({
          phase: "improving", attempt, maxAttempts: MAX_ATTEMPTS,
          accuracy: fix.accuracy,
          message: `Signal ±${fix.accuracy ?? "?"}m — improving accuracy…`,
        });
      } catch {
        logGpsDiagnostic({
          outcome: "failed", retry_count: attempt,
          failure_reason: "attempt_timeout", accuracy: best?.accuracy ?? null,
          permission_status: "granted", gps_enabled: true, context: "punch",
        });
      }
      if (attempt < MAX_ATTEMPTS) {
        report({
          phase: "waiting_retry", attempt, maxAttempts: MAX_ATTEMPTS,
          accuracy: best?.accuracy ?? null, etaSeconds: RETRY_WAIT_MS / 1000,
          message: "Weak signal — retrying automatically in 5 seconds…",
        });
        await sleep(RETRY_WAIT_MS);
      }
    }

    // All attempts done — accept ANY fix we saw (geofence maths already
    // buffers by accuracy) rather than blocking an honest punch.
    if (best) {
      report({ phase: "done", attempt: MAX_ATTEMPTS, maxAttempts: MAX_ATTEMPTS,
        accuracy: best.accuracy, message: `Using best available GPS · ±${best.accuracy ?? "?"}m` });
      logGpsDiagnostic({
        outcome: "weak", latitude: best.latitude, longitude: best.longitude,
        accuracy: best.accuracy, retry_count: MAX_ATTEMPTS,
        mock_location: best.mocked, permission_status: "granted",
        gps_enabled: true, context: "punch_best_effort",
      });
      return { ok: true, fix: best, retryCount: MAX_ATTEMPTS };
    }
    const d = diagnoseGpsFailure({ permission: "granted" as any, servicesEnabled: true,
      online: typeof navigator !== "undefined" ? navigator.onLine : true,
      lastAccuracy: null });
    logGpsDiagnostic({
      outcome: "failed", retry_count: MAX_ATTEMPTS, failure_reason: d.reason,
      permission_status: "granted", gps_enabled: true, context: "punch",
    });
    report({ phase: "failed", attempt: MAX_ATTEMPTS, maxAttempts: MAX_ATTEMPTS,
      accuracy: null, message: d.guidance });
    return { ok: false, reason: d.reason, guidance: d.guidance, retryCount: MAX_ATTEMPTS };
  }
}

// ---------------------------------------------------------------------------
// Convenience singleton for legacy punch paths (attendance tab): drop-in
// replacement for getAccurateFix() with the automatic retry engine.
// ---------------------------------------------------------------------------
let _sharedEngine: SmartGpsEngine | null = null;

export async function smartPunchFix(): Promise<GpsFix> {
  if (!_sharedEngine) _sharedEngine = new SmartGpsEngine();
  const out = await _sharedEngine.getPunchFix();
  if (!out.ok || !out.fix) throw new Error(out.guidance || "GPS unavailable");
  return out.fix;
}
