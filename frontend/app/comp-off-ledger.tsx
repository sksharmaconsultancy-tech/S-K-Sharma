/**
 * Iter 206 — Comp-Off Ledger (user request).
 * Per-employee compensatory-off balance earned by working week-off days
 * (policy: Week-Off Worked Attendance → Comp-Off) with a full ledger,
 * manual Grant / Use adjustments and auto-sync from attendance.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type Row = {
  user_id: string;
  name?: string;
  employee_code?: string | null;
  father_name?: string | null;
  designation?: string | null;
  earned: number;
  used: number;
  balance: number;
};
type Entry = {
  ledger_id: string;
  user_id: string;
  date: string;
  days: number;
  direction: "earn" | "use";
  source: string;
  remarks?: string;
};

export default function CompOffLedgerScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [data, setData] = useState<{ enabled: boolean; rows: Row[]; entries: Entry[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState("");
  const [openUid, setOpenUid] = useState<string | null>(null);
  const [adjUid, setAdjUid] = useState<string | null>(null);
  const [adjDays, setAdjDays] = useState("1");
  const [adjDir, setAdjDir] = useState<"earn" | "use">("use");
  const [adjRemarks, setAdjRemarks] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    (async () => {
      try {
        if (user.role !== "super_admin" && user.role !== "sub_admin") {
          setCompanyId(user.company_id || "");
        } else {
          const r = await api<{ companies: Company[] }>("/companies");
          setCompanies(r.companies || []);
          if ((r.companies || []).length === 1) setCompanyId(r.companies[0].company_id);
        }
      } catch { setCompanies([]); }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.role]);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    setMsg(null);
    try {
      const r = await api<any>(`/admin/comp-off/summary?company_id=${encodeURIComponent(companyId)}`);
      setData(r);
    } catch (e: any) {
      setMsg(e?.message || "Failed to load ledger.");
      setData(null);
    } finally { setLoading(false); }
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    const rows = data?.rows || [];
    const n = q.trim().toLowerCase();
    if (!n) return rows;
    return rows.filter((r) =>
      `${r.name || ""} ${r.employee_code || ""} ${r.designation || ""}`.toLowerCase().includes(n));
  }, [data, q]);

  const entriesFor = useCallback(
    (uid: string) => (data?.entries || []).filter((e) => e.user_id === uid),
    [data],
  );

  const submitAdjust = useCallback(async () => {
    if (!adjUid) return;
    setMsg(null);
    try {
      await api("/admin/comp-off/adjust", {
        method: "POST",
        body: { user_id: adjUid, days: Number(adjDays) || 0, direction: adjDir, remarks: adjRemarks },
      });
      setAdjUid(null); setAdjDays("1"); setAdjRemarks("");
      await load();
    } catch (e: any) { setMsg(e?.message || "Adjustment failed."); }
  }, [adjUid, adjDays, adjDir, adjRemarks, load]);

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) {
    return <Redirect href="/(tabs)" />;
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={st.backBtn} testID="cof-back">
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Comp-Off Ledger</Text>
          <Text style={st.sub}>Earned from worked week-offs · used via leave adjustments</Text>
        </View>
        <Pressable onPress={load} style={st.syncBtn} testID="cof-refresh">
          <Ionicons name="sync-outline" size={16} color="#fff" />
          <Text style={st.syncTxt}>Sync</Text>
        </Pressable>
      </View>

      {companies.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={st.firmRow}>
          {companies.map((c) => (
            <Pressable
              key={c.company_id}
              onPress={() => setCompanyId(c.company_id)}
              style={[st.chip, companyId === c.company_id && st.chipOn]}
              testID={`cof-firm-${c.company_id}`}
            >
              <Text style={[st.chipTxt, companyId === c.company_id && st.chipTxtOn]}>{c.name}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}

      {msg ? <Text style={st.err}>{msg}</Text> : null}

      {!companyId ? (
        <Text style={st.hint}>Pick a firm to view its comp-off balances.</Text>
      ) : loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
      ) : !data ? null : (
        <ScrollView contentContainerStyle={{ paddingBottom: 60 }}>
          {!data.enabled && (
            <View style={st.warnBox}>
              <Ionicons name="information-circle-outline" size={16} color="#92400E" />
              <Text style={st.warnTxt}>
                Comp-Off earning is OFF for this firm. Enable it in Attendance Policy →
                Week-Off Worked Attendance → Comp-Off. Manual grants still work below.
              </Text>
            </View>
          )}
          <TextInput
            style={st.search}
            placeholder="Search name / code / designation…"
            placeholderTextColor={colors.onSurfaceSecondary}
            value={q}
            onChangeText={setQ}
            testID="cof-search"
          />
          <View style={st.theadRow}>
            <Text style={[st.th, { flex: 2.2 }]}>Employee</Text>
            <Text style={[st.th, st.thNum]}>Earned</Text>
            <Text style={[st.th, st.thNum]}>Used</Text>
            <Text style={[st.th, st.thNum]}>Balance</Text>
            <Text style={[st.th, { width: 74, textAlign: "center" }]}>Adjust</Text>
          </View>
          {filtered.map((r, i) => (
            <View key={r.user_id}>
              <Pressable
                onPress={() => setOpenUid(openUid === r.user_id ? null : r.user_id)}
                style={[st.row, i % 2 === 1 && st.rowZebra]}
                testID={`cof-row-${r.user_id}`}
              >
                <View style={{ flex: 2.2 }}>
                  <Text style={st.name}>{r.name}</Text>
                  <Text style={st.meta} numberOfLines={1}>
                    {[r.employee_code, r.designation].filter(Boolean).join(" · ") || "—"}
                  </Text>
                </View>
                <Text style={[st.num, { color: colors.success }]}>{r.earned || 0}</Text>
                <Text style={[st.num, { color: "#B45309" }]}>{r.used || 0}</Text>
                <Text style={[st.num, st.balTxt, r.balance > 0 && { color: colors.brandPrimary }]}>
                  {r.balance || 0}
                </Text>
                <Pressable
                  onPress={() => { setAdjUid(r.user_id); setAdjDir("use"); }}
                  style={st.adjBtn}
                  testID={`cof-adjust-${r.user_id}`}
                >
                  <Ionicons name="create-outline" size={15} color={colors.brandPrimary} />
                </Pressable>
              </Pressable>
              {openUid === r.user_id && (
                <View style={st.ledgerBox}>
                  {entriesFor(r.user_id).length === 0 ? (
                    <Text style={st.meta}>No ledger entries yet.</Text>
                  ) : entriesFor(r.user_id).map((e) => (
                    <View key={e.ledger_id} style={st.ledgerRow}>
                      <Text style={st.ledgerDate}>{e.date}</Text>
                      <Text style={[st.ledgerDays,
                        e.direction === "use" ? { color: "#B45309" } : { color: colors.success }]}>
                        {e.direction === "use" ? "−" : "+"}{e.days}
                      </Text>
                      <Text style={st.ledgerSrc}>
                        {e.source === "weekoff_worked" ? "Worked week-off"
                          : e.source === "leave_adjust" ? "Leave adjustment" : "Manual"}
                      </Text>
                      <Text style={st.ledgerRemarks} numberOfLines={1}>{e.remarks || ""}</Text>
                    </View>
                  ))}
                </View>
              )}
              {adjUid === r.user_id && (
                <View style={st.adjBox}>
                  <Text style={st.adjTitle}>Adjust comp-off — {r.name}</Text>
                  <View style={st.adjRow}>
                    {(["use", "earn"] as const).map((d) => (
                      <Pressable key={d} onPress={() => setAdjDir(d)}
                        style={[st.chip, adjDir === d && st.chipOn]}
                        testID={`cof-dir-${d}`}>
                        <Text style={[st.chipTxt, adjDir === d && st.chipTxtOn]}>
                          {d === "use" ? "Use (−)" : "Grant (+)"}
                        </Text>
                      </Pressable>
                    ))}
                    <TextInput
                      style={st.daysInput}
                      value={adjDays}
                      onChangeText={setAdjDays}
                      keyboardType="decimal-pad"
                      testID="cof-days"
                    />
                    <Text style={st.meta}>day(s)</Text>
                  </View>
                  <TextInput
                    style={st.remarksInput}
                    placeholder="Remarks (optional)"
                    placeholderTextColor={colors.onSurfaceSecondary}
                    value={adjRemarks}
                    onChangeText={setAdjRemarks}
                    testID="cof-remarks"
                  />
                  <View style={st.adjRow}>
                    <Pressable style={st.saveBtn} onPress={submitAdjust} testID="cof-save">
                      <Text style={st.saveTxt}>Save</Text>
                    </Pressable>
                    <Pressable style={st.cancelBtn} onPress={() => setAdjUid(null)}>
                      <Text style={st.cancelTxt}>Cancel</Text>
                    </Pressable>
                  </View>
                </View>
              )}
            </View>
          ))}
          {filtered.length === 0 && (
            <Text style={st.hint}>No employees match.</Text>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  backBtn: { padding: 6 },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11.5, color: colors.onSurfaceSecondary },
  syncBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 12,
    paddingVertical: 8, borderRadius: radius.md,
  },
  syncTxt: { color: "#fff", fontWeight: "700", fontSize: 12.5 },
  firmRow: { maxHeight: 46, paddingHorizontal: spacing.md, marginTop: spacing.sm },
  chip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
    marginRight: 8,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  chipTxtOn: { color: "#fff" },
  err: { color: colors.error, margin: spacing.md, fontWeight: "600" },
  hint: { color: colors.onSurfaceSecondary, margin: spacing.lg, textAlign: "center" },
  warnBox: {
    flexDirection: "row", gap: 6, alignItems: "center",
    backgroundColor: "#FEF3C7", margin: spacing.md, padding: spacing.sm,
    borderRadius: radius.md,
  },
  warnTxt: { color: "#92400E", fontSize: 12, flex: 1 },
  search: {
    margin: spacing.md, marginBottom: spacing.sm,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 13.5,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  theadRow: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.brandPrimary,
    marginHorizontal: spacing.md, borderTopLeftRadius: 6, borderTopRightRadius: 6,
    paddingHorizontal: 10, paddingVertical: 9,
  },
  th: { color: "#fff", fontWeight: "700", fontSize: 11.5 },
  thNum: { width: 62, textAlign: "right" },
  row: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: colors.surface, marginHorizontal: spacing.md,
    paddingHorizontal: 10, paddingVertical: 9,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  rowZebra: { backgroundColor: colors.surfaceSecondary },
  name: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  meta: { fontSize: 11, color: colors.onSurfaceSecondary },
  num: { width: 62, textAlign: "right", fontSize: 13, fontWeight: "700" },
  balTxt: { color: colors.onSurface },
  adjBtn: { width: 74, alignItems: "center", paddingVertical: 4 },
  ledgerBox: {
    marginHorizontal: spacing.md, backgroundColor: "#F1F5F9",
    padding: spacing.sm, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  ledgerRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 3 },
  ledgerDate: { fontSize: 11.5, color: colors.onSurfaceSecondary, width: 82 },
  ledgerDays: { fontSize: 12.5, fontWeight: "800", width: 44 },
  ledgerSrc: { fontSize: 11.5, color: colors.onSurface, width: 130 },
  ledgerRemarks: { fontSize: 11, color: colors.onSurfaceSecondary, flex: 1 },
  adjBox: {
    marginHorizontal: spacing.md, backgroundColor: "#EFF6FF",
    padding: spacing.md, borderBottomWidth: 1, borderBottomColor: colors.divider,
    gap: 8,
  },
  adjTitle: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  adjRow: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  daysInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 6, width: 70, textAlign: "center",
    color: colors.onSurface, backgroundColor: colors.surface, fontSize: 13,
  },
  remarksInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  saveBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 18, paddingVertical: 8,
  },
  saveTxt: { color: "#fff", fontWeight: "700", fontSize: 12.5 },
  cancelBtn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 8, backgroundColor: colors.surface,
  },
  cancelTxt: { color: colors.onSurface, fontWeight: "600", fontSize: 12.5 },
});
