/**
 * Iter 95 — Bonus Registers (Forms A / B / C / D) + Statutory Annual Returns
 * (Equal Remuneration Act, Inter-State Migrant Workmen Act). Web portal only.
 *
 * Form A/B need financial figures (gross profit, deductions, set-on/set-off)
 * that the admin enters here and are stored per (firm, FY). Form C/D pull the
 * live bonus computation from the Bonus Process engine.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  TextInput,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type SetRow = {
  year: string;
  allocable_surplus: string;
  bonus_payable: string;
  set_on: string;
  set_off: string;
};

const currentFy = (): number => {
  const d = new Date();
  return d.getMonth() + 1 >= 4 ? d.getFullYear() : d.getFullYear() - 1;
};

const num = (s: string): number => Number(String(s).replace(/[^0-9.-]/g, "")) || 0;

export default function BonusRegistersScreen() {
  const insets = useSafeAreaInsets();
  const { user } = useAuth();
  const { selectedCompanyId, selectedCompany } = useSelectedCompany();
  const isAdmin =
    user?.role === "super_admin" ||
    user?.role === "company_admin" ||
    user?.role === "sub_admin";

  const cid = useMemo(() => {
    if (user?.role === "company_admin") return user.company_id || null;
    return selectedCompanyId && selectedCompanyId !== "all" ? selectedCompanyId : null;
  }, [user, selectedCompanyId]);

  const [fy, setFy] = useState<string>(String(currentFy()));
  const [year, setYear] = useState<string>(String(new Date().getFullYear() - 1));

  // Form A/B financial inputs
  const [gp, setGp] = useState("");
  const [dep, setDep] = useState("");
  const [dev, setDev] = useState("");
  const [tax, setTax] = useState("");
  const [oth, setOth] = useState("");
  const [pct, setPct] = useState("60");
  const [payDate, setPayDate] = useState("");
  const [industry, setIndustry] = useState("");
  const [employer, setEmployer] = useState("");
  const [setRows, setSetRows] = useState<SetRow[]>([]);

  const [loadingFin, setLoadingFin] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dl, setDl] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const loadFin = useCallback(async () => {
    if (!cid || !/^\d{4}$/.test(fy)) return;
    setLoadingFin(true);
    setErr(null);
    try {
      const r = await api<{ financials: any }>(
        `/admin/bonus-registers/financials?company_id=${encodeURIComponent(cid)}&fy_start_year=${fy}`,
      );
      const f = r.financials || {};
      setGp(f.gross_profit ? String(f.gross_profit) : "");
      setDep(f.depreciation ? String(f.depreciation) : "");
      setDev(f.development_rebate ? String(f.development_rebate) : "");
      setTax(f.direct_tax ? String(f.direct_tax) : "");
      setOth(f.other_sums ? String(f.other_sums) : "");
      setPct(f.allocable_percent ? String(f.allocable_percent) : "60");
      setPayDate(f.payment_date || "");
      setIndustry(f.nature_of_industry || "");
      setEmployer(f.employer_name || "");
      setSetRows(
        (f.set_on_off_rows || []).map((r0: any) => ({
          year: String(r0.year || ""),
          allocable_surplus: String(r0.allocable_surplus || ""),
          bonus_payable: String(r0.bonus_payable || ""),
          set_on: String(r0.set_on || ""),
          set_off: String(r0.set_off || ""),
        })),
      );
    } catch (e: any) {
      setErr(e?.message || "Could not load financials");
    } finally {
      setLoadingFin(false);
    }
  }, [cid, fy]);

  useEffect(() => { loadFin(); }, [loadFin]);

  const saveFin = useCallback(async () => {
    if (!cid || saving) return;
    setSaving(true);
    setErr(null);
    setMsg(null);
    try {
      await api("/admin/bonus-registers/financials", {
        method: "PUT",
        body: {
          company_id: cid,
          fy_start_year: Number(fy),
          gross_profit: num(gp),
          depreciation: num(dep),
          development_rebate: num(dev),
          direct_tax: num(tax),
          other_sums: num(oth),
          allocable_percent: num(pct) || 60,
          payment_date: payDate.trim(),
          nature_of_industry: industry.trim(),
          employer_name: employer.trim(),
          set_on_off_rows: setRows
            .filter((r) => r.year.trim())
            .map((r) => ({
              year: r.year.trim(),
              allocable_surplus: num(r.allocable_surplus),
              bonus_payable: num(r.bonus_payable),
              set_on: num(r.set_on),
              set_off: num(r.set_off),
            })),
        },
      });
      setMsg("Financial figures saved.");
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  }, [cid, fy, gp, dep, dev, tax, oth, pct, payDate, industry, employer, setRows, saving]);

  const download = useCallback(async (key: string, path: string, fname: string) => {
    if (!cid) return;
    setDl(key);
    setErr(null);
    try {
      const res = await apiBinary(path);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = fname;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      setErr(e?.message || "Download failed");
    } finally {
      setDl(null);
    }
  }, [cid]);

  if (!isAdmin) {
    return (
      <View style={[styles.center, { flex: 1 }]}>
        <Ionicons name="lock-closed-outline" size={36} color={colors.brandPrimary} />
        <Text style={styles.errTitle}>Admins only</Text>
      </View>
    );
  }

  const fyLabel = /^\d{4}$/.test(fy) ? `${fy}-${String(Number(fy) + 1).slice(2)}` : fy;

  const FORM_BTNS = [
    { key: "a", label: "Form A — Allocable Surplus", icon: "calculator-outline" },
    { key: "b", label: "Form B — Set-on / Set-off", icon: "swap-vertical-outline" },
    { key: "c", label: "Form C — Bonus Paid Register", icon: "people-outline" },
    { key: "d", label: "Form D — Annual Return", icon: "document-attach-outline" },
  ];

  return (
    <View style={[styles.root, { paddingTop: insets.top }]}>
      <View style={styles.toolbar}>
        <Text style={styles.title}>Bonus Registers & Annual Returns</Text>
        {selectedCompany ? <Text style={styles.firmTxt}>{selectedCompany.name}</Text> : null}
        <View style={{ flex: 1 }} />
        <Text style={styles.fyLbl}>FY (start year):</Text>
        <TextInput
          style={styles.fyInput}
          value={fy}
          onChangeText={(v) => setFy(v.replace(/\D/g, "").slice(0, 4))}
          keyboardType="numeric"
          maxLength={4}
          testID="br-fy"
        />
        <Text style={styles.fyBadge}>FY {fyLabel}</Text>
      </View>

      {!cid ? (
        <View style={styles.center}>
          <Ionicons name="business-outline" size={30} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyTxt}>Pick a firm first (top-right selector).</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 14 }}>
          {/* ---- Download buttons ---- */}
          <Text style={styles.secTitle}>Payment of Bonus Act, 1965 — Registers (FY {fyLabel})</Text>
          <View style={styles.btnRow}>
            {FORM_BTNS.map((b) => (
              <Pressable
                key={b.key}
                style={[styles.formBtn, dl === b.key && { opacity: 0.6 }]}
                disabled={!!dl}
                onPress={() =>
                  download(
                    b.key,
                    `/admin/bonus-registers/form-${b.key}.pdf?company_id=${encodeURIComponent(cid)}&fy_start_year=${fy}`,
                    `Bonus_Form${b.key.toUpperCase()}_${fyLabel}.pdf`,
                  )
                }
                testID={`br-form-${b.key}`}
              >
                {dl === b.key ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name={b.icon as any} size={15} color="#fff" />
                )}
                <Text style={styles.formBtnTxt}>{b.label}</Text>
                <Ionicons name="download-outline" size={13} color="#fff" />
              </Pressable>
            ))}
          </View>

          {/* ---- Financial inputs (Form A/B/C/D data) ---- */}
          <View style={styles.card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={styles.cardTitle}>Financial figures for FY {fyLabel}</Text>
              {loadingFin ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : null}
            </View>
            <Text style={styles.cardHint}>
              Used by Form A (computation), Form B (set-on/set-off), Form C (payment date)
              and Form D (return particulars).
            </Text>
            <View style={styles.grid}>
              {[
                { l: "Gross Profit (Rs.)", v: gp, s: setGp },
                { l: "Depreciation — Sec 6(a)", v: dep, s: setDep },
                { l: "Development Rebate — Sec 6(b)", v: dev, s: setDev },
                { l: "Direct Taxes — Sec 6(c)", v: tax, s: setTax },
                { l: "Further Sums — Sec 6(d)", v: oth, s: setOth },
                { l: "Allocable % (60 / 67)", v: pct, s: setPct },
              ].map((f) => (
                <View key={f.l} style={styles.field}>
                  <Text style={styles.fieldLbl}>{f.l}</Text>
                  <TextInput
                    style={styles.fieldInput}
                    value={f.v}
                    onChangeText={(t) => f.s(t.replace(/[^0-9.]/g, ""))}
                    keyboardType="numeric"
                    placeholder="0"
                    placeholderTextColor={colors.onSurfaceTertiary}
                  />
                </View>
              ))}
              <View style={styles.field}>
                <Text style={styles.fieldLbl}>Bonus Payment Date (DD-MM-YYYY)</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={payDate}
                  onChangeText={setPayDate}
                  placeholder="DD-MM-YYYY"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  maxLength={10}
                />
              </View>
              <View style={styles.field}>
                <Text style={styles.fieldLbl}>Nature of Industry (Form D)</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={industry}
                  onChangeText={setIndustry}
                  placeholder="e.g. Textile Manufacturing"
                  placeholderTextColor={colors.onSurfaceTertiary}
                />
              </View>
              <View style={styles.field}>
                <Text style={styles.fieldLbl}>Name of Employer (Form D)</Text>
                <TextInput
                  style={styles.fieldInput}
                  value={employer}
                  onChangeText={setEmployer}
                  placeholder="Proprietor / Partner name"
                  placeholderTextColor={colors.onSurfaceTertiary}
                />
              </View>
            </View>

            {/* Set-on / Set-off rows (Form B) */}
            <Text style={[styles.cardTitle, { marginTop: 12, fontSize: 12.5 }]}>
              Form B — Set-on / Set-off rows (one per accounting year)
            </Text>
            {setRows.map((r, i) => (
              <View key={i} style={styles.setRow}>
                {[
                  { k: "year" as const, ph: "Year (2025-26)", w: 96 },
                  { k: "allocable_surplus" as const, ph: "Allocable ₹", w: 110 },
                  { k: "bonus_payable" as const, ph: "Bonus Payable ₹", w: 120 },
                  { k: "set_on" as const, ph: "Set-on ₹", w: 100 },
                  { k: "set_off" as const, ph: "Set-off ₹", w: 100 },
                ].map((c) => (
                  <TextInput
                    key={c.k}
                    style={[styles.fieldInput, { width: c.w }]}
                    value={r[c.k]}
                    onChangeText={(t) =>
                      setSetRows((prev) =>
                        prev.map((row, j) => (j === i ? { ...row, [c.k]: t } : row)),
                      )
                    }
                    placeholder={c.ph}
                    placeholderTextColor={colors.onSurfaceTertiary}
                  />
                ))}
                <Pressable
                  onPress={() => setSetRows((prev) => prev.filter((_, j) => j !== i))}
                  hitSlop={6}
                >
                  <Ionicons name="trash-outline" size={16} color="#B91C1C" />
                </Pressable>
              </View>
            ))}
            <Pressable
              style={styles.addRowBtn}
              onPress={() =>
                setSetRows((prev) => [
                  ...prev,
                  { year: fyLabel, allocable_surplus: "", bonus_payable: "", set_on: "", set_off: "" },
                ])
              }
              testID="br-add-setrow"
            >
              <Ionicons name="add" size={14} color={colors.brandPrimary} />
              <Text style={styles.addRowTxt}>Add year row</Text>
            </Pressable>

            {err ? <Text style={styles.errTxt}>{err}</Text> : null}
            {msg ? <Text style={styles.okTxt}>{msg}</Text> : null}
            <Pressable
              style={[styles.saveBtn, saving && { opacity: 0.6 }]}
              onPress={saveFin}
              disabled={saving}
              testID="br-save-fin"
            >
              {saving ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Ionicons name="save-outline" size={15} color="#fff" />
              )}
              <Text style={styles.saveTxt}>Save Financial Figures</Text>
            </Pressable>
          </View>

          {/* ---- Annual Returns ---- */}
          <Text style={styles.secTitle}>Statutory Annual Returns</Text>
          <View style={styles.card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <Text style={styles.fieldLbl}>Calendar Year:</Text>
              <TextInput
                style={[styles.fieldInput, { width: 80 }]}
                value={year}
                onChangeText={(v) => setYear(v.replace(/\D/g, "").slice(0, 4))}
                keyboardType="numeric"
                maxLength={4}
                testID="br-year"
              />
            </View>
            <View style={[styles.btnRow, { marginTop: 10 }]}>
              <Pressable
                style={[styles.formBtn, { backgroundColor: "#7C3AED" }, dl === "er" && { opacity: 0.6 }]}
                disabled={!!dl}
                onPress={() =>
                  download(
                    "er",
                    `/admin/annual-returns/equal-remuneration.pdf?company_id=${encodeURIComponent(cid)}&year=${year}`,
                    `EqualRemuneration_AnnualReturn_${year}.pdf`,
                  )
                }
                testID="br-er"
              >
                {dl === "er" ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name="scale-outline" size={15} color="#fff" />
                )}
                <Text style={styles.formBtnTxt}>Equal Remuneration Act — Annual Return</Text>
                <Ionicons name="download-outline" size={13} color="#fff" />
              </Pressable>
              <Pressable
                style={[styles.formBtn, { backgroundColor: "#0369A1" }, dl === "ismw" && { opacity: 0.6 }]}
                disabled={!!dl}
                onPress={() =>
                  download(
                    "ismw",
                    `/admin/annual-returns/ismw.pdf?company_id=${encodeURIComponent(cid)}&year=${year}`,
                    `ISMW_AnnualReturn_${year}.pdf`,
                  )
                }
                testID="br-ismw"
              >
                {dl === "ismw" ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Ionicons name="train-outline" size={15} color="#fff" />
                )}
                <Text style={styles.formBtnTxt}>Inter-State Migrant Workmen — Annual Return</Text>
                <Ionicons name="download-outline" size={13} color="#fff" />
              </Pressable>
            </View>
          </View>
          <View style={{ height: 40 }} />
        </ScrollView>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  toolbar: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    flexWrap: "wrap",
  },
  title: { fontSize: type.md, fontWeight: "800", color: colors.onSurface },
  firmTxt: { fontSize: 11, color: colors.brandPrimary, fontWeight: "700" },
  fyLbl: { fontSize: 11.5, color: colors.onSurfaceSecondary, fontWeight: "600" },
  fyInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 8, paddingVertical: 6, fontSize: 12.5, fontWeight: "700",
    color: colors.onSurface, width: 66, backgroundColor: colors.surface,
  },
  fyBadge: {
    fontSize: 11, fontWeight: "800", color: colors.brandPrimary,
    backgroundColor: "rgba(15,46,61,0.08)", paddingHorizontal: 8,
    paddingVertical: 4, borderRadius: 6,
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 10 },
  errTitle: { fontSize: type.md, fontWeight: "800", color: colors.onSurface },
  emptyTxt: { padding: 18, color: colors.onSurfaceTertiary, fontSize: 12, textAlign: "center" },
  secTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  btnRow: { flexDirection: "row", gap: 10, flexWrap: "wrap" },
  formBtn: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 10,
    paddingHorizontal: 14, paddingVertical: 11,
  },
  formBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  card: {
    backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 16, gap: 6, maxWidth: 980,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  cardHint: { fontSize: 11, color: colors.onSurfaceTertiary },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 8 },
  field: { width: 220 },
  fieldLbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 3 },
  fieldInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 7, fontSize: 12,
    color: colors.onSurface, backgroundColor: colors.background,
  },
  setRow: { flexDirection: "row", gap: 8, alignItems: "center", marginTop: 6, flexWrap: "wrap" },
  addRowBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, marginTop: 8,
    alignSelf: "flex-start", paddingVertical: 4,
  },
  addRowTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#15803D", borderRadius: radius.md,
    paddingVertical: 11, marginTop: 10, maxWidth: 320,
  },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  errTxt: { color: "#B91C1C", fontSize: 12, fontWeight: "700", marginTop: 6 },
  okTxt: { color: "#15803D", fontSize: 12, fontWeight: "700", marginTop: 6 },
});
