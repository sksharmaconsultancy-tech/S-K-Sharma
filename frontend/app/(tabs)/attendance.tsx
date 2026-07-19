import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  Platform,
  Modal,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import * as Location from "expo-location";
import { MiniMap } from "@/src/components/MiniMap";
import { formatDistance, reverseGeocode } from "@/src/utils/location";
import * as LocalAuthentication from "expo-local-authentication";
import * as Haptics from "expo-haptics";
import { Redirect } from "expo-router";
import { useFocusEffect } from "@react-navigation/native";

import { api } from "@/src/api/client";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { useAuth } from "@/src/context/AuthContext";
import FaceCaptureModal from "@/src/components/FaceCaptureModal";
import PunchFlowModal from "@/src/components/PunchFlowModal";
import LocationPill from "@/src/components/LocationPill";
import {
  authenticateBiometricStrict,
} from "@/src/utils/biometric";
import {
  fingerprintSupported, verifyFingerprint, enrollFingerprint,
} from "@/src/utils/fingerprintGate";
import {
  enqueuePunch, flushQueue, getOfflinePunchEnabled, isOnline, pendingCount, setLastSync,
} from "@/src/utils/offlinePunch";

type Company = {
  name: string;
  office_lat: number;
  office_lng: number;
  geofence_radius_m: number;
};

