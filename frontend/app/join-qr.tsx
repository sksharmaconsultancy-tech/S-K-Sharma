/**
 * Iter 97 — Joining QR Code utility (Employer / Admin).
 * Generates a printable QR code that opens the employee self-signup form
 * pre-filled & locked to the selected firm:
 *   <origin>/employee-signup?company=<COMPANY_CODE>
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";
import QRCode from "react-native-qrcode-svg";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = {
  company_id: string;
  name: string;
  company_code?: string;
  logo_base64?: string | null;
};

const DEFAULT_BASE =
  Platform.OS === "web" && typeof window !== "undefined"
    ? window.location.origin
    : (process.env.EXPO_PUBLIC_BACKEND_URL as string) || "";

export default function JoinQrScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Company | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  // Iter 106 — QR links point to the configured public domain (the
  // user's personal VPS server) when set; else this portal's origin.
  const [publicBase, setPublicBase] = useState("");
  const [baseInput, setBaseInput] = useState("");
  const [savingBase, setSavingBase] = useState(false);

  const BASE_URL = publicBase || DEFAULT_BASE;

  useEffect(() => {
    api<{ public_base_url: string }>("/public-config")
      .then((r) => {
        setPublicBase(r.public_base_url || "");
        setBaseInput(r.public_base_url || "");
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        if (user.role === "company_admin") {
          // Employer sees only their own firm.
          const c = await api<Company>("/company");
          const list = c?.company_code ? [c] : [];
          setCompanies(list);
          if (list.length) setSelected(list[0]);
        } else {
          const r = await api<{ companies: Company[] }>("/companies");
          const list = (r.companies || []).filter((c) => c.company_code);
          setCompanies(list);
          if (list.length === 1) setSelected(list[0]);
        }
      } catch {
        setCompanies([]);
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.role]);


  // Iter 106 — the QR codes point to the "Get the App" landing page:
  // scan → install app → register (employee joining / employer signup).
  const employeeUrl = useMemo(() => selected?.company_code
    ? `${BASE_URL}/get-app?type=employee&company=${encodeURIComponent(selected.company_code)}`
    : `${BASE_URL}/get-app?type=employee`, [selected, BASE_URL]);
  const employerUrl = useMemo(
    () => `${BASE_URL}/get-app?type=employer`, [BASE_URL]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };



  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="joinqr-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>QR Codes — Joining & App</Text>
        <View style={{ width: 22 }} />
      </View>

      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.hint}>
          Print these QR codes and place them at your office. Scanning opens a
          page that first installs the app on the phone, then lets the person
          register — Employees join your firm, Employers register their company.
        </Text>

        {/* Iter 106 — public domain used inside every QR link */}
        {user.role === "super_admin" ? (
          <View style={styles.baseBox} testID="joinqr-basebox">
            <Text style={styles.lbl}>QR links point to (your server domain)</Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              <TextInput
                style={styles.baseInput}
                value={baseInput}
                onChangeText={setBaseInput}
                placeholder={`e.g. https://www.smartpayrolling.com (blank = ${DEFAULT_BASE})`}
                autoCapitalize="none"
                testID="joinqr-base-input"
              />
              <Pressable
                style={[styles.btn, styles.btnPrimary, savingBase && { opacity: 0.5 }]}
                disabled={savingBase}
                testID="joinqr-base-save"
                onPress={async () => {
                  setSavingBase(true);
                  try {
                    const r = await api<{ public_base_url: string }>("/admin/public-config", {
                      method: "PUT", body: { public_base_url: baseInput.trim() },
                    });
                    setPublicBase(r.public_base_url || "");
                    showToast(r.public_base_url
                      ? `QR links now point to ${r.public_base_url}`
                      : "Reset — QR links use this portal's domain");
                  } catch (e: any) {
                    showToast(e?.message || "Save failed");
                  } finally { setSavingBase(false); }
                }}>
                <Text style={[styles.btnTxt, { color: "#fff" }]}>Save</Text>
              </Pressable>
            </View>
            {publicBase ? (
              <Text style={styles.baseNow}>✓ Active: all QR codes open {publicBase}</Text>
            ) : null}
          </View>
        ) : null}

        <Text style={styles.lbl}>Select Firm</Text>
        {loading ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 24 }} />
        ) : companies.length === 0 ? (
          <Text style={styles.empty}>No firms with a company code found.</Text>
        ) : (
          <View style={styles.chipWrap}>
            {companies.map((c) => (
              <Pressable
                key={c.company_id}
                onPress={() => setSelected(c)}
                style={[styles.chip, selected?.company_id === c.company_id && styles.chipActive]}
                testID={`joinqr-firm-${c.company_id}`}
              >
                <Text
                  style={[
                    styles.chipTxt,
                    selected?.company_id === c.company_id && styles.chipTxtActive,
                  ]}
                >
                  {c.name}
                </Text>
              </Pressable>
            ))}
          </View>
        )}

        {/* Iter 106 — TWO QR codes: Employee registration & Employer registration.
            Both land on /get-app: install the app first, then register. */}
        <>
          <Text style={[styles.lbl, { marginTop: spacing.sm }]}>
            Scan → Install App → Register
          </Text>
          {[{
              key: "employee", title: "Employee QR", color: "#16A34A",
              icon: "person-add-outline" as const, url: employeeUrl,
              sub: selected
                ? `${selected.name} — employee registers himself (joining form)`
                : "Employee registers himself (joining form)",
              hindi: "कर्मचारी — QR स्कैन करें, ऐप इंस्टॉल करें और रजिस्टर करें",
            }, {
              key: "employer", title: "Employer QR", color: "#1E3A8A",
              icon: "briefcase-outline" as const, url: employerUrl,
              sub: "Employer registers his company (new firm signup)",
              hindi: "नियोक्ता — QR स्कैन करें, ऐप इंस्टॉल करें और कंपनी रजिस्टर करें",
            }].map((qc) => (
              <View key={qc.key} style={[styles.card, { borderTopWidth: 4, borderTopColor: qc.color }]}
                testID={`appqr-${qc.key}`}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                  <Ionicons name={qc.icon} size={20} color={qc.color} />
                  <Text style={styles.cardFirm}>{qc.title}</Text>
                </View>
                <Text style={styles.cardSub}>{qc.sub}</Text>
                <Text style={styles.cardHindi}>{qc.hindi}</Text>
                <View style={[styles.qrBox, { marginTop: spacing.sm }]}>
                  <QRCode value={qc.url} size={220} backgroundColor="#FFFFFF" color="#111111" />
                </View>
                {qc.key === "employee" && selected?.company_code ? (
                  <Text style={styles.codeTxt}>Company Code: {selected.company_code}</Text>
                ) : null}
                <Text style={styles.urlTxt} selectable>{qc.url}</Text>
                <View style={styles.btnRow}>
                  <Pressable style={styles.btn} testID={`appqr-${qc.key}-copy`}
                    onPress={() => {
                      if (Platform.OS === "web" && navigator?.clipboard) {
                        navigator.clipboard.writeText(qc.url);
                        showToast("Link copied to clipboard");
                      } else showToast(qc.url);
                    }}>
                    <Ionicons name="copy-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.btnTxt}>Copy Link</Text>
                  </Pressable>
                  {Platform.OS === "web" ? (
                    <Pressable style={[styles.btn, styles.btnPrimary]} testID={`appqr-${qc.key}-print`}
                      onPress={() => {
                        const w = window.open("", "_blank");
                        if (!w) return;
                        w.document.write(`<!DOCTYPE html><html><head><title>${qc.title}${selected ? " — " + selected.name : ""}</title>
                          <style>body{font-family:sans-serif;text-align:center;padding:40px}
                          .url{font-size:13px;color:#555;word-break:break-all}</style></head><body>
                          <h1>${qc.title}</h1><h3>${qc.key === "employee" && selected ? selected.name : "S.K. Sharma & Co."}</h3>
                          <img style="width:300px;height:300px;margin:20px 0"
                            src="https://api.qrserver.com/v1/create-qr-code/?size=600x600&data=${encodeURIComponent(qc.url)}" />
                          <p>Scan with your phone camera — install the app, then register.</p>
                          <p class="url">${qc.url}</p>
                          <script>window.onload=()=>setTimeout(()=>window.print(),600)</script></body></html>`);
                        w.document.close();
                      }}>
                      <Ionicons name="print-outline" size={16} color="#fff" />
                      <Text style={[styles.btnTxt, { color: "#fff" }]}>Print QR</Text>
                    </Pressable>
                  ) : null}
                </View>
              </View>
            ))}
          </>

        <View style={{ height: 40 }} />
      </ScrollView>

      {toast ? (
        <View style={styles.toast}>
          <Text style={styles.toastTxt}>{toast}</Text>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surfaceSecondary },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  body: { padding: spacing.md },
  hint: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginBottom: spacing.md, lineHeight: 19 },
  baseBox: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.md, marginBottom: spacing.md,
  },
  baseInput: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 9, fontSize: 12.5,
    color: colors.onSurface, backgroundColor: colors.surfaceSecondary,
  },
  baseNow: { color: "#16A34A", fontSize: 11.5, fontWeight: "700", marginTop: 6 },
  lbl: { color: colors.onSurface, fontSize: type.sm, fontWeight: "800", marginBottom: 8 },
  empty: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginVertical: 16 },
  chipWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: spacing.md },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 9,
    borderRadius: radius.pill ?? 999,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurface, fontSize: type.sm, fontWeight: "600" },
  chipTxtActive: { color: "#fff" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: "center",
    padding: spacing.lg,
    marginTop: spacing.sm,
  },
  cardLogo: { width: 64, height: 64, borderRadius: 12, marginBottom: 8 },
  cardFirm: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800", textAlign: "center" },
  cardSub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  cardHindi: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "700", marginTop: 4, marginBottom: spacing.md, textAlign: "center" },
  qrBox: {
    padding: 16,
    backgroundColor: "#FFFFFF",
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  codeTxt: { color: colors.onSurface, fontSize: type.base, fontWeight: "800", marginTop: spacing.md, letterSpacing: 1 },
  urlTxt: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 6, textAlign: "center" },
  btnRow: { flexDirection: "row", gap: 10, marginTop: spacing.md },
  btn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 16,
    paddingVertical: 11,
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  btnPrimary: { backgroundColor: colors.brandPrimary },
  btnTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "800" },
  toast: {
    position: "absolute",
    bottom: 30,
    alignSelf: "center",
    backgroundColor: "#111827",
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: radius.pill ?? 999,
    maxWidth: "90%",
  },
  toastTxt: { color: "#fff", fontSize: type.sm },
});
