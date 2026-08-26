/**
 * Iter 741 — COMMON ACCIDENT MASTER (ESIC + Factory & Boilers).
 * One entry → ESIC Form 12 PDF + F&B report PDF + register export, with
 * independent ESIC / F&B status tracking per accident.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";
import { BmField, BmBtn, BmToggle, bm, showWebMsg } from "@/src/components/firmMaster/branchMasterUi";

export default function AccidentRegisterScreen() {
  const { user } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;
  const [data, setData] = useState<any>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    if (!cid) return;
    try { setData(await api<any>(`/admin/accidents?company_id=${cid}`)); } catch { /* */ }
  }, [cid]);
  useEffect(() => { load(); }, [load]);

  const dl = async (path: string, name: string) => {
    try {
      const r = await apiBinary(path);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl; a.download = name; a.click();
      }
      load();
    } catch (e: any) { showWebMsg(e?.message || "Download failed"); }
  };

  const markStatus = async (acc: any, track: "esic_status" | "fnb_status") => {
    const done = track === "esic_status" ? "submitted" : "filed";
    const cur = (acc[track] || {}).submission_status;
    const ref = cur === done ? null
      : Platform.OS === "web" ? window.prompt("Acknowledgement / Reference No. (optional):") : null;
    try {
      await api(`/admin/accidents/${acc.accident_id}`, { method: "PATCH", body: {
        [track]: { submission_status: cur === done ? "pending" : done,
                   [track === "esic_status" ? "ack_no" : "ref_no"]: ref || undefined,
                   submission_date: cur === done ? null : new Date().toISOString().slice(0, 10) } } });
      load();
    } catch (e: any) { showWebMsg(e?.message || "Failed"); }
  };

  const d = data?.dashboard || {};
  return (
    <SafeAreaView style={s.root}>
      <ScrollView contentContainerStyle={{ padding: spacing.md }}>
        <View style={s.head}>
          <Text style={s.title}>Accident Register (ESIC + Factory & Boilers)</Text>
          <View style={{ flexDirection: "row", gap: 8 }}>
            <BmBtn label="Register Excel" kind="ghost" icon="download-outline" small
                   onPress={() => dl(`/admin/accidents/register/export?company_id=${cid}`, "Accident_Register.xlsx")} testID="ar-export" />
            <BmBtn label="Report Accident" icon="add" small onPress={() => setShowForm(!showForm)} testID="ar-add" />
          </View>
        </View>
        {user?.role !== "company_admin" ? (
          <CompanyPicker value={companyId || "all"} onChange={(v: any) => setCompanyId(v === "all" ? null : v)} allowAll={false} />
        ) : null}
        {!cid ? <Text style={s.hint}>Select a firm.</Text> : (
          <>
            <View style={s.cards}>
              {[["Total", d.total], ["ESIC Applicable", d.esic_applicable], ["F&B Applicable", d.fnb_applicable],
                ["Both", d.both], ["Fatal", d.fatal, "#B91C1C"], ["ESIC Pending", d.esic_pending, "#B45309"],
                ["ESIC Submitted", d.esic_submitted, "#15803D"], ["F&B Pending", d.fnb_pending, "#B45309"],
                ["F&B Filed", d.fnb_filed, "#15803D"]].map(([l, v, c]: any) => (
                <View key={l} style={s.card}>
                  <Text style={[s.cardV, c ? { color: c } : null]}>{v ?? 0}</Text>
                  <Text style={s.cardL}>{l}</Text>
                </View>
              ))}
            </View>
            {showForm ? <AccidentForm cid={cid} onDone={() => { setShowForm(false); load(); }} onCancel={() => setShowForm(false)} /> : null}
            {(data?.accidents || []).map((a: any) => {
              const es = a.esic_status || {}, fs = a.fnb_status || {};
              return (
                <View key={a.accident_id} style={s.row} testID={`ar-acc-${a.accident_id}`}>
                  <View style={{ flex: 1, minWidth: 220 }}>
                    <Text style={s.name}>{a.accident_no} · {a.employee_name} {a.fatal ? "· ⚠ FATAL" : ""}</Text>
                    <Text style={s.meta}>
                      {a.accident_date} {a.accident_time || ""} · {a.accident_type || "—"} · {a.injury_nature || "—"}
                    </Text>
                    <Text style={s.meta}>
                      ESIC: {a.esic_applicable ? (es.submission_status === "submitted" ? `✅ Submitted${es.ack_no ? ` (${es.ack_no})` : ""}` : "🟠 Pending") : "N/A"}
                      {"   "}F&B: {a.fnb_applicable ? (fs.submission_status === "filed" ? `✅ Filed${fs.ref_no ? ` (${fs.ref_no})` : ""}` : fs.report_generated ? "🟠 Report Generated – Pending Filing" : "🟠 Pending") : "N/A"}
                    </Text>
                  </View>
                  <View style={{ gap: 4 }}>
                    {a.esic_applicable ? (
                      <View style={{ flexDirection: "row", gap: 5 }}>
                        <BmBtn label="Form 12" kind="ghost" small
                               onPress={() => dl(`/admin/accidents/${a.accident_id}/report?kind=form12`, `${a.accident_no}_Form12.pdf`)} testID={`ar-f12-${a.accident_id}`} />
                        <BmBtn label={es.submission_status === "submitted" ? "Un-submit" : "Mark Submitted"} small
                               kind={es.submission_status === "submitted" ? "ghost" : "primary"}
                               onPress={() => markStatus(a, "esic_status")} />
                      </View>
                    ) : null}
                    {a.fnb_applicable ? (
                      <View style={{ flexDirection: "row", gap: 5 }}>
                        <BmBtn label="F&B Report" kind="ghost" small
                               onPress={() => dl(`/admin/accidents/${a.accident_id}/report?kind=fnb`, `${a.accident_no}_FnB.pdf`)} testID={`ar-fnb-${a.accident_id}`} />
                        <BmBtn label={fs.submission_status === "filed" ? "Un-file" : "Mark Filed"} small
                               kind={fs.submission_status === "filed" ? "ghost" : "primary"}
                               onPress={() => markStatus(a, "fnb_status")} />
                      </View>
                    ) : null}
                  </View>
                </View>
              );
            })}
            {data && !(data.accidents || []).length ? <Text style={s.hint}>No accidents recorded.</Text> : null}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

function AccidentForm({ cid, onDone, onCancel }: { cid: string; onDone: () => void; onCancel: () => void }) {
  const [q, setQ] = useState("");
  const [emps, setEmps] = useState<any[]>([]);
  const [sel, setSel] = useState<any>(null);
  const [f, setF] = useState<any>({ accident_date: new Date().toISOString().slice(0, 10),
    esic_applicable: true, fnb_applicable: false, fatal: false, fnb: {} });
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: any) => setF((p: any) => ({ ...p, [k]: v }));
  const setFnb = (k: string, v: any) => setF((p: any) => ({ ...p, fnb: { ...p.fnb, [k]: v } }));

  useEffect(() => {
    api<any>(`/admin/branch-management/employees?company_id=${cid}`)
      .then((r) => setEmps(r.employees || [])).catch(() => {});
  }, [cid]);
  const filtered = q.trim() ? emps.filter((e) =>
    (e.name || "").toLowerCase().includes(q.toLowerCase())
    || (e.employee_code || "").toLowerCase().includes(q.toLowerCase())).slice(0, 8) : [];

  const save = async () => {
    if (!sel) { showWebMsg("Employee चुनें"); return; }
    setBusy(true);
    try {
      await api("/admin/accidents", { method: "POST", body: { ...f, company_id: cid, user_id: sel.user_id } });
      onDone();
    } catch (e: any) { showWebMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  return (
    <View style={s.panel} testID="ar-form">
      <Text style={s.panelT}>Report Accident {sel ? `— ${sel.name}` : ""}</Text>
      {!sel ? (
        <>
          <BmField label="Search employee *" value={q} onChangeText={setQ} placeholder="Name / code…" testID="ar-emp-search" />
          {filtered.map((e) => (
            <Pressable key={e.user_id} onPress={() => setSel(e)} style={s.empOpt} testID={`ar-emp-${e.user_id}`}>
              <Text style={s.meta}>{e.employee_code ? `${e.employee_code} · ` : ""}{e.name}</Text>
            </Pressable>
          ))}
        </>
      ) : null}
      <View style={bm.row}>
        <BmField label="Accident Date (YYYY-MM-DD) *" value={f.accident_date} onChangeText={(v) => set("accident_date", v)} width={180} testID="ar-date" />
        <BmField label="Time (HH:MM)" value={f.accident_time || ""} onChangeText={(v) => set("accident_time", v)} width={110} />
        <BmField label="Accident Type" value={f.accident_type || ""} onChangeText={(v) => set("accident_type", v)} />
        <BmField label="Location" value={f.location || ""} onChangeText={(v) => set("location", v)} />
      </View>
      <View style={bm.row}>
        <BmField label="Nature of Injury" value={f.injury_nature || ""} onChangeText={(v) => set("injury_nature", v)} />
        <BmField label="Body Part" value={f.body_part || ""} onChangeText={(v) => set("body_part", v)} width={140} />
        <BmField label="Cause" value={f.cause || ""} onChangeText={(v) => set("cause", v)} />
      </View>
      <View style={bm.row}>
        <BmField label="Witnesses" value={f.witnesses || ""} onChangeText={(v) => set("witnesses", v)} />
        <BmField label="First Aid" value={f.first_aid || ""} onChangeText={(v) => set("first_aid", v)} />
        <BmField label="Doctor / Hospital" value={f.doctor_hospital || ""} onChangeText={(v) => set("doctor_hospital", v)} />
      </View>
      <BmField label="Description" value={f.description || ""} onChangeText={(v) => set("description", v)} />
      <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
        <BmToggle label="Fatal" value={!!f.fatal} onChange={(v) => set("fatal", v)} />
        <BmToggle label="Hospitalised" value={!!f.hospitalised} onChange={(v) => set("hospitalised", v)} />
        <BmToggle label="ESIC Reporting" value={!!f.esic_applicable} onChange={(v) => set("esic_applicable", v)} testID="ar-esic" />
        <BmToggle label="Factory & Boilers Reporting" value={!!f.fnb_applicable} onChange={(v) => set("fnb_applicable", v)} testID="ar-fnb" />
      </View>
      {f.fnb_applicable ? (
        <>
          <Text style={bm.secTitle}>Factory & Boilers Details</Text>
          <View style={bm.row}>
            <BmField label="Factory Regn / License No." value={f.fnb.factory_regn_no || ""} onChangeText={(v) => setFnb("factory_regn_no", v)} />
            <BmField label="Occupier Name" value={f.fnb.occupier_name || ""} onChangeText={(v) => setFnb("occupier_name", v)} />
            <BmField label="Manager Name" value={f.fnb.manager_name || ""} onChangeText={(v) => setFnb("manager_name", v)} />
          </View>
          <View style={bm.row}>
            <BmField label="Section / Department" value={f.fnb.section || ""} onChangeText={(v) => setFnb("section", v)} />
            <BmField label="Machine / Equipment" value={f.fnb.machine || ""} onChangeText={(v) => setFnb("machine", v)} testID="ar-machine" />
            <BmField label="Work / Process" value={f.fnb.work_process || ""} onChangeText={(v) => setFnb("work_process", v)} />
          </View>
          <View style={bm.row}>
            <BmField label="Immediate Cause" value={f.fnb.immediate_cause || ""} onChangeText={(v) => setFnb("immediate_cause", v)} />
            <BmField label="Root Cause" value={f.fnb.root_cause || ""} onChangeText={(v) => setFnb("root_cause", v)} />
            <BmField label="Corrective Action" value={f.fnb.corrective_action || ""} onChangeText={(v) => setFnb("corrective_action", v)} />
          </View>
          <BmToggle label="Dangerous Occurrence" value={!!f.fnb.dangerous_occurrence} onChange={(v) => setFnb("dangerous_occurrence", v)} />
        </>
      ) : null}
      <View style={{ flexDirection: "row", gap: 8, justifyContent: "flex-end", marginTop: 6 }}>
        <BmBtn label="Cancel" kind="ghost" onPress={onCancel} />
        <BmBtn label="Save Accident" onPress={save} busy={busy} testID="ar-save" />
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8, marginBottom: 8 },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 12.5, color: colors.onSurfaceTertiary, marginVertical: 10 },
  cards: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 },
  card: { minWidth: 105, flexGrow: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 9, backgroundColor: colors.surface },
  cardV: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  cardL: { fontSize: 10, fontWeight: "700", color: colors.onSurfaceTertiary },
  row: { flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1,
    borderColor: colors.border, borderRadius: radius.md, padding: 9, marginBottom: 6,
    backgroundColor: colors.surface, flexWrap: "wrap" },
  name: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  meta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  panel: { borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: 10, backgroundColor: colors.surface },
  panelT: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  empOpt: { padding: 7, borderBottomWidth: 1, borderColor: colors.border },
});
