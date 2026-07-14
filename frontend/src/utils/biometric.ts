import * as LocalAuthentication from "expo-local-authentication";
import { Platform } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";

const ENABLED_KEY = "sks_biometric_enabled_v1";
const PREF_KEY = "sks_biometric_pref_v1";

/**
 * Which biometric factor the user has explicitly chosen for punch
 * authentication.  Iter 93 — the DEFAULT (nothing saved) is
 * "fingerprint" whenever the device has a fingerprint sensor;
 * face-only devices fall back to "any" so they can still punch.
 * "face" or "fingerprint" force a single factor: if the requested
 * factor is not enrolled we block the punch and surface a hint so the
 * operator can either enrol it on-device or switch the preference.
 */
export type BiometricPreference = "any" | "face" | "fingerprint";

/**
 * Biometric availability + capability report.
 * `supported` reflects both hardware presence and at least one enrolled
 * biometric on the device. On web this always returns { supported: false }.
 */
export type BiometricCapability = {
  supported: boolean;
  hasHardware: boolean;
  enrolled: boolean;
  types: LocalAuthentication.AuthenticationType[];
  primaryLabel: string; // e.g. "Face ID", "Fingerprint", "Iris"
};

export async function getBiometricCapability(): Promise<BiometricCapability> {
  if (Platform.OS === "web") {
    return {
      supported: false,
      hasHardware: false,
      enrolled: false,
      types: [],
      primaryLabel: "Biometric",
    };
  }
  try {
    const [hasHardware, enrolled, types] = await Promise.all([
      LocalAuthentication.hasHardwareAsync(),
      LocalAuthentication.isEnrolledAsync(),
      LocalAuthentication.supportedAuthenticationTypesAsync(),
    ]);
    const primaryLabel = pickPrimaryLabel(types);
    return {
      supported: hasHardware && enrolled,
      hasHardware,
      enrolled,
      types,
      primaryLabel,
    };
  } catch {
    return {
      supported: false,
      hasHardware: false,
      enrolled: false,
      types: [],
      primaryLabel: "Biometric",
    };
  }
}

function pickPrimaryLabel(
  types: LocalAuthentication.AuthenticationType[],
): string {
  if (
    types.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION)
  ) {
    return Platform.OS === "ios" ? "Face ID" : "Face Unlock";
  }
  if (types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT)) {
    return Platform.OS === "ios" ? "Touch ID" : "Fingerprint";
  }
  if (types.includes(LocalAuthentication.AuthenticationType.IRIS)) {
    return "Iris";
  }
  return "Biometric";
}

/** Prompts the device biometric sheet. Returns true on success. */
export async function authenticateBiometric(reason: string): Promise<boolean> {
  const res = await authenticateBiometricStrict(reason);
  return res.ok;
}

/**
 * Strict biometric authentication that honours the user's Face-OR-
 * Fingerprint preference.  Returns a structured result so the caller
 * can render a specific error (e.g. "Face not enrolled — enrol Face
 * Unlock or switch the preference to Fingerprint").
 */
export async function authenticateBiometricStrict(
  reason: string,
): Promise<
  | { ok: true; used: "face" | "fingerprint" | "any" }
  | { ok: false; reason: "web" | "no_hw" | "not_enrolled" | "wrong_factor" | "cancelled" | "error"; message: string }
> {
  if (Platform.OS === "web") {
    return { ok: false, reason: "web", message: "Biometric is not available on web." };
  }
  try {
    const [hasHw, enrolled, types] = await Promise.all([
      LocalAuthentication.hasHardwareAsync(),
      LocalAuthentication.isEnrolledAsync(),
      LocalAuthentication.supportedAuthenticationTypesAsync(),
    ]);
    if (!hasHw) {
      return { ok: false, reason: "no_hw", message: "This device has no biometric hardware." };
    }
    if (!enrolled) {
      return {
        ok: false,
        reason: "not_enrolled",
        message: "No biometrics enrolled on this device. Add a face or fingerprint in the device settings first.",
      };
    }
    const pref = await getBiometricPreference();
    const hasFace = types.includes(
      LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION,
    );
    const hasFinger = types.includes(
      LocalAuthentication.AuthenticationType.FINGERPRINT,
    );
    if (pref === "face" && !hasFace) {
      return {
        ok: false,
        reason: "wrong_factor",
        message:
          "Face Unlock isn't enrolled on this device. Enrol a face or switch the preference to Fingerprint.",
      };
    }
    if (pref === "fingerprint" && !hasFinger) {
      return {
        ok: false,
        reason: "wrong_factor",
        message:
          "Fingerprint isn't enrolled on this device. Enrol a fingerprint or switch the preference to Face.",
      };
    }
    // When the user forces a single factor, disable the device
    // fallback so the OS cannot silently swap to a PIN / other biometric.
    const strictMode = pref !== "any";
    const res = await LocalAuthentication.authenticateAsync({
      promptMessage: reason,
      cancelLabel: strictMode ? "Cancel" : "Use PIN instead",
      disableDeviceFallback: strictMode,
      fallbackLabel: strictMode ? undefined : "Use PIN",
    });
    if (res.success) {
      return { ok: true, used: pref };
    }
    // res.error can be "user_cancel" / "system_cancel" / "authentication_failed"
    // etc. — surface the raw code so callers can decide whether to retry.
    if ((res as any).error === "user_cancel") {
      return { ok: false, reason: "cancelled", message: "Biometric cancelled." };
    }
    return {
      ok: false,
      reason: "error",
      message: (res as any).warning || "Biometric authentication failed.",
    };
  } catch (e: any) {
    return { ok: false, reason: "error", message: e?.message || "Biometric error." };
  }
}

export async function isBiometricEnabled(): Promise<boolean> {
  try {
    const v = await AsyncStorage.getItem(ENABLED_KEY);
    return v === "1";
  } catch {
    return false;
  }
}

export async function setBiometricEnabled(enabled: boolean): Promise<void> {
  try {
    if (enabled) {
      await AsyncStorage.setItem(ENABLED_KEY, "1");
    } else {
      await AsyncStorage.removeItem(ENABLED_KEY);
    }
  } catch {}
}

/** Reads the persisted single-factor preference.
 *
 * Iter 93 (user request) — DEFAULT for all employees is now
 * "fingerprint" (fingerprint-only punching). If the device has no
 * fingerprint hardware (e.g. Face-ID-only iPhones) we fall back to
 * "any" so those employees are not locked out of punching; they can
 * still explicitly pick "Face only" in Biometric Preferences. */
export async function getBiometricPreference(): Promise<BiometricPreference> {
  try {
    const v = await AsyncStorage.getItem(PREF_KEY);
    if (v === "face" || v === "fingerprint" || v === "any") return v;
    // No explicit choice saved → fingerprint by default when possible.
    if (Platform.OS !== "web") {
      try {
        const types = await LocalAuthentication.supportedAuthenticationTypesAsync();
        if (types.includes(LocalAuthentication.AuthenticationType.FINGERPRINT)) {
          return "fingerprint";
        }
      } catch {}
    }
    return "any";
  } catch {
    return "any";
  }
}

/** Persists the single-factor preference. */
export async function setBiometricPreference(
  pref: BiometricPreference,
): Promise<void> {
  try {
    await AsyncStorage.setItem(PREF_KEY, pref);
  } catch {}
}
