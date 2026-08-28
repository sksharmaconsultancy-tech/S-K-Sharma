/**
 * Iter 769 (user request) — Bulk Dummy Shift Assign now lives in the
 * EMPLOYEE MASTER (moved out of the Attendance Policy screen). Whatever
 * shift an employee gets assigned is exactly what the Dummy Shift Matrix
 * report shows. Report-only — attendance & salary are never touched.
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, Pressable, Platform, StyleSheet } from "react-native";
import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

export default function BulkDummyAssignCard({ companyId }: { companyId: string }) {
  const [opts, setOpts] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const [shift, setShift] = useState<string>("");
  const [scope, setScope] = useState<string>("all");
  const [onlyUnassigned, setOnlyUnassigned] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setErr(null);
      const r = await api<any>(
        `/admin/labour-reports/dummy-shift/bulk-options?company_id=${companyId}`);
      setOpts(r);
    } catch (e: any) {
      setErr(e?.message || "Could not load employee data");
    }
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  const apply = async (clear: boolean) => {
    if (!clear && !shift) {
      setErr("Pick a dummy shift first");
      return;
    }
    const scopeLabel = scope === "all"
      ? "ALL active employees"
      : `department "${scope === "__none__" ? "No Department" : scope}"`;
    const msg = clear
      ? `Clear dummy shift assignments for ${scopeLabel}?`
      : `Assign "${shift}" to ${scopeLabel}${onlyUnassigned
          ? " (only employees WITHOUT a dummy shift)"
          : " (REPLACING existing assignments)"}?`;
    if (Platform.OS === "web" && !globalThis.confirm(msg)) return;
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api<any>(
        "/admin/labour-reports/dummy-shift/bulk-assign", {
          method: "POST",
          body: {
            company_id: companyId,
            dummy_shift: shift,
            clear,
            scope: scope === "all" ? "all" : "department",
            department: scope === "all" ? "" : scope,
            only_unassigned: onlyUnassigned,
          },
        });
      setResult(clear
        ? `✓ Cleared ${r.modified} assignment(s).`
        : `✓ "${shift}" assigned to ${r.modified} employee(s).`);
      await load();
    } catch (e: any) {
      setErr(e?.message || "Bulk assign failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={s.card} testID="bulk-dummy-assign">
      <Text style={s.title}>Bulk Dummy Shift Assign</Text>
      <Text style={s.note}>
        Ek tap me poori firm ya department ko dummy shift assign karein —
        jo shift assign hogi wahi Dummy Shift Matrix report me dikhegi.
        Report-only: attendance & salary par koi asar nahi.
      </Text>
      {err ? <Text style={{ color: colors.error, fontSize: 12, marginBottom: 6 }}>{err}</Text> : null}
      {!opts ? (
        <Text style={s.note}>Loading employee data…</Text>
      ) : (
        <>
          <Text style={s.note}>
            {opts.total_employees} active employees · {opts.assigned} assigned
            · {opts.unassigned} without a dummy shift
          </Text>
          <Text style={s.stepLbl}>1. Dummy Shift</Text>
          <View style={s.chips}>
            {(opts.dummy_shifts || []).map((sh: any) => (
              <Pressable key={sh.name} onPress={() => setShift(sh.name)}
                style={[s.chip, shift === sh.name && s.chipOn]} testID={`bda-shift-${sh.name}`}>
                <Text style={[s.chipTxt, shift === sh.name && { color: "#fff" }]}>
                  {sh.name} ({sh.start}–{sh.end})
                </Text>
              </Pressable>
            ))}
          </View>
          <Text style={s.stepLbl}>2. Assign To</Text>
          <View style={s.chips}>
            <Pressable onPress={() => setScope("all")}
              style={[s.chip, scope === "all" && s.chipOn]} testID="bda-scope-all">
              <Text style={[s.chipTxt, scope === "all" && { color: "#fff" }]}>
                All Employees ({opts.total_employees})
              </Text>
            </Pressable>
            {(opts.departments || []).map((d: any) => (
              <Pressable key={d.key} onPress={() => setScope(d.key)}
                style={[s.chip, scope === d.key && s.chipOn]} testID={`bda-dept-${d.key}`}>
                <Text style={[s.chipTxt, scope === d.key && { color: "#fff" }]}>
                  {d.label} ({d.count})
                </Text>
              </Pressable>
            ))}
          </View>
          <Text style={s.stepLbl}>3. Mode</Text>
          <View style={s.chips}>
            {[
              { v: true, l: "Only employees without a dummy shift" },
              { v: false, l: "Replace existing assignments too" },
            ].map((o) => (
              <Pressable key={String(o.v)} onPress={() => setOnlyUnassigned(o.v)}
                style={[s.chip, onlyUnassigned === o.v && s.chipOn]}
                testID={`bda-mode-${o.v ? "unassigned" : "replace"}`}>
                <Text style={[s.chipTxt, onlyUnassigned === o.v && { color: "#fff" }]}>
                  {o.l}
                </Text>
              </Pressable>
            ))}
          </View>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <Pressable onPress={() => apply(false)} disabled={busy}
              style={[s.btn, { backgroundColor: "#0F3B5C", opacity: busy ? 0.5 : 1 }]}
              testID="bda-apply">
              <Text style={[s.btnTxt, { color: "#fff" }]}>
                {busy ? "Working…" : "⚡ Assign Now"}
              </Text>
            </Pressable>
            <Pressable onPress={() => apply(true)} disabled={busy}
              style={[s.btn, { backgroundColor: "#FEE2E2", opacity: busy ? 0.5 : 1 }]}
              testID="bda-clear">
              <Text style={[s.btnTxt, { color: "#991B1B" }]}>Clear In Scope</Text>
            </Pressable>
          </View>
          {result ? (
            <Text style={{ color: "#047857", fontWeight: "800", fontSize: 12.5, marginTop: 8 }}
              testID="bda-result">
              {result}
            </Text>
          ) : null}
        </>
      )}
    </View>
  );
}

const s = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: 12, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginTop: 12,
  },
  title: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 4 },
  note: { fontSize: 12, color: colors.onSurfaceSecondary, lineHeight: 17, marginBottom: 4 },
  stepLbl: { fontSize: 12, fontWeight: "800", color: colors.onSurface, marginTop: 10, marginBottom: 4 },
  chips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    paddingHorizontal: 10, paddingVertical: 7, borderRadius: 16,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: "#0F3B5C", borderColor: "#0F3B5C" },
  chipTxt: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "600" },
  btn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: 10 },
  btnTxt: { fontSize: 13, fontWeight: "800" },
});
