/**
 * Biometric Preferences — Iter 70.
 *
 * Employees pick which single biometric factor the app should use when
 * punching in / out.  The chosen mode is persisted on-device via
 * AsyncStorage and honoured by `authenticateBiometricStrict()` in
 * `src/utils/biometric.ts`.
 *
 * Modes:
 *   • Any (default) — whatever is enrolled on the device.
 *   • Face only     — refuses the punch if Face Unlock isn't enrolled.
 *   • Fingerprint only — refuses the punch if fingerprint isn't enrolled.
 *
 * We surface the current device capability up-front so an employee
 * doesn't accidentally lock themselves out by picking a factor that
 * isn't enrolled.  A quick "Test now" button runs a live prompt so the
 * choice can be validated before the next real punch.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as LocalAuthentication from "expo-local-authentication";

import { colors, radius, shadow, spacing, type } from "@/src/theme";
import {
  authenticateBiometricStrict,
  BiometricPreference,
  getBiometricCapability,
  getBiometricPreference,
  setBiometricPreference,
} from "@/src/utils/biometric";

export default function BiometricPrefsScreen() {
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [pref, setPref] = useState<BiometricPreference>("any");
  const [saving, setSaving] = useState<BiometricPreference | null>(null);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "err"; text: string } | null>(null);
  const [capability, setCapability] = useState<{
    hasFace: boolean;
    hasFinger: boolean;
    hasIris: boolean;
    enrolled: boolean;
    hasHardware: boolean;
  }>({
    hasFace: false,
    hasFinger: false,
    hasIris: false,
    enrolled: false,
    hasHardware: false,
  });

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [cur, cap] = await Promise.all([
        getBiometricPreference(),
        getBiometricCapability(),
      ]);
      setPref(cur);
      setCapability({
        hasFace: cap.types.includes(
          LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION,
        ),
        hasFinger: cap.types.includes(
          LocalAuthentication.AuthenticationType.FINGERPRINT,
        ),
        hasIris: cap.types.includes(
          LocalAuthentication.AuthenticationType.IRIS,
        ),
        enrolled: cap.enrolled,
        hasHardware: cap.hasHardware,
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const choose = async (next: BiometricPreference) => {
    if (next === pref) return;
    setSaving(next);
    setMsg(null);
    try {
      await setBiometricPreference(next);
      setPref(next);
      setMsg({
        tone: "ok",
        text:
          next === "any"
            ? "Preference cleared — the app will use any enrolled biometric."
            : next === "face"
              ? "Face-only mode saved."
              : "Fingerprint-only mode saved.",
      });
    } catch (e: any) {
      setMsg({ tone: "err", text: e?.message || "Save failed." });
    } finally {
      setSaving(null);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setMsg(null);
    try {
      const res = await authenticateBiometricStrict(
        "Testing your biometric preference",
      );
      if (res.ok) {
        setMsg({ tone: "ok", text: "Success — biometric ready for punching." });
      } else {
        setMsg({ tone: "err", text: res.message });
      }
    } finally {
      setTesting(false);
    }
  };

  if (Platform.OS === "web") {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()} hitSlop={8}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <View style={{ flex: 1, alignItems: "center" }}>
              <Text style={styles.h1}>Biometric preferences</Text>
            </View>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>
        <View style={styles.forbid}>
          <Ionicons name="phone-portrait-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbidT}>Open this on your phone</Text>
          <Text style={styles.forbidHint}>
            Biometric options are device-level — set this from the mobile app.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Biometric preferences</Text>
            <Text style={styles.hsub}>Face-only · Fingerprint-only · Any</Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        {/* Device capability */}
        <View style={styles.card}>
          <Text style={styles.section}>This device</Text>
          {loading ? (
            <ActivityIndicator />
          ) : (
            <>
              <CapRow
                icon="hardware-chip-outline"
                label="Biometric hardware"
                value={capability.hasHardware ? "Detected" : "Missing"}
                ok={capability.hasHardware}
              />
              <CapRow
                icon="finger-print-outline"
                label="Fingerprint enrolled"
                value={capability.hasFinger ? "Yes" : "No"}
                ok={capability.hasFinger}
              />
              <CapRow
                icon="happy-outline"
                label="Face enrolled"
                value={capability.hasFace ? "Yes" : "No"}
                ok={capability.hasFace}
              />
              {capability.hasIris ? (
                <CapRow
                  icon="eye-outline"
                  label="Iris enrolled"
                  value="Yes"
                  ok
                />
              ) : null}
              {!capability.enrolled ? (
                <Text style={styles.warnHint}>
                  No biometrics enrolled on this device. Open the phone&apos;s
                  system settings and enrol a face or fingerprint before
                  picking a single-factor mode.
                </Text>
              ) : null}
            </>
          )}
        </View>

        {/* Preference chooser */}
        <View style={styles.card}>
          <Text style={styles.section}>Preferred factor for punching</Text>
          <Text style={styles.hint}>
            Choose the exact biometric the app should use when you punch in
            or out. Locking one factor keeps the flow consistent even if
            multiple biometrics are enrolled on the device.
          </Text>

          <Option
            active={pref === "any"}
            icon="shield-checkmark-outline"
            title="Any enrolled biometric"
            subtitle="Whichever face or fingerprint is enrolled on the device."
            onPress={() => choose("any")}
            saving={saving === "any"}
          />
          <Option
            active={pref === "face"}
            icon="happy-outline"
            title="Face only"
            subtitle={
              capability.hasFace
                ? "Punching will only accept Face Unlock. Fingerprint prompts are refused."
                : "Face isn't enrolled on this device — enrol one first."
            }
            onPress={() => choose("face")}
            saving={saving === "face"}
            disabled={!capability.hasFace}
          />
          <Option
            active={pref === "fingerprint"}
            icon="finger-print-outline"
            title="Fingerprint only"
            subtitle={
              capability.hasFinger
                ? "Default — punching will only accept your fingerprint. Face prompts are refused."
                : "Fingerprint isn't enrolled on this device — enrol one first."
            }
            onPress={() => choose("fingerprint")}
            saving={saving === "fingerprint"}
            disabled={!capability.hasFinger}
          />
        </View>

        {/* Test button */}
        <View style={styles.card}>
          <Text style={styles.section}>Test now</Text>
          <Text style={styles.hint}>
            Run a live biometric prompt to confirm the selected factor is
            working. This won&apos;t record a punch.
          </Text>
          <Pressable
            onPress={runTest}
            disabled={testing}
            style={[styles.primaryBtn, testing && styles.btnDisabled]}
          >
            {testing ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="play-circle-outline" size={18} color="#fff" />
                <Text style={styles.primaryBtnTxt}>Prompt biometric</Text>
              </>
            )}
          </Pressable>
          {msg ? (
            <View
              style={[
                styles.msgBox,
                msg.tone === "err" ? styles.errBox : styles.okBox,
              ]}
            >
              <Ionicons
                name={msg.tone === "err" ? "alert-circle" : "checkmark-circle"}
                size={16}
                color={msg.tone === "err" ? "#B0002B" : "#0F7B4F"}
              />
              <Text
                style={
                  msg.tone === "err" ? styles.errTxt : styles.okTxt
                }
              >
                {msg.text}
              </Text>
            </View>
          ) : null}
        </View>

        <Text style={styles.footHint}>
          Tip — the operator can still fall back to their PIN for punching if
          biometrics are unavailable, but only in &quot;Any&quot; mode. Locked
          Face-only or Fingerprint-only modes will refuse the punch if the
          requested factor is missing on the device.
        </Text>
      </ScrollView>
    </View>
  );
}

