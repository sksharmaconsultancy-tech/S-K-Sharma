/**
 * Iter 295 — accurate GPS fix helper (geofence punching).
 *
 * Browser/PWA geolocation returns a COARSE Wi-Fi/IP-based position on the
 * first reading (often 300–1500 m off), which made employees standing
 * inside the office show as "outside the zone". This helper watches the
 * position stream for up to `timeoutMs` and resolves as soon as a reading
 * reaches `targetAccuracyM`, otherwise returns the BEST fix seen.
 *
 * Iter 306 (user bug — "Could not fetch GPS location" for many employees):
 * on many Android phones / PWAs the position WATCHER never emits a single
 * reading (cold GPS, battery saver, WebView quirks) and the old 8-second
 * timer rejected outright. Now:
 *   • a one-shot Balanced fix runs in PARALLEL as a seed,
 *   • on timeout we fall back to getCurrentPositionAsync, then to the
 *     device's LAST KNOWN position, before giving up,
 *   • overall budget raised to 15 s.
 */
import * as Location from "expo-location";

export type GpsFix = {
  latitude: number;
  longitude: number;
  accuracy: number | null;
  mocked: boolean;
};

function withTimeout<T>(p: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const t = setTimeout(() => reject(new Error("timeout")), ms);
    p.then((v) => { clearTimeout(t); resolve(v); },
      (e) => { clearTimeout(t); reject(e); });
  });
}

export async function getAccurateFix(opts?: {
  targetAccuracyM?: number;
  timeoutMs?: number;
}): Promise<GpsFix> {
  const target = opts?.targetAccuracyM ?? 35;
  const timeoutMs = opts?.timeoutMs ?? 15000;
  let best: GpsFix | null = null;
  let sub: Location.LocationSubscription | null = null;
  let settled = false;

  const toFix = (l: Location.LocationObject): GpsFix => ({
    latitude: l.coords.latitude,
    longitude: l.coords.longitude,
    accuracy:
      typeof l.coords.accuracy === "number" ? Math.round(l.coords.accuracy) : null,
    mocked: (l as any)?.mocked === true || (l.coords as any)?.mocked === true,
  });

  return new Promise<GpsFix>((resolve, reject) => {
    const finish = (fix: GpsFix | null, err?: Error) => {
      if (settled) return;
      settled = true;
      try { sub?.remove(); } catch { /* noop */ }
      clearTimeout(timer);
      if (fix) resolve(fix);
      else reject(err || new Error("Location timeout"));
    };

    const timer = setTimeout(async () => {
      if (settled) return;
      if (best) return finish(best);
      // The watcher produced NOTHING — try the one-shot & last-known
      // fallbacks before failing the punch.
      try {
        const l = await withTimeout(
          Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
          6000,
        );
        return finish(toFix(l));
      } catch { /* continue */ }
      try {
        const lk = await Location.getLastKnownPositionAsync({ maxAge: 5 * 60 * 1000 });
        if (lk) return finish(toFix(lk));
      } catch { /* continue */ }
      finish(null, new Error("Location timeout"));
    }, timeoutMs);

    // Parallel one-shot seed — often returns in 1–2 s where the watcher
    // stays silent (indoors / web). Never rejects the main promise.
    Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced })
      .then((l) => {
        const f = toFix(l);
        if (!best || (f.accuracy ?? 9e9) < (best.accuracy ?? 9e9)) best = f;
        if (f.accuracy != null && f.accuracy <= target) finish(f);
      })
      .catch(() => { /* seed is best-effort */ });

    Location.watchPositionAsync(
      {
        accuracy: Location.Accuracy.BestForNavigation,
        timeInterval: 1000,
        distanceInterval: 0,
      },
      (l) => {
        const fix = toFix(l);
        if (!best || (fix.accuracy ?? 9e9) < (best.accuracy ?? 9e9)) best = fix;
        if (fix.accuracy != null && fix.accuracy <= target) finish(fix);
      },
    )
      .then((s) => {
        sub = s;
        if (settled) { try { s.remove(); } catch { /* noop */ } }
      })
      .catch(async () => {
        // watch unsupported → single high-accuracy reading fallback
        try {
          const l = await Location.getCurrentPositionAsync({
            accuracy: Location.Accuracy.High,
          });
          finish(toFix(l));
        } catch (e: any) {
          if (best) finish(best);
          else finish(null, e);
        }
      });
  });
}
