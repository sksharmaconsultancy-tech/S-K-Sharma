import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { requestLocation, reverseGeocode } from "@/src/utils/location";
import { ddmmyyyyDashToISO } from "@/src/utils/date";
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

type Step = "phone" | "details" | "done";

/**
 * Employee self-registration flow:
 * Step 1: Mobile number + PIN + Company code
 * Step 2: Personal + work details
 * Step 3: Success — waiting for admin approval
 */
export default function EmployeeSignupScreen() {
  const router = useRouter();
  // Iter 96p — a company QR/link can pre-fill & lock the company code
  // (e.g. /employee-signup?company=SKS123 opened after scanning the QR).
  const params = useLocalSearchParams<{ company?: string }>();
  const prefillCompany = params.company ? String(params.company).toUpperCase() : "";

  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");
  const [companyCode, setCompanyCode] = useState(prefillCompany);
  const [companyName, setCompanyName] = useState<string | null>(null);
  const [companyLocked, setCompanyLocked] = useState(false);

  const [name, setName] = useState("");
  const [fatherName, setFatherName] = useState("");
  const [dob, setDob] = useState("");
  const [doj, setDoj] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState("");
  // Iter 85 — Employee-provided code (from offer letter).
  const [employeeCode, setEmployeeCode] = useState("");
  const [locBusy, setLocBusy] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Verify & lock the company when arriving from a QR/link.
  useEffect(() => {
    if (!prefillCompany) return;
    let alive = true;
    (async () => {
      try {
        const r = await api<{ company_id: string; name: string }>(
          `/companies/lookup/${encodeURIComponent(prefillCompany)}`,
          { auth: false },
        );
        if (!alive) return;
        setCompanyName(r.name);
        setCompanyLocked(true);
      } catch {
        // Invalid code in the link — let the user type it manually.
      }
    })();
    return () => { alive = false; };
  }, [prefillCompany]);

  const validateStep1 = (): boolean => {
    setError(null);
    if (phone.replace(/\D/g, "").length < 10) {
      setError("Enter a valid mobile number");
      return false;
    }
    if (!/^\d{6}$/.test(pin)) {
      setError("PIN must be exactly 6 digits");
      return false;
    }
    if (pin !== confirmPin) {
      setError("PINs do not match");
      return false;
    }
    if (new Set(pin).size === 1) {
      setError("PIN cannot be all the same digit");
      return false;
    }
    if (["123456", "654321", "000000", "111111"].includes(pin)) {
      setError("Please choose a less obvious PIN");
      return false;
    }
    if (!companyCode.trim()) {
      setError("Enter your company code");
      return false;
    }
    return true;
  };

  const goToDetails = async () => {
    if (!validateStep1()) return;
    // Verify company code exists before advancing
    setBusy(true);
    try {
      const r = await api<{ company_id: string; name: string }>(
        `/companies/lookup/${encodeURIComponent(companyCode.trim().toUpperCase())}`,
        { auth: false },
      );
      setCompanyName(r.name);
      setStep("details");
    } catch (e: any) {
      setError(e.message || "Company code not recognised");
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    setError(null);
    if (!name.trim()) {
      setError("Please enter your full name");
      return;
    }
    setBusy(true);
    try {
      await api("/auth/employee-signup", {
        method: "POST",
        auth: false,
        body: {
          phone: phone.trim(),
          pin,
          company_code: companyCode.trim().toUpperCase(),
          name: name.trim(),
          employee_code: employeeCode.trim().toUpperCase() || undefined,
          father_name: fatherName.trim() || undefined,
          dob: ddmmyyyyDashToISO(dob.trim()) || undefined,
          doj: ddmmyyyyDashToISO(doj.trim()) || undefined,
          email: email.trim().toLowerCase() || undefined,
          address: address.trim() || undefined,
        },
      });
      setStep("done");
    } catch (e: any) {
      setError(e.message || "Sign-up failed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root} testID="employee-signup-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable
            onPress={() => (step === "details" ? setStep("phone") : router.back())}
            hitSlop={8}
          >
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Create employee account</Text>
          <View style={{ width: 26 }} />
        </View>

        {/* Progress dots */}
        <View style={styles.dotsRow}>
          <Dot active={step === "phone"} done={step !== "phone"} />
          <View style={styles.dotLine} />
          <Dot active={step === "details"} done={step === "done"} />
          <View style={styles.dotLine} />
          <Dot active={false} done={step === "done"} />
        </View>

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
          <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            {step === "phone" && (
              <>
                <Text style={styles.title}>Your mobile & PIN</Text>
                <Text style={styles.subtitle}>
                  Set up your login credentials. You&apos;ll change the PIN once your admin approves you.
                </Text>

                <Text style={styles.label}>Mobile number</Text>
                <TextInput
                  testID="signup-phone-input"
                  value={phone}
                  onChangeText={setPhone}
                  placeholder="+91 98765 43210"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="phone-pad"
                  style={styles.input}
                />

                <Text style={styles.label}>Choose a 6-digit PIN</Text>
                <TextInput
                  testID="signup-pin-input"
                  value={pin}
                  onChangeText={(t) => setPin(t.replace(/\D/g, "").slice(0, 6))}
                  placeholder="6-digit PIN"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="number-pad"
                  secureTextEntry
                  maxLength={6}
                  style={[styles.input, { letterSpacing: 4 }]}
                />

                <Text style={styles.label}>Confirm PIN</Text>
                <TextInput
                  testID="signup-pin-confirm"
                  value={confirmPin}
                  onChangeText={(t) => setConfirmPin(t.replace(/\D/g, "").slice(0, 6))}
                  placeholder="Re-enter PIN"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="number-pad"
                  secureTextEntry
                  maxLength={6}
                  style={[styles.input, { letterSpacing: 4 }]}
                />

                <Text style={styles.label}>Company code</Text>
                <TextInput
                  testID="signup-company-code"
                  value={companyCode}
                  onChangeText={(t) => setCompanyCode(t.toUpperCase().slice(0, 12))}
                  placeholder="e.g. ACME01"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="characters"
                  autoCorrect={false}
                  editable={!companyLocked}
                  style={[styles.input, companyLocked && { opacity: 0.7 }]}
                />
                <Text style={styles.hint}>
                  {companyLocked && companyName
                    ? `You're joining ${companyName}.`
                    : "Your company admin will share this code with you."}
                </Text>

                {error && (
                  <View style={styles.errBox} testID="signup-error">
                    <Ionicons name="alert-circle" size={16} color={colors.onError} />
                    <Text style={styles.errTxt}>{error}</Text>
                  </View>
                )}

                <Pressable
                  testID="signup-next"
                  style={[styles.cta, busy && { opacity: 0.7 }]}
                  onPress={goToDetails}
                  disabled={busy}
                >
                  {busy ? (
                    <ActivityIndicator color={colors.onCta} />
                  ) : (
                    <>
                      <Text style={styles.ctaTxt}>Continue</Text>
                      <Ionicons name="arrow-forward" size={18} color={colors.onCta} />
                    </>
                  )}
                </Pressable>
              </>
            )}

            {step === "details" && (
              <>
                <Text style={styles.title}>Tell us about yourself</Text>
                <Text style={styles.subtitle}>
                  Joining <Text style={styles.brand}>{companyName || companyCode}</Text>
                </Text>

                <Text style={styles.label}>Full name *</Text>
                <TextInput
                  testID="signup-name"
                  value={name}
                  onChangeText={(v) => setName(v.toUpperCase())}
                  placeholder="RAJESH KUMAR"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />

                {/* Iter 85 — Employee-provided code from offer letter */}
                <Text style={styles.label}>Employee code (from offer letter)</Text>
                <TextInput
                  testID="signup-employee-code"
                  value={employeeCode}
                  onChangeText={(v) => setEmployeeCode(v.toUpperCase().slice(0, 16))}
                  placeholder="e.g. SKSCO1001 (optional)"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="characters"
                  autoCorrect={false}
                  style={styles.input}
                />
                <Text style={styles.hint}>
                  If your employer already gave you a code, enter it here — otherwise leave blank and one will be assigned.
                </Text>

                <Text style={styles.label}>Father&apos;s name</Text>
                <TextInput
                  testID="signup-father"
                  value={fatherName}
                  onChangeText={(v) => setFatherName(v.toUpperCase())}
                  placeholder="(OPTIONAL)"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />

                <Text style={styles.label}>Date of birth</Text>
                <TextInput
                  testID="signup-dob"
                  value={dob}
                  onChangeText={(t) => setDob(maskDashDate(t))}
                  keyboardType="number-pad"
                  placeholder="DD-MM-YYYY (optional)"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                  maxLength={10}
                />

                <Text style={styles.label}>Date of joining</Text>
                <TextInput
                  testID="signup-doj"
                  value={doj}
                  onChangeText={(t) => setDoj(maskDashDate(t))}
                  keyboardType="number-pad"
                  placeholder="DD-MM-YYYY (optional)"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                  maxLength={10}
                />

                <Text style={styles.label}>Email (optional)</Text>
                <TextInput
                  testID="signup-email"
                  value={email}
                  onChangeText={setEmail}
                  placeholder="you@example.com"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  autoCapitalize="none"
                  keyboardType="email-address"
                  style={styles.input}
                />

                <View style={styles.addressHeader}>
                  <Text style={styles.label}>Home address (optional)</Text>
                  <Pressable
                    testID="signup-use-my-location"
                    onPress={async () => {
                      setLocBusy(true);
                      const loc = await requestLocation();
                      if (loc) {
                        const a = await reverseGeocode(loc.latitude, loc.longitude);
                        if (a) setAddress(a);
                        else setAddress(`${loc.latitude.toFixed(5)}, ${loc.longitude.toFixed(5)}`);
                      }
                      setLocBusy(false);
                    }}
                    disabled={locBusy}
                    style={styles.locBtn}
                  >
                    {locBusy ? (
                      <ActivityIndicator size="small" color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons name="location" size={14} color={colors.brandPrimary} />
                        <Text style={styles.locBtnTxt}>Use my current location</Text>
                      </>
                    )}
                  </Pressable>
                </View>
                <TextInput
                  testID="signup-address"
                  value={address}
                  onChangeText={setAddress}
                  placeholder="House / street / city"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  multiline
                  numberOfLines={2}
                  style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]}
                />

                {error && (
                  <View style={styles.errBox} testID="signup-error">
                    <Ionicons name="alert-circle" size={16} color={colors.onError} />
                    <Text style={styles.errTxt}>{error}</Text>
                  </View>
                )}

                <Pressable
                  testID="signup-submit"
                  style={[styles.cta, busy && { opacity: 0.7 }]}
                  onPress={submit}
                  disabled={busy}
                >
                  {busy ? (
                    <ActivityIndicator color={colors.onCta} />
                  ) : (
                    <>
                      <Text style={styles.ctaTxt}>Create account</Text>
                      <Ionicons name="checkmark" size={18} color={colors.onCta} />
                    </>
                  )}
                </Pressable>
              </>
            )}

            {step === "done" && (
              <View style={styles.doneBox} testID="signup-done">
                <View style={styles.successIcon}>
                  <Ionicons name="hourglass-outline" size={38} color={colors.onCta} />
                </View>
                <Text style={styles.title}>Account created!</Text>
                <Text style={styles.subtitle}>
                  Your details have been submitted to
                  {" "}<Text style={styles.brand}>{companyName || companyCode}</Text>.
                  A company admin will review your account. You&apos;ll be able to sign in as soon
                  as they approve you.
                </Text>
                <View style={styles.tipsBox}>
                  <Tip icon="phone-portrait-outline" text={`Mobile: ${phone}`} />
                  <Tip icon="key-outline" text="PIN: use the one you just set — you&apos;ll change it after admin approval" />
                  <Tip icon="time-outline" text="Approvals typically take a few minutes to a couple of hours" />
                </View>
                <Pressable
                  style={styles.cta}
                  onPress={() => router.replace("/pin-login")}
                  testID="signup-goto-login"
                >
                  <Text style={styles.ctaTxt}>Go to sign in</Text>
                  <Ionicons name="arrow-forward" size={18} color={colors.onCta} />
                </Pressable>
              </View>
            )}
          </KeyboardAwareScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

function Dot({ active, done }: { active: boolean; done: boolean }) {
  return (
    <View
      style={[
        styles.dot,
        active && styles.dotActive,
        done && styles.dotDone,
      ]}
    >
      {done ? <Ionicons name="checkmark" size={12} color="#fff" /> : null}
    </View>
  );
}

function Tip({ icon, text }: { icon: any; text: string }) {
  return (
    <View style={styles.tipRow}>
      <Ionicons name={icon} size={16} color={colors.brandPrimary} />
      <Text style={styles.tipTxt}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  dotsRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
  },
  dot: {
    width: 22, height: 22, borderRadius: 11,
    borderWidth: 2, borderColor: colors.border,
    backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center",
  },
  dotActive: { borderColor: colors.brandPrimary, backgroundColor: colors.brandPrimary },
  dotDone: { borderColor: "#218739", backgroundColor: "#218739" },
  dotLine: { width: 30, height: 2, backgroundColor: colors.border },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },
  title: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800", textAlign: "center" },
  brand: { color: colors.brandPrimary, fontWeight: "800" },
  subtitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    lineHeight: 20,
    textAlign: "center",
    marginTop: 6,
    marginBottom: spacing.lg,
  },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600", marginTop: spacing.md, marginBottom: 6 },
  hint: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 4 },
  addressHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.md,
    marginBottom: 6,
  },
  locBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  locBtnTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "600" },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 12,
    color: colors.onSurface, fontSize: type.base,
  },
  errBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.error,
    borderRadius: radius.md,
    padding: spacing.sm,
    marginTop: spacing.md,
  },
  errTxt: { color: colors.onError, fontSize: type.sm, flex: 1 },
  cta: {
    marginTop: spacing.lg,
    backgroundColor: colors.cta,
    borderRadius: radius.pill,
    paddingVertical: 16,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  doneBox: { alignItems: "center", paddingTop: spacing.lg },
  successIcon: {
    width: 72, height: 72, borderRadius: 36,
    backgroundColor: colors.cta,
    alignItems: "center", justifyContent: "center",
    marginBottom: spacing.md,
  },
  tipsBox: {
    alignSelf: "stretch",
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    gap: 10,
    marginTop: spacing.md,
  },
  tipRow: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  tipTxt: { color: colors.onSurface, fontSize: type.sm, flex: 1, lineHeight: 18 },
});
