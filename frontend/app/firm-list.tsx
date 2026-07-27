/**
 * List of Firms — Iter 325 (user request).
 *
 * Excel-style grid of ALL Firm Master data (name, addresses, PF/ESI codes,
 * bank, contact, status) with search, tap-to-copy cells and one-click
 * "Export Excel" download.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator,
  ScrollView, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, spacing } from "@/src/theme";

type Col = { key: string; label: string };
type FirmRow = Record<string, any>;

const COL_W: Record<string, number> = {
  firm_name: 220, category: 110, business_nature: 140, start_date: 96,
  city: 110, state: 110, pin_code: 84, address: 240, email_1: 190,
  email_2: 150, epf_no: 150, epf_applicable: 90, esi_no: 150,
  esi_applicable: 90, bank_name: 150, account_no: 140, ifsc: 110,
  contact_person: 140, contact_phone: 120, firm_active: 70,
};

export default function FirmListScreen() {
  const { user } = useAuth();
  const [cols, setCols] = useState<Col[]>([]);
  const [rows, setRows] = useState<FirmRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [search, setSearch] = useState("");
  const [copied, setCopied] = useState("");
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ columns: Col[]; firms: FirmRow[] }>("/admin/firms-master-list");
        setCols(r.columns || []);
        setRows(r.firms || []);
      } catch (e: any) {
        setErr(e?.message || "Failed to load firms");
      } finally { setLoading(false); }
    })();
  }, []);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      ["firm_name", "city", "epf_no", "esi_no", "category"].some((k) =>
        String(r[k] || "").toLowerCase().includes(q)));
  }, [rows, search]);

  const copyCell = (key: string, v: string) => {
    if (!v) return;
    if (Platform.OS === "web") {
      try { (navigator as any)?.clipboard?.writeText(v); } catch { /* noop */ }
    }
    setCopied(key);
    setTimeout(() => setCopied((c) => (c === key ? "" : c)), 1200);
  };

  const exportXlsx = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const res = await apiBinary("/admin/firms-master-list/export.xlsx");
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = "Firms_Master_List.xlsx";
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      setErr(e?.message || "Export failed");
    } finally { setExporting(false); }
  };

  if (user && !["super_admin", "sub_admin"].includes(user.role as string)) {
    return (
      <SafeAreaView style={st.safe} edges={["top"]}>
        <View style={st.lockBox}>
          <Ionicons name="lock-closed-outline" size={34} color={colors.onSurfaceSecondary} />
          <Text style={st.lockTitle}>Admins only</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.container}>
        <View style={st.headerRow}>
          <View style={st.headerIcon}>
            <Ionicons name="list-outline" size={20} color={colors.onBrandPrimary} />
          </View>
          <View style={{ flex: 1 }}>
            <Text style={st.title}>List of Firms</Text>
            <Text style={st.subtitle}>
              Complete Firm Master data · tap any cell to copy · {rows.length} firms
            </Text>
          </View>
          <Pressable style={st.exportBtn} onPress={exportXlsx} disabled={exporting} testID="firm-export">
            {exporting
              ? <ActivityIndicator size="small" color={colors.onBrandPrimary} />
              : <Ionicons name="download-outline" size={15} color={colors.onBrandPrimary} />}
            <Text style={st.exportTxt}>Export Excel</Text>
          </Pressable>
        </View>

        <View style={st.searchBox}>
          <Ionicons name="search-outline" size={15} color={colors.onSurfaceSecondary} />
          <TextInput
            style={st.searchInput}
            placeholder="Search firm / city / PF code / ESIC code…"
            placeholderTextColor={colors.onSurfaceTertiary}
            value={search}
            onChangeText={setSearch}
          />
        </View>
        {!!err && <Text style={st.errTxt}>{err}</Text>}

        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : (
          <ScrollView horizontal showsHorizontalScrollIndicator style={{ flex: 1 }}>
            <ScrollView style={{ flex: 1 }} stickyHeaderIndices={[0]}>
              <View style={st.hRow}>
                <Text style={[st.hCell, { width: 46 }]}>S.No</Text>
                {cols.map((c) => (
                  <Text key={c.key} style={[st.hCell, { width: COL_W[c.key] || 120 }]}>
                    {c.label}
                  </Text>
                ))}
              </View>
              {visible.map((r, i) => (
                <View key={r.company_id || i} style={[st.dRow, i % 2 === 1 && st.dRowAlt]}>
                  <Text style={[st.dCellTxt, { width: 46, textAlign: "center", paddingVertical: 7 }]}>{i + 1}</Text>
                  {cols.map((c) => {
                    const v = String(r[c.key] ?? "");
                    const ck = `${r.company_id}:${c.key}`;
                    return (
                      <Pressable
                        key={c.key}
                        style={[st.dCell, { width: COL_W[c.key] || 120 }]}
                        onPress={() => copyCell(ck, v)}
                      >
                        {copied === ck ? (
                          <Text style={st.copiedTxt}>✓ Copied</Text>
                        ) : (
                          <Text style={st.dCellTxt} numberOfLines={2}>{v || "—"}</Text>
                        )}
                      </Pressable>
                    );
                  })}
                </View>
              ))}
              {!visible.length && (
                <Text style={[st.subtitle, { padding: 24, textAlign: "center" }]}>No firms found.</Text>
              )}
            </ScrollView>
          </ScrollView>
        )}
      </View>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surfaceSecondary },
  container: { flex: 1, padding: spacing.lg, paddingBottom: 16 },
  headerRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 12 },
  headerIcon: {
    width: 40, height: 40, borderRadius: 10, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 1 },
  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#15803D",
    paddingHorizontal: 14, paddingVertical: 10, borderRadius: 10, minHeight: 40,
  },
  exportTxt: { color: colors.onBrandPrimary, fontSize: 12.5, fontWeight: "800" },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 6, height: 40,
    borderWidth: 1, borderColor: colors.border, borderRadius: 10,
    paddingHorizontal: 10, backgroundColor: colors.surface, marginBottom: 10,
    maxWidth: 460,
  },
  searchInput: { flex: 1, fontSize: 13, color: colors.onSurface, ...(Platform.OS === "web" ? { outlineStyle: "none" } as any : null) },
  errTxt: { color: colors.error, fontSize: 12, marginBottom: 6 },
  lockBox: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  lockTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  hRow: { flexDirection: "row", backgroundColor: "#0F3B5C" },
  hCell: {
    color: "#fff", fontSize: 11, fontWeight: "800", paddingVertical: 9,
    paddingHorizontal: 8, borderRightWidth: 1, borderRightColor: "#2C567A",
  },
  dRow: { flexDirection: "row", backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border },
  dRowAlt: { backgroundColor: "#F6F8FA" },
  dCell: {
    paddingVertical: 7, paddingHorizontal: 8, justifyContent: "center",
    borderRightWidth: 1, borderRightColor: colors.border, minHeight: 36,
  },
  dCellTxt: { fontSize: 11.5, color: colors.onSurface },
  copiedTxt: { fontSize: 11, color: "#15803D", fontWeight: "800" },
});
