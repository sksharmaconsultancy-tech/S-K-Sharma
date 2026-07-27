/**
 * Firms ID & Password (PF · ESIC) — Iter 306 (user #14).
 *
 * SUPER ADMIN ONLY vault screen. The portal login credentials of every
 * firm (EPF portal, ESIC portal + any extra portal logins captured in the
 * Firm Master) are revealed ONLY after the super admin re-enters their
 * login PIN. Passwords stay hidden behind per-row eye toggles.
 */
import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator,
  ScrollView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing } from "@/src/theme";

type FirmCred = {
  company_id: string;
  firm_name: string;
  city?: string | null;
  epf_code?: string | null;
  epf_user_id?: string | null;
  epf_password?: string | null;
  esi_no?: string | null;
  esi_user_id?: string | null;
  esi_password?: string | null;
  other_logins?: { login_type?: string; user_name?: string; password?: string | null }[];
};

function copyText(t: string) {
  if (Platform.OS === "web") {
    try { (navigator as any)?.clipboard?.writeText(t); } catch { /* noop */ }
  }
}

function SecretCell({ value }: { value?: string | null }) {
  const [show, setShow] = useState(false);
  if (!value) return <Text style={styles.mutedTxt}>—</Text>;
  return (
    <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
      <Text style={styles.credTxt} numberOfLines={1}>
        {show ? value : "••••••••"}
      </Text>
      <Pressable onPress={() => setShow((s) => !s)} hitSlop={6}>
        <Ionicons name={show ? "eye-off-outline" : "eye-outline"} size={15} color={colors.brandPrimary} />
      </Pressable>
      <Pressable onPress={() => copyText(value)} hitSlop={6}>
        <Ionicons name="copy-outline" size={13} color={colors.onSurfaceSecondary} />
      </Pressable>
    </View>
  );
}

