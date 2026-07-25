/**
 * Iter 294 — Bank Transfer Files (salary upload for corporate net-banking).
 *
 * Flow: Salary processed → pick month + bank + file type → download the
 * ready-to-upload NEFT/salary bulk file → upload in your bank's corporate
 * portal → bank credits salaries. No bank API needed.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  Platform, TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

type BankDef = { key: string; label: string; headers: string[] };
type Row = {
  sn: number; name: string; bank_name: string; name_as_per_bank: string;
  ifsc: string; account_no: string; net_salary: number;
};

const FILE_TYPES = ["xlsx", "csv", "txt", "xml"];

function monthOptions(): { value: string; label: string }[] {
  const out: { value: string; label: string }[] = [];
  const d = new Date();
  for (let i = 0; i < 12; i++) {
    const dt = new Date(d.getFullYear(), d.getMonth() - i, 1);
    out.push({
      value: `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}`,
      label: dt.toLocaleString("en", { month: "short", year: "numeric" }),
    });
  }
  return out;
}

export default function BankTransferScreen() {
  const { selectedCompanyId } = useSelectedCompany();
  const months = useMemo(() => monthOptions(), []);
  const [month, setMonth] = useState(months[0].value);
  const [banks, setBanks] = useState<BankDef[]>([]);
  const [bank, setBank] = useState("icici");
  const [fmt, setFmt] = useState("xlsx");
  const [debitAcc, setDebitAcc] = useState("");
  const [payDate, setPayDate] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [dl, setDl] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<{ banks: BankDef[] }>("/admin/bank-transfer/formats")
      .then((r) => setBanks(r.banks || []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    (async () => {
      setBusy(true); setErr(null);
      try {
        const params = new URLSearchParams({ month, pay_mode: "Bank" });
        if (selectedCompanyId) params.set("company_id", selectedCompanyId);
        const r = await api<{ rows: Row[]; total_net: number; has_compliance: boolean }>(
          `/admin/bank-sheet?${params.toString()}`);
        const payable = (r.rows || []).filter((x) => x.net_salary > 0 && (x.account_no || "").trim());
        setRows(payable);
        setTotal(payable.reduce((s, x) => s + x.net_salary, 0));
        if (!r.has_compliance) setErr("No Compliance Salary run found for this month — process salary first.");
      } catch (e: any) {
        setErr(e?.message || "Failed to load"); setRows([]);
      } finally { setBusy(false); }
    })();
  }, [month, selectedCompanyId]);

  const download = async () => {
    setDl(true);
    try {
      const params = new URLSearchParams({ month, bank, fmt });
      if (selectedCompanyId) params.set("company_id", selectedCompanyId);
      if (debitAcc.trim()) params.set("debit_account", debitAcc.trim());
      if (payDate.trim()) params.set("payment_date", payDate.trim());
      const r = await apiBinary(`/admin/bank-transfer/file?${params.toString()}`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl; a.download = `salary-upload-${bank}-${month}.${fmt}`;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(r.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Download failed");
    } finally { setDl(false); }
  };

  const selBank = banks.find((b) => b.key === bank);

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Bank Transfer Files", headerShown: false }} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>🏦 Bank Transfer Files</Text>
        <Text style={styles.sub}>
          Generate ready-to-upload salary files for your corporate net-banking.
          Upload the file in the bank portal, approve, and the bank credits salaries.
        </Text>

        {/* Steps strip */}
        <View style={styles.steps}>
          {["Salary Processed", "Generate Bank File", "Upload to Net Banking", "Bank Credits Salaries"].map((s, i) => (
            <View key={s} style={styles.step}>
              <View style={styles.stepNum}><Text style={styles.stepNumTxt}>{i + 1}</Text></View>
              <Text style={styles.stepTxt}>{s}</Text>
            </View>
          ))}
        </View>

        {/* Month */}
        <Text style={styles.lbl}>Salary Month</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 12 }}>
          <View style={{ flexDirection: "row", gap: 6 }}>
            {months.map((m) => (
              <Pressable key={m.value} onPress={() => setMonth(m.value)}
                style={[styles.chip, month === m.value && styles.chipActive]}
                testID={`bt-month-${m.value}`}>
                <Text style={[styles.chipTxt, month === m.value && styles.chipTxtActive]}>{m.label}</Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>

        {/* Bank format */}
        <Text style={styles.lbl}>Bank Format</Text>
        <View style={styles.bankGrid}>
          {banks.map((b) => (
            <Pressable key={b.key} onPress={() => setBank(b.key)}
              style={[styles.bankCard, bank === b.key && styles.bankCardActive]}
              testID={`bt-bank-${b.key}`}>
              <Ionicons name="business-outline" size={16}
                color={bank === b.key ? "#2563EB" : "#64748B"} />
              <Text style={[styles.bankTxt, bank === b.key && { color: "#2563EB" }]}>{b.label}</Text>
            </Pressable>
          ))}
        </View>
        {selBank ? (
          <Text style={styles.headersHint}>Columns: {selBank.headers.join(" · ")}</Text>
        ) : null}

        {/* File type + inputs */}
        <View style={{ flexDirection: "row", gap: 16, flexWrap: "wrap", marginTop: 12 }}>
          <View>
            <Text style={styles.lbl}>File Type</Text>
            <View style={{ flexDirection: "row", gap: 6 }}>
              {FILE_TYPES.map((f) => (
                <Pressable key={f} onPress={() => setFmt(f)}
                  style={[styles.chip, fmt === f && styles.chipActive]} testID={`bt-fmt-${f}`}>
                  <Text style={[styles.chipTxt, fmt === f && styles.chipTxtActive]}>.{f}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          <View style={{ minWidth: 220 }}>
            <Text style={styles.lbl}>Debit Account No (your firm A/c)</Text>
            <TextInput style={styles.input} value={debitAcc} onChangeText={setDebitAcc}
              placeholder="e.g. 000405001234" placeholderTextColor="#94A3B8" testID="bt-debit-acc" />
          </View>
          <View style={{ minWidth: 160 }}>
            <Text style={styles.lbl}>Payment Date (DD/MM/YYYY)</Text>
            <TextInput style={styles.input} value={payDate} onChangeText={setPayDate}
              placeholder={new Date().toLocaleDateString("en-GB")} placeholderTextColor="#94A3B8"
              testID="bt-pay-date" />
          </View>
        </View>

        {/* Summary + download */}
        <View style={styles.summary}>
          <View>
            <Text style={styles.sumBig}>{rows.length} employees · ₹{total.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</Text>
            <Text style={styles.sumSub}>Bank-mode employees with account details & net pay &gt; 0</Text>
          </View>
          <Pressable onPress={download} disabled={dl || rows.length === 0}
            style={[styles.dlBtn, (dl || rows.length === 0) && { opacity: 0.5 }]}
            testID="bt-download">
            {dl ? <ActivityIndicator size="small" color="#fff" />
              : <Ionicons name="download-outline" size={16} color="#fff" />}
            <Text style={styles.dlBtnTxt}>Download {bank.toUpperCase()} .{fmt}</Text>
          </Pressable>
        </View>
        {err ? <Text style={styles.err}>{err}</Text> : null}
        <Text style={styles.note}>
          ⚠️ Before your FIRST upload, verify the column order with your bank branch —
          corporate portal templates can differ per account setup.
        </Text>

        {/* Preview */}
        {busy ? <ActivityIndicator style={{ marginTop: 16 }} color={colors.brandPrimary} /> : (
          rows.length > 0 ? (
            <View style={styles.table}>
              <View style={[styles.tr, styles.trHead]}>
                {["S.No", "Name", "Bank", "IFSC", "Account No", "Net ₹"].map((h) => (
                  <Text key={h} style={[styles.th, h === "Name" && { flex: 2 }]}>{h}</Text>
                ))}
              </View>
              {rows.slice(0, 100).map((r) => (
                <View key={r.sn} style={styles.tr}>
                  <Text style={styles.td}>{r.sn}</Text>
                  <Text style={[styles.td, { flex: 2 }]}>{r.name_as_per_bank || r.name}</Text>
                  <Text style={styles.td}>{r.bank_name}</Text>
                  <Text style={styles.td}>{r.ifsc}</Text>
                  <Text style={styles.td}>{r.account_no}</Text>
                  <Text style={[styles.td, { fontWeight: "700" }]}>{r.net_salary.toFixed(2)}</Text>
                </View>
              ))}
            </View>
          ) : null
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F8FAFC" },
  scroll: { padding: spacing.lg, paddingBottom: 60 },
  title: { fontSize: 20, fontWeight: "800", color: "#1F2937" },
  sub: { fontSize: 12.5, color: "#64748B", marginTop: 4, marginBottom: 14, maxWidth: 720 },
  steps: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginBottom: 16 },
  step: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#FFFFFF",
    borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7,
  },
  stepNum: {
    width: 18, height: 18, borderRadius: 9, backgroundColor: "#2563EB",
    alignItems: "center", justifyContent: "center",
  },
  stepNumTxt: { color: "#fff", fontSize: 10, fontWeight: "800" },
  stepTxt: { fontSize: 11.5, color: "#1F2937", fontWeight: "600" },
  lbl: { fontSize: 11, fontWeight: "800", color: "#64748B", marginBottom: 6, letterSpacing: 0.3 },
  chip: {
    borderRadius: 999, borderWidth: 1, borderColor: "#E2E8F0", backgroundColor: "#FFFFFF",
    paddingHorizontal: 12, paddingVertical: 7,
  },
  chipActive: { backgroundColor: "#2563EB", borderColor: "#2563EB" },
  chipTxt: { fontSize: 12, color: "#334155", fontWeight: "600" },
  chipTxtActive: { color: "#fff" },
  bankGrid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  bankCard: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#FFFFFF",
    borderWidth: 1, borderColor: "#E2E8F0", borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, minWidth: 220,
  },
  bankCardActive: { borderColor: "#2563EB", backgroundColor: "#EFF6FF" },
  bankTxt: { fontSize: 12, color: "#334155", fontWeight: "600", flexShrink: 1 },
  headersHint: { fontSize: 11, color: "#94A3B8", marginTop: 6 },
  input: {
    height: 38, borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 8,
    paddingHorizontal: 10, fontSize: 13, color: "#1F2937", backgroundColor: "#FFFFFF",
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  summary: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#E2E8F0",
    borderRadius: radius.md, padding: 14, marginTop: 16, gap: 12, flexWrap: "wrap",
  },
  sumBig: { fontSize: 16, fontWeight: "800", color: "#1F2937" },
  sumSub: { fontSize: 11, color: "#64748B", marginTop: 2 },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#22C55E",
    borderRadius: 10, paddingHorizontal: 18, paddingVertical: 11,
  },
  dlBtnTxt: { color: "#fff", fontSize: 13, fontWeight: "800" },
  err: { color: "#EF4444", fontSize: 12, marginTop: 8, fontWeight: "600" },
  note: { fontSize: 11.5, color: "#B45309", marginTop: 10 },
  table: {
    marginTop: 16, backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#E2E8F0",
    borderRadius: radius.md, overflow: "hidden",
  },
  tr: {
    flexDirection: "row", borderBottomWidth: 1, borderBottomColor: "#F1F5F9",
    paddingHorizontal: 12, paddingVertical: 8,
  },
  trHead: { backgroundColor: "#F8FAFC" },
  th: { flex: 1, fontSize: 11, fontWeight: "800", color: "#64748B" },
  td: { flex: 1, fontSize: 12, color: "#1F2937" },
});
