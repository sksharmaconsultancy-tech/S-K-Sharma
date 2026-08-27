/**
 * Iter 688 — Attendance & Shift → Attendance Report (Monthly Editable).
 * Excel-style monthly attendance sheet: tap a day cell → pick
 * P / A / L / WO / CO / HD (no In/Out time needed). Firm Master settings
 * decide Direct Save vs Submit-for-Approval. Approvals tab included.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, ScrollView, Pressable, TextInput, ActivityIndicator,
  StyleSheet, Platform, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { ExportButtons } from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

const CODES = ["P", "A", "L", "CL", "WO", "CO", "HD", "H"] as const;
const CODE_COLORS: Record<string, string> = {
  P: "#15803D", A: "#DC2626", L: "#B45309", CL: "#0D9488", WO: "#6B7280",
  CO: "#7C3AED", HD: "#0369A1", H: "#DB2777",
};
const CODE_LABELS: Record<string, string> = {
  P: "Present", A: "Absent", L: "Leave", CL: "Casual Leave", WO: "Weekly Off",
  CO: "Comp Off", HD: "Half Day", H: "Holiday",
};

function nowMM() {
  const d = new Date();
  return `${String(d.getMonth() + 1).padStart(2, "0")}-${d.getFullYear()}`;
}

export default function AttendanceReportEditable() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const companyId = user?.role === "company_admin" ? user.company_id : selectedCompanyId;
  const [month, setMonth] = useState(nowMM());
  const [tab, setTab] = useState<"grid" | "approvals" | "settings">("grid");
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [edits, setEdits] = useState<Record<string, any>>({});
  const [picker, setPicker] = useState<{ uid: string; d: string } | null>(null);
  const [search, setSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [reqs, setReqs] = useState<any[]>([]);
  const [msg, setMsg] = useState("");
  // Iter 689 — Phase 2 approval matrix
  const [apprOpts, setApprOpts] = useState<any>({ approvers: [], departments: [] });

  useEffect(() => {
    if (tab !== "settings" || !companyId || apprOpts.approvers.length) return;
    void (async () => {
      try {
        const r = await api<any>(
          `/admin/manual-attendance/approver-options?company_id=${companyId}`);
        setApprOpts(r);
      } catch {}
    })();
  }, [tab, companyId, apprOpts.approvers.length]);

  const saveSettings = useCallback(async (patch: any) => {
    const next = { ...(data?.settings || {}), ...patch };
    await api<any>(`/admin/manual-attendance/settings/${companyId}`, {
      method: "POST", body: JSON.stringify(next),
    });
    setData((d: any) => ({ ...d, settings: next }));
  }, [companyId, data]);

  const load = useCallback(async () => {
    if (!companyId || !/^\d{2}-\d{4}$/.test(month)) return;
    setLoading(true);
    try {
      const g = await api<any>(
        `/admin/manual-attendance/monthly?company_id=${companyId}&month=${month}`);
      setData(g);
      setEdits({});
      const a = await api<any>(`/admin/manual-attendance/approvals?company_id=${companyId}`);
      setReqs(a.requests || []);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, month]);

  useEffect(() => { void load(); }, [load]);

  const setCell = useCallback((uid: string, d: string, st: string, prev: string) => {
    setEdits((e) => ({ ...e, [`${uid}|${d}`]: { user_id: uid, date: d, status: st, previous_status: prev } }));
    setPicker(null);
  }, []);

  const onCellPress = useCallback((uid: string, d: string) => {
    setPicker((p) => (p && p.uid === uid && p.d === d ? null : { uid, d }));
  }, []);

  // Iter 747 (user perf bug) — group unsaved edits per employee so each
  // GridRow only re-renders when ITS OWN edits / picker change (pehle har
  // click par poora 127×31 grid re-render hota tha → bahut slow).
  const editsByUser = useMemo(() => {
    const m: Record<string, Record<string, any>> = {};
    for (const k of Object.keys(edits)) {
      const [uid, d] = k.split("|");
      (m[uid] = m[uid] || {})[d] = edits[k];
    }
    return m;
  }, [edits]);

  const save = useCallback(async () => {
    if (!companyId || !Object.keys(edits).length) return;
    const st = data?.settings || {};
    let reason = "";
    if (st.require_reason) {
      reason = Platform.OS === "web"
        ? (window.prompt("Reason for manual change (required by Firm Master):") || "")
        : "Manual correction";
      if (!reason.trim()) return;
    }
    setSaving(true);
    try {
      const r = await api<any>(`/admin/manual-attendance/save`, {
        method: "POST",
        body: JSON.stringify({
          company_id: companyId,
          changes: Object.values(edits).map((c: any) => ({ ...c, reason })),
        }),
      });
      setMsg(r.approval_required
        ? `✅ ${r.pending} change(s) submitted for approval`
        : `✅ ${r.applied} change(s) saved`);
      await load();
    } catch (e: any) {
      setMsg(`⚠ ${e?.message || "Save failed"}`);
    } finally {
      setSaving(false);
    }
  }, [companyId, edits, data, load]);

  const decide = useCallback(async (ids: string[], action: string) => {
    try {
      await api<any>(`/admin/manual-attendance/approvals/decide`, {
        method: "POST",
        body: JSON.stringify({ company_id: companyId, request_ids: ids, action }),
      });
      setMsg(`✅ ${ids.length} request(s) ${action.toLowerCase()}d`);
      await load();
    } catch (e: any) {
      setMsg(`⚠ ${e?.message || "Failed"}`);
    }
  }, [companyId, load]);

  const toggleSetting = useCallback(async (k: string) => {
    const st = { ...(data?.settings || {}) };
    st[k] = !st[k];
    await api<any>(`/admin/manual-attendance/settings/${companyId}`, {
      method: "POST", body: JSON.stringify(st),
    });
    setData((d: any) => ({ ...d, settings: st }));
  }, [companyId, data]);

  const RULE_KEYS = ["ANY", "A>P", "P>A", "A>L", "P>L", "P>HD", "A>HD", "WO>P"];

  const rows = useMemo(() => {
    let r = data?.rows || [];
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      r = r.filter((x: any) => x.name.toLowerCase().includes(q)
        || String(x.employee_code).toLowerCase().includes(q)
        || x.department.toLowerCase().includes(q));
    }
    return r;
  }, [data, search]);

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const st = data?.settings || {};
  const unsaved = Object.keys(edits).length;
  const sum = data?.summary || {};

  return (
    <SafeAreaView style={s.safe} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>Attendance Report — Monthly Editable</Text>
        {companyId ? (
          <ExportButtons
            basePath={`/admin/manual-attendance/monthly?company_id=${companyId}&month=${month}`}
            fileBase={`attendance-${month}`} xlsxOnly />
        ) : <View style={{ width: 30 }} />}
      </View>

      <View style={s.bar}>
        {(["grid", "approvals", "settings"] as const).map((t) => (
          <Pressable key={t} onPress={() => setTab(t)}
            style={[s.tab, tab === t && s.tabOn]} testID={`ar-tab-${t}`}>
            <Text style={[s.tabTxt, tab === t && s.tabTxtOn]}>
              {t === "grid" ? "📅 Monthly Sheet"
                : t === "approvals" ? `🟡 Approvals (${reqs.length})` : "⚙ Firm Settings"}
            </Text>
          </Pressable>
        ))}
      </View>

      <View style={s.filters}>
        <Text style={s.lbl}>Month (MM-YYYY)</Text>
        <TextInput value={month} onChangeText={setMonth} style={s.input}
          placeholder="08-2026" maxLength={7} testID="ar-month" />
        <TextInput value={search} onChangeText={setSearch}
          style={[s.input, { flex: 1, minWidth: 120 }]}
          placeholder="Search name / code / dept…" testID="ar-search" />
        <Pressable onPress={() => void load()} style={s.btn} testID="ar-refresh">
          <Text style={s.btnTxt}>Search</Text>
        </Pressable>
        {unsaved > 0 && st.enabled ? (
          <Pressable onPress={() => void save()} style={[s.btn, s.btnSave]}
            disabled={saving} testID="ar-save">
            <Text style={[s.btnTxt, { color: "#fff" }]}>
              {saving ? "Saving…"
                : st.approval_required
                  ? `Submit for Approval (${unsaved})` : `Save Changes (${unsaved})`}
            </Text>
          </Pressable>
        ) : null}
      </View>
      {msg ? <Text style={s.msg}>{msg}</Text> : null}

      {loading && <ActivityIndicator style={{ marginTop: 24 }} />}

      {!loading && tab === "grid" && data && (
        <ScrollView>
          <View style={s.cards}>
            {[["Employees", sum.employees], ["P", sum.P], ["A", sum.A],
              ["L", sum.L], ["WO", sum.WO], ["CO", sum.CO], ["HD", sum.HD],
              ["Manual", sum.manual], ["Pending", sum.pending]].map(([l, v]) => (
              <View key={String(l)} style={s.card}>
                <Text style={s.cardVal}>{v ?? 0}</Text>
                <Text style={s.cardLbl}>{l}</Text>
              </View>
            ))}
          </View>
          {!st.enabled ? (
            <Text style={s.warn}>⚠ Manual editing is DISABLED in Firm Settings — grid is read-only.</Text>
          ) : null}
          <ScrollView horizontal>
            <View>
              <View style={s.tr}>
                <Text style={[s.hcell, { width: 64 }]}>Code</Text>
                <Text style={[s.hcell, { width: 150, textAlign: "left" }]}>Employee</Text>
                <Text style={[s.hcell, { width: 92 }]}>Dept</Text>
                {(data.days || []).map((d: string, i: number) => (
                  <View key={d} style={{ width: 38 }}>
                    <Text style={s.hcell2}>{d.slice(8)}</Text>
                    <Text style={s.hday}>{data.weekdays[i]}</Text>
                  </View>
                ))}
                {CODES.map((c) => (
                  <Text key={c} style={[s.hcell, { width: 36, color: CODE_COLORS[c] }]}>{c}</Text>
                ))}
              </View>
              {rows.map((r: any) => (
                <GridRow
                  key={r.user_id}
                  r={r}
                  days={data.days || []}
                  rowEdits={editsByUser[r.user_id]}
                  pickerD={picker?.uid === r.user_id ? picker.d : null}
                  enabled={!!st.enabled}
                  onCellPress={onCellPress}
                />
              ))}
            </View>
          </ScrollView>
          <Text style={s.legend}>
            P Present · A Absent · L Leave · CL Casual Leave · WO Week Off · CO Camp Off ·
            HD Half Day · H Holiday · ✓ Manual · ✎ Unsaved · 🟡 Pending Approval
          </Text>
        </ScrollView>
      )}

      {!loading && tab === "approvals" && (
        <ScrollView contentContainerStyle={{ padding: 12 }}>
          {reqs.length ? (
            <View style={{ flexDirection: "row", gap: 8, marginBottom: 10 }}>
              <Pressable style={[s.btn, s.btnSave]}
                onPress={() => void decide(reqs.map((r) => r.request_id), "APPROVE")}
                testID="ar-approve-all">
                <Text style={[s.btnTxt, { color: "#fff" }]}>Approve All</Text>
              </Pressable>
              <Pressable style={[s.btn, { backgroundColor: "#DC2626", borderColor: "#DC2626" }]}
                onPress={() => void decide(reqs.map((r) => r.request_id), "REJECT")}>
                <Text style={[s.btnTxt, { color: "#fff" }]}>Reject All</Text>
              </Pressable>
            </View>
          ) : <Text style={s.legend}>No pending attendance change requests.</Text>}
          {reqs.map((r) => (
            <View key={r.request_id} style={s.reqCard}>
              <Text style={{ fontWeight: "800", color: colors.onSurface }}>
                {r.name} ({r.employee_code}) · {r.date}
                {Number(r.levels) === 2 ? `  ·  Level ${r.level || 1}/2` : ""}
              </Text>
              <Text style={s.legend}>
                {r.previous_status || "—"} → {r.requested_status} · by {r.requested_by}
                {r.reason ? ` · "${r.reason}"` : ""}
              </Text>
              <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
                <Pressable style={[s.btn, s.btnSave]}
                  onPress={() => void decide([r.request_id], "APPROVE")}
                  testID={`ar-approve-${r.request_id}`}>
                  <Text style={[s.btnTxt, { color: "#fff" }]}>Approve</Text>
                </Pressable>
                <Pressable style={[s.btn, { backgroundColor: "#DC2626", borderColor: "#DC2626" }]}
                  onPress={() => void decide([r.request_id], "REJECT")}>
                  <Text style={[s.btnTxt, { color: "#fff" }]}>Reject</Text>
                </Pressable>
              </View>
            </View>
          ))}
        </ScrollView>
      )}

      {!loading && tab === "settings" && (
        <ScrollView contentContainerStyle={{ padding: 12 }}>
          <Text style={[s.legend, { marginBottom: 8 }]}>
            Firm Master → Manual Attendance Settings (per firm)
          </Text>
          {[["enabled", "Allow Manual Attendance Editing"],
            ["approval_required", "Attendance Change Approval Required"],
            ["require_reason", "Require Reason for Manual Change"],
            ["maker_checker", "Maker Cannot Approve Own Request"]].map(([k, l]) => (
            <Pressable key={k} style={s.setRow}
              onPress={() => user.role !== "company_admin" && void toggleSetting(k)}
              testID={`ar-set-${k}`}>
              <Text style={{ color: colors.onSurface, flex: 1 }}>{l}</Text>
              <Text style={{ fontWeight: "800", color: st[k] ? "#15803D" : "#DC2626" }}>
                {st[k] ? "ENABLED" : "DISABLED"}
              </Text>
            </Pressable>
          ))}
          {user.role === "company_admin" ? (
            <Text style={s.warn}>Only Super/Sub Admin can change these settings.</Text>
          ) : null}

          {/* Iter 689 — Approval Levels */}
          <Text style={s.secHead}>Approval Type</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            {[1, 2].map((lv) => (
              <Pressable key={lv}
                onPress={() => user.role !== "company_admin"
                  && void saveSettings({ approval_levels: lv })}
                style={[s.chip, (st.approval_levels || 1) === lv && s.chipOn]}
                testID={`ar-levels-${lv}`}>
                <Text style={[s.chipTxt, (st.approval_levels || 1) === lv && { color: "#fff" }]}>
                  {lv === 1 ? "Single Level" : "Multi Level (2)"}
                </Text>
              </Pressable>
            ))}
          </View>

          {/* Iter 689 — Per-change-type approval rules */}
          <Text style={s.secHead}>Changes Requiring Approval</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
            {RULE_KEYS.map((rk) => {
              const on = !!(st.rules || {})[rk];
              return (
                <Pressable key={rk}
                  onPress={() => user.role !== "company_admin"
                    && void saveSettings({ rules: { ...(st.rules || {}), [rk]: !on } })}
                  style={[s.chip, on && s.chipOn]} testID={`ar-rule-${rk}`}>
                  <Text style={[s.chipTxt, on && { color: "#fff" }]}>
                    {rk === "ANY" ? "Any Manual Change" : rk.replace(">", " → ")}
                  </Text>
                </Pressable>
              );
            })}
          </View>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
            <Pressable style={s.chip}
              onPress={() => void saveSettings({
                rules: Object.fromEntries(RULE_KEYS.map((k) => [k, true])) })}>
              <Text style={s.chipTxt}>Select All</Text>
            </Pressable>
            <Pressable style={s.chip}
              onPress={() => void saveSettings({
                rules: Object.fromEntries(RULE_KEYS.map((k) => [k, false])) })}>
              <Text style={s.chipTxt}>Clear All</Text>
            </Pressable>
          </View>
          <Text style={s.legend}>
            If &quot;Any Manual Change&quot; is OFF, only the ticked transitions go for
            approval — everything else saves directly.
          </Text>

          {/* Iter 689 — Level approvers */}
          {[["level1_approver_id", "Level 1 Approver"],
            ...((st.approval_levels || 1) === 2
              ? [["level2_approver_id", "Level 2 Approver"]] : [])].map(([key, lbl]) => (
            <View key={key}>
              <Text style={s.secHead}>{lbl}</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                <Pressable onPress={() => void saveSettings({ [key]: "" })}
                  style={[s.chip, !st[key] && s.chipOn]}>
                  <Text style={[s.chipTxt, !st[key] && { color: "#fff" }]}>Any Admin</Text>
                </Pressable>
                {apprOpts.approvers.map((a: any) => (
                  <Pressable key={a.user_id}
                    onPress={() => void saveSettings({ [key]: a.user_id })}
                    style={[s.chip, st[key] === a.user_id && s.chipOn]}>
                    <Text style={[s.chipTxt, st[key] === a.user_id && { color: "#fff" }]}>
                      {a.name}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          ))}

          {/* Iter 689 — Department-wise approvers */}
          <Text style={s.secHead}>Department-wise Approver (overrides Level 1)</Text>
          {apprOpts.departments.map((dep: string) => {
            const cur = (st.dept_approvers || {})[dep] || "";
            return (
              <View key={dep} style={[s.setRow, { flexWrap: "wrap", gap: 6 }]}>
                <Text style={{ color: colors.onSurface, width: 130, fontWeight: "700" }}>
                  {dep}
                </Text>
                <Pressable
                  onPress={() => {
                    const da = { ...(st.dept_approvers || {}) };
                    delete da[dep];
                    void saveSettings({ dept_approvers: da });
                  }}
                  style={[s.chip, !cur && s.chipOn]}>
                  <Text style={[s.chipTxt, !cur && { color: "#fff" }]}>Common</Text>
                </Pressable>
                {apprOpts.approvers.map((a: any) => (
                  <Pressable key={a.user_id}
                    onPress={() => void saveSettings({
                      dept_approvers: { ...(st.dept_approvers || {}), [dep]: a.user_id } })}
                    style={[s.chip, cur === a.user_id && s.chipOn]}>
                    <Text style={[s.chipTxt, cur === a.user_id && { color: "#fff" }]}>
                      {a.name}
                    </Text>
                  </Pressable>
                ))}
              </View>
            );
          })}
        </ScrollView>
      )}
      {/* Iter 750 (user bug) — proper STATUS DROPDOWN as a Modal list:
          pehle chhoti horizontal strip cells ke upar overlap hoti thi jo
          dropdown jaisi nahi dikhti thi. Ab full-label vertical menu. */}
      <Modal visible={!!picker} transparent animationType="fade"
        onRequestClose={() => setPicker(null)}>
        <Pressable style={s.mWrap} onPress={() => setPicker(null)}>
          <Pressable style={s.mCard} onPress={() => {}}>
            {(() => {
              if (!picker) return null;
              const row = rows.find((x: any) => x.user_id === picker.uid);
              const cell = row?.cells?.[picker.d] || {};
              const cur = edits[`${picker.uid}|${picker.d}`]?.status || cell.st;
              return (
                <>
                  <Text style={s.mTitle} numberOfLines={1}>
                    {row?.name} · {picker.d.slice(8)}/{picker.d.slice(5, 7)}
                  </Text>
                  <Text style={s.mSub}>
                    Abhi: {cur ? `${cur} — ${CODE_LABELS[cur] || ""}` : "blank"} · naya status chunein
                  </Text>
                  {CODES.map((cd) => (
                    <Pressable key={cd} testID={`ar-pick-${cd}`}
                      onPress={() => setCell(picker.uid, picker.d, cd, cell.st)}
                      style={[s.mOpt, cur === cd && { backgroundColor: "#EFF6FF" }]}>
                      <Text style={[s.mOptCode, { color: CODE_COLORS[cd] }]}>{cd}</Text>
                      <Text style={s.mOptLbl}>{CODE_LABELS[cd]}</Text>
                      {cur === cd ? <Text style={{ color: "#2563EB" }}>✓</Text> : null}
                    </Pressable>
                  ))}
                  <Pressable onPress={() => setPicker(null)} style={s.mCancel} testID="ar-pick-cancel">
                    <Text style={{ color: colors.onSurfaceSecondary, fontWeight: "700" }}>Cancel</Text>
                  </Pressable>
                </>
              );
            })()}
          </Pressable>
        </Pressable>
      </Modal>
    </SafeAreaView>
  );
}

