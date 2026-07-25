/**
 * Iter 301 — Legacy vs Current comparison report.
 * Spot-check migrated data: old salary history alongside the new portal's
 * payroll, per employee, with basic-salary mismatch flags.
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const money = (v: any) =>
  v === null || v === undefined ? "—" :
    Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 });

export default function LegacyCompareScreen() {
  const [companies, setCompanies] = useState<any[]>([]);
  const [cid, setCid] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [err, setErr] = useState("");
  const [onlyMismatch, setOnlyMismatch] = useState(false);
  const [detail, setDetail] = useState<any>(null);   // {employee, months}
  const [detailBusy, setDetailBusy] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/companies");
        setCompanies(r.companies || r || []);
      } catch { /* ignore */ }
    })();
  }, []);

  const load = async (c: string, q = "") => {
    setBusy(true); setErr("");
    try {
      const r = await api<any>(
        `/admin/legacy-compare?company_id=${encodeURIComponent(c)}` +
        (q ? `&search=${encodeURIComponent(q)}` : ""));
      setRows(r.rows || []);
      setStats(r);
      if (!(r.rows || []).length) setErr("No legacy-imported employees in this firm — run the Legacy Import Wizard first.");
    } catch (e: any) { setErr(e?.message || "Failed"); }
    finally { setBusy(false); }
  };

  const openDetail = async (u: any) => {
    setDetailBusy(true);
    setDetail({ employee: u, months: [] });
    try {
      const r = await api<any>(`/admin/legacy-compare/${u.user_id}`);
      setDetail(r);
    } catch (e: any) {
      setDetail(null); setErr(e?.message || "Failed");
    } finally { setDetailBusy(false); }
  };

  const shown = onlyMismatch ? rows.filter((r) => r.mismatch_basic) : rows;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Legacy vs Current" }} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        <Text style={st.h1}>Legacy vs Current</Text>
        <Text style={st.sub}>
          Spot-check migrated data — each employee&apos;s old salary history next to the
          new portal&apos;s master &amp; payroll. Amber flag = master Basic differs from the
          last legacy Basic.
        </Text>

        <View style={st.card}>
          <Text style={st.lbl}>Firm</Text>
          <View style={st.wrap}>
            {companies.map((c: any) => (
              <Pressable
                key={c.company_id}
                style={[st.chip, cid === c.company_id && st.chipOn]}
                onPress={() => { setCid(c.company_id); load(c.company_id, search); }}
              >
                <Text style={[st.chipTxt, cid === c.company_id && st.chipTxtOn]}>{c.name}</Text>
              </Pressable>
            ))}
          </View>
        </View>

        {cid ? (
          <View style={st.card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <View style={st.searchBox}>
                <Ionicons name="search" size={14} color={colors.onSurfaceTertiary} />
                <TextInput
                  style={st.searchInput}
                  placeholder="Search name / code…"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  value={search}
                  onChangeText={setSearch}
                  onSubmitEditing={() => load(cid, search)}
                  returnKeyType="search"
                />
              </View>
              <Pressable style={[st.mmBtn, onlyMismatch && st.mmBtnOn]} onPress={() => setOnlyMismatch(!onlyMismatch)}>
                <Ionicons name="warning-outline" size={13} color={onlyMismatch ? "#fff" : "#B45309"} />
                <Text style={[st.mmTxt, onlyMismatch && { color: "#fff" }]}>
                  Mismatches{stats ? ` (${stats.mismatches})` : ""}
                </Text>
              </Pressable>
            </View>
            {stats ? (
              <Text style={st.meta}>
                {stats.count} employees · {stats.with_legacy} with legacy history · {stats.mismatches} basic mismatches
              </Text>
            ) : null}
            {busy ? <ActivityIndicator style={{ marginTop: 20 }} color={colors.brandPrimary} /> : null}

            {/* header row */}
            {shown.length ? (
              <View style={[st.row, { borderBottomWidth: 2 }]}>
                <Text style={[st.cName, st.hTxt]}>Employee</Text>
                <Text style={[st.cCol, st.hTxt]}>Legacy last (mo)</Text>
                <Text style={[st.cCol, st.hTxt]}>Master Basic</Text>
                <Text style={[st.cCol, st.hTxt]}>Current last (mo)</Text>
              </View>
            ) : null}
            {shown.map((r) => {
              const lo = r.legacy_online || r.legacy_offline;
              const cu = r.current_compliance || r.current_actual;
              return (
                <Pressable key={r.user_id} style={st.row} onPress={() => openDetail(r)}>
                  <View style={st.cName}>
                    <Text style={st.name} numberOfLines={1}>
                      {r.mismatch_basic ? "⚠️ " : ""}{r.name}
                    </Text>
                    <Text style={st.meta} numberOfLines={1}>
                      {r.employee_code ? `#${r.employee_code} · ` : ""}
                      {(r.legacy_online?.months || 0) + (r.legacy_offline?.months || 0)} legacy mo ·{" "}
                      {(r.current_actual?.months || 0) + (r.current_compliance?.months || 0)} current mo
                    </Text>
                  </View>
                  <View style={st.cCol}>
                    <Text style={st.val}>{lo ? `₹${money(lo.last_net)}` : "—"}</Text>
                    <Text style={st.meta}>{lo?.last_month || ""}</Text>
                  </View>
                  <View style={st.cCol}>
                    <Text style={[st.val, r.mismatch_basic && { color: "#B45309", fontWeight: "800" }]}>
                      ₹{money(r.basic_salary)}
                    </Text>
                    {r.mismatch_basic ? (
                      <Text style={[st.meta, { color: "#B45309" }]}>
                        legacy ₹{money(r.legacy_online?.last_basic)}
                      </Text>
                    ) : null}
                  </View>
                  <View style={st.cCol}>
                    <Text style={st.val}>{cu ? `₹${money(cu.last_net)}` : "—"}</Text>
                    <Text style={st.meta}>{cu?.last_month || ""}</Text>
                  </View>
                </Pressable>
              );
            })}
          </View>
        ) : null}
        {err ? <Text style={st.errTxt}>{err}</Text> : null}
      </ScrollView>

      {/* month-wise detail */}
      <Modal transparent visible={detail !== null} animationType="fade" onRequestClose={() => setDetail(null)}>
        <Pressable style={st.backdrop} onPress={() => setDetail(null)} />
        <View style={st.sheet}>
          <View style={{ flexDirection: "row", alignItems: "center" }}>
            <Text style={[st.h1, { fontSize: 16, flex: 1 }]} numberOfLines={1}>
              {detail?.employee?.name}
            </Text>
            <Pressable onPress={() => setDetail(null)} hitSlop={10}>
              <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>
          <Text style={st.meta}>
            {detail?.employee?.employee_code ? `#${detail.employee.employee_code} · ` : ""}
            Master: Basic ₹{money(detail?.employee?.basic_salary)} · Gross ₹{money(detail?.employee?.compliance_gross)}
            {detail?.employee?.salary_monthly ? ` · Actual ₹${money(detail.employee.salary_monthly)}` : ""}
          </Text>
          {detailBusy ? <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} /> : (
            <ScrollView style={{ marginTop: 10 }} horizontal>
              <View>
                <View style={[st.dRow, { borderBottomWidth: 2 }]}>
                  <Text style={[st.dMon, st.hTxt]}>Month</Text>
                  {["Legacy Online", "Legacy Offline", "Compliance (new)", "Actual (new)"].map((h) => (
                    <Text key={h} style={[st.dCell, st.hTxt]}>{h}</Text>
                  ))}
                </View>
                <ScrollView style={{ maxHeight: 430 }}>
                  {(detail?.months || []).map((m: any) => (
                    <View key={m.month} style={st.dRow}>
                      <Text style={st.dMon}>{m.month}</Text>
                      {[m.legacy_online, m.legacy_offline, m.compliance, m.actual].map((c: any, i: number) => (
                        <View key={i} style={st.dCell}>
                          {c ? (
                            <>
                              <Text style={st.val}>₹{money(c.net)}</Text>
                              <Text style={st.meta}>
                                {c.days ?? "—"} d · G ₹{money(c.gross)}
                              </Text>
                            </>
                          ) : <Text style={st.meta}>—</Text>}
                        </View>
                      ))}
                    </View>
                  ))}
                  {!(detail?.months || []).length ? (
                    <Text style={[st.meta, { marginTop: 20 }]}>No salary records found for this employee.</Text>
                  ) : null}
                </ScrollView>
              </View>
            </ScrollView>
          )}
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    marginTop: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  lbl: { fontSize: 12, fontWeight: "800", color: colors.onSurfaceSecondary, marginBottom: 6 },
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6, backgroundColor: colors.surfaceSecondary,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  chipTxtOn: { color: "#fff" },
  searchBox: {
    flex: 1, flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, height: 38, backgroundColor: colors.surfaceSecondary,
  },
  searchInput: { flex: 1, fontSize: 13, color: colors.onSurface },
  mmBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: "#B45309", borderRadius: 999,
    paddingHorizontal: 10, height: 38,
  },
  mmBtnOn: { backgroundColor: "#B45309" },
  mmTxt: { fontSize: 11.5, fontWeight: "800", color: "#B45309" },
  meta: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  row: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  hTxt: { fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  cName: { flex: 1.6, minWidth: 0 },
  cCol: { flex: 1, alignItems: "flex-end" },
  name: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  val: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  errTxt: { color: "#DC2626", fontSize: 12, marginTop: 8 },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.45)" },
  sheet: {
    position: "absolute", left: 16, right: 16, top: "8%",
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    maxHeight: "84%",
  },
  dRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 7, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  dMon: { width: 76, fontSize: 12, fontWeight: "800", color: colors.onSurface },
  dCell: { width: 128, alignItems: "flex-end", paddingRight: 8 },
});