export default function AttendanceScreen() {
  const { user, refresh } = useAuth();
  const [company, setCompany] = useState<Company | null>(null);
  const [loc, setLoc] = useState<{ latitude: number; longitude: number } | null>(null);
  const [distance, setDistance] = useState<number | null>(null);
  const [inside, setInside] = useState<boolean>(false);
  // Iter 53: location is OFF by default. Flips true only after the user
  // explicitly grants foreground permission (via the banner CTA or the
  // manual Punch button).
  const [locationEnabled, setLocationEnabled] = useState<boolean>(false);
  const [today, setToday] = useState<any>(null);
  const [busy, setBusy] = useState(false);

  // Offline punch (Phase 2) — gated by the firm's "Offline punching" switch.
  const [offlineEnabled, setOfflineEnabled] = useState(false);
  const [online, setOnline] = useState(isOnline());
  const [pendingSync, setPendingSync] = useState(0);

  const refreshPending = useCallback(async () => {
    try { setPendingSync(await pendingCount()); } catch {}
  }, []);

  const doFlush = useCallback(async () => {
    if (!offlineEnabled || !isOnline()) return;
    try {
      const r = await flushQueue(api as any);
      if (r.synced > 0) { await setLastSync(Date.now()); await loadAllRef.current?.(); }
      setPendingSync(r.remaining);
    } catch {}
  }, [offlineEnabled]);

  // Keep a ref to loadAll so the flush callback can refresh the screen.
  const loadAllRef = useRef<null | (() => Promise<void>)>(null);
  // Ref to the latest doFlush so mount-only listeners never go stale.
  const doFlushRef = useRef(doFlush);
  useEffect(() => { doFlushRef.current = doFlush; }, [doFlush]);

  useEffect(() => {
    // MOUNT-ONLY: resolve whether this firm allows offline punching
    // (TTL-cached — see offlinePunch.ts, prevents 429 storms on remounts)
    // and hook up online/offline listeners once.
    getOfflinePunchEnabled(api as any)
      .then((enabled) => setOfflineEnabled(enabled))
      .catch(() => {});
    void refreshPending();
    if (Platform.OS === "web" && typeof window !== "undefined") {
      const on = () => { setOnline(true); void doFlushRef.current(); };
      const off = () => setOnline(false);
      window.addEventListener("online", on);
      window.addEventListener("offline", off);
      return () => {
        window.removeEventListener("online", on);
        window.removeEventListener("offline", off);
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Attempt a sync whenever offline is enabled + we think we're online.
  useEffect(() => { if (offlineEnabled && online) void doFlush(); }, [offlineEnabled, online, doFlush]);

  // Punch poster with offline fallback. When the firm allows offline
  // punching and we're offline (or the request fails on the network), the
  // punch is queued on-device and synced later. Returns {offline:true} then.
  const postPunch = useCallback(
    async (body: Record<string, any>): Promise<any> => {
      const enrich = {
        ...body,
        gps_accuracy_m: body.gps_accuracy_m ?? null,
        battery_level: body.battery_level ?? null,
      };
      if (offlineEnabled && !isOnline()) {
        await enqueuePunch(enrich);
        await refreshPending();
        return { ok: true, offline: true, status: "pending_sync", distance_m: 0 };
      }
      try {
        return await api("/attendance/punch", { method: "POST", body: enrich });
      } catch (e: any) {
        const netErr = /network|failed to fetch|timeout|load failed/i.test(
          String(e?.message || ""),
        );
        if (offlineEnabled && netErr) {
          await enqueuePunch(enrich);
          await refreshPending();
          return { ok: true, offline: true, status: "pending_sync", distance_m: 0 };
        }
        throw e;
      }
    },
    [offlineEnabled, refreshPending],
  );

  // Punch-mode flags — MUST be declared before any effect that lists them
  // as dependencies (previously declared near the render return, which
  // crashed the whole punch page with a TDZ error on phones).
  // effective_auto_punch is server-computed (company × per-user × live-in).
  const autoPunchActive = user?.effective_auto_punch !== false;
  // Iter 64 — GPS punching gate (firm AND user opt-in, default FALSE).
  const gpsPunchAllowed = user?.effective_gps_punch === true;
  const biometricOnlyMode = !gpsPunchAllowed;
  const [toast, setToast] = useState<{ msg: string; kind: "ok" | "err" } | null>(null);
  const [locError, setLocError] = useState<string | null>(null);
  const [address, setAddress] = useState<string | null>(null);
  const [officeAddress, setOfficeAddress] = useState<string | null>(null);
  const [lastRefresh, setLastRefresh] = useState<number>(0);

  const showToast = (msg: string, kind: "ok" | "err") => {
    setToast({ msg, kind });
    setTimeout(() => setToast(null), 3200);
  };

  // Iter 97 — punch photo (selfie) viewer for the employee's own punches.
  const [photo, setPhoto] = useState<{ loading: boolean; b64: string | null; open: boolean }>(
    { loading: false, b64: null, open: false },
  );
  const openPunchPhoto = async (recordId: string) => {
    setPhoto({ loading: true, b64: null, open: true });
    try {
      const r = await api<{ selfie_base64: string | null }>(`/attendance/${recordId}/selfie`);
      setPhoto({ loading: false, b64: r.selfie_base64 || null, open: true });
    } catch {
      setPhoto({ loading: false, b64: null, open: true });
    }
  };

  const loadAll = useCallback(async () => {
    try {
      const [c, t] = await Promise.all([
        api<Company>("/company"),
        api<{ records: any[] }>("/attendance/today"),
      ]);
      setCompany(c);
      setToday(t);
    } catch (e: any) {
      showToast(e.message || "Failed to load", "err");
    }
  }, []);

  // Keep flush callback able to refresh the screen after background syncs.
  useEffect(() => { loadAllRef.current = loadAll; }, [loadAll]);

  const refreshLocation = useCallback(async () => {
    setLocError(null);
    try {
      // Location permission is requested lazily now (Iter 53) — only
      // when the user is on auto-punch (contextual banner) or when they
      // explicitly tap the manual Punch button. Never on app startup.
      const cur = await Location.getForegroundPermissionsAsync();
      if (cur.status !== "granted") {
        const req = await Location.requestForegroundPermissionsAsync();
        if (req.status !== "granted") {
          setLocError("Location permission denied");
          setLocationEnabled(false);
          return false;
        }
      }
      setLocationEnabled(true);
      const l = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      const coords = { latitude: l.coords.latitude, longitude: l.coords.longitude };
      setLoc(coords);
      setLastRefresh(Date.now());
      // Silently persist last-known location so employer's "present but not
      // punched" report can pick this employee up if they're inside the
      // office geofence. Fire and forget — failures should not block the UI.
      api("/me/location-ping", {
        method: "POST",
        body: { latitude: coords.latitude, longitude: coords.longitude },
      }).catch(() => {});
      if (company) {
        const dLat = (coords.latitude - company.office_lat) * Math.PI / 180;
        const dLng = (coords.longitude - company.office_lng) * Math.PI / 180;
        const R = 6371000;
        const s =
          Math.sin(dLat / 2) ** 2 +
          Math.cos((coords.latitude * Math.PI) / 180) *
            Math.cos((company.office_lat * Math.PI) / 180) *
            Math.sin(dLng / 2) ** 2;
        const d = 2 * R * Math.asin(Math.sqrt(s));
        setDistance(d);
        setInside(d <= company.geofence_radius_m);
      }
      // A) reverse-geocode current location to a readable address (fire & forget)
      reverseGeocode(coords.latitude, coords.longitude).then((a) => {
        if (a) setAddress(a);
      });
      return true;
    } catch (e: any) {
      setLocError(e.message || "Location error");
      return false;
    }
  }, [company]);

  // A) reverse-geocode the office address once we know the company
  useEffect(() => {
    if (!company) return;
    reverseGeocode(company.office_lat, company.office_lng).then((a) => {
      if (a) setOfficeAddress(a);
    });
  }, [company]);

  // Iter 100 — GEOFENCE ENTRY REMINDER: when the employee is inside the
  // office premises and has NOT punched in yet, fire a phone notification
  // "You are in office premises — please punch your attendance."
  // NOTE: declared BEFORE the effect below that depends on it (a later
  // edit had this after, crashing the whole punch page with a TDZ error).
  const lastRec = today?.records?.[today.records.length - 1];
  const isPunchedIn = lastRec?.kind === "in";
  const nextKind: "in" | "out" = isPunchedIn ? "out" : "in";

  const insideNotifiedRef = useRef(false);
  const exitNotifiedRef = useRef(false);
  const prevInsideRef = useRef<boolean | null>(null);

  // Iter 176 — rich duty notification (user-specified format):
  //   Good Morning, <Name>
  //   📅 17-Jul-2026 / 🕘 Current Time / 📍 Current Location
  //   Firm Name / Status / [Punch IN / Punch Out]
  const sendDutyNotification = async (punchKind: "in" | "out") => {
    const now = new Date();
    const hr = now.getHours();
    const greet = hr < 12 ? "Good Morning" : hr < 17 ? "Good Afternoon" : "Good Evening";
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const dateTxt = `${String(now.getDate()).padStart(2, "0")}-${months[now.getMonth()]}-${now.getFullYear()}`;
    let hh = now.getHours() % 12; if (hh === 0) hh = 12;
    const ampm = now.getHours() >= 12 ? "PM" : "AM";
    const timeTxt = `${String(hh).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")} ${ampm}`;
    const title = `${greet}, ${user?.name || "Employee"}`;
    const body = [
      `📅 ${dateTxt}`,
      `🕘 Current Time : ${timeTxt}`,
      `📍 ${address || "Current Location"}`,
      company?.name ? `🏢 ${company.name}` : null,
      `Status: ${isPunchedIn ? "Punched In" : "Not Punched In"}`,
      `👉 Tap to Punch ${punchKind.toUpperCase()}`,
    ].filter(Boolean).join("\n");
    try {
      if (Platform.OS === "web") {
        if (typeof window !== "undefined" && "Notification" in window) {
          let perm = window.Notification.permission;
          if (perm !== "granted" && perm !== "denied") {
            perm = await window.Notification.requestPermission();
          }
          if (perm === "granted") {
            // Prefer the service worker so the notification supports the
            // action button + opens the punch screen on tap (PWA).
            let shown = false;
            try {
              const reg = await (navigator as any).serviceWorker?.ready;
              if (reg?.showNotification) {
                await reg.showNotification(title, {
                  body,
                  icon: "/icons/icon-192.png",
                  badge: "/icons/icon-192.png",
                  tag: `duty-${punchKind}`,
                  data: { url: "/attendance" },
                  actions: [{ action: "punch", title: punchKind === "in" ? "Punch IN" : "Punch OUT" }],
                } as any);
                shown = true;
              }
            } catch { /* fall through */ }
            if (!shown) new window.Notification(title, { body });
          }
        }
      } else {
        const Notifications = await import("expo-notifications");
        let perm = await Notifications.getPermissionsAsync();
        if (!perm.granted && perm.canAskAgain) {
          perm = await Notifications.requestPermissionsAsync();
        }
        if (perm.granted) {
          await Notifications.scheduleNotificationAsync({
            content: { title, body, data: { url: "/attendance" } },
            trigger: null,
          });
        }
      }
    } catch {}
    showToast(`${title} — Tap to Punch ${punchKind.toUpperCase()}`, "ok");
  };

  useEffect(() => {
    // Reset when the employee leaves the geofence so a fresh entry
    // (e.g., returning after lunch) triggers the reminder again.
    if (!inside) {
      insideNotifiedRef.current = false;
      // Iter 176 — EXIT notification: left the geofence while still
      // punched IN → "going out from duty" nudge with Punch OUT.
      if (prevInsideRef.current === true && isPunchedIn && !exitNotifiedRef.current) {
        exitNotifiedRef.current = true;
        sendDutyNotification("out");
      }
      prevInsideRef.current = false;
      return;
    }
    exitNotifiedRef.current = false;
    prevInsideRef.current = true;
    if (isPunchedIn || insideNotifiedRef.current) return;
    insideNotifiedRef.current = true;
    // Iter 176 — ARRIVAL notification (come to duty) with Punch IN.
    sendDutyNotification("in");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inside, isPunchedIn]);

  // Iter 99 — FIRST-LOGIN AUTO PUNCH-IN. After an employee registers via
  // the QR/joining form and logs in for the first time, the app marks
  // their first Punch IN automatically (geofence still enforced — the
  // punch goes through the normal handlePunch flow).
  const firstPunchTried = useRef(false);
  useEffect(() => {
    if (firstPunchTried.current) return;
    if (!company || !today) return;
    if ((today.records || []).length > 0) {
      firstPunchTried.current = true;
      return;
    }
    (async () => {
      try {
        const st = await api<{ first_punch_pending: boolean }>(
          "/attendance/first-punch-status",
        );
        firstPunchTried.current = true;
        if (!st.first_punch_pending) return;
        showToast(`Welcome to ${company?.name || "your firm"}! Marking your first Punch IN…`, "ok");
        await handlePunch();
      } catch {
        firstPunchTried.current = true;
      }
    })();
  }, [company, today]);

  // Auto-refresh location every 30 seconds — but only when auto-punch
  // mode is active AND the user has explicitly granted GPS. Manual-punch
  // employees never trigger a background poll; they get a contextual
  // prompt when they tap the Punch button.
  useEffect(() => {
    if (!company) return;
    if (!autoPunchActive) return;
    if (!locationEnabled) return;
    const t = setInterval(() => {
      refreshLocation().catch(() => {});
    }, 30000);
    return () => clearInterval(t);
  }, [company, refreshLocation, autoPunchActive, locationEnabled]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);
  // Iter 72 — Refresh live attendance data when the tab regains focus
  // (e.g. switching from Home to Attendance after an admin update).
  useFocusEffect(useCallback(() => {
    // Iter 77 - Also re-hydrate the user record so admin master-data
    // edits (department, group, name, DOJ, salary, …) reflect on the
    // employee's phone without a re-login.
    void refresh();
    loadAll();
  }, [loadAll, refresh]));

  // Initial location fetch — ONLY for auto-punch users. Manual users don't
  // get a GPS prompt on app startup.
  useEffect(() => {
    if (!company) return;
    if (!autoPunchActive) return;
    // Silent check first (Location.getForegroundPermissionsAsync). If not
    // granted, do NOT prompt on startup — we show the "Turn on Location"
    // banner instead which triggers the prompt on tap.
    (async () => {
      const cur = await Location.getForegroundPermissionsAsync();
      if (cur.status === "granted") {
        setLocationEnabled(true);
        refreshLocation();
      }
    })();
  }, [company, refreshLocation, autoPunchActive]);

  const [faceOpen, setFaceOpen] = useState(false);
  // Iter 176 — guided punch workflow modal (GPS → Worksite → Face →
  // Device Biometric → Save). All manual punch CTAs open this.
  const [flowOpen, setFlowOpen] = useState(false);

  /** Iter 165 — WEB (PWA) fingerprint gate before a punch. Runs only when
   *  the admin requires fingerprint for this employee AND the browser has
   *  a platform authenticator; silently passes otherwise (user choice:
   *  fall back to the normal flow). First use auto-enrolls the device
   *  (WebAuthn create performs fingerprint verification itself). */
  const ensureFingerprintWeb = async (): Promise<boolean> => {
    if (Platform.OS !== "web") return true; // native path prompts already
    if ((user as any)?.effective_fingerprint_required !== true) return true;
    if (!(await fingerprintSupported())) return true; // silent fallback
    const r = await verifyFingerprint(user!.user_id, `Verify fingerprint to punch ${nextKind}`);
    if (!r.ok && r.message === "NOT_ENROLLED") {
      showToast("Set up fingerprint for punching — follow the prompt.", "ok");
      const e = await enrollFingerprint(user!.user_id, user!.name || "");
      if (e.ok) {
        api("/me/fingerprint/enrolled", {
          method: "POST", body: { device: "web-pwa" },
        }).catch(() => {});
        return true; // enrollment itself verified the fingerprint
      }
      showToast(e.message || "Fingerprint setup failed", "err");
      return false;
    }
    if (!r.ok) {
      showToast(r.message || "Fingerprint verification failed", "err");
      return false;
    }
    return true;
  };

  /** Shared punch call. If a selfie base64 is provided the method is "face"
   *  and the selfie is uploaded to the server for the record.
   *
   *  Iter 64 — call site is either:
   *   • Biometric-only mode (firm/user GPS off): route MUST be no-GPS with
   *     both device biometric AND face selfie.
   *   • Auto-punch OFF legacy: no-GPS allowed with face selfie only.
   *   • Auto-punch ON: GPS-verified geofence punch.
   */
  const submitPunch = async (
    method: "fingerprint" | "face",
    selfie_base64?: string,
  ) => {
    // Iter 165 — web fingerprint gate (admin-required, silent fallback).
    if (!(await ensureFingerprintWeb())) return;
    // Biometric-only OR auto-punch off → no-GPS manual punch.
    if (biometricOnlyMode || !autoPunchActive) {
      if (biometricOnlyMode && !selfie_base64) {
        showToast("Face selfie is required in biometric-only mode.", "err");
        return;
      }
      // Iter 99 — GEOFENCE / LOCATION IS MANDATORY IN EVERY CONDITION.
      // Even in biometric-only mode the punch must carry GPS coordinates
      // and (when the firm has a geofence) be physically inside it.
      let punchLoc: { latitude: number; longitude: number } | null = loc;
      if (!punchLoc) {
        const ok = await refreshLocation();
        if (!ok) {
          showToast(
            "Turn on location — geofence verification is mandatory for every punch.",
            "err",
          );
          return;
        }
      }
      // refreshLocation() updates state which may not have flushed yet;
      // read fresh coords directly so the geofence check is reliable.
      try {
        const l = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.High,
        });
        punchLoc = { latitude: l.coords.latitude, longitude: l.coords.longitude };
        setLoc(punchLoc);
      } catch {
        showToast(
          "Couldn't read location — required for punching inside the office zone.",
          "err",
        );
        return;
      }
      if (company && company.office_lat != null && company.office_lng != null) {
        const dLat = (punchLoc.latitude - company.office_lat) * Math.PI / 180;
        const dLng = (punchLoc.longitude - company.office_lng) * Math.PI / 180;
        const R = 6371000;
        const s =
          Math.sin(dLat / 2) ** 2 +
          Math.cos((punchLoc.latitude * Math.PI) / 180) *
            Math.cos((company.office_lat * Math.PI) / 180) *
            Math.sin(dLng / 2) ** 2;
        const d = 2 * R * Math.asin(Math.sqrt(s));
        setDistance(d);
        const insideNow = d <= company.geofence_radius_m;
        setInside(insideNow);
        if (!insideNow) {
          showToast(
            `You're ${formatDistance(d)} outside the office zone. Come inside the geofence to punch.`,
            "err",
          );
          return;
        }
      }
      // In biometric-only mode we ALSO try to run the device biometric to
      // satisfy the "both factors" rule on native. On web we cannot run
      // LocalAuthentication so the selfie is the sole biometric factor.
      if (biometricOnlyMode && Platform.OS !== "web") {
        try {
          const hasHw = await LocalAuthentication.hasHardwareAsync();
          const enrolled = await LocalAuthentication.isEnrolledAsync();
          if (hasHw && enrolled) {
            const bio = await authenticateBiometricStrict(
              `Authenticate to punch ${nextKind}`,
            );
            if (!bio.ok) {
              showToast(bio.message || "Device biometric failed", "err");
              return;
            }
          }
        } catch {
          // Silent — device biometric is best-effort on top of the selfie.
        }
      }
      setBusy(true);
      try {
        // Iter 86 — Response now carries `status` + `approval_required`.
        // Every app-punch is queued for admin review by design, so surface
        // that to the employee instead of a blanket "success" toast.
        const res = await postPunch({
          kind: nextKind,
          latitude: punchLoc?.latitude ?? null,
          longitude: punchLoc?.longitude ?? null,
          biometric_method: method,
          selfie_base64,
          device_info: Platform.OS,
          source: "manual",
        });
        if (Platform.OS !== "web")
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        if (res?.offline) {
          showToast("Attendance saved successfully. Status: Pending Synchronization", "ok");
          await loadAll();
          return;
        }
        const isPending = res?.status === "pending" || res?.approval_required === true;
        const kindTxt = nextKind === "in" ? "Duty IN" : "Duty OUT";
        const firmTxt = company?.name ? ` · ${company.name}` : "";
        showToast(
          isPending
            ? `${kindTxt} submitted (biometric)${firmTxt} — awaiting admin approval`
            : `${kindTxt} successfully (biometric)${firmTxt}`,
          "ok",
        );
        await loadAll();
      } catch (e: any) {
        showToast(e.message || "Punch failed", "err");
      } finally {
        setBusy(false);
      }
      return;
    }

    // -------- Auto-punch ON path — GPS required --------
    // Iter 53: For manual-punch employees the app does NOT track location
    // in the background — we fetch it on-demand when they tap Punch.
    let currentLoc = loc;
    if (!currentLoc) {
      const ok = await refreshLocation();
      if (!ok) {
        showToast(
          "Turn on Location permission to punch. Or disable Auto-punch in Profile for manual biometric mode.",
          "err",
        );
        return;
      }
      // refreshLocation set state; use its latest reading directly
      currentLoc = null; // trigger the local re-read below via state
    }
    if (!loc && !currentLoc) {
      // React may not have flushed setLoc yet; re-fetch quickly
      try {
        const l = await Location.getCurrentPositionAsync({
          accuracy: Location.Accuracy.High,
        });
        currentLoc = { latitude: l.coords.latitude, longitude: l.coords.longitude };
        setLoc(currentLoc);
      } catch {
        showToast("Could not read GPS. Please try again.", "err");
        return;
      }
    }
    const useLoc = loc || currentLoc;
    if (!useLoc) {
      showToast("Fetch your location first", "err");
      return;
    }
    // Re-check geofence with the freshly obtained location
    let insideNow = inside;
    if (company) {
      const dLat = (useLoc.latitude - company.office_lat) * Math.PI / 180;
      const dLng = (useLoc.longitude - company.office_lng) * Math.PI / 180;
      const R = 6371000;
      const s =
        Math.sin(dLat / 2) ** 2 +
        Math.cos((useLoc.latitude * Math.PI) / 180) *
          Math.cos((company.office_lat * Math.PI) / 180) *
          Math.sin(dLng / 2) ** 2;
      const d = 2 * R * Math.asin(Math.sqrt(s));
      insideNow = d <= company.geofence_radius_m;
      setDistance(d);
      setInside(insideNow);
    }
    if (!insideNow) {
      showToast("You're outside the office zone", "err");
      return;
    }
    setBusy(true);
    try {
      const res = await postPunch({
        kind: nextKind,
        latitude: useLoc.latitude,
        longitude: useLoc.longitude,
        biometric_method: method,
        selfie_base64,
        device_info: Platform.OS,
      });
      if (Platform.OS !== "web")
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      if (res?.offline) {
        showToast("Attendance saved successfully. Status: Pending Synchronization", "ok");
        await loadAll();
        return;
      }
      const isPending = res?.status === "pending" || res?.approval_required === true;
      const kindTxt = nextKind === "in" ? "Duty IN" : "Duty OUT";
      const distanceTxt = `${Math.round(res.distance_m)}m from office`;
      const firmTxt = company?.name ? ` · ${company.name}` : "";
      showToast(
        isPending
          ? `${kindTxt} submitted · ${distanceTxt}${firmTxt} — awaiting admin approval`
          : `${kindTxt} successfully · ${distanceTxt}${firmTxt}`,
        "ok",
      );
      await loadAll();
    } catch (e: any) {
      showToast(e.message || "Punch failed", "err");
    } finally {
      setBusy(false);
    }
  };

  const handlePunch = async () => {
    // Iter 176 — every manual punch goes through the guided workflow:
    // GPS Verification → Select Worksite (if applicable) → Face
    // Verification → Optional Device Biometric → Attendance Saved
    // (photo + location + time stored) → Payroll updated.
    setFlowOpen(true);
  };


  const canPunch = !!loc && inside && !busy;
  const canPunchBiometric = !busy;   // manual biometric mode never blocks on GPS

  // Super admins don't punch — redirect them out if they somehow land here.
  if (user?.role === "super_admin") {
    return <Redirect href="/(tabs)" />;
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Text style={styles.h1}>
            {user?.role === "employee" ? "Smart Punch" : "My Attendance"}
          </Text>
          <Text style={styles.sub}>
            {user?.role === "employee"
              ? `${user?.name} · ${company?.name || "—"}`
              : `${user?.name} · Employee Mode — your own attendance only`}
          </Text>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Geofence Phase 2 — offline punch status banner (firm-gated). */}
        {offlineEnabled && (!online || pendingSync > 0) ? (
          <View
            style={[styles.syncBanner, !online ? styles.syncBannerOffline : null]}
            testID="offline-sync-banner"
          >
            <Ionicons
              name={!online ? "cloud-offline-outline" : "cloud-upload-outline"}
              size={18}
              color={!online ? "#B45309" : "#0369A1"}
            />
            <View style={{ flex: 1 }}>
              <Text style={[styles.syncBannerTitle, !online && { color: "#92400E" }]}>
                {!online
                  ? "You're offline — punches will be saved on this device"
                  : `${pendingSync} punch${pendingSync === 1 ? "" : "es"} pending synchronization`}
              </Text>
              {pendingSync > 0 ? (
                <Text style={styles.syncBannerSub}>
                  {!online
                    ? `${pendingSync} saved punch${pendingSync === 1 ? "" : "es"} will sync automatically when internet returns`
                    : "Syncs automatically — or tap Sync now"}
                </Text>
              ) : null}
            </View>
            {online && pendingSync > 0 ? (
              <Pressable onPress={() => void doFlush()} style={styles.syncNowBtn} testID="sync-now-btn">
                <Text style={styles.syncNowTxt}>Sync now</Text>
              </Pressable>
            ) : null}
          </View>
        ) : null}

        {(company as any)?.attendance_punching_enabled === false ? (
          /* Iter 114 — process flow: Bio Matrix Attendance OFF for this firm
             → employees cannot punch; they can only VIEW their service data,
             salary and master data. Admins record punches manually. */
          <View style={styles.bioModeCard} testID="punch-disabled-card">
            <View style={styles.bioIconWrap}>
              <Ionicons name="eye-outline" size={26} color={colors.brandPrimary} />
              <Ionicons name="document-text-outline" size={26} color={colors.brandPrimary} />
            </View>
            <Text style={styles.bioTitle}>Attendance punching is disabled</Text>
            <Text style={styles.bioBody}>
              Your company records attendance manually / via biometric machine.{"\n"}
              You can still view your attendance history, salary details and
              profile from the app.
            </Text>
            <Text style={styles.bioHint}>
              Contact your employer if you believe app punching should be enabled.
            </Text>
          </View>
        ) : biometricOnlyMode ? (
          /* Iter 64 — Biometric-only mode banner (GPS disabled). */
          <View style={styles.bioModeCard} testID="biometric-only-card">
            <View style={styles.bioIconWrap}>
              <Ionicons name="happy-outline" size={26} color={colors.brandPrimary} />
              <Ionicons name="finger-print" size={26} color={colors.brandPrimary} />
            </View>
            <Text style={styles.bioTitle}>Biometric-only punch mode</Text>
            <Text style={styles.bioBody}>
              GPS-based punching is turned off for you.{"\n"}
              Punch In/Out using{"\n"}
              <Text style={styles.bioBold}>Face scan + Fingerprint</Text> together.
            </Text>
            <Text style={styles.bioHint}>
              Ask your employer to enable GPS punching if you need location-based tracking.
            </Text>
          </View>
        ) : (
          <>
        {/* Geofence card */}
        <View style={styles.card} testID="geofence-card">
          <View style={styles.rowBetween}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
              <View style={[styles.pill, inside ? styles.pillOk : styles.pillErr]}>
                <Ionicons
                  name={inside ? "checkmark-circle" : "close-circle"}
                  size={14}
                  color={inside ? colors.onSuccess : colors.onError}
                />
                <Text style={inside ? styles.pillOkTxt : styles.pillErrTxt}>
                  {inside ? "Inside office zone" : "Outside office zone"}
                </Text>
              </View>
            </View>
            <Pressable
              testID="refresh-location"
              onPress={refreshLocation}
              style={styles.refreshBtn}
            >
              <Ionicons name="refresh" size={16} color={colors.brandPrimary} />
            </Pressable>
          </View>
          <View style={styles.mapPlaceholder}>
            {company && loc ? (
              <MiniMap
                office={{
                  lat: company.office_lat,
                  lng: company.office_lng,
                  label: "Office",
                  color: "#218739",
                }}
                me={{
                  lat: loc.latitude,
                  lng: loc.longitude,
                  label: "You",
                  color: "#0F3D3E",
                }}
                height={180}
              />
            ) : (
              <View style={styles.mapFallback}>
                <Ionicons name="location-sharp" size={44} color={colors.brandPrimary} />
                <Text style={styles.mapDist}>Locating…</Text>
              </View>
            )}
            <View style={styles.distRow}>
              <Ionicons name="navigate" size={14} color={colors.onSurfaceSecondary} />
              <Text style={styles.mapDist}>
                {distance !== null ? `${formatDistance(distance)} from office` : "Locating…"}
              </Text>
              {company ? (
                <Text style={styles.mapAllowed}>
                  · allowed {company.geofence_radius_m}m
                </Text>
              ) : null}
            </View>
            {address ? (
              <View style={styles.addrRow}>
                <Ionicons name="pin" size={14} color={colors.brandPrimary} />
                <Text style={styles.addrTxt} numberOfLines={2}>You: {address}</Text>
              </View>
            ) : null}
            {officeAddress ? (
              <View style={styles.addrRow}>
                <Ionicons name="business-outline" size={14} color="#218739" />
                <Text style={styles.addrTxt} numberOfLines={2}>Office: {officeAddress}</Text>
              </View>
            ) : null}
            {lastRefresh > 0 ? (
              <Text style={styles.lastRefresh}>
                Auto-refreshes every 30s · last updated {new Date(lastRefresh).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
              </Text>
            ) : null}
          </View>
          {locError && <Text style={styles.errText}>{locError}</Text>}
        </View>

        {/* Big biometric circle */}
        <View style={styles.circleWrap} testID="biometric-circle">
          <View
            style={[
              styles.circle,
              { borderColor: canPunch ? colors.cta : colors.borderStrong },
            ]}
          >
            <Ionicons
              name={isPunchedIn ? "log-out-outline" : "finger-print"}
              size={64}
              color={canPunch ? colors.cta : colors.onSurfaceTertiary}
            />
            <Text style={styles.circleTxt}>
              {isPunchedIn ? "Ready to Punch Out" : "Ready to Punch In"}
            </Text>
            <Text style={styles.circleSub}>Face / Fingerprint verified</Text>
          </View>
        </View>
          </>
        )}

        {/* Today activity */}
        <Text style={styles.section}>Today&apos;s activity</Text>
        {today?.records?.length ? (
          today.records.map((r: any) => (
            <View key={r.record_id} style={styles.actRow}>
              <View style={styles.actIcon}>
                <Ionicons
                  name={r.kind === "in" ? "arrow-down-circle" : "arrow-up-circle"}
                  size={20}
                  color={colors.onBrandTertiary}
                />
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.actTitle}>
                  Punched {r.kind === "in" ? "In" : "Out"}
                </Text>
                <Text style={styles.actSub}>
                  {(/T(\d{2}:\d{2})/.exec(r.at) || [])[1] || "—"}
                  {typeof r.distance_m === "number" && r.distance_m > 0
                    ? ` · ${Math.round(r.distance_m)}m from office`
                    : ""}
                </Text>
                <View style={{ marginTop: 4 }}>
                  <LocationPill status={r.location_status} distanceM={r.distance_m} />
                </View>
              </View>
              <View style={styles.methodChip}>
                <Ionicons
                  name={r.biometric_method === "face" ? "happy-outline" : "finger-print-outline"}
                  size={12}
                  color={colors.onBrandTertiary}
                />
                <Text style={styles.methodTxt}>{r.biometric_method}</Text>
              </View>
              <Pressable
                onPress={() => openPunchPhoto(r.record_id)}
                style={photoStyles.iconBtn}
                testID={`punch-photo-${r.record_id}`}
              >
                <Ionicons name="camera-outline" size={18} color={colors.brandPrimary} />
              </Pressable>
            </View>
          ))
        ) : (
          <Text style={styles.emptyTxt}>No activity yet.</Text>
        )}

        <View style={{ height: 120 }} />
      </ScrollView>

      {/* Iter 97 — punch selfie viewer */}
      <Modal visible={photo.open} transparent animationType="fade" onRequestClose={() => setPhoto((p) => ({ ...p, open: false }))}>
        <Pressable style={photoStyles.overlay} onPress={() => setPhoto((p) => ({ ...p, open: false }))}>
          <View style={photoStyles.box}>
            <View style={photoStyles.boxHead}>
              <Text style={photoStyles.boxTitle}>Punch Photo</Text>
              <Pressable onPress={() => setPhoto((p) => ({ ...p, open: false }))} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            {photo.loading ? (
              <ActivityIndicator size="large" color={colors.brandPrimary} style={{ marginVertical: 48 }} />
            ) : photo.b64 ? (
              <Image source={{ uri: `data:image/jpeg;base64,${photo.b64}` }} style={photoStyles.img} resizeMode="contain" />
            ) : (
              <View style={photoStyles.noPhoto}>
                <Ionicons name="camera-outline" size={34} color={colors.onSurfaceTertiary} />
                <Text style={photoStyles.noPhotoTxt}>No photo captured for this punch.</Text>
              </View>
            )}
          </View>
        </Pressable>
      </Modal>

      {/* Sticky CTA — hidden entirely when the firm's attendance punching
       *  is OFF (Iter 176 fix: view-only mode must not show punch buttons).
       *  Iter 64 — three modes:
       *   • Biometric-only: single big CTA that opens Face Capture. GPS
       *     is disabled at firm or user level. Both fingerprint (device)
       *     AND face selfie are required.
       *   • Manual + GPS: Face scan + Punch In/Out (needs geofence pass).
       *   • Auto-punch ON: no manual UI — the geofence handler fires in
       *     the background. */}
      {(company as any)?.attendance_punching_enabled === false ? null : biometricOnlyMode ? (
        <View style={styles.stickyBar}>
          <Pressable
            testID="biometric-punch-cta"
            disabled={!canPunchBiometric}
            onPress={() => setFlowOpen(true)}
            style={[
              styles.cta,
              { flex: 1 },
              !canPunchBiometric && { backgroundColor: colors.borderStrong },
            ]}
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="happy-outline" size={20} color="#fff" />
                <Text style={styles.ctaTxt}>
                  {isPunchedIn ? "Punch Out (Face + Fingerprint)" : "Punch In (Face + Fingerprint)"}
                </Text>
              </>
            )}
          </Pressable>
        </View>
      ) : !autoPunchActive ? (
        <View style={styles.stickyBar}>
          <Pressable
            testID="face-cta"
            disabled={busy}
            onPress={() => setFlowOpen(true)}
            style={[
              styles.ctaSecondary,
              !canPunch && { borderColor: colors.borderStrong, opacity: 0.6 },
            ]}
          >
            <Ionicons
              name="happy-outline"
              size={18}
              color={canPunch ? colors.brandPrimary : colors.onSurfaceTertiary}
            />
            <Text
              style={[
                styles.ctaSecondaryTxt,
                !canPunch && { color: colors.onSurfaceTertiary },
              ]}
            >
              Face scan
            </Text>
          </Pressable>
          <Pressable
            testID="punch-cta"
            disabled={!canPunch}
            onPress={handlePunch}
            style={[styles.cta, !canPunch && { backgroundColor: colors.borderStrong }]}
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="finger-print" size={20} color="#fff" />
                <Text style={styles.ctaTxt}>
                  {isPunchedIn ? "Punch Out" : "Punch In"}
                </Text>
              </>
            )}
          </Pressable>
        </View>
      ) : (
        <View style={styles.stickyInfo} testID="auto-punch-info">
          <Ionicons
            name={locationEnabled ? "flash-outline" : "location-outline"}
            size={18}
            color={colors.brandPrimary}
          />
          <View style={{ flex: 1 }}>
            {!locationEnabled ? (
              <>
                <Text style={styles.stickyInfoTitle}>Turn on Location</Text>
                <Text style={styles.stickyInfoSub}>
                  Auto-punch needs your GPS. Tap below to enable location.
                </Text>
              </>
            ) : (
              <>
                <Text style={styles.stickyInfoTitle}>Auto-punch is active</Text>
                <Text style={styles.stickyInfoSub}>
                  {inside
                    ? "Your entry/exit will be recorded automatically. Keep GPS on."
                    : "Move inside the office zone. Punch will fire automatically."}
                </Text>
              </>
            )}
          </View>
          {!locationEnabled ? (
            <Pressable
              testID="enable-location-cta"
              onPress={() => refreshLocation()}
              style={styles.enableGpsBtn}
            >
              <Text style={styles.enableGpsBtnTxt}>Enable</Text>
            </Pressable>
          ) : null}
        </View>
      )}

      <FaceCaptureModal
        visible={faceOpen}
        subtitle={
          isPunchedIn
            ? "Take a quick selfie to punch OUT"
            : "Take a quick selfie to punch IN"
        }
        onCancel={() => setFaceOpen(false)}
        onCapture={async (b64) => {
          setFaceOpen(false);
          await submitPunch("face", b64);
        }}
      />

      {/* Iter 176 — guided punch workflow (GPS → Worksite → Face →
          Biometric → Save). */}
      <PunchFlowModal
        visible={flowOpen}
        kind={nextKind}
        user={user}
        postPunch={postPunch}
        onClose={() => setFlowOpen(false)}
        onDone={() => { void loadAll(); void refreshPending(); }}
      />

      {toast && (
        <View
          testID="punch-toast"
          style={[
            styles.toast,
            { backgroundColor: toast.kind === "ok" ? colors.success : colors.error },
          ]}
        >
          <Ionicons
            name={toast.kind === "ok" ? "checkmark-circle" : "alert-circle"}
            size={16}
            color="#fff"
          />
          <Text style={styles.toastTxt}>{toast.msg}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  syncBanner: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: "#F0F9FF", borderWidth: 1, borderColor: "#BAE6FD",
    borderRadius: radius.md, padding: 12, marginBottom: 12,
  },
  syncBannerOffline: { backgroundColor: "#FFFBEB", borderColor: "#FDE68A" },
  syncBannerTitle: { fontSize: 12.5, fontWeight: "800", color: "#0369A1" },
  syncBannerSub: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  syncNowBtn: {
    backgroundColor: "#0369A1", borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  syncNowTxt: { color: "#fff", fontSize: 11.5, fontWeight: "800" },
  header: { paddingHorizontal: spacing.xl, paddingVertical: spacing.md },
  h1: { fontSize: 26, color: colors.onSurface, fontWeight: "500" },
  sub: { fontSize: type.sm, color: colors.onSurfaceTertiary, marginTop: 2 },
  scroll: { paddingHorizontal: spacing.xl, paddingBottom: 40 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    padding: spacing.lg, borderWidth: 1, borderColor: colors.border,
  },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  pill: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: spacing.md, paddingVertical: 6, borderRadius: radius.pill,
  },
  pillOk: { backgroundColor: colors.success },
  pillErr: { backgroundColor: colors.error },
  pillOkTxt: { color: colors.onSuccess, fontSize: type.sm, fontWeight: "500" },
  pillErrTxt: { color: colors.onError, fontSize: type.sm, fontWeight: "500" },
  refreshBtn: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  mapPlaceholder: {
    marginTop: spacing.md, backgroundColor: colors.brandTertiary,
    borderRadius: radius.md, paddingVertical: spacing.xl, alignItems: "center",
  },
  mapDist: { color: colors.onBrandTertiary, fontSize: type.lg, fontWeight: "500", marginTop: 8 },
  mapAllowed: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  mapFallback: {
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 20,
  },
  distRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 10,
    justifyContent: "center",
    flexWrap: "wrap",
  },
  addrRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 6,
    paddingHorizontal: 8,
    alignSelf: "stretch",
  },
  addrTxt: { color: colors.onSurfaceSecondary, fontSize: 12, flex: 1, lineHeight: 16 },
  lastRefresh: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 8, fontStyle: "italic" },
  errText: { color: colors.error, fontSize: type.sm, marginTop: spacing.sm },
  circleWrap: { alignItems: "center", marginTop: spacing.xl },
  circle: {
    width: 220, height: 220, borderRadius: 110,
    borderWidth: 2, borderStyle: "dashed",
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceSecondary,
  },
  circleTxt: { color: colors.onSurface, fontSize: type.lg, fontWeight: "500", marginTop: spacing.md },
  circleSub: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 4 },
  section: { fontSize: type.lg, color: colors.onSurface, fontWeight: "500", marginTop: spacing.xl, marginBottom: spacing.md },
  actRow: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  actIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  actTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "500" },
  actSub: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  methodChip: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brandTertiary, paddingHorizontal: 8, paddingVertical: 4, borderRadius: radius.pill,
  },
  methodTxt: { color: colors.onBrandTertiary, fontSize: 11, textTransform: "capitalize" },
  emptyTxt: { color: colors.onSurfaceTertiary, fontSize: type.base, paddingVertical: spacing.md },
  stickyBar: {
    position: "absolute", left: 0, right: 0, bottom: 90,
    paddingHorizontal: spacing.xl,
    gap: 10,
  },
  stickyInfo: {
    position: "absolute",
    left: spacing.xl,
    right: spacing.xl,
    bottom: 100,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 14,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    ...shadow.cta,
  },
  stickyInfoTitle: {
    color: colors.brandPrimary,
    fontWeight: "700",
    fontSize: type.base,
  },
  stickyInfoSub: {
    color: colors.onBrandTertiary,
    fontSize: type.sm,
    marginTop: 2,
    lineHeight: 18,
  },
  enableGpsBtn: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 16,
    backgroundColor: colors.brandPrimary,
  },
  enableGpsBtnTxt: {
    color: "#fff",
    fontWeight: "700",
    fontSize: 12,
  },
  cta: {
    backgroundColor: colors.cta, borderRadius: radius.pill,
    paddingVertical: 20, flexDirection: "row", alignItems: "center",
    justifyContent: "center", gap: 10,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700", letterSpacing: 0.5 },
  ctaSecondary: {
    borderRadius: radius.pill,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  ctaSecondaryTxt: {
    color: colors.brandPrimary,
    fontSize: type.base,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
  toast: {
    position: "absolute", left: 24, right: 24, bottom: 170,
    borderRadius: radius.md, paddingVertical: 12, paddingHorizontal: 14,
    flexDirection: "row", alignItems: "center", gap: 8,
  },
  toastTxt: { color: "#fff", fontSize: type.base, flexShrink: 1 },
  bioModeCard: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    marginBottom: spacing.md,
    alignItems: "center",
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  bioIconWrap: {
    flexDirection: "row",
    gap: 16,
    marginBottom: spacing.md,
  },
  bioTitle: {
    color: colors.brandPrimary,
    fontSize: type.lg,
    fontWeight: "800",
    marginBottom: spacing.sm,
  },
  bioBody: {
    color: colors.onSurface,
    fontSize: type.base,
    textAlign: "center",
    lineHeight: 22,
  },
  bioBold: { fontWeight: "800", color: colors.brandPrimary },
  bioHint: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    textAlign: "center",
    marginTop: spacing.md,
    fontStyle: "italic",
  },
});

// Iter 97 — punch selfie viewer styles.
const photoStyles = StyleSheet.create({
  iconBtn: {
    marginLeft: 8,
    width: 34,
    height: 34,
    borderRadius: 17,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brandTertiary,
  },
  overlay: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.55)",
    alignItems: "center",
    justifyContent: "center",
    padding: 24,
  },
  box: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  boxHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: spacing.sm,
  },
  boxTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  img: { width: "100%", height: 340, borderRadius: radius.sm, backgroundColor: "#111" },
  noPhoto: { alignItems: "center", paddingVertical: 40, gap: 8 },
  noPhotoTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center" },
});