/**
 * Iter 747 (user perf bug) — memoized row: sirf USI row ka re-render hota
 * hai jisme picker khula ya edit hua. Shallow-compare on row edits map.
 */
const GridRow = React.memo(function GridRow({
  r, days, rowEdits, pickerD, enabled, onCellPress,
}: {
  r: any; days: string[]; rowEdits?: Record<string, any>;
  pickerD: string | null; enabled: boolean;
  onCellPress: (uid: string, d: string) => void;
}) {
  const tot = { ...r.totals };
  for (const d of Object.keys(rowEdits || {})) {
    const prev = r.cells[d]?.st;
    if (prev && tot[prev] != null) tot[prev] -= 1;
    const nw = (rowEdits as any)[d].status;
    if (tot[nw] != null) tot[nw] += 1;
  }
  return (
    <View style={[s.tr, pickerD && { zIndex: 100 }]}>
      <Text style={[s.cell, { width: 64 }]}>{r.employee_code}</Text>
      <Text style={[s.cell, { width: 150, textAlign: "left", fontWeight: "700" }]}
        numberOfLines={1}>{r.name}</Text>
      <Text style={[s.cell, { width: 92 }]} numberOfLines={1}>{r.department}</Text>
      {days.map((d: string) => {
        const c = r.cells[d] || {};
        const ed = (rowEdits || {})[d];
        const stv = ed ? ed.status : c.st;
        const isPick = pickerD === d;
        return (
          <Pressable
            key={d}
            disabled={!enabled}
            onPress={() => onCellPress(r.user_id, d)}
            style={[s.dcell, { width: 38 },
              ed && { backgroundColor: "#FEF3C7" },
              c.pending && { backgroundColor: "#FEF9C3" },
              isPick && { backgroundColor: "#DBEAFE", borderWidth: 1, borderColor: "#2563EB" }]}
            testID={`ar-cell-${r.employee_code}-${d.slice(8)}`}
          >
            <Text style={[s.dtxt, { color: CODE_COLORS[stv] || colors.onSurfaceTertiary }]}>
              {stv || "·"}{c.pending ? "🟡" : ed ? "✎" : c.src === "manual" ? "✓" : ""}
            </Text>
          </Pressable>
        );
      })}
      {CODES.map((cd) => (
        <Text key={cd} style={[s.cell, { width: 36, fontWeight: "800" }]}>{tot[cd]}</Text>
      ))}
    </View>
  );
}, (a, b) => {
  if (a.r !== b.r || a.enabled !== b.enabled || a.pickerD !== b.pickerD
      || a.days !== b.days) return false;
  const ea = a.rowEdits || {}, eb = b.rowEdits || {};
  const ka = Object.keys(ea), kb = Object.keys(eb);
  if (ka.length !== kb.length) return false;
  for (const k of ka) if (ea[k] !== eb[k]) return false;
  return true;
});