function CapRow(props: {
  icon: any;
  label: string;
  value: string;
  ok: boolean;
}) {
  return (
    <View style={styles.capRow}>
      <Ionicons name={props.icon} size={18} color={colors.onSurfaceSecondary} />
      <Text style={styles.capLabel}>{props.label}</Text>
      <Text
        style={[
          styles.capVal,
          { color: props.ok ? "#0F7B4F" : colors.onSurfaceTertiary },
        ]}
      >
        {props.value}
      </Text>
    </View>
  );
}

function Option(props: {
  active: boolean;
  icon: any;
  title: string;
  subtitle: string;
  onPress: () => void;
  saving?: boolean;
  disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={props.disabled ? undefined : props.onPress}
      style={[
        styles.optRow,
        props.active && styles.optRowActive,
        props.disabled && { opacity: 0.5 },
      ]}
    >
      <View style={styles.optIcon}>
        <Ionicons
          name={props.icon}
          size={20}
          color={props.active ? colors.brandPrimary : colors.onSurfaceSecondary}
        />
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.optTitle}>{props.title}</Text>
        <Text style={styles.optSub}>{props.subtitle}</Text>
      </View>
      {props.saving ? (
        <ActivityIndicator />
      ) : (
        <Ionicons
          name={props.active ? "radio-button-on" : "radio-button-off"}
          size={22}
          color={props.active ? colors.brandPrimary : colors.onSurfaceTertiary}
        />
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    gap: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h2, color: colors.onSurface },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: 8,
    ...shadow.card,
  },
  section: {
    ...type.body,
    fontWeight: "800",
    color: colors.onSurface,
    marginBottom: 2,
  },
  hint: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    marginBottom: 4,
  },
  warnHint: {
    ...type.caption,
    color: "#7A4B00",
    backgroundColor: "#FFF9EA",
    borderRadius: radius.sm,
    padding: 8,
    marginTop: 6,
  },
  capRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 4,
  },
  capLabel: {
    ...type.body,
    color: colors.onSurface,
    flex: 1,
  },
  capVal: {
    ...type.caption,
    fontWeight: "700",
  },
  optRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    padding: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.divider,
    backgroundColor: colors.surface,
    marginTop: 8,
  },
  optRowActive: {
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surfaceSecondary,
  },
  optIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surfaceSecondary,
  },
  optTitle: { ...type.body, fontWeight: "700", color: colors.onSurface },
  optSub: {
    ...type.caption,
    color: colors.onSurfaceSecondary,
    marginTop: 2,
  },
  primaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.md,
    backgroundColor: colors.brandPrimary,
    marginTop: 4,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700", fontSize: 14 },
  btnDisabled: { opacity: 0.5 },
  msgBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderRadius: radius.sm,
    padding: 8,
    marginTop: 8,
  },
  okBox: {
    backgroundColor: "#E7F5EE",
    borderColor: "#B7DEC7",
    borderWidth: 1,
  },
  errBox: {
    backgroundColor: "#FFE9EE",
    borderColor: "#F1B6C2",
    borderWidth: 1,
  },
  okTxt: { color: "#0F7B4F", fontSize: 12, flex: 1 },
  errTxt: { color: "#B0002B", fontSize: 12, flex: 1 },
  footHint: {
    ...type.caption,
    color: colors.onSurfaceTertiary,
  },
  forbid: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: spacing.md,
  },
  forbidT: { ...type.h3, color: colors.onSurfaceSecondary },
  forbidHint: {
    ...type.caption,
    color: colors.onSurfaceTertiary,
    textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
});
