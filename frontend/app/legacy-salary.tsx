/**
 * Iter 300 — Legacy Salary Records viewer.
 * Browse the imported OLD salary history (online / offline) firm + month
 * wise, with head-wise columns and employee search.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

export default function LegacySalaryScreen() {
  const [companies, setCompanies] = useState<any[]>([]);
  const [cid, setCid] = useState("");
  const [kind, setKind] = useState<"online" | "offline">("online");
  const [months, setMonths] = useState<string[]>([]);
  const [month, setMonth] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [search, setSearch] = useState("");
  const [err, setErr] = useState("");
  // Iter 302 (user) — publish legacy ONLINE months into Compliance Salary.
  const [pubStep, setPubStep] = useState(0);   // 0 hidden, 1, 2
  const [pubJob, setPubJob] = useState<any>(null);
  const [pubBusy, setPubBusy] = useState(false);
  const [lockConfirm, setLockConfirm] = useState(false);
  const [lockBusy, setLockBusy] = useState(false);
  const [lockMsg, setLockMsg] = useState("");
  // Iter 302c (user) — choose WHICH months to publish (Select All option).
  const [pubSel, setPubSel] = useState<Record<string, boolean>>({});

  const openPublish = () => {
    const all: Record<string, boolean> = {};
    months.forEach((m) => { all[m] = true; });
    setPubSel(all);
    setPubStep(1);
  };
  const selCount = Object.values(pubSel).filter(Boolean).length;

  const startPublish = async () => {
    setPubStep(0); setPubBusy(true); setPubJob(null);
    try {
      const r = await api<any>("/admin/legacy-salary/publish-compliance", {
        method: "POST",
        body: {
          company_id: cid, lock: false,
          months: Object.keys(pubSel).filter((m) => pubSel[m]),
        },
      });
      pollPub(r.job_id);
    } catch (e: any) { setErr(e?.message || "Publish failed"); setPubBusy(false); }
  };

  const lockAll = async () => {
    setLockConfirm(false); setLockBusy(true); setLockMsg("");
    try {
      const r = await api<any>("/admin/legacy-salary/lock-compliance", {
        method: "POST", body: { company_id: cid },
      });
      setLockMsg(`🔒 ${r.locked} legacy month(s) are now LOCKED (finalized).`);
      // refresh firm badges (LOCKED highlight)
      try {
        const fr = await api<any>("/admin/legacy-salary/firms");
        setCompanies(fr.companies || []);
      } catch { /* ignore */ }
    } catch (e: any) { setErr(e?.message || "Lock failed"); }
    finally { setLockBusy(false); }
  };

  const pollPub = async (id: string) => {
    try {
      const j = await api<any>(`/admin/legacy-import/jobs/${id}`);
      setPubJob(j);
      if (j.status === "done" || j.status === "failed") { setPubBusy(false); return; }
    } catch { /* keep polling */ }
    setTimeout(() => pollPub(id), 2500);
  };

  useEffect(() => {
    (async () => {
      try {
        // Iter 304b (user) — only firms whose legacy data imported successfully.
        const r = await api<any>("/admin/legacy-salary/firms");
        setCompanies(r.companies || []);
      } catch { /* ignore */ }
    })();
  }, []);

  const loadMonths = async (c: string, k: string) => {
    setBusy(true); setErr(""); setRows([]); setMonth("");
    try {
      const r = await api<any>(`/admin/legacy-salary?company_id=${encodeURIComponent(c)}&kind=${k}`);
      setMonths(r.months || []);
      if (!(r.months || []).length) setErr("No imported records for this firm — run the Legacy Import Wizard first.");
    } catch (e: any) { setErr(e?.message || "Failed"); }
    finally { setBusy(false); }
  };

  const loadRows = async (m: string, q = "") => {
    setMonth(m); setBusy(true); setErr("");
    try {
      const r = await api<any>(
        `/admin/legacy-salary?company_id=${encodeURIComponent(cid)}&kind=${kind}&month=${m}` +
        (q ? `&search=${encodeURIComponent(q)}` : ""));
      setRows(r.rows || []);
    } catch (e: any) { setErr(e?.message || "Failed"); }
    finally { setBusy(false); }
  };

  // dynamic head columns
  const headCols = useMemo(() => {
    const earn = new Set<string>(); const ded = new Set<string>();
    rows.forEach((r) => {
      Object.keys(r.earn_heads || {}).forEach((k) => earn.add(k));
      Object.keys(r.deduct_heads || {}).forEach((k) => ded.add(k));
    });
    return { earn: [...earn], ded: [...ded] };
  }, [rows]);

  const money = (v: any) => (v === null || v === undefined || v === 0 ? "—" :
    Number(v).toLocaleString("en-IN", { maximumFractionDigits: 0 }));

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Legacy Salary Records" }} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        <Text style={st.h1}>Legacy Salary Records</Text>
        <Text style={st.sub}>Old software&apos;s salary history — read-only archive.</Text>

        <View style={st.card}>
          <Text style={st.lbl}>Firm</Text>
          <View style={st.wrap}>
            {companies.map((c: any) => (
              <Pressable
                key={c.company_id}
                style={[st.chip, cid === c.company_id && st.chipOn,
                  c.fully_locked && { borderColor: "#B45309", borderWidth: 1.5 }]}
                onPress={() => { setCid(c.company_id); loadMonths(c.company_id, kind); }}
              >
                <Text style={[st.chipTxt, cid === c.company_id && { color: "#fff" }]}>{c.name}</Text>
                {c.fully_locked ? (
                  <View style={[st.badge, { backgroundColor: "#FEF3C7" }]}>
                    <Text style={[st.badgeTxt, { color: "#B45309" }]}>🔒 LOCKED</Text>
                  </View>
                ) : c.published_months ? (
                  <View style={[st.badge, { backgroundColor: "#DCFCE7" }]}>
                    <Text style={[st.badgeTxt, { color: "#16a34a" }]}>
                      ✓ SALARY IMPORTED ({c.published_months})
                    </Text>
                  </View>
                ) : null}
              </Pressable>
            ))}
          </View>
          <Text style={st.lbl}>Type</Text>
          <View style={st.wrap}>
            {(["online", "offline"] as const).map((k) => (
              <Pressable
                key={k}
                style={[st.chip, kind === k && st.chipOn]}
                onPress={() => { setKind(k); if (cid) loadMonths(cid, k); }}
              >
                <Text style={[st.chipTxt, kind === k && { color: "#fff" }]}>
                  {k === "online" ? "Online (PF/ESIC)" : "Offline (Actual)"}
                </Text>
              </Pressable>
            ))}
          </View>
          {months.length ? (
            <>
              <Text style={st.lbl}>Month</Text>
              <View style={st.wrap}>
                {months.map((m) => (
                  <Pressable key={m} style={[st.chip, month === m && st.chipOn]} onPress={() => loadRows(m, search)}>
                    <Text style={[st.chipTxt, month === m && { color: "#fff" }]}>{m}</Text>
                  </Pressable>
                ))}
              </View>
              {kind === "online" ? (
                <>
                  <Pressable
                    style={[st.pubBtn, pubBusy && { opacity: 0.5 }]}
                    disabled={pubBusy}
                    onPress={openPublish}
                  >
                    <Ionicons name="cloud-upload-outline" size={15} color="#fff" />
                    <Text style={st.pubBtnTxt}>
                      Publish months to Compliance Salary Process (unlocked — check first)
                    </Text>
                  </Pressable>
                  <Pressable
                    style={[st.lockBtn, lockBusy && { opacity: 0.5 }]}
                    disabled={lockBusy}
                    onPress={() => setLockConfirm(true)}
                  >
                    <Ionicons name="lock-closed-outline" size={15} color="#B45309" />
                    <Text style={st.lockBtnTxt}>
                      Data checked &amp; OK → Lock all published legacy months
                    </Text>
                  </Pressable>
                  {lockMsg ? <Text style={[st.sub, { color: "#16a34a", fontWeight: "700" }]}>{lockMsg}</Text> : null}
                </>
              ) : null}
              {pubJob ? (
                <View style={{ marginTop: 8 }}>
                  <Text style={[st.lbl, { marginTop: 0 }]}>
                    {pubJob.status === "done" ? "✅ Publish complete" :
                      pubJob.status === "failed" ? "❌ Publish failed" : "⏳ Publishing…"}
                    {"  —  "}{pubJob.totals?.published || 0} published · {pubJob.totals?.skipped || 0} skipped (month already processed)
                  </Text>
                  {(pubJob.errors || []).slice(0, 5).map((e: string, i: number) => (
                    <Text key={i} style={st.errTxt}>{e}</Text>
                  ))}
                  {pubJob.status === "done" ? (
                    <Text style={st.sub}>
                      Old months now appear in Compliance Salary Process (unlocked).
                      Check the data there — when everything is OK, press the Lock button above.
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </>
          ) : null}
        </View>

        {busy ? <ActivityIndicator style={{ marginTop: 24 }} color={colors.brandPrimary} /> : null}
        {err ? <Text style={st.errTxt}>{err}</Text> : null}

        {month && !busy ? (
          <View style={st.card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Text style={[st.lbl, { flex: 1, marginTop: 0 }]}>
                {month} · {rows.length} employees
              </Text>
              <TextInput
                value={search}
                onChangeText={setSearch}
                onSubmitEditing={() => loadRows(month, search)}
                placeholder="Search name… (Enter)"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={st.input}
              />
            </View>
            <ScrollView horizontal style={{ marginTop: 8 }}>
              <View>
                <View style={[st.tr, st.trHead]}>
                  {["Name", "Type", "Days", "Basic",
                    ...headCols.earn, "Gross",
                    ...(kind === "online" ? ["EPF", ...headCols.ded] :
                      ["Others", "TDS", "Less EPF", "Less ESI", "Adv", "Other Ded"]),
                    "Net"].map((h) => (
                      <Text key={h} style={[st.td, st.th]} numberOfLines={1}>{h}</Text>
                    ))}
                </View>
                {rows.map((r, i) => (
                  <View key={i} style={[st.tr, i % 2 ? st.trOdd : null]}>
                    <Text style={[st.td, { width: 170, textAlign: "left" }]} numberOfLines={1}>{r.name}</Text>
                    <Text style={st.td} numberOfLines={1}>{r.employee_type || "—"}</Text>
                    <Text style={st.td}>{r.present_days ?? "—"}</Text>
                    <Text style={st.td}>{money(r.basic)}</Text>
                    {headCols.earn.map((h) => (
                      <Text key={h} style={st.td}>{money((r.earn_heads || {})[h])}</Text>
                    ))}
                    <Text style={st.td}>{money(r.gross)}</Text>
                    {kind === "online" ? (
                      <>
                        <Text style={st.td}>{money(r.ee_pf)}</Text>
                        {headCols.ded.map((h) => (
                          <Text key={h} style={st.td}>{money((r.deduct_heads || {})[h])}</Text>
                        ))}
                      </>
                    ) : (
                      <>
                        <Text style={st.td}>{money(r.others)}</Text>
                        <Text style={st.td}>{money(r.tds)}</Text>
                        <Text style={st.td}>{money(r.less_epf)}</Text>
                        <Text style={st.td}>{money(r.less_esi)}</Text>
                        <Text style={st.td}>{money(r.less_adv)}</Text>
                        <Text style={st.td}>{money(r.less_other)}</Text>
                      </>
                    )}
                    <Text style={[st.td, { fontWeight: "700" }]}>{money(r.net)}</Text>
                  </View>
                ))}
              </View>
            </ScrollView>
          </View>
        ) : null}
      </ScrollView>

      {/* Iter 302 (user) — 2-step publish confirmation */}
      <Modal transparent visible={pubStep > 0} animationType="fade" onRequestClose={() => setPubStep(0)}>
        <Pressable style={st.backdrop} onPress={() => setPubStep(0)} />
        <View style={st.sheet}>
          {pubStep === 1 ? (
            <>
              <Text style={st.confTitle}>1️⃣ Select months to publish ({selCount} of {months.length})</Text>
              <Text style={st.confTxt}>
                Only the ticked months will be created inside the Compliance Salary Process as
                UNLOCKED (draft) runs — you check the data first, then lock.
              </Text>
              <Pressable
                style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 12, paddingVertical: 4 }}
                onPress={() => {
                  const all: Record<string, boolean> = {};
                  const on = selCount !== months.length;
                  months.forEach((m) => { all[m] = on; });
                  setPubSel(all);
                }}
              >
                <Ionicons
                  name={selCount === months.length ? "checkbox" : selCount ? "remove-circle-outline" : "square-outline"}
                  size={22}
                  color={selCount ? colors.brandPrimary : colors.onSurfaceTertiary}
                />
                <Text style={{ fontSize: 13.5, fontWeight: "800", color: colors.onSurface }}>
                  Select All Months ({months.length})
                </Text>
              </Pressable>
              <View style={[st.wrap, { marginTop: 8 }]}>
                {months.map((m) => (
                  <Pressable
                    key={m}
                    style={[st.chip, pubSel[m] && st.chipOn]}
                    onPress={() => setPubSel({ ...pubSel, [m]: !pubSel[m] })}
                  >
                    <Text style={[st.chipTxt, pubSel[m] && { color: "#fff" }]}>{m}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={st.confTxt}>
                • Months that already have a compliance run are SKIPPED — nothing is ever overwritten.
              </Text>
              <Pressable
                style={[st.confBtn, { backgroundColor: colors.brandPrimary, opacity: selCount ? 1 : 0.5 }]}
                disabled={!selCount}
                onPress={() => setPubStep(2)}
              >
                <Ionicons name="checkmark" size={16} color="#fff" />
                <Text style={st.confBtnTxt}>Continue with {selCount} month(s) (1/2)</Text>
              </Pressable>
              <Pressable style={st.cancelBtn} onPress={() => setPubStep(0)}>
                <Text style={st.cancelTxt}>Cancel</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Text style={st.confTitle}>🔴 Final Confirmation 2 of 2</Text>
              <Text style={st.confTxt}>
                Create draft compliance runs for {selCount} legacy month(s) now?
              </Text>
              <Pressable style={[st.confBtn, { backgroundColor: "#B45309" }]} onPress={startPublish}>
                <Ionicons name="cloud-upload-outline" size={16} color="#fff" />
                <Text style={st.confBtnTxt}>YES — Publish Now (2/2)</Text>
              </Pressable>
              <Pressable style={st.cancelBtn} onPress={() => setPubStep(1)}>
                <Text style={st.cancelTxt}>← Back</Text>
              </Pressable>
            </>
          )}
        </View>
      </Modal>

      {/* Lock-all confirmation */}
      <Modal transparent visible={lockConfirm} animationType="fade" onRequestClose={() => setLockConfirm(false)}>
        <Pressable style={st.backdrop} onPress={() => setLockConfirm(false)} />
        <View style={st.sheet}>
          <Text style={st.confTitle}>🔒 Lock all published legacy months?</Text>
          <Text style={st.confTxt}>
            Every legacy month published into the Compliance Salary Process for this firm will
            be FINALIZED (read-only). Do this only after you have checked the data. Individual
            months can still be unlocked later via Unlock Request.
          </Text>
          <Pressable style={[st.confBtn, { backgroundColor: "#B45309" }]} onPress={lockAll}>
            <Ionicons name="lock-closed" size={16} color="#fff" />
            <Text style={st.confBtnTxt}>YES — Lock all legacy months</Text>
          </Pressable>
          <Pressable style={st.cancelBtn} onPress={() => setLockConfirm(false)}>
            <Text style={st.cancelTxt}>Cancel</Text>
          </Pressable>
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
  lbl: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface, marginTop: 10, marginBottom: 6 },
  wrap: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 11, paddingVertical: 6,
    flexDirection: "row", alignItems: "center", gap: 6,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  badge: { borderRadius: 999, paddingHorizontal: 6, paddingVertical: 2 },
  badgeTxt: { fontSize: 9, fontWeight: "800" },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 7 : 5,
    fontSize: 12, color: colors.onSurface, minWidth: 180, backgroundColor: colors.surface,
  },
  tr: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border },
  trHead: { backgroundColor: colors.brandPrimary, borderTopLeftRadius: 6, borderTopRightRadius: 6 },
  trOdd: { backgroundColor: colors.surfaceSecondary },
  th: { color: "#fff", fontWeight: "800" },
  td: { width: 90, fontSize: 11, color: colors.onSurface, paddingHorizontal: 6, paddingVertical: 6, textAlign: "right" },
  errTxt: { color: "#DC2626", fontSize: 12, marginTop: 10 },
  pubBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#B45309", borderRadius: radius.md, paddingVertical: 11, marginTop: 12,
  },
  pubBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  lockBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderWidth: 1.5, borderColor: "#B45309", borderRadius: radius.md,
    paddingVertical: 10, marginTop: 8,
  },
  lockBtnTxt: { color: "#B45309", fontWeight: "800", fontSize: 12.5 },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.45)" },
  sheet: {
    position: "absolute", left: 20, right: 20, top: "18%",
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
  },
  confTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  confTxt: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 4, lineHeight: 18 },
  confBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderRadius: radius.md, paddingVertical: 12, marginTop: 12,
  },
  confBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  cancelBtn: { alignItems: "center", paddingVertical: 12, marginTop: 4 },
  cancelTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
});
