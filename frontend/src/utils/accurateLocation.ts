/**
 * Iter 295 — accurate GPS fix helper (geofence punching).
 *
 * Browser/PWA geolocation returns a COARSE Wi-Fi/IP-based position on the
 * first reading (often 300–1500 m off), which made employees standing
 * inside the office show as "outside the zone". This helper watches the
 * position stream for up to `timeoutMs` and resolves as soon as a reading
 * reaches `targetAccuracyM`, otherwise returns the BEST fix seen.
 */
import * as Location from "expo-location";

export type GpsFix = {
  latitude: number;
  longitude: number;
  accuracy: number | null;
  mocked: boolean;
};

export async function getAccurateFix(opts?: {
  targetAccuracyM?: number;
  timeoutMs?: number;
}): Promise<GpsFix> {
  const target = opts?.targetAccuracyM ?? 35;
  const timeoutMs = opts?.timeoutMs ?? 8000;
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
    const timer = setTimeout(() => finish(best), timeoutMs);

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
          finish(null, e);
        }
      });
  });
}
