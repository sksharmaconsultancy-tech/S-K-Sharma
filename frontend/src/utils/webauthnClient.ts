/**
 * Iter 601 — WebAuthn / Passkey client helpers (web PWA).
 *
 * The phone's Face ID / Face Unlock / fingerprint NEVER leaves the device:
 * the browser's platform authenticator signs a server challenge and the
 * backend verifies the assertion cryptographically.
 */
import { api } from "@/src/api/client";

function b64uToBuf(s: string): ArrayBuffer {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const bin = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}

function bufToB64u(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function webauthnSupport(): Promise<{ supported: boolean; platform: boolean }> {
  const supported = typeof window !== "undefined" && !!(window as any).PublicKeyCredential;
  let platform = false;
  if (supported) {
    try {
      platform = await (window as any).PublicKeyCredential
        .isUserVerifyingPlatformAuthenticatorAvailable();
    } catch { platform = false; }
  }
  return { supported, platform };
}

/** Register THIS device (first device or approved replacement). */
export async function registerDevice(deviceLabel: string): Promise<string> {
  const { challenge_id, options } = await api<{ challenge_id: string; options: any }>(
    "/attendance/device/register-options", { method: "POST", body: {} });
  const pk: any = { ...options };
  pk.challenge = b64uToBuf(options.challenge);
  pk.user = { ...options.user, id: b64uToBuf(options.user.id) };
  pk.excludeCredentials = (options.excludeCredentials || []).map((c: any) => ({
    ...c, id: b64uToBuf(c.id),
  }));
  const cred: any = await (navigator as any).credentials.create({ publicKey: pk });
  if (!cred) throw new Error("Device registration was cancelled");
  const body = {
    challenge_id,
    device_label: deviceLabel,
    transports: cred.response.getTransports?.() || [],
    credential: {
      id: cred.id,
      rawId: bufToB64u(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64u(cred.response.clientDataJSON),
        attestationObject: bufToB64u(cred.response.attestationObject),
      },
    },
  };
  const r = await api<{ ok: boolean; message: string }>(
    "/attendance/device/register-verify", { method: "POST", body });
  return r.message;
}

/** Authenticate with the registered device → verification_session_id. */
export async function authenticateDevice(): Promise<string> {
  const { challenge_id, options } = await api<{ challenge_id: string; options: any }>(
    "/attendance/device/auth-options", { method: "POST", body: {} });
  const pk: any = { ...options };
  pk.challenge = b64uToBuf(options.challenge);
  pk.allowCredentials = (options.allowCredentials || []).map((c: any) => ({
    ...c, id: b64uToBuf(c.id),
  }));
  const cred: any = await (navigator as any).credentials.get({ publicKey: pk });
  if (!cred) throw new Error("Device verification was cancelled");
  const body = {
    challenge_id,
    credential: {
      id: cred.id,
      rawId: bufToB64u(cred.rawId),
      type: cred.type,
      response: {
        clientDataJSON: bufToB64u(cred.response.clientDataJSON),
        authenticatorData: bufToB64u(cred.response.authenticatorData),
        signature: bufToB64u(cred.response.signature),
        userHandle: cred.response.userHandle ? bufToB64u(cred.response.userHandle) : null,
      },
    },
  };
  const r = await api<{ ok: boolean; verification_session_id: string }>(
    "/attendance/device/auth-verify", { method: "POST", body });
  return r.verification_session_id;
}