export default function FirmCredentialsScreen() {
  const { user } = useAuth();
  const [pin, setPin] = useState("");
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [firms, setFirms] = useState<FirmCred[] | null>(null);
  const [search, setSearch] = useState("");
  // Iter 325 (user request) — Excel-sheet view with tap-to-copy cells.
  const [copied, setCopied] = useState("");
  const [showPw, setShowPw] = useState(false);
  // Iter 328 (user report) — opening this page from the search menu could
  // "click through" onto a cell and copy an email/value unintentionally.
  // Ignore any copy in the first moments after the sheet mounts.
  const mountedAt = React.useRef(Date.now());

  const copyCell = (key: string, v: string) => {
    if (!v || Date.now() - mountedAt.current < 900) return;
    copyText(v);
    setCopied(key);
    setTimeout(() => setCopied((c) => (c === key ? "" : c)), 1200);
  };

  if (user && user.role !== "super_admin" && user.role !== "sub_admin") {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.lockBox}>
          <Ionicons name="lock-closed-outline" size={34} color={colors.onSurfaceSecondary} />
          <Text style={styles.lockTitle}>Super Admin / Sub Super Admin only</Text>
          <Text style={styles.mutedTxt}>Firm portal credentials are restricted.</Text>
        </View>
      </SafeAreaView>
    );
  }

  const unlock = async () => {
    if (!pin.trim()) { setErr("Enter your Admin PIN"); return; }
    setLoading(true); setErr("");
    try {
      const r = await api<{ firms: FirmCred[] }>("/admin/firm-credentials", {
        method: "POST",
        body: { pin: pin.trim() },
      });
      setFirms(r.firms || []);
    } catch (e: any) {
      setErr(e?.message || "PIN verification failed");
    } finally { setLoading(false); }
  };

  const visible = (firms || []).filter((f) =>
    !search.trim() || f.firm_name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.headerRow}>
          <View style={styles.headerIcon}>
            <Ionicons name="key-outline" size={20} color={colors.onBrandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Firms ID & Password</Text>
            <Text style={styles.subtitle}>EPF · ESIC portal logins for every firm</Text>
          </View>
          {firms ? (
            <Pressable style={styles.lockBtn} onPress={() => { setFirms(null); setPin(""); }}>
              <Ionicons name="lock-closed-outline" size={14} color={colors.error} />
              <Text style={styles.lockBtnTxt}>Lock</Text>
            </Pressable>
          ) : null}
        </View>

        {!firms ? (
          <View style={styles.pinCard}>
            <Ionicons name="shield-checkmark-outline" size={30} color={colors.brandPrimary} />
            <Text style={styles.pinTitle}>Verify your PIN</Text>
            <Text style={styles.mutedTxt}>
              Enter your login PIN to reveal firm portal credentials.
            </Text>
            <TextInput
              style={styles.pinInput}
              placeholder="PIN"
              placeholderTextColor={colors.onSurfaceTertiary}
              value={pin}
              onChangeText={setPin}
              secureTextEntry
              keyboardType="numeric"
              maxLength={8}
              onSubmitEditing={unlock}
              testID="cred-pin-input"
            />
            {!!err && <Text style={styles.errTxt}>{err}</Text>}
            <Pressable style={styles.unlockBtn} onPress={unlock} disabled={loading} testID="cred-unlock">
              {loading
                ? <ActivityIndicator color={colors.onBrandPrimary} size="small" />
                : <Ionicons name="lock-open-outline" size={15} color={colors.onBrandPrimary} />}
              <Text style={styles.unlockTxt}>Unlock credentials</Text>
            </Pressable>
          </View>
        ) : (
          <>
            <View style={styles.searchBox}>
              <Ionicons name="search-outline" size={15} color={colors.onSurfaceSecondary} />
              <TextInput
                style={styles.searchInput}
                placeholder="Search firm…"
                placeholderTextColor={colors.onSurfaceTertiary}
                value={search}
                onChangeText={setSearch}
              />
            </View>
            {/* Iter 325 (user request) — Excel-sheet view, tap any cell to copy */}
            <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <Pressable style={styles.pwToggle} onPress={() => setShowPw((s) => !s)} testID="cred-showpw">
                <Ionicons name={showPw ? "eye-off-outline" : "eye-outline"} size={14} color={colors.brandPrimary} />
                <Text style={styles.pwToggleTxt}>{showPw ? "Hide passwords" : "Show passwords"}</Text>
              </Pressable>
              <Text style={styles.mutedTxt}>Tap any cell to copy its value</Text>
            </View>
            {/* Iter 328 (user request) — ONE PAGE: flexible columns, no
                left/right scrolling. */}
            <View>
              <View style={styles.shRow}>
                {[
                  ["S.No", 0.5], ["Firm Name", 2.2], ["City", 1],
                  ["PF Code", 1.4], ["PF Login Id", 1.3], ["PF Password", 1.3],
                  ["ESIC Code", 1.5], ["ESIC Login Id", 1.3], ["ESIC Password", 1.3],
                ].map(([h, f]) => (
                  <Text key={h as string} style={[styles.shCell, { flex: f as number }]}>{h}</Text>
                ))}
              </View>
                {visible.map((f, i) => {
                  const cells: [string, string, number, boolean][] = [
                    ["name", f.firm_name || "", 2.2, false],
                    ["city", f.city || "", 1, false],
                    ["pfc", f.epf_code || "", 1.4, false],
                    ["pfu", f.epf_user_id || "", 1.3, false],
                    ["pfp", f.epf_password || "", 1.3, true],
                    ["esc", f.esi_no || "", 1.5, false],
                    ["esu", f.esi_user_id || "", 1.3, false],
                    ["esp", f.esi_password || "", 1.3, true],
                  ];
                  return (
                    <View key={f.company_id} style={[styles.sdRow, i % 2 === 1 && styles.sdRowAlt]}>
                      <Text style={[styles.sdTxt, { flex: 0.5, textAlign: "center", paddingVertical: 8 }]}>{i + 1}</Text>
                      {cells.map(([k, v, fx, secret]) => {
                        const ck = `${f.company_id}:${k}`;
                        return (
                          <Pressable
                            key={k}
                            style={[styles.sdCell, { flex: fx }]}
                            onPress={() => copyCell(ck, v)}
                          >
                            {copied === ck ? (
                              <Text style={styles.copiedTxt}>✓ Copied</Text>
                            ) : (
                              <Text style={styles.sdTxt} numberOfLines={2}>
                                {!v ? "—" : secret && !showPw ? "••••••••" : v}
                              </Text>
                            )}
                          </Pressable>
                        );
                      })}
                    </View>
                  );
                })}
            </View>
            {/* Extra portal logins (non EPF/ESIC) kept below the sheet */}
            {visible.some((f) => (f.other_logins || []).length) ? (
              <View style={{ marginTop: 14 }}>
                <Text style={styles.credColTitle}>OTHER PORTAL LOGINS</Text>
                {visible.map((f) =>
                  (f.other_logins || []).map((o, i) => (
                    <View key={`${f.company_id}-${i}`} style={styles.credRow}>
                      <Text style={[styles.credLabel, { width: 200 }]} numberOfLines={1}>
                        {f.firm_name} · {(o.login_type || "OTHER").toUpperCase()}
                      </Text>
                      <Text style={styles.credTxt} selectable>{o.user_name || "—"}</Text>
                      <SecretCell value={o.password} />
                    </View>
                  )),
                )}
              </View>
            ) : null}
            {!visible.length && (
              <Text style={[styles.mutedTxt, { textAlign: "center", padding: 24 }]}>
                No firms found.
              </Text>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surfaceSecondary },
  container: { padding: spacing.lg, paddingBottom: 60, maxWidth: 1100, width: "100%", alignSelf: "center" },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 16 },
  headerIcon: {
    width: 40, height: 40, borderRadius: 10, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 1 },
  lockBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 12,
    paddingVertical: 8, borderRadius: 8, borderWidth: 1, borderColor: colors.error,
  },
  lockBtnTxt: { fontSize: 12, fontWeight: "700", color: colors.error },
  lockBox: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  lockTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  mutedTxt: { fontSize: 12, color: colors.onSurfaceSecondary },
  pinCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: 28,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", gap: 10,
    maxWidth: 420, width: "100%", alignSelf: "center", marginTop: 30, ...shadow.card,
  },
  pinTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  pinInput: {
    width: 180, height: 46, borderWidth: 1, borderColor: colors.border,
    borderRadius: 10, textAlign: "center", fontSize: 18, letterSpacing: 6,
    color: colors.onSurface, backgroundColor: colors.surfaceSecondary,
  },
  errTxt: { color: colors.error, fontSize: 12 },
  unlockBtn: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.brandPrimary,
    paddingHorizontal: 18, paddingVertical: 11, borderRadius: 10, minHeight: 44,
  },
  unlockTxt: { color: colors.onBrandPrimary, fontSize: 13, fontWeight: "700" },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 6, height: 42,
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    paddingHorizontal: 10, backgroundColor: colors.surface, marginBottom: 12,
  },
  searchInput: { flex: 1, fontSize: 13, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" } as any : null) },
  firmCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12,
  },
  firmHead: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 10 },
  firmName: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  credGrid: { flexDirection: "row", flexWrap: "wrap", gap: 14 },
  credCol: {
    flexGrow: 1, flexBasis: 260, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: 12, gap: 6,
  },
  credColTitle: {
    fontSize: 10.5, fontWeight: "800", color: colors.brandPrimary, letterSpacing: 0.6,
  },
  credRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  credLabel: { width: 70, fontSize: 11.5, color: colors.onSurfaceSecondary, fontWeight: "600" },
  credTxt: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600", flexShrink: 1 },
  // Iter 325 — Excel-sheet view
  pwToggle: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1.5,
    borderColor: colors.brandPrimary, borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 6,
  },
  pwToggleTxt: { fontSize: 11.5, fontWeight: "800", color: colors.brandPrimary },
  shRow: { flexDirection: "row", backgroundColor: "#0F3B5C" },
  shCell: {
    color: "#fff", fontSize: 11, fontWeight: "800", paddingVertical: 9,
    paddingHorizontal: 8, borderRightWidth: 1, borderRightColor: "#2C567A",
  },
  sdRow: { flexDirection: "row", backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  sdRowAlt: { backgroundColor: "#F6F8FA" },
  sdCell: {
    paddingVertical: 8, paddingHorizontal: 8, justifyContent: "center",
    borderRightWidth: 1, borderRightColor: colors.border, minHeight: 36,
  },
  sdTxt: { fontSize: 12, color: colors.onSurface, fontWeight: "600" },
  copiedTxt: { fontSize: 11, color: "#15803D", fontWeight: "800" },
});