const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", padding: 12 },
  title: { fontSize: 15, fontWeight: "800", color: colors.onSurface, flex: 1, marginLeft: 10 },
  bar: { flexDirection: "row", gap: 6, paddingHorizontal: 12, flexWrap: "wrap" },
  tab: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6 },
  tabOn: { backgroundColor: "#1D4ED8", borderColor: "#1D4ED8" },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  tabTxtOn: { color: "#fff" },
  filters: { flexDirection: "row", alignItems: "center", gap: 8, padding: 12, flexWrap: "wrap" },
  lbl: { fontSize: 12, color: colors.onSurfaceSecondary },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6, width: 90, color: colors.onSurface, backgroundColor: colors.surface },
  btn: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 12, paddingVertical: 7, backgroundColor: colors.surface },
  btnSave: { backgroundColor: "#15803D", borderColor: "#15803D" },
  btnTxt: { fontSize: 12, fontWeight: "800", color: colors.onSurface },
  msg: { paddingHorizontal: 12, color: "#1D4ED8", fontSize: 12, fontWeight: "700" },
  cards: { flexDirection: "row", flexWrap: "wrap", gap: 6, padding: 12 },
  card: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, padding: 8, minWidth: 74, backgroundColor: colors.surface },
  cardVal: { fontSize: 15, fontWeight: "800", color: colors.onSurface, textAlign: "center" },
  cardLbl: { fontSize: 10.5, color: colors.onSurfaceSecondary, textAlign: "center" },
  tr: { flexDirection: "row", alignItems: "center", borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  hcell: { fontSize: 11, fontWeight: "800", color: colors.onSurface, textAlign: "center", paddingVertical: 6 },
  hcell2: { fontSize: 11, fontWeight: "800", color: colors.onSurface, textAlign: "center" },
  hday: { fontSize: 9, color: colors.onSurfaceSecondary, textAlign: "center" },
  cell: { fontSize: 11.5, color: colors.onSurface, textAlign: "center", paddingVertical: 8 },
  dcell: { height: 34, alignItems: "center", justifyContent: "center", borderLeftWidth: StyleSheet.hairlineWidth, borderLeftColor: colors.border },
  dtxt: { fontSize: 11, fontWeight: "800" },
  // Iter 750 — status dropdown modal
  mWrap: { flex: 1, backgroundColor: "rgba(0,0,0,0.45)", alignItems: "center", justifyContent: "center", padding: 20 },
  mCard: { backgroundColor: colors.surface, borderRadius: 14, padding: 16, width: "100%", maxWidth: 340 },
  mTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  mSub: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 2, marginBottom: 8 },
  mOpt: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 10, paddingHorizontal: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border, borderRadius: 8 },
  mOptCode: { fontSize: 14, fontWeight: "800", width: 32 },
  mOptLbl: { fontSize: 13, color: colors.onSurface, flex: 1 },
  mCancel: { alignItems: "center", paddingVertical: 12, marginTop: 4 },
  legend: { fontSize: 11.5, color: colors.onSurfaceSecondary, padding: 12 },
  warn: { color: "#B45309", fontSize: 12, paddingHorizontal: 12, paddingBottom: 6 },
  reqCard: { borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 10, marginBottom: 8, backgroundColor: colors.surface },
  setRow: { flexDirection: "row", alignItems: "center", borderWidth: 1, borderColor: colors.border, borderRadius: 10, padding: 12, marginBottom: 8, backgroundColor: colors.surface },
  secHead: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginTop: 14, marginBottom: 6 },
  chip: { borderWidth: 1, borderColor: colors.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 6, backgroundColor: colors.surface },
  chipOn: { backgroundColor: "#1D4ED8", borderColor: "#1D4ED8" },
  chipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurface },
});
