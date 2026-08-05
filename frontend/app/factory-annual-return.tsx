/**
 * Iter 499 — Factory & Boiler Annual Return
 * (Compliance → Statutory Returns). Government-style annual return built
 * from existing payroll + attendance data with a unified data layer:
 * Combined (default) / Current DB only / Legacy (imported) only.
 * Legacy records are read-only — details are saved on the firm only.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  TextInput,
  Modal,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import ReportTable, { ReportCol } from "@/src/components/ReportTable";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing } from "@/src/theme";

const SOURCES = [
  { key: "combined", label: "Combined (default)" },
  { key: "current", label: "Current DB only" },
  { key: "legacy", label: "Legacy DB only" },
];

const DETAIL_LABELS: { key: string; label: string }[] = [
  { key: "factory_name", label: "Factory Name" },
  { key: "factory_address", label: "Factory Address" },
  { key: "factory_license_no", label: "Factory License No." },
  { key: "factory_registration_no", label: "Factory Registration No." },
  { key: "boiler_registration_no", label: "Boiler Registration No." },
  { key: "occupier_name", label: "Occupier" },
  { key: "factory_manager", label: "Factory Manager" },
  { key: "nature_of_manufacturing", label: "Nature of Manufacturing" },
  { key: "district", label: "District" },
  { key: "state", label: "State" },
];
const WELFARE_LABELS: { key: string; label: string }[] = [
  { key: "canteen", label: "Canteen" },
  { key: "rest_room", label: "Rest Room" },
  { key: "creche", label: "Crèche" },
  { key: "first_aid", label: "First Aid" },
  { key: "ambulance_room", label: "Ambulance Room" },
  { key: "drinking_water", label: "Drinking Water" },
  { key: "washing_facility", label: "Washing Facility" },
];

const EMP_COLS: ReportCol<any>[] = [
  { key: "employee_code", label: "Code", type: "center", min: 64, sticky: true },
  { key: "name", label: "Name", min: 200, max: 300, sticky: true },
  { key: "gender", label: "Sex", type: "center", min: 48 },
  { key: "doj", label: "DOJ", type: "date" },
  { key: "category", label: "Category", min: 110, max: 200 },
  { key: "department", label: "Department", min: 120, max: 220 },
  { key: "designation", label: "Designation", min: 120, max: 220 },
  { key: "status", label: "Status", type: "center", min: 70 },
  { key: "months", label: "Months", type: "num", min: 72 },
  { key: "man_days", label: "Man Days", type: "num", min: 88 },
  {
    key: "wages", label: "Wages ₹", type: "num", min: 110,
    value: (r) => (r.wages || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 }),
  },
  { key: "ot_hours", label: "OT Hrs", type: "num", min: 76 },
];

const MONTH_COLS: ReportCol<any>[] = [
  { key: "month", label: "Month", type: "center", min: 90, sticky: true },
  { key: "employees", label: "Workers", type: "num", min: 84 },
  { key: "man_days", label: "Man Days", type: "num", min: 92 },
  { key: "avg_daily_employment", label: "Avg Daily", type: "num", min: 88 },
  {
    key: "wages", label: "Wages ₹", type: "num", min: 120,
    value: (r) => (r.wages || 0).toLocaleString("en-IN"),
  },
  { key: "ot_hours", label: "OT Hrs", type: "num", min: 76 },
  {
    key: "ot_amount", label: "OT ₹", type: "num", min: 96,
    value: (r) => (r.ot_amount || 0).toLocaleString("en-IN"),
  },
  { key: "leave_days", label: "Leave", type: "num", min: 70 },
  { key: "current_rows", label: "Current", type: "num", min: 76 },
  { key: "legacy_rows", label: "Legacy", type: "num", min: 72 },
];

const GRP_COLS: ReportCol<any>[] = [
  { key: "name", label: "Name", min: 180, max: 300, sticky: true },
  { key: "employees", label: "Workers", type: "num", min: 84 },
  { key: "man_days", label: "Man Days", type: "num", min: 92 },
  {
    key: "wages", label: "Wages ₹", type: "num", min: 120,
    value: (r) => (r.wages || 0).toLocaleString("en-IN"),
  },
];

export default function FactoryAnnualReturnScreen() {
  const router = useRouter();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const thisYear = new Date().getFullYear();
  const [cid, setCid] = useState<string | null>(selectedCompanyId);
  const [year, setYear] = useState(thisYear);
  const [source, setSource] = useState("combined");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<"monthly" | "employees" | "dept" | "cat">("monthly");
  const [dl, setDl] = useState("");
  // details editor
  const [editOpen, setEditOpen] = useState(false);
  const [form, setForm] = useState<any>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => { if (selectedCompanyId) setCid(selectedCompanyId); }, [selectedCompanyId]);

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    try {
      setData(await api(`/admin/factory-return/${cid}/${year}?source=${source}`));
    } catch { setData(null); }
    setLoading(false);
  }, [cid, year, source]);
  useEffect(() => { load(); }, [load]);

  const openEdit = () => {
    const f = data?.firm || {};
    setForm({
      ...Object.fromEntries(DETAIL_LABELS.map((d) => [d.key, f[d.key] || ""])),
      welfare: { ...(f.welfare || {}) },
      accidents: {
        ...(f.accidents || {}),
        [String(year)]: (f.accidents || {})[String(year)] || { fatal: 0, nonfatal: 0, mandays_lost: 0 },
      },
    });
    setEditOpen(true);
  };

  const saveDetails = async () => {
    if (!cid) return;
    setSaving(true);
    try {
      await api(`/admin/factory-return/details/${cid}`, { method: "PUT", body: form });
      setEditOpen(false);
      await load();
    } catch (e: any) {
      alert(e?.message || "Failed to save");
    }
    setSaving(false);
  };

  const download = async (kind: "pdf" | "boiler" | "xlsx") => {
    if (!cid || dl) return;
    setDl(kind);
    try {
      const path = kind === "boiler"
        ? `/admin/factory-return/${cid}/${year}/boiler.pdf?source=${source}`
        : `/admin/factory-return/${cid}/${year}.${kind}?source=${source}`;
      const name = kind === "boiler"
        ? `boiler-annual-return-${year}.pdf`
        : `factory-annual-return-${year}.${kind}`;
      const r = await apiBinary(path);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(r.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      alert(e?.message || "Download failed");
    }
    setDl("");
  };

  const s = data?.summary;
  const yearOpts = [thisYear, thisYear - 1, thisYear - 2, thisYear - 3, thisYear - 4];

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.head}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Factory & Boiler Annual Return</Text>
          <Text style={st.sub}>Statutory Returns · unified current + legacy data</Text>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        {/* firm picker */}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={st.chips}>
          {companies.map((c: any) => (
            <Pressable key={c.company_id}
              onPress={() => setCid(c.company_id)}
              style={[st.chip, cid === c.company_id && st.chipOn]}>
              <Text style={[st.chipTxt, cid === c.company_id && st.chipTxtOn]} numberOfLines={1}>
                {c.name}
              </Text>
            </Pressable>
          ))}
        </ScrollView>

        {/* year + source */}
        <View style={st.rowWrap}>
          {yearOpts.map((y) => (
            <Pressable key={y} onPress={() => setYear(y)}
              style={[st.chip, year === y && st.chipOn]}>
              <Text style={[st.chipTxt, year === y && st.chipTxtOn]}>{y}</Text>
            </Pressable>
          ))}
          <View style={{ width: 12 }} />
          {SOURCES.map((sc) => (
            <Pressable key={sc.key} onPress={() => setSource(sc.key)}
              style={[st.chip, source === sc.key && st.chipSrcOn]}
              testID={`far-src-${sc.key}`}>
              <Text style={[st.chipTxt, source === sc.key && { color: "#7C2D12", fontWeight: "800" }]}>
                {sc.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {!cid ? (
          <Text style={st.dim}>Select a firm to generate the return.</Text>
        ) : loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : !data ? (
          <Text style={st.dim}>Failed to load. Pull to retry.</Text>
        ) : (
          <>
            {/* firm details */}
            <View style={st.card}>
              <View style={st.cardHead}>
                <Text style={st.cardTitle}>🏭 Factory Particulars</Text>
                <Pressable onPress={openEdit} style={st.editBtn} testID="far-edit">
                  <Ionicons name="create-outline" size={13} color={colors.brandPrimary} />
                  <Text style={st.editTxt}>Edit</Text>
                </Pressable>
              </View>
              {DETAIL_LABELS.map((dfd) => (
                <View key={dfd.key} style={st.kvRow}>
                  <Text style={st.kvL}>{dfd.label}</Text>
                  <Text style={st.kvV}>{data.firm?.[dfd.key] || "—"}</Text>
                </View>
              ))}
            </View>

            {/* summary */}
            {s ? (
              <View style={st.kpiWrap}>
                {[
                  ["Avg Daily Employment", s.avg_daily_employment],
                  ["Max Employment", s.max_employment],
                  ["Male / Female", `${s.male} / ${s.female}`],
                  ["Contract Labour", s.contract_labour],
                  ["Total Man Days", s.total_man_days?.toLocaleString?.("en-IN") ?? s.total_man_days],
                  ["Total Wages ₹", (s.total_wages || 0).toLocaleString("en-IN")],
                  ["OT Hours", s.total_ot_hours],
                  ["OT Amount ₹", (s.total_ot_amount || 0).toLocaleString("en-IN")],
                  ["Leave with Wages", s.leave_with_wages],
                  ["Workers (year)", s.employees_total],
                ].map(([l, v]) => (
                  <View key={String(l)} style={st.kpi}>
                    <Text style={st.kpiV}>{String(v ?? "—")}</Text>
                    <Text style={st.kpiL}>{l}</Text>
                  </View>
                ))}
              </View>
            ) : null}

            {/* downloads */}
            <View style={st.dlRow}>
              {[
                ["pdf", "Factory Return PDF", "document-text-outline", "#B91C1C"],
                ["boiler", "Boiler Return PDF", "flame-outline", "#C2410C"],
                ["xlsx", "Excel", "grid-outline", "#15803D"],
              ].map(([k, l, ic, cl]) => (
                <Pressable key={k as string} onPress={() => download(k as any)}
                  style={[st.dlBtn, { borderColor: cl as string }]}
                  disabled={!!dl} testID={`far-dl-${k}`}>
                  {dl === k ? (
                    <ActivityIndicator size={12} color={cl as string} />
                  ) : (
                    <Ionicons name={ic as any} size={14} color={cl as string} />
                  )}
                  <Text style={[st.dlTxt, { color: cl as string }]}>{l as string}</Text>
                </Pressable>
              ))}
            </View>

            {/* tabs */}
            <View style={st.rowWrap}>
              {[
                ["monthly", "Monthly Statistics"],
                ["employees", `Employee Statistics (${data.employees?.length || 0})`],
                ["dept", "Department-wise"],
                ["cat", "Category-wise"],
              ].map(([k, l]) => (
                <Pressable key={k} onPress={() => setTab(k as any)}
                  style={[st.chip, tab === k && st.chipOn]}>
                  <Text style={[st.chipTxt, tab === k && st.chipTxtOn]}>{l}</Text>
                </Pressable>
              ))}
            </View>

            <View style={{ minHeight: 300, maxHeight: 620 }}>
              {tab === "monthly" ? (
                <ReportTable reportKey="factory_return_monthly" columns={MONTH_COLS}
                  rows={data.monthly || []} maxHeight={560}
                  emptyText={`No salary data found for ${year} in the ${source} source.`}
                  pdfTitle={`Factory Return — Monthly Statistics ${year}`}
                  pdfSubtitle={data.firm?.factory_name || ""} />
              ) : tab === "employees" ? (
                <ReportTable reportKey="factory_return_employees" columns={EMP_COLS}
                  rows={data.employees || []} maxHeight={560}
                  emptyText="No workers found for this year."
                  pdfTitle={`Factory Return — Employee Statistics ${year}`}
                  pdfSubtitle={data.firm?.factory_name || ""} />
              ) : (
                <ReportTable reportKey={`factory_return_${tab}`} columns={GRP_COLS}
                  rows={(tab === "dept" ? data.departments : data.categories) || []}
                  maxHeight={560} emptyText="No data."
                  pdfTitle={`Factory Return — ${tab === "dept" ? "Department" : "Category"}-wise ${year}`}
                  pdfSubtitle={data.firm?.factory_name || ""} />
              )}
            </View>
          </>
        )}
      </ScrollView>

      {/* details editor */}
      <Modal visible={editOpen} transparent animationType="fade"
        onRequestClose={() => setEditOpen(false)}>
        <View style={st.mWrap}>
          <View style={st.mCard}>
            <Text style={st.mTitle}>Factory & Boiler Particulars</Text>
            <ScrollView style={{ maxHeight: 430 }}>
              {DETAIL_LABELS.map((dfd) => (
                <View key={dfd.key} style={{ marginBottom: 8 }}>
                  <Text style={st.mLbl}>{dfd.label}</Text>
                  <TextInput
                    style={st.mInput}
                    value={String(form[dfd.key] ?? "")}
                    onChangeText={(v) => setForm((f: any) => ({ ...f, [dfd.key]: v }))}
                    placeholderTextColor={colors.onSurfaceTertiary}
                    testID={`far-f-${dfd.key}`}
                  />
                </View>
              ))}
              <Text style={[st.mLbl, { marginTop: 4 }]}>Welfare Facilities</Text>
              <View style={st.rowWrap}>
                {WELFARE_LABELS.map((w) => {
                  const on = !!form.welfare?.[w.key];
                  return (
                    <Pressable key={w.key}
                      onPress={() => setForm((f: any) => ({
                        ...f, welfare: { ...f.welfare, [w.key]: !on },
                      }))}
                      style={[st.chip, on && st.chipOn]}>
                      <Text style={[st.chipTxt, on && st.chipTxtOn]}>{w.label}</Text>
                    </Pressable>
                  );
                })}
              </View>
              <Text style={[st.mLbl, { marginTop: 8 }]}>Accidents in {year}</Text>
              <View style={{ flexDirection: "row", gap: 8 }}>
                {[["fatal", "Fatal"], ["nonfatal", "Non-fatal"], ["mandays_lost", "Man-days lost"]].map(([k, l]) => (
                  <View key={k} style={{ flex: 1 }}>
                    <Text style={st.mLbl}>{l}</Text>
                    <TextInput
                      style={st.mInput}
                      keyboardType="number-pad"
                      value={String(form.accidents?.[String(year)]?.[k] ?? 0)}
                      onChangeText={(v) => setForm((f: any) => ({
                        ...f,
                        accidents: {
                          ...f.accidents,
                          [String(year)]: {
                            ...(f.accidents?.[String(year)] || {}),
                            [k]: v.replace(/\D/g, ""),
                          },
                        },
                      }))}
                    />
                  </View>
                ))}
              </View>
            </ScrollView>
            <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 12 }}>
              <Pressable onPress={() => setEditOpen(false)} style={st.mCancel} disabled={saving}>
                <Text style={{ fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary }}>Cancel</Text>
              </Pressable>
              <Pressable onPress={saveDetails} style={st.mSave} disabled={saving} testID="far-save">
                {saving ? <ActivityIndicator size="small" color="#fff" /> : (
                  <Text style={{ fontSize: 12.5, fontWeight: "800", color: "#fff" }}>Save</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  head: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: spacing.md, paddingVertical: 10, backgroundColor: colors.surface },
  title: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 1 },
  chips: { flexDirection: "row", gap: 6, paddingBottom: 8 },
  rowWrap: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10, alignItems: "center" },
  chip: { borderWidth: 1, borderColor: colors.divider, borderRadius: 999, paddingHorizontal: 11, paddingVertical: 6, backgroundColor: colors.surface, maxWidth: 220 },
  chipOn: { borderColor: colors.brandPrimary, backgroundColor: `${colors.brandPrimary}14` },
  chipSrcOn: { borderColor: "#C2410C", backgroundColor: "#FFF7ED" },
  chipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: colors.brandPrimary },
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 30, textAlign: "center" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.divider, padding: 12, marginBottom: 10 },
  cardHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 6 },
  cardTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  editBtn: { flexDirection: "row", alignItems: "center", gap: 4, borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  editTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  kvRow: { flexDirection: "row", paddingVertical: 4, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider },
  kvL: { width: 190, fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  kvV: { flex: 1, fontSize: 11.5, color: colors.onSurface },
  kpiWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 },
  kpi: { minWidth: 128, flexGrow: 1, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.divider, padding: 10 },
  kpiV: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  kpiL: { fontSize: 9.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  dlRow: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 },
  dlBtn: { flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1.5, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: colors.surface },
  dlTxt: { fontSize: 11.5, fontWeight: "800" },
  mWrap: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", alignItems: "center", justifyContent: "center", padding: 16 },
  mCard: { width: Platform.OS === "web" ? 520 : "100%", maxWidth: 560, backgroundColor: colors.surface, borderRadius: radius.lg, padding: 16 },
  mTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  mLbl: { fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceSecondary, marginBottom: 3 },
  mInput: { borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 7, fontSize: 12.5, color: colors.onSurface, backgroundColor: colors.background },
  mCancel: { paddingHorizontal: 14, paddingVertical: 9 },
  mSave: { backgroundColor: colors.brandPrimary, borderRadius: radius.md, paddingHorizontal: 18, paddingVertical: 9 },
});
