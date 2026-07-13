import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, KeyboardAvoidingView, Platform, Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import {
  requestLocation,
  reverseGeocodeDetailed,
} from "@/src/utils/location";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import BusinessCategoryPicker, {
  BusinessCategoryValue,
} from "@/src/components/BusinessCategoryPicker";

type Step = "firm" | "contact" | "pin" | "done";

export default function CompanyRegisterScreen() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("firm");

  // Firm details
  const [companyName, setCompanyName] = useState("");
  const [address, setAddress] = useState("");
  const [city, setCity] = useState("");
  const [state, setState] = useState("");
  const [businessCat, setBusinessCat] = useState<BusinessCategoryValue>({
    category: null,
    subcategory: null,
    label: "",
  });
  const [lat, setLat] = useState<string>("");
  const [lng, setLng] = useState<string>("");
  const [locBusy, setLocBusy] = useState(false);

  // Contact / owner
  const [ownerName, setOwnerName] = useState("");
  const [mobile, setMobile] = useState("");
  const [email, setEmail] = useState("");

  // Iter 89 — Optional firm logo captured at registration time so it
  // is available the moment the firm is approved (no separate upload
  // step). Stored as a data-URL string (base64 PNG/JPEG).
  const [logoDataUrl, setLogoDataUrl] = useState<string | null>(null);
  const [logoMime, setLogoMime] = useState<string | null>(null);
  const pickLogo = () => {
    if (Platform.OS !== "web") return;
    const input = (globalThis as any).document?.createElement?.("input");
    if (!input) return;
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp";
    input.onchange = (e: any) => {
      const file = e?.target?.files?.[0];
      if (!file) return;
      if (file.size > 2 * 1024 * 1024) {
        setError("Logo must be under 2 MB — please resize and try again.");
        return;
      }
      const reader = new (globalThis as any).FileReader();
      reader.onloadend = () => {
        setLogoDataUrl(reader.result as string);
        setLogoMime(file.type);
        setError(null);
      };
      reader.readAsDataURL(file);
    };
    input.click();
  };
  const clearLogo = () => { setLogoDataUrl(null); setLogoMime(null); };

  // PIN
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trim = (v: string) => v.trim();

  const validateFirm = () => {
    setError(null);
    if (!trim(companyName)) { setError("Firm name is required"); return false; }
    if (!trim(address)) { setError("Address is required"); return false; }
    if (!trim(city)) { setError("City is required"); return false; }
    if (!trim(state)) { setError("State is required"); return false; }
    if (!businessCat.category) { setError("Please select your business type"); return false; }
    return true;
  };
  const validateContact = () => {
    setError(null);
    if (!trim(ownerName)) { setError("Owner name is required"); return false; }
    if (mobile.replace(/\D/g, "").length < 10) { setError("Enter a valid mobile number"); return false; }
    const em = trim(email).toLowerCase();
    if (!em || !em.includes("@") || !em.includes(".")) { setError("Enter a valid email address"); return false; }
    return true;
  };
  const validatePin = () => {
    setError(null);
    if (!/^\d{6}$/.test(pin)) { setError("PIN must be exactly 6 digits"); return false; }
    if (pin !== confirmPin) { setError("PINs do not match"); return false; }
    if (new Set(pin).size === 1) { setError("PIN cannot be all the same digit"); return false; }
    if (["123456", "654321", "000000", "111111"].includes(pin)) { setError("Please choose a less obvious PIN"); return false; }
    return true;
  };

  const submit = async () => {
    if (!validatePin()) return;
    setBusy(true);
    try {
      await api("/auth/company-register", {
        method: "POST",
        auth: false,
        body: {
          company_name: trim(companyName),
          address: trim(address),
          city: trim(city),
          state: trim(state),
          nature_of_business: businessCat.label,
          business_category: businessCat.category,
          business_subcategory: businessCat.subcategory,
          contact_name: trim(ownerName),
          contact_mobile: trim(mobile),
          contact_email: trim(email).toLowerCase(),
          pin,
          office_lat: lat ? parseFloat(lat) : undefined,
          office_lng: lng ? parseFloat(lng) : undefined,
          // Iter 89 — optional logo captured at registration.
          logo_base64: logoDataUrl,
          logo_mime: logoMime,
        },
      });
      setStep("done");
    } catch (e: any) {
      setError(e.message || "Registration failed. Please try again.");
    } finally {
      setBusy(false);
    }
  };

  const back = () => {
    if (step === "firm") router.back();
    else if (step === "contact") setStep("firm");
    else if (step === "pin") setStep("contact");
  };

  const useMyLocation = async () => {
    setError(null);
    setLocBusy(true);
    try {
      const loc = await requestLocation();
      if (!loc) {
        setError("Location permission denied. Please enable it in Settings.");
        return;
      }
      setLat(loc.latitude.toFixed(6));
      setLng(loc.longitude.toFixed(6));
      const info = await reverseGeocodeDetailed(loc.latitude, loc.longitude);
      if (info) {
        if (info.display_name) setAddress(info.display_name);
        if (info.city && !city.trim()) setCity(info.city);
        if (info.state && !state.trim()) setState(info.state);
      }
    } catch (e: any) {
      setError(e?.message || "Could not read your current location");
    } finally {
      setLocBusy(false);
    }
  };

  return (
    <View style={styles.root} testID="company-register-screen">
      <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
        <View style={styles.header}>
          <Pressable onPress={back} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Register your company</Text>
          <View style={{ width: 26 }} />
        </View>

        <View style={styles.dotsRow}>
          <Dot active={step === "firm"} done={step === "contact" || step === "pin" || step === "done"} />
          <View style={styles.dotLine} />
          <Dot active={step === "contact"} done={step === "pin" || step === "done"} />
          <View style={styles.dotLine} />
          <Dot active={step === "pin"} done={step === "done"} />
        </View>

        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
          <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
            {step === "firm" && (
              <>
                <Text style={styles.title}>About your firm</Text>
                <Field label="Firm name *" value={companyName} onChangeText={setCompanyName} placeholder="Acme Manufacturing Pvt Ltd" testID="cr-firm-name" />

                <View style={styles.gpsRow}>
                  <Text style={styles.gpsLabel}>Office address</Text>
                  <Pressable
                    testID="cr-use-my-location"
                    onPress={useMyLocation}
                    disabled={locBusy}
                    style={[styles.gpsBtn, locBusy && { opacity: 0.7 }]}
                  >
                    {locBusy ? (
                      <ActivityIndicator size="small" color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons name="locate" size={14} color={colors.brandPrimary} />
                        <Text style={styles.gpsBtnTxt}>Use my current location</Text>
                      </>
                    )}
                  </Pressable>
                </View>

                <Field label="Address *" value={address} onChangeText={setAddress} placeholder="Sector 5, Industrial Area" testID="cr-address" />
                <Field label="City *" value={city} onChangeText={setCity} placeholder="Noida" testID="cr-city" />
                <Field label="State *" value={state} onChangeText={setState} placeholder="Uttar Pradesh" testID="cr-state" />

                {lat && lng ? (
                  <View style={styles.gpsBadge} testID="cr-gps-badge">
                    <Ionicons name="location" size={12} color="#0F5B22" />
                    <Text style={styles.gpsBadgeTxt}>
                      GPS captured — lat {lat}, lng {lng}
                    </Text>
                  </View>
                ) : (
                  <Text style={styles.hint}>
                    Tap “Use my current location” to auto-fill your office address, city, state, and coordinates for accurate geo-fencing.
                  </Text>
                )}

                <BusinessCategoryPicker
                  label="Nature of business *"
                  value={businessCat}
                  onChange={setBusinessCat}
                  testID="cr-nature-picker"
                />

                {/* Iter 89 — Optional firm logo (Web only). Shown as a
                    64px preview + Upload/Remove buttons. Included in
                    the registration payload so admins see the logo the
                    moment they approve the request. */}
                {Platform.OS === "web" ? (
                  <View style={styles.logoBlock} testID="cr-logo-block">
                    <View style={styles.logoPreview}>
                      {logoDataUrl ? (
                        <Image
                          source={{ uri: logoDataUrl }}
                          style={{ width: "100%", height: "100%" }}
                          resizeMode="contain"
                        />
                      ) : (
                        <Ionicons name="image-outline" size={26} color={colors.onSurfaceTertiary} />
                      )}
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.logoLbl}>Firm Logo (optional)</Text>
                      <Text style={styles.logoHelp}>
                        Appears on portal sidebar, mobile app header, salary
                        slips & email attachments once approved.
                      </Text>
                      <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                        <Pressable onPress={pickLogo} style={styles.logoBtn}>
                          <Ionicons name="cloud-upload-outline" size={12} color={colors.brandPrimary} />
                          <Text style={styles.logoBtnTxt}>
                            {logoDataUrl ? "Replace" : "Upload"}
                          </Text>
                        </Pressable>
                        {logoDataUrl ? (
                          <Pressable onPress={clearLogo} style={[styles.logoBtn, { borderColor: "#FCA5A5" }]}>
                            <Ionicons name="trash-outline" size={12} color={colors.error} />
                            <Text style={[styles.logoBtnTxt, { color: colors.error }]}>Remove</Text>
                          </Pressable>
                        ) : null}
                      </View>
                    </View>
                  </View>
                ) : null}

                {error && <ErrorBox msg={error} />}
                <Next label="Continue" busy={busy} onPress={() => { if (validateFirm()) setStep("contact"); }} testID="cr-next-1" />
              </>
            )}

            {step === "contact" && (
              <>
                <Text style={styles.title}>Owner &amp; contact</Text>
                <Text style={styles.subtitle}>These become the login credentials for your firm.</Text>
                <Field label="Owner name *" value={ownerName} onChangeText={setOwnerName} placeholder="Full name" testID="cr-owner-name" />
                <Field label="Mobile number *" value={mobile} onChangeText={setMobile} placeholder="+91 98765 43210" keyboardType="phone-pad" testID="cr-mobile" />
                <Field label="Email *" value={email} onChangeText={setEmail} placeholder="owner@yourfirm.com" keyboardType="email-address" autoCapitalize="none" testID="cr-email" />
                {error && <ErrorBox msg={error} />}
                <Next label="Continue" busy={busy} onPress={() => { if (validateContact()) setStep("pin"); }} testID="cr-next-2" />
              </>
            )}

            {step === "pin" && (
              <>
                <Text style={styles.title}>Choose a 6-digit PIN</Text>
                <Text style={styles.subtitle}>You&apos;ll use this PIN with your mobile / email to sign in.</Text>
                <Field label="Choose PIN *" value={pin} onChangeText={(t) => setPin(t.replace(/\D/g, "").slice(0, 6))} placeholder="6-digit PIN" secureTextEntry keyboardType="number-pad" maxLength={6} testID="cr-pin" />
                <Field label="Confirm PIN *" value={confirmPin} onChangeText={(t) => setConfirmPin(t.replace(/\D/g, "").slice(0, 6))} placeholder="Repeat PIN" secureTextEntry keyboardType="number-pad" maxLength={6} testID="cr-pin-confirm" />
                {error && <ErrorBox msg={error} />}
                <Next label="Submit registration" busy={busy} onPress={submit} testID="cr-submit" />
              </>
            )}

            {step === "done" && (
              <View style={styles.doneBox} testID="cr-done">
                <View style={styles.successIcon}>
                  <Ionicons name="hourglass-outline" size={38} color={colors.onCta} />
                </View>
                <Text style={styles.title}>Registration submitted!</Text>
                <Text style={styles.subtitle}>
                  Your firm registration for <Text style={styles.brand}>{companyName}</Text> has been sent to
                  our Super Admin for approval. You&apos;ll be able to sign in with your mobile /
                  email + PIN as soon as it&apos;s approved (usually within a few hours).
                </Text>
                <View style={styles.tipsBox}>
                  <Tip icon="phone-portrait-outline" text={`Login: ${mobile} or ${email}`} />
                  <Tip icon="key-outline" text="Use the 6-digit PIN you just set" />
                  <Tip icon="time-outline" text="Approval typically takes a few hours" />
                </View>
                <Pressable style={styles.cta} onPress={() => router.replace("/company-login")} testID="cr-go-signin">
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

function Field(props: any) {
  return (
    <>
      <Text style={styles.label}>{props.label}</Text>
      <TextInput
        value={props.value}
        onChangeText={props.onChangeText}
        placeholder={props.placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        keyboardType={props.keyboardType}
        autoCapitalize={props.autoCapitalize}
        secureTextEntry={props.secureTextEntry}
        maxLength={props.maxLength}
        style={[styles.input, props.secureTextEntry && { letterSpacing: 4 }]}
        testID={props.testID}
      />
    </>
  );
}

function Next({ label, busy, onPress, testID }: any) {
  return (
    <Pressable testID={testID} onPress={onPress} disabled={busy} style={[styles.cta, busy && { opacity: 0.7 }]}>
      {busy ? <ActivityIndicator color={colors.onCta} /> : (
        <>
          <Text style={styles.ctaTxt}>{label}</Text>
          <Ionicons name="arrow-forward" size={18} color={colors.onCta} />
        </>
      )}
    </Pressable>
  );
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <View style={styles.errBox} testID="cr-error">
      <Ionicons name="alert-circle" size={16} color={colors.onError} />
      <Text style={styles.errTxt}>{msg}</Text>
    </View>
  );
}

function Dot({ active, done }: { active: boolean; done: boolean }) {
  return (
    <View style={[styles.dot, active && styles.dotActive, done && styles.dotDone]}>
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
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 8, paddingHorizontal: spacing.lg, paddingBottom: spacing.md,
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
    color: colors.onSurfaceSecondary, fontSize: type.sm, lineHeight: 20,
    textAlign: "center", marginTop: 6, marginBottom: spacing.md,
  },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600", marginTop: spacing.md, marginBottom: 6 },
  hint: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 6, lineHeight: 16 },
  // Iter 89 — Optional logo block in the firm step
  logoBlock: {
    flexDirection: "row", alignItems: "center", gap: 12,
    marginTop: 12, padding: 10,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, backgroundColor: colors.surface,
  },
  logoPreview: {
    width: 64, height: 64,
    borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surfaceSecondary,
    overflow: "hidden",
  },
  logoLbl: { ...type.label, color: colors.onSurface, fontWeight: "700" },
  logoHelp: { ...type.caption, color: colors.onSurfaceSecondary, lineHeight: 15, marginTop: 2 },
  logoBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 5,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  logoBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 11 },
  gpsRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: spacing.md,
  },
  gpsLabel: { color: colors.onSurfaceSecondary, fontSize: type.sm, fontWeight: "600" },
  gpsBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  gpsBtnTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "700" },
  gpsBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#E7F5EA",
    borderWidth: 1,
    borderColor: "#B7E0C0",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginTop: 8,
    alignSelf: "flex-start",
  },
  gpsBadgeTxt: { color: "#0F5B22", fontSize: 11, fontWeight: "700" },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 12,
    color: colors.onSurface, fontSize: type.base,
  },
  errBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.error, borderRadius: radius.md,
    padding: spacing.sm, marginTop: spacing.md,
  },
  errTxt: { color: colors.onError, fontSize: type.sm, flex: 1 },
  cta: {
    marginTop: spacing.lg,
    backgroundColor: colors.cta, borderRadius: radius.pill,
    paddingVertical: 16, flexDirection: "row",
    alignItems: "center", justifyContent: "center", gap: 8,
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
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, gap: 10, marginTop: spacing.md,
  },
  tipRow: { flexDirection: "row", alignItems: "flex-start", gap: 10 },
  tipTxt: { color: colors.onSurface, fontSize: type.sm, flex: 1, lineHeight: 18 },
});
