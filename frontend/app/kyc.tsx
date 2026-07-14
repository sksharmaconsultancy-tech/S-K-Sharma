import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

type Kyc = {
  aadhar_number?: string | null;
  name_as_per_aadhar?: string | null;
  pan_number?: string | null;
  name_as_per_pan?: string | null;
  dl_number?: string | null;
  bank_account_number?: string | null;
  bank_name?: string | null;
  ifsc_code?: string | null;
  name_as_per_bank?: string | null;
  kyc_updated_at?: string | null;
};

/**
 * "Update Details" screen — self-serve KYC editor for the signed-in user.
 * Employees, company admins and super admins can update their own KYC.
 */
export default function KycScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  const [aadhar, setAadhar] = useState("");
  const [nameAadhar, setNameAadhar] = useState("");
  const [pan, setPan] = useState("");
  const [namePan, setNamePan] = useState("");
  const [dl, setDl] = useState("");
  const [bankAcc, setBankAcc] = useState("");
  const [bankName, setBankName] = useState("");
  const [ifsc, setIfsc] = useState("");
  const [nameBank, setNameBank] = useState("");
  const [updatedAt, setUpdatedAt] = useState<string | null>(null);
  const [scanning, setScanning] = useState<string | null>(null);

  /**
   * Take/pick an image of a document, send it to Gemini OCR, then
   * merge extracted fields into the relevant KYC inputs. The image is
   * NOT persisted — only the parsed fields are kept.
   */
  const scanDoc = async (
    docType: "aadhaar" | "pan" | "dl" | "passbook",
    source: "camera" | "library",
  ) => {
    setScanning(docType);
    try {
      let picker: any;
      if (source === "camera") {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (perm.status !== "granted") {
          throw new Error("Camera permission required.");
        }
        picker = await ImagePicker.launchCameraAsync({
          allowsEditing: true,
          quality: 0.7,
        });
      } else {
        const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (perm.status !== "granted") {
          throw new Error("Photos permission required.");
        }
        picker = await ImagePicker.launchImageLibraryAsync({
          allowsEditing: true,
          quality: 0.7,
        });
      }
      if (picker?.canceled || !picker?.assets?.[0]?.uri) {
        setScanning(null);
        return;
      }
      // Compress to keep payload small
      const manip = await ImageManipulator.manipulateAsync(
        picker.assets[0].uri,
        [{ resize: { width: 1200 } }],
        {
          compress: 0.75,
          format: ImageManipulator.SaveFormat.JPEG,
          base64: true,
        },
      );
      const b64 = manip.base64
        ? `data:image/jpeg;base64,${manip.base64}`
        : picker.assets[0].uri;

      const r = await api<{
        ok: boolean;
        parsed?: any;
        raw?: string;
        detail?: string;
      }>("/me/ocr-id-proof", {
        method: "POST",
        body: { image_base64: b64, doc_type: docType },
      });
      if (!r.ok || !r.parsed) {
        throw new Error(r.detail || "Could not read the document.");
      }
      const p = r.parsed;
      // Handle both auto-mode ({doc_type, fields: {...}}) and forced mode
      const f = p.fields || p;
      if (docType === "aadhaar" || f.aadhaar_number) {
        if (f.aadhaar_number) setAadhar(String(f.aadhaar_number).replace(/\D/g, ""));
        if (f.name) setNameAadhar(String(f.name));
      }
      if (docType === "pan" || f.pan_number) {
        if (f.pan_number) setPan(String(f.pan_number).toUpperCase());
        if (f.name) setNamePan(String(f.name));
      }
      if (docType === "dl" || f.dl_number) {
        if (f.dl_number) setDl(String(f.dl_number));
      }
      if (docType === "passbook" || f.account_number) {
        if (f.account_number) setBankAcc(String(f.account_number).replace(/\D/g, ""));
        if (f.ifsc) setIfsc(String(f.ifsc).toUpperCase());
        if (f.bank_name) setBankName(String(f.bank_name));
        if (f.account_holder) setNameBank(String(f.account_holder));
      }
      setOkMsg(`Scanned ${docType} — please review the auto-filled fields.`);
    } catch (e: any) {
      setError(e?.message || "Scan failed");
    } finally {
      setScanning(null);
    }
  };

  const promptScan = (docType: "aadhaar" | "pan" | "dl" | "passbook") => {
    if (Platform.OS === "web") {
      // Web: image_picker falls back to <input type=file> so just launch
      // the library flow directly.
      scanDoc(docType, "library");
      return;
    }
    Alert.alert(
      "Scan document",
      "Take a photo or pick from your library?",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Camera", onPress: () => scanDoc(docType, "camera") },
        { text: "Library", onPress: () => scanDoc(docType, "library") },
      ],
    );
  };

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const r = await api<{ kyc: Kyc }>("/me/kyc");
        if (cancelled) return;
        const k = r.kyc || {};
        setAadhar(k.aadhar_number || "");
        setNameAadhar(k.name_as_per_aadhar || "");
        setPan(k.pan_number || "");
        setNamePan(k.name_as_per_pan || "");
        setDl(k.dl_number || "");
        setBankAcc(k.bank_account_number || "");
        setBankName(k.bank_name || "");
        setIfsc(k.ifsc_code || "");
        setNameBank(k.name_as_per_bank || "");
        setUpdatedAt(k.kyc_updated_at || null);
      } catch (e: any) {
        if (!cancelled) setError(e?.message || "Could not load your details");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const formatAadharDisplay = (v: string) => {
    const digits = v.replace(/\D/g, "").slice(0, 12);
    // group into 4-4-4
    return digits.replace(/(\d{4})(\d{4})(\d{0,4})/, (_m, a, b, c) =>
      c ? `${a} ${b} ${c}` : `${a} ${b}`,
    );
  };

  const save = async () => {
    setError(null);
    setOkMsg(null);
    setSaving(true);
    try {
      await api("/me/kyc", {
        method: "PATCH",
        body: {
          aadhar_number: aadhar.replace(/\D/g, ""),
          name_as_per_aadhar: nameAadhar,
          pan_number: pan.trim().toUpperCase(),
          name_as_per_pan: namePan,
          dl_number: dl,
          bank_account_number: bankAcc.replace(/\D/g, ""),
          bank_name: bankName,
          ifsc_code: ifsc.trim().toUpperCase(),
          name_as_per_bank: nameBank,
        },
      });
      setOkMsg("Your details have been updated.");
      setUpdatedAt(new Date().toISOString());
    } catch (e: any) {
      setError(e?.message || "Could not save. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const askConfirmSave = () => {
    if (Platform.OS === "web") {
      // React Native Web's Alert.alert wraps window.alert which has no button
      // callbacks — fall back to the native confirm dialog so the Save button
      // actually reaches its PATCH call.
      const ok = window.confirm(
        "Save details? These will be used for compliance records. Please double-check them.",
      );
      if (ok) void save();
      return;
    }
    Alert.alert(
      "Save details?",
      "These will be used for compliance records. Please double-check them.",
      [
        { text: "Cancel", style: "cancel" },
        { text: "Save", onPress: save },
      ],
    );
  };

  const insetsBottom = 24;

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable
            onPress={() => router.back()}
            hitSlop={12}
            testID="kyc-back"
          >
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Update details</Text>
            <Text style={styles.subtitle}>
              {user?.name || user?.email || "Your profile"}
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <KeyboardAwareScrollView bottomOffset={62}
          contentContainerStyle={[
            styles.scroll,
            { paddingBottom: 60 + insetsBottom },
          ]}
          keyboardShouldPersistTaps="handled"
        >
          {loading ? (
            <ActivityIndicator
              style={{ marginTop: 40 }}
              color={colors.brandPrimary}
            />
          ) : (
            <>
              <Text style={styles.blurb}>
                Add your ID details to keep your compliance records up to date.
                All fields are optional — fill only what you have.
              </Text>

              {/* Aadhaar */}
              <View style={styles.card}>
                <View style={styles.cardHeader}>
                  <Ionicons
                    name="card-outline"
                    size={16}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.cardTitle}>Aadhaar</Text>
                  <View style={{ flex: 1 }} />
                  <Pressable
                    onPress={() => promptScan("aadhaar")}
                    disabled={!!scanning}
                    style={[styles.scanBtn, scanning === "aadhaar" && { opacity: 0.7 }]}
                    testID="kyc-scan-aadhaar"
                  >
                    {scanning === "aadhaar" ? (
                      <ActivityIndicator size="small" color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons name="scan-outline" size={14} color={colors.brandPrimary} />
                        <Text style={styles.scanBtnTxt}>Scan</Text>
                      </>
                    )}
                  </Pressable>
                </View>
                <Text style={styles.label}>Aadhaar number</Text>
                <TextInput
                  testID="kyc-aadhar"
                  value={formatAadharDisplay(aadhar)}
                  onChangeText={(t) => setAadhar(t.replace(/\D/g, "").slice(0, 12))}
                  keyboardType="number-pad"
                  placeholder="1234 5678 9012"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                  maxLength={14}
                />
                <Text style={styles.label}>Name as per Aadhaar</Text>
                <TextInput
                  testID="kyc-name-aadhar"
                  value={nameAadhar}
                  onChangeText={setNameAadhar}
                  autoCapitalize="words"
                  placeholder="Full name printed on your Aadhaar card"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />
              </View>

              {/* PAN */}
              <View style={styles.card}>
                <View style={styles.cardHeader}>
                  <Ionicons
                    name="document-text-outline"
                    size={16}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.cardTitle}>PAN</Text>
                  <View style={{ flex: 1 }} />
                  <Pressable
                    onPress={() => promptScan("pan")}
                    disabled={!!scanning}
                    style={[styles.scanBtn, scanning === "pan" && { opacity: 0.7 }]}
                    testID="kyc-scan-pan"
                  >
                    {scanning === "pan" ? (
                      <ActivityIndicator size="small" color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons name="scan-outline" size={14} color={colors.brandPrimary} />
                        <Text style={styles.scanBtnTxt}>Scan</Text>
                      </>
                    )}
                  </Pressable>
                </View>
                <Text style={styles.label}>PAN number</Text>
                <TextInput
                  testID="kyc-pan"
                  value={pan}
                  onChangeText={(t) =>
                    setPan(t.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10))
                  }
                  autoCapitalize="characters"
                  autoCorrect={false}
                  placeholder="ABCDE1234F"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                  maxLength={10}
                />
                <Text style={styles.label}>Name as per PAN</Text>
                <TextInput
                  testID="kyc-name-pan"
                  value={namePan}
                  onChangeText={setNamePan}
                  autoCapitalize="words"
                  placeholder="Full name printed on your PAN card"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />
              </View>

              {/* Driving licence */}
              <View style={styles.card}>
                <View style={styles.cardHeader}>
                  <Ionicons
                    name="car-outline"
                    size={16}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.cardTitle}>Driving licence</Text>
                  <View style={{ flex: 1 }} />
                  <Pressable
                    onPress={() => promptScan("dl")}
                    disabled={!!scanning}
                    style={[styles.scanBtn, scanning === "dl" && { opacity: 0.7 }]}
                    testID="kyc-scan-dl"
                  >
                    {scanning === "dl" ? (
                      <ActivityIndicator size="small" color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons name="scan-outline" size={14} color={colors.brandPrimary} />
                        <Text style={styles.scanBtnTxt}>Scan</Text>
                      </>
                    )}
                  </Pressable>
                </View>
                <Text style={styles.label}>DL number</Text>
                <TextInput
                  testID="kyc-dl"
                  value={dl}
                  onChangeText={(t) => setDl(t.toUpperCase())}
                  autoCapitalize="characters"
                  autoCorrect={false}
                  placeholder="DL-1420110012345"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                  maxLength={20}
                />
              </View>

              {/* Bank details */}
              <View style={styles.card}>
                <View style={styles.cardHeader}>
                  <Ionicons
                    name="wallet-outline"
                    size={16}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.cardTitle}>Bank details</Text>
                  <View style={{ flex: 1 }} />
                  <Pressable
                    onPress={() => promptScan("passbook")}
                    disabled={!!scanning}
                    style={[styles.scanBtn, scanning === "passbook" && { opacity: 0.7 }]}
                    testID="kyc-scan-passbook"
                  >
                    {scanning === "passbook" ? (
                      <ActivityIndicator size="small" color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons name="scan-outline" size={14} color={colors.brandPrimary} />
                        <Text style={styles.scanBtnTxt}>Scan</Text>
                      </>
                    )}
                  </Pressable>
                </View>
                <Text style={styles.label}>Bank name</Text>
                <TextInput
                  testID="kyc-bank-name"
                  value={bankName}
                  onChangeText={setBankName}
                  autoCapitalize="words"
                  placeholder="State Bank of India"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />
                <Text style={styles.label}>Bank account number</Text>
                <TextInput
                  testID="kyc-bank-acc"
                  value={bankAcc}
                  onChangeText={(t) =>
                    setBankAcc(t.replace(/\D/g, "").slice(0, 20))
                  }
                  keyboardType="number-pad"
                  placeholder="123456789012"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                  maxLength={20}
                />
                <Text style={styles.label}>IFSC code</Text>
                <TextInput
                  testID="kyc-ifsc"
                  value={ifsc}
                  onChangeText={(t) =>
                    setIfsc(
                      t.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 11),
                    )
                  }
                  autoCapitalize="characters"
                  autoCorrect={false}
                  placeholder="SBIN0001234"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                  maxLength={11}
                />
                <Text style={styles.label}>Name as per Bank</Text>
                <TextInput
                  testID="kyc-name-bank"
                  value={nameBank}
                  onChangeText={setNameBank}
                  autoCapitalize="words"
                  placeholder="Name printed on your passbook / cheque"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />
              </View>

              {updatedAt ? (
                <Text style={styles.footNote}>
                  Last updated:{" "}
                  {new Date(updatedAt).toLocaleString()}
                </Text>
              ) : null}

              {error ? (
                <View style={styles.errBox} testID="kyc-error">
                  <Ionicons
                    name="alert-circle"
                    size={16}
                    color={colors.error}
                  />
                  <Text style={styles.errTxt}>{error}</Text>
                </View>
              ) : null}
              {okMsg ? (
                <View style={styles.okBox} testID="kyc-ok">
                  <Ionicons
                    name="checkmark-circle"
                    size={16}
                    color="#0F5B22"
                  />
                  <Text style={styles.okTxt}>{okMsg}</Text>
                </View>
              ) : null}

              <Pressable
                testID="kyc-save"
                onPress={askConfirmSave}
                disabled={saving}
                style={[styles.cta, saving && { opacity: 0.7 }]}
              >
                {saving ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons
                      name="save-outline"
                      size={18}
                      color="#fff"
                    />
                    <Text style={styles.ctaTxt}>Save details</Text>
                  </>
                )}
              </Pressable>
            </>
          )}
        </KeyboardAwareScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
  },
  title: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  subtitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 2,
  },
  scroll: { padding: spacing.lg },
  blurb: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    lineHeight: 20,
    marginBottom: spacing.md,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 6,
  },
  cardTitle: {
    color: colors.brandPrimary,
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  scanBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: colors.brandTertiary,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 999,
    minHeight: 28,
  },
  scanBtnTxt: {
    color: colors.brandPrimary,
    fontSize: 11,
    fontWeight: "700",
  },
  label: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
    marginTop: spacing.md,
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: Platform.OS === "ios" ? 12 : 8,
    color: colors.onSurface,
    fontSize: type.base,
  },
  footNote: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    textAlign: "center",
    marginTop: spacing.md,
  },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEECEC",
    borderColor: "#F3B4B4",
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  errTxt: { color: colors.error, fontSize: type.sm, flex: 1 },
  okBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#E7F5EA",
    borderColor: "#B7E0C0",
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.md,
  },
  okTxt: { color: "#0F5B22", fontSize: type.sm, flex: 1 },
  cta: {
    marginTop: spacing.lg,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.pill,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
  },
  ctaTxt: { color: "#fff", fontSize: type.base, fontWeight: "800" },
});
