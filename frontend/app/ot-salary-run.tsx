/**
 * OT Salary Process — Textile Policy 2 firms ONLY (Iter 129).
 *
 * Pays OVERTIME hours separately from the Compliance / Actual salary:
 *   • OT rate basis: % of BASIC or % of GROSS (per-day, from Employee
 *     Master's Actual salary structure) — configurable & auto-saved.
 *   • Recorded OT HRS shown as Duty HRS ÷ 2 (divisor configurable).
 *   • Bank Sheet (XLSX) download with account / IFSC per employee.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  ScrollView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";

const colors = {
  bg: "#F4F7F9",
  surface: "#FFFFFF",
  border: "#DCE4EA",
  onSurface: "#12262F",
  sub: "#5B707B",
  brand: "#0F2E3D",
  accent: "#1B7A67",
  danger: "#B3261E",
};

type Firm = {
  company_id: string;
  name: string;
  ot_salary_cfg?: { calc_on?: string; pct?: number; divide?: number };
  // Iter 131 — Firm Master OT Calculation config (Policy 2).
  ot_pct_basic?: number;
  ot_pct_gross?: number;
};
type Row = {
  user_id: string;
  employee_code?: string;
  name?: string;
  designation?: string;
  ot_duty_hours: number;
  ot_hours: number;
  per_day_base: number;
  hourly_rate: number;
  amount: number;
  esic_employee: number;
  net: number;
  bank_name?: string;
  bank_account_number?: string;
  ifsc_code?: string;
};
type Run = {
  company_id: string;
  company_name: string;
  month: string;
  full_day_hours: number;
  cfg: { calc_on: string; pct: number; divide: number; ot_pct_basic?: number; ot_pct_gross?: number };
  rows: Row[];
  totals: { ot_duty_hours: number; ot_hours: number; amount: number; esic_employee: number; net: number };
  employees_count: number;
};

function defaultMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function OtSalaryRunScreen() {
  const router = useRouter();
  const [firms, setFirms] = useState<Firm[]>([]);
  const [firmId, setFirmId] = useState<string | null>(null);
  const [month, setMonth] = useState(defaultMonth());
  const [calcOn, setCalcOn] = useState<"basic" | "gross">("gross");
  const [pct, setPct] = useState("100");
  const [halve, setHalve] = useState(true); // OT HRS = Duty ÷ 2
  const [run, setRun] = useState<Run | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const loadFirms = useCallback(async () => {
    try {
      const r = await api<{ firms: Firm[] }>("/admin/ot-salary/firms");
      setFirms(r.firms || []);
      if ((r.firms || []).length && !firmId) {
        const f = r.firms[0];
        setFirmId(f.company_id);
        const cfg = f.ot_salary_cfg || {};
        if (cfg.calc_on === "basic" || cfg.calc_on === "gross") setCalcOn(cfg.calc_on);
        if (cfg.pct) setPct(String(cfg.pct));
        if (cfg.divide) setHalve(Number(cfg.divide) >= 2);
      }
    } catch (e: any) {
      setErr(e?.message || "Failed to load firms");
    }
  }, [firmId]);

  useEffect(() => { loadFirms(); }, [loadFirms]);

  const qs = () =>
    `calc_on=${calcOn}&pct=${encodeURIComponent(Number(pct) || 100)}&divide=${halve ? 2 : 1}`;

  const generate = async () => {
    if (!firmId || loading) return;
    setLoading(true);
    setErr(null);
    try {
      const r = await api<{ run: Run }>(`/admin/ot-salary/${firmId}/${month}?${qs()}`);
      setRun(r.run);
    } catch (e: any) {
      setRun(null);
      setErr(e?.message || "Failed to compute OT salary");
    } finally { setLoading(false); }
  };

  const downloadBank = async () => {
    if (!firmId || downloading) return;
    setDownloading(true);
    try {
      const res = await apiBinary(`/admin/ot-salary/${firmId}/${month}/bank.xlsx?${qs()}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `OT_BankSheet_${month}.xlsx`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      setErr(e?.message || "Download failed");
    } finally { setDownloading(false); }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="ot-back">
          <Ionicons name="arrow-back" size={22} color={colors.brand} />
        </Pressable>
        <Text style={styles.headerTitle}>OT Salary Process</Text>
        <View style={{ width: 22 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 60 }}>
        <Text style={styles.note}>
          Separate overtime payout for Textile Policy 2 firms. OT hours come from approved
          biometric punches (same as the OT Report). Compliance / Actual salary are not affected.
        </Text>

        {/* Firm chips */}
        <Text style={styles.label}>Firm (Textile Policy 2 only)</Text>
        <View style={styles.chipsRow}>
          {firms.length === 0 ? (
            <Text style={styles.sub}>No firms have Policy 2 selected in Firm Master.</Text>
          ) : firms.map((f) => (
            <Pressable
              key={f.company_id}
              testID={`ot-firm-${f.company_id}`}
              onPress={() => { setFirmId(f.company_id); setRun(null); }}
              style={[styles.chip, firmId === f.company_id && styles.chipActive]}
            >
              <Text style={[styles.chipTxt, firmId === f.company_id && styles.chipTxtActive]}>{f.name}</Text>
            </Pressable>
          ))}
        </View>

        {/* Config */}
        {(() => {
          const f = firms.find((x) => x.company_id === firmId);
          const fmOn = !!f && ((f.ot_pct_basic || 0) > 0 || (f.ot_pct_gross || 0) > 0);
          return (
        <View style={styles.cfgRow}>
          <View style={{ flex: 1, minWidth: 120 }}>
            <Text style={styles.label}>Month</Text>
            <TextInput value={month} onChangeText={setMonth} placeholder="YYYY-MM" style={styles.input} testID="ot-month" />
          </View>
          {fmOn ? (
            <View style={{ flex: 2, minWidth: 220 }}>
              <Text style={styles.label}>OT calculation (from Firm Master)</Text>
              <Text style={styles.sub} testID="ot-fm-cfg">
                {(f?.ot_pct_basic || 0) > 0 ? `${f?.ot_pct_basic}% of Basic` : ""}
                {(f?.ot_pct_basic || 0) > 0 && (f?.ot_pct_gross || 0) > 0 ? " + " : ""}
                {(f?.ot_pct_gross || 0) > 0 ? `${f?.ot_pct_gross}% of Gross` : ""}
                {"  ·  set in Firm Master → Attendance Policy → OT Calculation"}
              </Text>
            </View>
          ) : (
            <>
          <View style={{ flex: 1, minWidth: 150 }}>
            <Text style={styles.label}>OT calculation on</Text>
            <View style={{ flexDirection: "row", gap: 6 }}>
              {(["basic", "gross"] as const).map((k) => (
                <Pressable key={k} testID={`ot-calcon-${k}`} onPress={() => setCalcOn(k)}
                  style={[styles.chip, calcOn === k && styles.chipActive]}>
                  <Text style={[styles.chipTxt, calcOn === k && styles.chipTxtActive]}>{k === "basic" ? "Basic" : "Gross"}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          <View style={{ width: 110 }}>
            <Text style={styles.label}>% of salary</Text>
            <TextInput value={pct} onChangeText={(t) => setPct(t.replace(/[^0-9.]/g, ""))}
              keyboardType="numeric" style={styles.input} testID="ot-pct" />
          </View>
            </>
          )}
          <View style={{ width: 170 }}>
            <Text style={styles.label}>OT HRS shown as</Text>
            <Pressable testID="ot-halve" onPress={() => setHalve(!halve)} style={[styles.chip, halve && styles.chipActive]}>
              <Text style={[styles.chipTxt, halve && styles.chipTxtActive]}>
                {halve ? "Duty HRS ÷ 2" : "Full Duty HRS"}
              </Text>
            </Pressable>
          </View>
        </View>
          );
        })()}

        <Pressable testID="ot-generate" onPress={generate} style={styles.primaryBtn} disabled={loading || !firmId}>
          {loading ? <ActivityIndicator color="#fff" /> : (
            <Text style={styles.primaryBtnTxt}>Salary Process (OT)</Text>
          )}
        </Pressable>

        {err ? <Text style={styles.err}>{err}</Text> : null}

        {run ? (
          <View style={styles.card}>
            <View style={styles.cardHead}>
              <Text style={styles.cardTitle}>
                {run.company_name} · {run.month} · {run.employees_count} employees
              </Text>
              <Pressable testID="ot-bank-xlsx" onPress={downloadBank} style={styles.dlBtn} disabled={downloading}>
                <Ionicons name="download-outline" size={15} color="#fff" />
                <Text style={styles.dlBtnTxt}>{downloading ? "..." : "Bank Sheet (Excel)"}</Text>
              </Pressable>
            </View>
            <Text style={styles.sub}>
              {run.cfg.calc_on === "firm_master"
                ? `OT per Firm Master: ${(run.cfg.ot_pct_basic || 0) > 0 ? `${run.cfg.ot_pct_basic}% Basic` : ""}${(run.cfg.ot_pct_basic || 0) > 0 && (run.cfg.ot_pct_gross || 0) > 0 ? " + " : ""}${(run.cfg.ot_pct_gross || 0) > 0 ? `${run.cfg.ot_pct_gross}% Gross` : ""} · OT HRS = Duty ÷ ${run.cfg.divide} · Full day ${run.full_day_hours} hrs`
                : `OT on ${run.cfg.calc_on.toUpperCase()} @ ${run.cfg.pct}% · OT HRS = Duty ÷ ${run.cfg.divide} · Full day ${run.full_day_hours} hrs`}
            </Text>
            <ScrollView horizontal showsHorizontalScrollIndicator>
              <View>
                <View style={[styles.tr, styles.trHead]}>
                  {["Code", "Name", "OT Duty HRS", "OT HRS", "Per-day base", "Rate/Hr", "OT Amount", "ESIC", "Net", "Bank A/c", "IFSC"].map((h, i) => (
                    <Text key={h} style={[styles.th, { width: COLW[i] }]}>{h}</Text>
                  ))}
                </View>
                {run.rows.map((r) => (
                  <View key={r.user_id} style={styles.tr}>
                    <Text style={[styles.td, { width: COLW[0] }]}>{r.employee_code || "—"}</Text>
                    <Text style={[styles.td, { width: COLW[1], textAlign: "left" }]} numberOfLines={1}>{r.name}</Text>
                    <Text style={[styles.td, { width: COLW[2] }]}>{r.ot_duty_hours}</Text>
                    <Text style={[styles.td, { width: COLW[3], fontWeight: "700" }]}>{r.ot_hours}</Text>
                    <Text style={[styles.td, { width: COLW[4] }]}>{Math.round(r.per_day_base)}</Text>
                    <Text style={[styles.td, { width: COLW[5] }]}>{r.hourly_rate}</Text>
                    <Text style={[styles.td, { width: COLW[6] }]}>{r.amount}</Text>
                    <Text style={[styles.td, { width: COLW[7] }]}>{r.esic_employee || "—"}</Text>
                    <Text style={[styles.td, { width: COLW[8], fontWeight: "800" }]}>{r.net}</Text>
                    <Text style={[styles.td, { width: COLW[9] }]} numberOfLines={1}>{r.bank_account_number || "—"}</Text>
                    <Text style={[styles.td, { width: COLW[10] }]} numberOfLines={1}>{r.ifsc_code || "—"}</Text>
                  </View>
                ))}
                <View style={[styles.tr, styles.trTotal]}>
                  <Text style={[styles.td, { width: COLW[0] + COLW[1], fontWeight: "800", textAlign: "left" }]}>TOTAL</Text>
                  <Text style={[styles.td, { width: COLW[2], fontWeight: "800" }]}>{run.totals.ot_duty_hours}</Text>
                  <Text style={[styles.td, { width: COLW[3], fontWeight: "800" }]}>{run.totals.ot_hours}</Text>
                  <Text style={[styles.td, { width: COLW[4] }]} />
                  <Text style={[styles.td, { width: COLW[5] }]} />
                  <Text style={[styles.td, { width: COLW[6], fontWeight: "800" }]}>{run.totals.amount}</Text>
                  <Text style={[styles.td, { width: COLW[7], fontWeight: "800" }]}>{run.totals.esic_employee}</Text>
                  <Text style={[styles.td, { width: COLW[8], fontWeight: "900" }]}>{run.totals.net}</Text>
                  <Text style={[styles.td, { width: COLW[9] + COLW[10] }]} />
                </View>
              </View>
            </ScrollView>
            {run.rows.length === 0 ? (
              <Text style={[styles.sub, { padding: 10 }]}>No OT hours found for this month (approved punches only).</Text>
            ) : null}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const COLW = [64, 180, 92, 76, 100, 76, 90, 70, 90, 140, 110];

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.bg },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 14, paddingVertical: 12, backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  headerTitle: { fontSize: 16, fontWeight: "800", color: colors.brand },
  note: { fontSize: 12.5, color: colors.sub, marginBottom: 12, lineHeight: 18 },
  label: { fontSize: 12, fontWeight: "700", color: colors.sub, marginBottom: 5 },
  sub: { fontSize: 12, color: colors.sub, marginTop: 4 },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 18,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipTxt: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  chipTxtActive: { color: "#fff" },
  cfgRow: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginBottom: 12 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, backgroundColor: colors.surface,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, color: colors.onSurface,
  },
  primaryBtn: {
    backgroundColor: colors.accent, borderRadius: 10, paddingVertical: 12,
    alignItems: "center", marginBottom: 12, minHeight: 44, justifyContent: "center",
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  err: { color: colors.danger, fontSize: 12.5, marginBottom: 10 },
  card: {
    backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1,
    borderColor: colors.border, padding: 12,
  },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 4, gap: 8, flexWrap: "wrap" },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brand,
    borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8, minHeight: 36,
  },
  dlBtnTxt: { color: "#fff", fontWeight: "700", fontSize: 12.5 },
  tr: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border, alignItems: "center" },
  trHead: { backgroundColor: "#EDF2F5" },
  trTotal: { backgroundColor: "#F6FAF8" },
  th: { fontSize: 11.5, fontWeight: "800", color: colors.sub, paddingVertical: 8, paddingHorizontal: 6, textAlign: "center" },
  td: { fontSize: 12, color: colors.onSurface, paddingVertical: 8, paddingHorizontal: 6, textAlign: "center" },
});
