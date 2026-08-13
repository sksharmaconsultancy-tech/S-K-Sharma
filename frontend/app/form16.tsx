/**
 * Iter 551 — FORM 16 (Phase 1). Payroll → TDS → Form 16.
 * Dashboard cards · FY selector · employee readiness list · generation-time
 * extra income/deduction heads · PDF / bulk ZIP download.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView,
  StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius } from "@/src/theme";

type Row = {
  user_id: string; employee_code?: string; name?: string; pan?: string;
  gross: number; tds: number; tds_applicable: boolean; ready: boolean;
  issues: string[]; generated: boolean; record_id?: string; version?: number;
};
type Extra = { label: string; amount: string };

const FYS = ["2024-25", "2025-26", "2026-27"];

export default function Form16Screen() {
  const router = useRouter();
  const { selectedCompanyId, companies } = useSelectedCompany() as any;
  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  const [fy, setFy] = useState("2025-26");
  const [rows, setRows] = useState<Row[]>([]);
  const [dash, setDash] = useState<any>({});
  const [tan, setTan] = useState<string | null>(null);
  const [sel, setSel] = useState<Record<string, boolean>>({});
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [extrasFor, setExtrasFor] = useState<string | null>(null);
  const [extraInc, setExtraInc] = useState<Extra[]>([]);
  const [extraDed, setExtraDed] = useState<Extra[]>([]);
  const [extrasMap, setExtrasMap] = useState<Record<string, any>>({});

  useEffect(() => { if (!firmId && selectedCompanyId) setFirmId(selectedCompanyId); }, [selectedCompanyId, firmId]);

  const load = useCallback(async () => {
    if (!firmId) return;
    setLoading(true); setErr("");
    try {
      const r = await api<any>(`/admin/form16/employees?company_id=${firmId}&fy=${fy}`);
      setRows(r.rows || []); setDash(r.dashboard || {}); setTan(r.company?.tan || null);
    } catch (x: any) { setErr(x?.message || "Failed to load"); }
    finally { setLoading(false); }
  }, [firmId, fy]);
  useEffect(() => { load(); }, [load]);

  const openDownload = async (path: string) => {
    try {
      const r = await apiBinary(path);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl;
        a.download = path.includes("zip") ? `Form16_${fy}.zip` : `Form16_${fy}.pdf`;
        a.click();
      }
    } catch (x: any) { setErr(x?.message || "Download failed"); }
  };

  const generate = async () => {
    const ids = Object.keys(sel).filter((k) => sel[k]);
    if (!ids.length) { setErr("Select at least one employee"); return; }
    setBusy(true); setErr("");
    try {
      const r = await api<any>(`/admin/form16/generate`, {
        method: "POST",
        body: JSON.stringify({ company_id: firmId, fy, user_ids: ids, extras: extrasMap }),
      });
      const s = r.skipped || [];
      if (s.length) setErr(`Skipped ${s.length}: ${s.map((x: any) => `${x.name || x.user_id} (${x.reason})`).join("; ").slice(0, 300)}`);
      setSel({}); await load();
    } catch (x: any) { setErr(x?.message || "Generation failed"); }
    finally { setBusy(false); }
  };

  const saveExtras = () => {
    if (!extrasFor) return;
    const clean = (a: Extra[]) => a.filter((x) => x.label.trim() && parseFloat(x.amount) > 0)
      .map((x) => ({ label: x.label.trim(), amount: parseFloat(x.amount) }));
    setExtrasMap((m) => ({ ...m, [extrasFor]: { other_income: clean(extraInc), deductions: clean(extraDed) } }));
    setExtrasFor(null);
  };

  const ql = q.trim().toLowerCase();
  const vRows = ql ? rows.filter((r) => (r.name || "").toLowerCase().includes(ql) || String(r.employee_code || "").includes(ql)) : rows;

  const Card = ({ label, value, tone }: any) => (
    <View style={[st.card, tone === "warn" && { borderColor: "#F59E0B" }, tone === "ok" && { borderColor: "#16A34A" }]}>
      <Text style={st.cardVal}>{value ?? 0}</Text>
      <Text style={st.cardLbl}>{label}</Text>
    </View>
  );

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={st.h1}>TDS · Form 16</Text>
        <Pressable onPress={load} hitSlop={8} testID="f16-refresh">
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ maxHeight: 40, paddingHorizontal: 10 }}>
        {(companies || []).map((c: any) => (
          <Pressable key={c.company_id} onPress={() => setFirmId(c.company_id)}
            style={[st.chip, firmId === c.company_id && st.chipOn]}>
            <Text style={[st.chipTxt, firmId === c.company_id && { color: "#fff" }]} numberOfLines={1}>{c.name}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <View style={st.fyRow}>
        {FYS.map((f) => (
          <Pressable key={f} onPress={() => setFy(f)} style={[st.chip, fy === f && st.chipOn]} testID={`f16-fy-${f}`}>
            <Text style={[st.chipTxt, fy === f && { color: "#fff" }]}>FY {f}</Text>
          </Pressable>
        ))}
        <TextInput style={st.search} value={q} onChangeText={setQ}
          placeholder="Search employee" placeholderTextColor={colors.onSurfaceTertiary} testID="f16-search" />
      </View>

      {tan === null || tan === "" ? (
        <Text style={st.warnTxt}>⚠ Employer TAN not set in Firm Master — it will print blank on Form 16.</Text>
      ) : null}
      {err ? <Text style={st.errTxt}>{err}</Text> : null}

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 10, paddingBottom: 60 }}>
        <View style={st.cards}>
          <Card label="Employees (FY payroll)" value={dash.total_employees} />
          <Card label="TDS Applicable" value={dash.tds_applicable} />
          <Card label="Form 16 Ready" value={dash.ready} tone="ok" />
          <Card label="Pending Issues" value={dash.pending} tone="warn" />
          <Card label="Generated" value={dash.generated} />
        </View>
        <View style={st.actions}>
          <Pressable style={st.btn} onPress={() => {
            const all: Record<string, boolean> = {};
            vRows.forEach((r) => { if (r.ready) all[r.user_id] = true; });
            setSel(all);
          }} testID="f16-select-all"><Text style={st.btnTxt}>Select All Ready</Text></Pressable>
          <Pressable style={[st.btn, st.btnPrimary]} onPress={generate} disabled={busy} testID="f16-generate">
            {busy ? <ActivityIndicator color="#fff" size="small" /> :
              <Text style={[st.btnTxt, { color: "#fff" }]}>Generate Form 16 ({Object.values(sel).filter(Boolean).length})</Text>}
          </Pressable>
          <Pressable style={st.btn} onPress={() => openDownload(`/admin/form16/bulk.zip?company_id=${firmId}&fy=${fy}`)} testID="f16-zip">
            <Text style={st.btnTxt}>Bulk ZIP</Text>
          </Pressable>
        </View>

        {loading ? <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} /> :
          vRows.map((r) => (
            <View key={r.user_id} style={st.row} testID={`f16-row-${r.user_id}`}>
              <Pressable onPress={() => r.ready && setSel((s) => ({ ...s, [r.user_id]: !s[r.user_id] }))}
                style={[st.check, sel[r.user_id] && st.checkOn, !r.ready && { opacity: 0.3 }]}>
                {sel[r.user_id] ? <Ionicons name="checkmark" size={13} color="#fff" /> : null}
              </Pressable>
              <View style={{ flex: 1 }}>
                <Text style={st.rowName} numberOfLines={1}>{r.name} · {r.employee_code}</Text>
                <Text style={st.rowMeta}>
                  PAN {r.pan || "—"} · Gross ₹{(r.gross || 0).toLocaleString()} · TDS ₹{(r.tds || 0).toLocaleString()}
                  {r.generated ? ` · v${r.version} generated` : ""}
                </Text>
                {!r.ready && <Text style={st.rowIssue}>⛔ {r.issues.join(", ")}</Text>}
                {extrasMap[r.user_id] ? <Text style={st.rowExtra}>＋ extra heads added</Text> : null}
              </View>
              <Pressable onPress={() => {
                setExtrasFor(r.user_id);
                const ex = extrasMap[r.user_id] || {};
                setExtraInc((ex.other_income || []).map((x: any) => ({ label: x.label, amount: String(x.amount) })));
                setExtraDed((ex.deductions || []).map((x: any) => ({ label: x.label, amount: String(x.amount) })));
              }} hitSlop={6} testID={`f16-extras-${r.user_id}`}>
                <Ionicons name="add-circle-outline" size={20} color="#B45309" />
              </Pressable>
              {r.generated && (
                <Pressable onPress={() => openDownload(`/admin/form16/${r.record_id}.pdf`)} hitSlop={6} testID={`f16-pdf-${r.user_id}`}>
                  <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
                </Pressable>
              )}
            </View>
          ))}
        {!loading && vRows.length === 0 && (
          <Text style={st.empty}>No employees with finalized payroll found for FY {fy}.</Text>
        )}
      </ScrollView>

      {extrasFor && (
        <View style={st.modalWrap}>
          <View style={st.modal}>
            <Text style={st.modalTitle}>Extra Form 16 heads — {rows.find((r) => r.user_id === extrasFor)?.name}</Text>
            <Text style={st.modalHint}>Add income/deduction heads not present in the existing masters. They apply only to this Form 16.</Text>
            {[["Other Income (adds to taxable)", extraInc, setExtraInc],
              ["Deductions (reduces taxable)", extraDed, setExtraDed]].map(([lbl, arr, setArr]: any) => (
              <View key={lbl} style={{ marginTop: 8 }}>
                <Text style={st.modalSec}>{lbl}</Text>
                {arr.map((x: Extra, i: number) => (
                  <View key={i} style={st.exRow}>
                    <TextInput style={[st.exInput, { flex: 2 }]} value={x.label} placeholder="Head name"
                      placeholderTextColor={colors.onSurfaceTertiary}
                      onChangeText={(v) => setArr((a: Extra[]) => a.map((y, j) => j === i ? { ...y, label: v } : y))} />
                    <TextInput style={[st.exInput, { flex: 1 }]} value={x.amount} placeholder="₹" keyboardType="numeric"
                      placeholderTextColor={colors.onSurfaceTertiary}
                      onChangeText={(v) => setArr((a: Extra[]) => a.map((y, j) => j === i ? { ...y, amount: v.replace(/[^\d.]/g, "") } : y))} />
                    <Pressable onPress={() => setArr((a: Extra[]) => a.filter((_, j) => j !== i))}>
                      <Ionicons name="trash-outline" size={18} color="#DC2626" />
                    </Pressable>
                  </View>
                ))}
                <Pressable onPress={() => setArr((a: Extra[]) => [...a, { label: "", amount: "" }])} style={st.addLine}>
                  <Ionicons name="add" size={14} color={colors.brandPrimary} />
                  <Text style={{ fontSize: 12, color: colors.brandPrimary, fontWeight: "700" }}>Add head</Text>
                </Pressable>
              </View>
            ))}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <Pressable style={[st.btn, { flex: 1 }]} onPress={() => setExtrasFor(null)}><Text style={st.btnTxt}>Cancel</Text></Pressable>
              <Pressable style={[st.btn, st.btnPrimary, { flex: 1 }]} onPress={saveExtras} testID="f16-extras-save">
                <Text style={[st.btnTxt, { color: "#fff" }]}>Save Heads</Text>
              </Pressable>
            </View>
          </View>
        </View>
      )}
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12 },
  h1: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  chip: { borderWidth: 1, borderColor: colors.divider, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, marginRight: 6, backgroundColor: colors.surface, maxWidth: 220 },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  fyRow: { flexDirection: "row", alignItems: "center", paddingHorizontal: 10, marginTop: 8, gap: 4 },
  search: { flex: 1, borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 7, fontSize: 12.5, color: colors.onSurface, backgroundColor: colors.surface },
  warnTxt: { color: "#B45309", fontSize: 11.5, paddingHorizontal: 12, paddingTop: 6, fontWeight: "700" },
  errTxt: { color: "#DC2626", fontSize: 11.5, paddingHorizontal: 12, paddingTop: 6 },
  cards: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  card: { borderWidth: 1, borderColor: colors.divider, borderRadius: radius.lg, backgroundColor: colors.surface, paddingVertical: 10, paddingHorizontal: 14, minWidth: 110, alignItems: "center" },
  cardVal: { fontSize: 18, fontWeight: "900", color: colors.onSurface },
  cardLbl: { fontSize: 10.5, color: colors.onSurfaceSecondary, marginTop: 2, textAlign: "center" },
  actions: { flexDirection: "row", gap: 8, marginVertical: 10, flexWrap: "wrap" },
  btn: { borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md, paddingHorizontal: 14, paddingVertical: 9, alignItems: "center", justifyContent: "center" },
  btnPrimary: { backgroundColor: colors.brandPrimary },
  btnTxt: { fontSize: 12.5, fontWeight: "800", color: colors.brandPrimary },
  row: { flexDirection: "row", alignItems: "center", gap: 10, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.divider, borderRadius: radius.lg, padding: 10, marginBottom: 6 },
  check: { width: 20, height: 20, borderRadius: 5, borderWidth: 1.5, borderColor: colors.brandPrimary, alignItems: "center", justifyContent: "center" },
  checkOn: { backgroundColor: colors.brandPrimary },
  rowName: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  rowMeta: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  rowIssue: { fontSize: 10.5, color: "#DC2626", marginTop: 2, fontWeight: "700" },
  rowExtra: { fontSize: 10.5, color: "#B45309", marginTop: 2, fontWeight: "700" },
  empty: { textAlign: "center", marginTop: 40, fontSize: 13, color: colors.onSurfaceTertiary },
  modalWrap: { position: "absolute", inset: 0, backgroundColor: "rgba(0,0,0,0.45)", alignItems: "center", justifyContent: "center", padding: 16 },
  modal: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: 16, width: "100%", maxWidth: 520 },
  modalTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  modalHint: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 4 },
  modalSec: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary, marginBottom: 4 },
  exRow: { flexDirection: "row", gap: 6, alignItems: "center", marginBottom: 6 },
  exInput: { borderWidth: 1, borderColor: colors.divider, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6, fontSize: 12, color: colors.onSurface },
  addLine: { flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4 },
});
