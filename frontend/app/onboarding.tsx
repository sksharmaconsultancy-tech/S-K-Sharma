import React, { useCallback, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { ddmmyyyyDashToISO } from "@/src/utils/date";
import ScanOCRButton from "@/src/components/ScanOCRButton";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

/**
 * Progressive input mask for DD-MM-YYYY: strips non-digits, groups them
 * into "DD-MM-YYYY", so users can type "01011990" and see "01-01-1990".
 */
function maskDashDate(input: string): string {
  const d = (input || "").replace(/\D/g, "").slice(0, 8);
  if (d.length <= 2) return d;
  if (d.length <= 4) return `${d.slice(0, 2)}-${d.slice(2)}`;
  return `${d.slice(0, 2)}-${d.slice(2, 4)}-${d.slice(4)}`;
}

const LOGO_MARK = require("../assets/images/logo-mark.png");

type Step = "code" | "personal" | "employment";

export default function OnboardingScreen() {
  const { user, refresh, logout } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<Step>("code");
  const [code, setCode] = useState("");
  const [checkedCompany, setCheckedCompany] = useState<{
    company_id: string;
    company_code: string;
    name: string;
    address?: string;
  } | null>(null);
  const [checking, setChecking] = useState(false);

  const [name, setName] = useState("");
  const [father, setFather] = useState("");
  const [dob, setDob] = useState("");
  const [doj, setDoj] = useState("");
  const [shiftStart, setShiftStart] = useState("09:00");
  const [shiftEnd, setShiftEnd] = useState("18:00");
  const [salary, setSalary] = useState("");
  const [halfHrs, setHalfHrs] = useState("4");
  const [fullHrs, setFullHrs] = useState("8");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const verifyCode = useCallback(async () => {
    setError(null);
    if (!code.trim()) {
      setError("Enter your company code");
      return;
    }
    setChecking(true);
    try {
      const c = await api<any>(`/companies/by-code/${code.trim().toUpperCase()}`);
      setCheckedCompany(c);
      setStep("personal");
    } catch (e: any) {
      setError(e.message || "Company code not found");
    } finally {
      setChecking(false);
    }
  }, [code]);

  // Do NOT pre-fill Full Name from the Google account — many users have their
  // company / workspace name on the Google account and it causes confusion
  // during onboarding. Let them type it fresh.

  // If user is already onboarded, or is not an employee, skip screen
  if (!user) return <Redirect href="/" />;
  if (user.onboarded) return <Redirect href="/(tabs)" />;

  const validatePersonal = () => {
    if (!name.trim() || !father.trim() || !dob.trim() || !doj.trim()) {
      setError("Please fill Name, Father's name, DOB and DOJ");
      return false;
    }
    return true;
  };

  const submit = async () => {
    setError(null);
    const salN = parseFloat(salary);
    const hHrs = parseFloat(halfHrs);
    const fHrs = parseFloat(fullHrs);
    if (Number.isNaN(salN) || Number.isNaN(hHrs) || Number.isNaN(fHrs)) {
      setError("Salary and hours must be numbers");
      return;
    }
    if (hHrs >= fHrs) {
      setError("Half-day hours must be less than full-day hours");
      return;
    }
    if (!shiftStart || !shiftEnd) {
      setError("Enter your shift timings");
      return;
    }
    const dobIso = ddmmyyyyDashToISO(dob.trim());
    const dojIso = ddmmyyyyDashToISO(doj.trim());
    if (!dobIso || !dojIso) {
      setError("DOB and DOJ must be in DD-MM-YYYY format");
      return;
    }
    setSubmitting(true);
    try {
      await api("/onboarding", {
        method: "POST",
        body: {
          company_code: code.trim().toUpperCase(),
          name: name.trim(),
          father_name: father.trim(),
          dob: dobIso,
          doj: dojIso,
          shift_start: shiftStart,
          shift_end: shiftEnd,
          salary_monthly: salN,
          half_day_hrs: hHrs,
          full_day_hrs: fHrs,
        },
      });
      await refresh();
      router.replace("/(tabs)");
    } catch (e: any) {
      setError(e.message || "Onboarding failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Image source={LOGO_MARK} style={styles.headerLogo} contentFit="contain" />
          <View style={{ flex: 1 }}>
            <Text style={styles.brand}>S.K. Sharma & Co.</Text>
            <Text style={styles.brandTag}>Employee Onboarding</Text>
          </View>
          <Pressable onPress={logout} hitSlop={8}>
            <Ionicons name="log-out-outline" size={22} color={colors.onSurfaceTertiary} />
          </Pressable>
        </View>

        <View style={styles.progressRow}>
          <ProgressDot done label="Sign in" done2 />
          <ProgressBar filled />
          <ProgressDot
            done={step !== "code"}
            active={step === "code"}
            label="Company"
          />
          <ProgressBar filled={step !== "code"} />
          <ProgressDot
            done={step === "employment"}
            active={step === "personal"}
            label="Details"
          />
          <ProgressBar filled={step === "employment"} />
          <ProgressDot active={step === "employment"} label="Submit" />
        </View>
      </SafeAreaView>

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <KeyboardAwareScrollView bottomOffset={62}
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          {step === "code" && (
            <View style={styles.card}>
              <View style={styles.stepIcon}>
                <Ionicons name="business-outline" size={28} color={colors.onBrandTertiary} />
              </View>
              <Text style={styles.stepTitle}>Enter your company code</Text>
              <Text style={styles.stepBody}>
                Your HR team at S.K. Sharma & Co. has shared a 6-character code
                for your company. Enter it below to link your account.
              </Text>

              <Text style={styles.label}>Company code</Text>
              <TextInput
                testID="company-code-input"
                value={code}
                onChangeText={(t) => setCode(t.toUpperCase())}
                style={[styles.input, styles.codeInput]}
                placeholder="ABC123"
                placeholderTextColor={colors.onSurfaceTertiary}
                autoCapitalize="characters"
                maxLength={8}
              />

              {error && <Text style={styles.err}>{error}</Text>}

              <Pressable
                testID="verify-code"
                style={[styles.cta, checking && { opacity: 0.7 }]}
                onPress={verifyCode}
                disabled={checking}
              >
                {checking ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Text style={styles.ctaTxt}>Continue</Text>
                    <Ionicons name="arrow-forward" size={18} color="#fff" />
                  </>
                )}
              </Pressable>
            </View>
          )}

          {step === "personal" && checkedCompany && (
            <>
              <View style={styles.matchCard} testID="company-matched-card">
                <View style={styles.matchIcon}>
                  <Ionicons name="checkmark-circle" size={22} color={colors.onSuccess} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.matchTitle}>{checkedCompany.name}</Text>
                  {checkedCompany.address ? (
                    <Text style={styles.matchSub}>{checkedCompany.address}</Text>
                  ) : null}
                </View>
                <Pressable onPress={() => { setCheckedCompany(null); setStep("code"); }}>
                  <Text style={styles.linkTxt}>Change</Text>
                </Pressable>
              </View>

              <Text style={styles.section}>Personal details</Text>

              {/* Iter 155 (user spec) — only TWO documents at joining:
                  Aadhaar + Bank passbook/cheque. Both OPTIONAL — they can
                  be scanned after joining from Edit Profile. */}
              {Platform.OS === "web" && (
                <View style={{ marginBottom: 12, gap: 8 }}>
                  <ScanOCRButton
                    documentType="aadhaar"
                    endpoint="/ocr/parse-my-document"
                    label="Scan Aadhaar card (optional)"
                    onApply={(f) => {
                      if (f.name) setName(String(f.name));
                      if (f.father_name) setFather(String(f.father_name));
                      if (f.dob) setDob(maskDashDate(String(f.dob).replace(/\//g, "-")));
                    }}
                  />
                  <ScanOCRButton
                    documentType="bank_passbook"
                    endpoint="/ocr/parse-my-document"
                    label="Scan Bank passbook / cheque (optional)"
                    onApply={() => {}}
                  />
                  <Text style={styles.ocrHint}>
                    Aadhaar fills your name & DOB; bank details are saved to
                    your profile automatically. Don&apos;t have them now? Skip —
                    you can scan both later from Edit Profile after joining.
                  </Text>
                </View>
              )}

              <Field label="Full name *" value={name} onChangeText={setName}
                     testID="name-input" placeholder="Ramesh Kumar" />
              <Field label="Father's name *" value={father} onChangeText={setFather}
                     testID="father-input" placeholder="Suresh Kumar" />
              <Field
                label="Date of birth (DD-MM-YYYY) *"
                value={dob}
                onChangeText={(t) => setDob(maskDashDate(t))}
                testID="dob-input"
                placeholder="24-08-1995"
              />
              <Field
                label="Date of joining (DD-MM-YYYY) *"
                value={doj}
                onChangeText={(t) => setDoj(maskDashDate(t))}
                testID="doj-input"
                placeholder="01-04-2026"
              />

              {error && <Text style={styles.err}>{error}</Text>}

              <Pressable
                testID="next-employment"
                style={styles.cta}
                onPress={() => {
                  setError(null);
                  if (validatePersonal()) setStep("employment");
                }}
              >
                <Text style={styles.ctaTxt}>Next</Text>
                <Ionicons name="arrow-forward" size={18} color="#fff" />
              </Pressable>
            </>
          )}

          {step === "employment" && (
            <>
              <Text style={styles.section}>Employment terms</Text>

              <View style={styles.split}>
                <View style={{ flex: 1 }}>
                  <Field label="Shift start (HH:MM) *" value={shiftStart}
                         onChangeText={setShiftStart} testID="shift-start-input"
                         placeholder="09:00" />
                </View>
                <View style={{ width: 12 }} />
                <View style={{ flex: 1 }}>
                  <Field label="Shift end (HH:MM) *" value={shiftEnd}
                         onChangeText={setShiftEnd} testID="shift-end-input"
                         placeholder="18:00" />
                </View>
              </View>

              <Field label="Monthly salary (INR) *" value={salary}
                     onChangeText={setSalary} testID="salary-input"
                     placeholder="25000" keyboardType="numeric" />

              <View style={styles.split}>
                <View style={{ flex: 1 }}>
                  <Field label="Half-day hours *" value={halfHrs}
                         onChangeText={setHalfHrs} testID="half-hrs-input"
                         placeholder="4" keyboardType="numeric" />
                </View>
                <View style={{ width: 12 }} />
                <View style={{ flex: 1 }}>
                  <Field label="Full-day hours *" value={fullHrs}
                         onChangeText={setFullHrs} testID="full-hrs-input"
                         placeholder="8" keyboardType="numeric" />
                </View>
              </View>

              <Text style={styles.hint}>
                These terms are per your offer letter. If anything is incorrect, contact your HR before submitting.
              </Text>

              {error && <Text style={styles.err}>{error}</Text>}

              <View style={styles.split}>
                <Pressable
                  style={styles.secondaryCta}
                  onPress={() => { setError(null); setStep("personal"); }}
                >
                  <Ionicons name="arrow-back" size={16} color={colors.brandPrimary} />
                  <Text style={styles.secondaryTxt}>Back</Text>
                </Pressable>
                <View style={{ width: 12 }} />
                <Pressable
                  testID="submit-onboarding"
                  style={[styles.cta, { flex: 1 }, submitting && { opacity: 0.7 }]}
                  onPress={submit}
                  disabled={submitting}
                >
                  {submitting ? (
                    <ActivityIndicator color="#fff" />
                  ) : (
                    <>
                      <Text style={styles.ctaTxt}>Submit</Text>
                      <Ionicons name="checkmark" size={18} color="#fff" />
                    </>
                  )}
                </Pressable>
              </View>
            </>
          )}
          <View style={{ height: 40 }} />
        </KeyboardAwareScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

function Field({
  label, value, onChangeText, placeholder, testID, keyboardType,
}: {
  label: string; value: string; onChangeText: (v: string) => void;
  placeholder?: string; testID?: string; keyboardType?: any;
}) {
  return (
    <View>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.input}
        keyboardType={keyboardType}
      />
    </View>
  );
}

function ProgressDot({
  done, active, label, done2,
}: { done?: boolean; active?: boolean; label: string; done2?: boolean }) {
  const doneVal = done || done2;
  return (
    <View style={{ alignItems: "center", flex: 1 }}>
      <View
        style={[
          styles.dot,
          doneVal && styles.dotDone,
          active && styles.dotActive,
        ]}
      >
        {doneVal ? (
          <Ionicons name="checkmark" size={14} color="#fff" />
        ) : (
          <View style={active ? styles.dotInner : styles.dotInnerIdle} />
        )}
      </View>
      <Text
        style={[
          styles.dotLabel,
          (active || doneVal) && { color: colors.onSurface, fontWeight: "500" },
        ]}
        numberOfLines={1}
      >
        {label}
      </Text>
    </View>
  );
}

function ProgressBar({ filled }: { filled?: boolean }) {
  return <View style={[styles.bar, filled && styles.barFilled]} />;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.md,
    paddingBottom: spacing.md,
  },
  headerLogo: { width: 36, height: 36 },
  brand: { color: colors.onSurface, fontSize: type.base, fontWeight: "500" },
  brandTag: { color: colors.onSurfaceTertiary, fontSize: type.sm },
  progressRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.xl,
    paddingBottom: spacing.md,
  },
  dot: {
    width: 22, height: 22, borderRadius: 11,
    borderWidth: 1, borderColor: colors.borderStrong,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface,
  },
  dotActive: { borderColor: colors.brandPrimary, backgroundColor: colors.surface },
  dotDone: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  dotInner: {
    width: 8, height: 8, borderRadius: 4, backgroundColor: colors.brandPrimary,
  },
  dotInnerIdle: {
    width: 6, height: 6, borderRadius: 3, backgroundColor: colors.borderStrong,
  },
  dotLabel: {
    color: colors.onSurfaceTertiary, fontSize: 10, marginTop: 4,
  },
  bar: { flex: 1, height: 2, backgroundColor: colors.border, marginHorizontal: 4, marginTop: -14 },
  barFilled: { backgroundColor: colors.brandPrimary },
  scroll: { padding: spacing.xl },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "flex-start",
  },
  stepIcon: {
    width: 52, height: 52, borderRadius: 26,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
    marginBottom: spacing.md,
  },
  stepTitle: { color: colors.onSurface, fontSize: type.xl, fontWeight: "500" },
  stepBody: {
    color: colors.onSurfaceTertiary,
    fontSize: type.base,
    marginTop: 6,
    lineHeight: 20,
  },
  label: {
    color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.md,
  },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: type.base,
    marginTop: 6, backgroundColor: colors.surfaceSecondary,
  },
  codeInput: {
    fontSize: 24, letterSpacing: 6, textAlign: "center", fontWeight: "500",
    minWidth: 220,
  },
  err: { color: colors.error, fontSize: type.sm, marginTop: spacing.md },
  cta: {
    marginTop: spacing.lg, backgroundColor: colors.cta,
    paddingVertical: 16, borderRadius: radius.pill,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  secondaryCta: {
    marginTop: spacing.lg, paddingVertical: 16, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.brandPrimary,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    paddingHorizontal: spacing.lg,
  },
  secondaryTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "600" },
  matchCard: {
    flexDirection: "row", alignItems: "center", gap: spacing.md,
    backgroundColor: colors.brandTertiary, borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  matchIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.success, alignItems: "center", justifyContent: "center",
  },
  matchTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "500" },
  matchSub: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  linkTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "500" },
  section: {
    color: colors.onSurface, fontSize: type.lg, fontWeight: "500",
    marginTop: spacing.xl,
  },
  ocrHint: {
    fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 6, lineHeight: 16,
  },
  split: { flexDirection: "row" },
  hint: {
    color: colors.onSurfaceTertiary, fontSize: type.sm,
    marginTop: spacing.md, lineHeight: 18,
  },
});
