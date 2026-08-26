/**
 * Iter 741 — ALTERNATE / OCCURRENCE-BASED WEEKOFF rules + calendar preview.
 * Saves weekoff_rules onto the firm's existing Attendance Policy (PATCH
 * /attendance/policy). Fixed weekly off stays default; employee override
 * always wins. Attendance engine untouched — per-date mapping only.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";
import { BmField, BmBtn, BmChip, bm, showWebMsg } from "@/src/components/firmMaster/branchMasterUi";

const WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function WeekoffRulesScreen() {
  const { user } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;
  const [wtype, setWtype] = useState<"fixed" | "occurrence" | "alternate">("fixed");
  const [occDay, setOccDay] = useState(5);
  const [occs, setOccs] = useState<number[]>([2, 4]);
  const [altDays, setAltDays] = useState<number[]>([6]);
  const [cycleStart, setCycleStart] = useState("");
  const [month, setMonth] = useState(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  });
  const [preview, setPreview] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);

  const loadCurrent = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await api<any>(`/attendance/policy?company_id=${cid}`);
      const wr = r?.policy?.weekoff_rules;
      if (wr?.type) {
        setWtype(wr.type);
        const occ = wr.occurrence || {};
        const k = Object.keys(occ)[0];
        if (k) { setOccDay(parseInt(k, 10)); setOccs(occ[k] === "all" ? [] : occ[k]); }
        if (wr.alternate) {
          setAltDays(wr.alternate.weekdays || [6]);
          setCycleStart(wr.alternate.cycle_start || "");
        }
      }
    } catch { /* ignore */ }
  }, [cid]);
  useEffect(() => { loadCurrent(); }, [loadCurrent]);

  const save = async () => {
    if (!cid) return;
    setBusy(true);
    try {
      const rules: any = { type: wtype, active: true };
      if (wtype === "occurrence") rules.occurrence = { [String(occDay)]: occs.length ? occs : "all" };
      if (wtype === "alternate") {
        if (!/^\d{4}-\d{2}-\d{2}$/.test(cycleStart)) { showWebMsg("Cycle start date YYYY-MM-DD में दें"); setBusy(false); return; }
        rules.alternate = { weekdays: altDays, cycle_start: cycleStart, pattern: ["off", "work"] };
      }
      await api(`/attendance/policy?company_id=${cid}`, { method: "PATCH", body: { weekoff_rules: rules } });
      showWebMsg("Weekoff rules saved ✓");
      loadPreview();
    } catch (e: any) { showWebMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const loadPreview = async () => {
    if (!cid) return;
    try {
      const r = await api<any>(`/admin/weekoff/preview?company_id=${cid}&month=${month}`);
      setPreview(r.days || []);
    } catch (e: any) { showWebMsg(e?.message || "Preview failed"); }
  };

  return (
    <SafeAreaView style={s.root}>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <Text style={s.title}>Alternate / Occurrence Weekoff</Text>
        <Text style={s.hint}>
          Fixed weekly off (Attendance Policy) default रहता है. यहाँ 2nd/4th
          Saturday जैसे occurrence rules या alternate-week pattern set करें.
          Employee-level override हमेशा priority में सबसे ऊपर.
        </Text>
        {user?.role !== "company_admin" ? (
          <CompanyPicker value={companyId || "all"} onChange={(v: any) => setCompanyId(v === "all" ? null : v)} allowAll={false} />
        ) : null}
        {cid ? (
          <>
            <Text style={bm.secTitle}>Weekoff Type</Text>
            <View style={bm.chipsWrap}>
              {(["fixed", "occurrence", "alternate"] as const).map((t) => (
                <BmChip key={t} label={t === "fixed" ? "Fixed (existing)" : t === "occurrence" ? "Occurrence-based" : "Alternate weeks"}
                        on={wtype === t} onPress={() => setWtype(t)} testID={`wo-type-${t}`} />
              ))}
            </View>
            {wtype === "occurrence" ? (
              <>
                <Text style={bm.secTitle}>Weekday</Text>
                <View style={bm.chipsWrap}>
                  {WD.map((d, i) => (
                    <BmChip key={d} label={d} on={occDay === i} onPress={() => setOccDay(i)} testID={`wo-day-${d}`} />
                  ))}
                </View>
                <Text style={bm.secTitle}>Occurrences (blank = every week)</Text>
                <View style={bm.chipsWrap}>
                  {[1, 2, 3, 4, 5].map((n) => (
                    <BmChip key={n} label={`${n}${n === 1 ? "st" : n === 2 ? "nd" : n === 3 ? "rd" : "th"}`}
                            on={occs.includes(n)}
                            onPress={() => setOccs(occs.includes(n) ? occs.filter((x) => x !== n) : [...occs, n].sort())}
                            testID={`wo-occ-${n}`} />
                  ))}
                </View>
              </>
            ) : null}
            {wtype === "alternate" ? (
              <>
                <Text style={bm.secTitle}>Weekday(s) for alternate off</Text>
                <View style={bm.chipsWrap}>
                  {WD.map((d, i) => (
                    <BmChip key={d} label={d} on={altDays.includes(i)}
                            onPress={() => setAltDays(altDays.includes(i) ? altDays.filter((x) => x !== i) : [...altDays, i])} />
                  ))}
                </View>
                <BmField label="Cycle Start Date (YYYY-MM-DD — off-week का पहला Monday)"
                         value={cycleStart} onChangeText={setCycleStart} width={260} testID="wo-cycle" />
              </>
            ) : null}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
              <BmBtn label="Save Rules" onPress={save} busy={busy} testID="wo-save" />
              <BmField label="Preview month (YYYY-MM)" value={month} onChangeText={setMonth} width={150} testID="wo-month" />
              <BmBtn label="Preview Calendar" kind="ghost" onPress={loadPreview} testID="wo-preview" />
            </View>
            {preview ? (
              <View style={{ marginTop: 10 }}>
                {preview.map((d) => (
                  <View key={d.date} style={[s.pRow, d.status === "Weekoff" && s.pOff]}>
                    <Text style={s.pDate}>{d.date}</Text>
                    <Text style={s.pDay}>{d.day}</Text>
                    <Text style={s.pRule}>{d.rule}</Text>
                    <Text style={[s.pStatus, d.status === "Weekoff" && { color: "#B45309" }]}>{d.status}</Text>
                  </View>
                ))}
              </View>
            ) : null}
            {preview && !preview.length ? <ActivityIndicator color={colors.brandPrimary} /> : null}
          </>
        ) : <Text style={s.hint}>Select a firm.</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  title: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 12, color: colors.onSurfaceTertiary, marginVertical: 8 },
  pRow: { flexDirection: "row", gap: 10, paddingVertical: 5, paddingHorizontal: 8,
    borderBottomWidth: 1, borderColor: colors.border, alignItems: "center" },
  pOff: { backgroundColor: "#FFFBEB", borderRadius: radius.sm },
  pDate: { width: 90, fontSize: 12, color: colors.onSurface, fontWeight: "600" },
  pDay: { width: 80, fontSize: 12, color: colors.onSurfaceSecondary },
  pRule: { flex: 1, fontSize: 11.5, color: colors.onSurfaceTertiary },
  pStatus: { width: 70, fontSize: 12, fontWeight: "800", color: "#15803D" },
});
