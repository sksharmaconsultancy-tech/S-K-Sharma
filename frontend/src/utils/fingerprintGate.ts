/**
 * Iter 165 — Unified device-fingerprint gate for the Employee PWA.
 *
 * WEB (PWA):    WebAuthn platform authenticator (fingerprint / face unlock
 *               via the browser) — device-local enroll + verify. Credential
 *               id is kept in localStorage per user; the private key never
 *               leaves the phone's secure hardware.
 * NATIVE:       expo-local-authentication (existing behaviour).
 * UNSUPPORTED:  silent fallback — callers treat {supported:false} as "skip".
 */
import { Platform } from "react-native";
import * as LocalAuthentication from "expo-local-authentication";

const CRED_KEY = (userId: string) => `sks_fp_cred_${userId}`;

function b64urlEncode(buf: ArrayBuffer): string {
  let s = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.byteLength; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlDecode(str: string): Uint8Array {
  const b64 = str.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64 + "=".repeat((4 - (b64.length % 4)) % 4));
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
function randomChallenge(): Uint8Array {
  const c = new Uint8Array(32);
  crypto.getRandomValues(c);
  return c;
}

/** Is a user-verifying fingerprint/biometric available on this device? */
export async function fingerprintSupported(): Promise<boolean> {
  if (Platform.OS === "web") {
    try {
      if (typeof window === "undefined" || !("PublicKeyCredential" in window)) return false;
      return await (window as any).PublicKeyCredential
        .isUserVerifyingPlatformAuthenticatorAvailable();
    } catch { return false; }
  }
  try {
    const [hw, enrolled] = await Promise.all([
      LocalAuthentication.hasHardwareAsync(),
      LocalAuthentication.isEnrolledAsync(),
    ]);
    return hw && enrolled;
  } catch { return false; }
}

/** Web only — has this user enrolled a WebAuthn credential on THIS device?
 *  (Native devices are "enrolled" at OS level, nothing app-side to store.) */
export function fingerprintEnrolled(userId: string): boolean {
  if (Platform.OS !== "web") return true;
  try { return !!window.localStorage.getItem(CRED_KEY(userId)); }
  catch { return false; }
}

export type FpResult = { ok: boolean; supported: boolean; message?: string };

/** Enroll the device fingerprint for this user (web = WebAuthn create). */
export async function enrollFingerprint(
  userId: string, displayName: string,
): Promise<FpResult> {
  if (!(await fingerprintSupported())) {
    return { ok: false, supported: false };
  }
  if (Platform.OS !== "web") {
    // Native — OS biometrics already enrolled; just confirm once.
    const r = await LocalAuthentication.authenticateAsync({
      promptMessage: "Confirm fingerprint to enable",
      cancelLabel: "Cancel",
      disableDeviceFallback: false,
    });
    return { ok: r.success, supported: true, message: r.success ? undefined : "Cancelled" };
  }
  try {
    const cred: any = await navigator.credentials.create({
      publicKey: {
        challenge: randomChallenge(),
        rp: { name: "S.K. Sharma & Co.", id: window.location.hostname },
        user: {
          id: new TextEncoder().encode(userId),
          name: displayName || userId,
          displayName: displayName || userId,
        },
        pubKeyCredParams: [
          { type: "public-key", alg: -7 },    // ES256
          { type: "public-key", alg: -257 },  // RS256
        ],
        authenticatorSelection: {
          authenticatorAttachment: "platform",
          userVerification: "required",
          residentKey: "preferred",
        },
        timeout: 60000,
        attestation: "none",
      },
    });
    if (!cred?.rawId) return { ok: false, supported: true, message: "Enrollment failed" };
    window.localStorage.setItem(CRED_KEY(userId), b64urlEncode(cred.rawId));
    return { ok: true, supported: true };
  } catch (e: any) {
    return {
      ok: false, supported: true,
      message: e?.name === "NotAllowedError" ? "Cancelled" : (e?.message || "Enrollment failed"),
    };
  }
}

/** Verify the user's fingerprint (web = WebAuthn get with the stored
 *  credential; native = LocalAuthentication prompt). */
export async function verifyFingerprint(
  userId: string, reason: string,
): Promise<FpResult> {
  if (!(await fingerprintSupported())) {
    return { ok: false, supported: false };
  }
  if (Platform.OS !== "web") {
    const r = await LocalAuthentication.authenticateAsync({
      promptMessage: reason,
      cancelLabel: "Cancel",
      disableDeviceFallback: false,
    });
    return { ok: r.success, supported: true, message: r.success ? undefined : "Fingerprint failed" };
  }
  const stored = (() => {
    try { return window.localStorage.getItem(CRED_KEY(userId)); } catch { return null; }
  })();
  if (!stored) return { ok: false, supported: true, message: "NOT_ENROLLED" };
  try {
    const assertion: any = await navigator.credentials.get({
      publicKey: {
        challenge: randomChallenge(),
        rpId: window.location.hostname,
        allowCredentials: [{ type: "public-key", id: b64urlDecode(stored) }],
        userVerification: "required",
        timeout: 60000,
      },
    });
    return { ok: !!assertion, supported: true, message: assertion ? undefined : "Fingerprint failed" };
  } catch (e: any) {
    // Credential may have been wiped on-device → let caller re-enroll.
    if (e?.name === "InvalidStateError") {
      try { window.localStorage.removeItem(CRED_KEY(userId)); } catch { /* noop */ }
      return { ok: false, supported: true, message: "NOT_ENROLLED" };
    }
    return {
      ok: false, supported: true,
      message: e?.name === "NotAllowedError" ? "Fingerprint cancelled" : (e?.message || "Fingerprint failed"),
    };
  }
}

/** Remove the locally stored web credential (e.g. admin turned the
 *  requirement off, or user wants to re-enroll). */
export function clearFingerprintEnrollment(userId: string): void {
  if (Platform.OS !== "web") return;
  try { window.localStorage.removeItem(CRED_KEY(userId)); } catch { /* noop */ }
}
