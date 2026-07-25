/**
 * Iter 300 — Legacy Import Wizard.
 *
 * 1) Map old firms → portal firms (tick which to import)
 * 2) Head-wise selection (employee field groups + online/offline salary)
 * 3) Preview counts → Start Import → live progress → summary
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const FIELD_GROUPS: { key: string; label: string }[] = [
  { key: "personal", label: "Personal (Name, F/H Name, DOB, DOJ, Type, Desig.)" },
  { key: "contact", label: "Contact (Mobile, Email, Address)" },
  { key: "ids", label: "IDs (PAN, Aadhaar, UAN, PF No, ESIC No)" },
  { key: "bank", label: "Bank (A/c, IFSC, Bank name)" },
  { key: "salary", label: "Salary heads (Basic, PF Basic, Gross, Allowances)" },
  { key: "status", label: "Status (Resign / Left date)" },
];

export default function LegacyImportScreen() {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [firms, setFirms] = useState<any[]>([]);
  const [portalFirms, setPortalFirms] = useState<any[]>([]);
  const [sel, setSel] = useState<Record<number, string>>({});   // firm_no -> company_id
  const [pickFor, setPickFor] = useState<number | null>(null);  // modal
  const [groups, setGroups] = useState<string[]>(FIELD_GROUPS.map((g) => g.key));
  const [impEmp, setImpEmp] = useState(true);
  const [impOn, setImpOn] = useState(true);
  const [impOff, setImpOff] = useState(true);
  const [preview, setPreview] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<any>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/admin/legacy-import/firms");
        setFirms(r.firms || []);
        setPortalFirms(r.portal_firms || []);
      } catch (e: any) {
        setErr(e?.message || "Legacy server not reachable — run the setup first.");
      } finally { setLoading(false); }
    })();
  }, []);

  const body = () => ({
    mappings: Object.entries(sel).map(([fn, cid]) => ({ firm_no: Number(fn), company_id: cid })),
    import_employees: impEmp,
    employee_fields: groups,
    salary_online: impOn,
    salary_offline: impOff,
  });

  const runPreview = async () => {
    setBusy(true); setErr(""); setPreview(null);
    try {
      const r = await api<any>("/admin/legacy-import/preview", { method: "POST", body: JSON.stringify(body()) });
      setPreview(r.firms || []);
    } catch (e: any) { setErr(e?.message || "Preview failed"); }
    finally { setBusy(false); }
  };

  const startImport = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api<any>("/admin/legacy-import/run", { method: "POST", body: JSON.stringify(body()) });
      pollJob(r.job_id);
    } catch (e: any) { setErr(e?.message || "Import failed to start"); setBusy(false); }
  };

  const pollJob = async (id: string) => {
    try {
      const j = await api<any>(`/admin/legacy-import/jobs/${id}`);
      setJob(j);
      if (j.status === "done" || j.status === "failed") { setBusy(false); return; }
    } catch { /* keep polling */ }
    setTimeout(() => pollJob(id), 2500);
  };

  const mappedCount = Object.keys(sel).length;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Legacy Import Wizard" }} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 80 }}>
        <Text style={st.h1}>Legacy Import Wizard</Text>
        <Text style={st.sub}>
          Choose the firms, tick the heads you want, preview, then import.
          Nothing is written until you press Start Import.
        </Text>
        {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} /> : (
          <>
            {/* STEP 1 — firm mapping */}
            <View style={st.card}>
              <Text style={st.cardTitle}>1️⃣  Select old firms &amp; map to portal firms ({mappedCount} selected)</Text>
              {firms.map((f) => {
                const cid = sel[f.firm_no];
                const pname = portalFirms.find((p) => p.company_id === cid)?.name;
                return (
                  <View key={f.firm_no} style={st.firmRow}>
                    <Pressable
                      onPress={() => {
                        const c = { ...sel };
                        if (cid) delete c[f.firm_no];
                        else c[f.firm_no] = f.suggested_company_id || "";
                        if (c[f.firm_no] === "") { setPickFor(f.firm_no); }
                        setSel(c);
                      }}
                      hitSlop={8}
                    >
                      <Ionicons
                        name={cid !== undefined ? "checkbox" : "square-outline"}
                        size={20}
                        color={cid !== undefined ? colors.brandPrimary : colors.onSurfaceTertiary}
                      />
                    </Pressable>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text style={st.firmName} numberOfLines={1}>{f.firm_name}</Text>
                      <Text style={st.firmMeta} numberOfLines={1}>
                        {f.employees} emp · online {f.online_months} mo · offline {f.offline_months} mo
                      </Text>
                    </View>
                    {cid !== undefined ? (
                      <Pressable style={st.mapBtn} onPress={() => setPickFor(f.firm_no)}>
                        <Text style={st.mapBtnTxt} numberOfLines={1}>
                          {pname || "→ choose portal firm"}
                        </Text>
                        <Ionicons name="chevron-down" size={12} color={colors.brandPrimary} />
                      </Pressable>
                    ) : null}
                  </View>
                );
              })}
            </View>

            {/* STEP 2 — head-wise selection */}
            <View style={st.card}>
              <Text style={st.cardTitle}>2️⃣  What to import (tick the heads)</Text>
              <Pressable style={st.tickRow} onPress={() => setImpEmp(!impEmp)}>
                <Ionicons name={impEmp ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Employee Master</Text>
              </Pressable>
              {impEmp ? FIELD_GROUPS.map((g) => (
                <Pressable
                  key={g.key}
                  style={[st.tickRow, { paddingLeft: 28 }]}
                  onPress={() => setGroups(groups.includes(g.key)
                    ? groups.filter((x) => x !== g.key) : [...groups, g.key])}
                >
                  <Ionicons
                    name={groups.includes(g.key) ? "checkbox" : "square-outline"}
                    size={17} color={groups.includes(g.key) ? colors.brandPrimary : colors.onSurfaceTertiary}
                  />
                  <Text style={st.tickTxt}>{g.label}</Text>
                </Pressable>
              )) : null}
              <Pressable style={st.tickRow} onPress={() => setImpOn(!impOn)}>
                <Ionicons name={impOn ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Salary History — ONLINE (PF/ESIC salary, head-wise)</Text>
              </Pressable>
              <Pressable style={st.tickRow} onPress={() => setImpOff(!impOff)}>
                <Ionicons name={impOff ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Salary History — OFFLINE (actual salary)</Text>
              </Pressable>
            </View>

            {/* STEP 3 — preview & run */}
            <View style={st.card}>
              <Text style={st.cardTitle}>3️⃣  Preview &amp; Import</Text>
              <Pressable
                style={[st.actBtn, { backgroundColor: colors.brandPrimary, opacity: mappedCount && !busy ? 1 : 0.5 }]}
                disabled={!mappedCount || busy}
                onPress={runPreview}
              >
                <Ionicons name="eye-outline" size={16} color="#fff" />
                <Text style={st.actTxt}>Preview (nothing is saved)</Text>
              </Pressable>
              {preview ? preview.map((p) => (
                <View key={p.firm_no} style={st.prevRow}>
                  <Text style={st.firmName}>→ {p.company_name}</Text>
                  <Text style={st.firmMeta}>
                    {impEmp ? `Employees: ${p.employees_new ?? 0} new + ${p.employees_existing ?? 0} update · ` : ""}
                    {impOn ? `Online: ${p.online_rows ?? 0} rows / ${p.online_months ?? 0} months · ` : ""}
                    {impOff ? `Offline: ${p.offline_rows ?? 0} rows / ${p.offline_months ?? 0} months` : ""}
                  </Text>
                </View>
              )) : null}
              {preview ? (
                <Pressable
                  style={[st.actBtn, { backgroundColor: "#B45309", opacity: busy ? 0.5 : 1 }]}
                  disabled={busy}
                  onPress={startImport}
                >
                  <Ionicons name="download-outline" size={16} color="#fff" />
                  <Text style={st.actTxt}>Start Import</Text>
                </Pressable>
              ) : null}
              {job ? (
                <View style={st.prevRow}>
                  <Text style={st.firmName}>
                    {job.status === "done" ? "✅ Import complete" :
                      job.status === "failed" ? "❌ Import failed" : "⏳ Importing…"}
                  </Text>
                  <Text style={st.firmMeta}>
                    Employees: {job.totals?.employees_created || 0} created, {job.totals?.employees_updated || 0} updated ·
                    Online rows: {job.totals?.online_rows || 0} · Offline rows: {job.totals?.offline_rows || 0}
                  </Text>
                  {(job.errors || []).slice(0, 5).map((e: string, i: number) => (
                    <Text key={i} style={st.errTxt}>{e}</Text>
                  ))}
                  {job.status === "done" ? (
                    <Text style={st.firmMeta}>
                      View imported salary: Import / Export → Legacy Salary Records
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </View>
          </>
        )}
        {err ? <Text style={st.errTxt}>{err}</Text> : null}
      </ScrollView>

      {/* portal firm picker */}
      <Modal transparent visible={pickFor !== null} animationType="fade" onRequestClose={() => setPickFor(null)}>
        <Pressable style={st.backdrop} onPress={() => setPickFor(null)} />
        <View style={st.pickSheet}>
          <Text style={st.cardTitle}>Import into which portal firm?</Text>
          <ScrollView style={{ maxHeight: 400 }}>
            {portalFirms.map((p) => (
              <Pressable
                key={p.company_id}
                style={st.pickRow}
                onPress={() => {
                  if (pickFor !== null) setSel({ ...sel, [pickFor]: p.company_id });
                  setPickFor(null);
                }}
              >
                <Ionicons name="business-outline" size={15} color={colors.brandPrimary} />
                <Text style={st.tickTxt}>{p.name}</Text>
              </Pressable>
            ))}
          </ScrollView>
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
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  firmRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  firmName: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  firmMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  mapBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, maxWidth: 220,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5,
  },
  mapBtnTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  tickRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7 },
  tickMain: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  tickTxt: { fontSize: 12.5, color: colors.onSurface, flex: 1 },
  actBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderRadius: radius.md, paddingVertical: 12, marginTop: 10,
  },
  actTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  prevRow: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  errTxt: { color: "#DC2626", fontSize: 12, marginTop: 8 },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.45)" },
  pickSheet: {
    position: "absolute", left: 20, right: 20, top: "15%",
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
  },
  pickRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
});
