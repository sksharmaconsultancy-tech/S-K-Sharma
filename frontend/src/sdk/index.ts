/**
 * Iter 418 — SMART PUNCH NATIVE SDK BRIDGE.
 *
 * A capability layer between the existing PWA UI and the device:
 *   • Native builds (APK/IPA): Expo native modules — GPS (SmartGpsEngine),
 *     device biometrics (expo-local-authentication), secure storage,
 *     background sync (expo-background-task → WorkManager on Android /
 *     BGTaskScheduler on iOS), device telemetry (expo-device / battery /
 *     network) and root detection.
 *   • Web PWA: graceful fallback to browser APIs — WebAuthn biometrics,
 *     navigator.onLine / connection, Battery API, localStorage queue,
 *     online-event + foreground auto-sync.
 *
 * The attendance workflow is UNCHANGED — the SDK only makes each step
 * more reliable and adds offline caching + diagnostics.
 */
import { Platform } from "react-native";
import * as Device from "expo-device";
import * as Battery from "expo-battery";
import * as Network from "expo-network";
import * as LocalAuthentication from "expo-local-authentication";
import { verifyFingerprint, fingerprintSupported } from "@/src/utils/fingerprintGate";
import { SmartGpsEngine, smartPunchFix, logGpsDiagnostic } from "@/src/utils/smartGps";
import {
  enqueuePunch, flushPunchQueue, queuedPunchCount, startAutoSync,
  onSyncResult, offlinePunchAllowed,
} from "./offlineQueue";

export type SdkTelemetry = {
  device_model: string;
  os_version: string;
  platform: string;
  battery_level: number | null;   // 0-100
  network_type: string;           // wifi | cellular | none | unknown
  rooted: boolean | null;         // null = not determinable (web / iOS)
  is_native: boolean;
};

/** Device model / OS / battery / network / root status — never throws. */
export async function getTelemetry(): Promise<SdkTelemetry> {
  const isNative = Platform.OS !== "web";
  let battery: number | null = null;
  try {
    if (isNative) {
      const lvl = await Battery.getBatteryLevelAsync();
      if (typeof lvl === "number" && lvl >= 0) battery = Math.round(lvl * 100);
    } else if (typeof navigator !== "undefined" && (navigator as any).getBattery) {
      const b = await (navigator as any).getBattery();
      battery = Math.round((b?.level ?? -0.01) * 100);
      if (battery < 0) battery = null;
    }
  } catch { /* best-effort */ }

  let network = "unknown";
  try {
    if (isNative) {
      const st = await Network.getNetworkStateAsync();
      network = st.isConnected
        ? String(st.type || "unknown").toLowerCase()
        : "none";
    } else if (typeof navigator !== "undefined") {
      const conn = (navigator as any).connection;
      network = !navigator.onLine
        ? "none"
        : (conn?.effectiveType || conn?.type || "online");
    }
  } catch { /* best-effort */ }

  let rooted: boolean | null = null;
  try {
    if (isNative && (Device as any).isRootedExperimentalAsync) {
      rooted = await (Device as any).isRootedExperimentalAsync();
    }
  } catch { rooted = null; }

  return {
    device_model: isNative
      ? `${Device.manufacturer || ""} ${Device.modelName || ""}`.trim() || Platform.OS
      : (typeof navigator !== "undefined" ? navigator.userAgent.slice(0, 120) : "web"),
    os_version: isNative
      ? `${Device.osName || Platform.OS} ${Device.osVersion || Platform.Version}`
      : "web",
    platform: Platform.OS,
    battery_level: battery,
    network_type: network,
    rooted,
    is_native: isNative,
  };
}

/** Device biometric authentication — native LocalAuthentication first,
 *  WebAuthn fallback on browsers. */
export async function biometricAuth(userId: string, reason = "Verify it's you to punch"):
    Promise<{ ok: boolean; method: string }> {
  try {
    if (Platform.OS !== "web") {
      const hasHw = await LocalAuthentication.hasHardwareAsync();
      const enrolled = await LocalAuthentication.isEnrolledAsync();
      if (!hasHw || !enrolled) return { ok: false, method: "unsupported" };
      const res = await LocalAuthentication.authenticateAsync({ promptMessage: reason });
      return { ok: res.success, method: "native" };
    }
    const supported = await fingerprintSupported();
    if (!supported) return { ok: false, method: "unsupported" };
    const r = await verifyFingerprint(userId, reason);
    return { ok: r.ok, method: "webauthn" };
  } catch {
    return { ok: false, method: "error" };
  }
}

export const SmartPunchSDK = {
  /** Runtime capability report (used for diagnostics + graceful fallback). */
  async capabilities() {
    const t = await getTelemetry();
    return {
      native: t.is_native,
      gps: true,
      biometric: t.is_native
        ? await LocalAuthentication.hasHardwareAsync().catch(() => false)
        : await fingerprintSupported().catch(() => false),
      offline_queue: true,
      background_sync: t.is_native, // WorkManager/BGTask on builds only
      telemetry: t,
    };
  },
  telemetry: getTelemetry,
  biometricAuth,
  gps: { SmartGpsEngine, smartPunchFix },
  offline: {
    enqueuePunch,
    flush: flushPunchQueue,
    count: queuedPunchCount,
    startAutoSync,
    onSyncResult,
    allowed: offlinePunchAllowed,
  },
  logDiagnostic: logGpsDiagnostic,
};

export default SmartPunchSDK;
