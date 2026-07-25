/**
 * Iter 300 — Legacy Salary Records viewer.
 * Browse the imported OLD salary history (online / offline) firm + month
 * wise, with head-wise columns and employee search.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
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

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/companies");
        setCompanies(r.companies || r || []);
      } catch { /* company admin — endpoint may differ; ignore */ }
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
                style={[st.chip, cid === c.company_id && st.chipOn]}
                onPress={() => { setCid(c.company_id); loadMonths(c.company_id, kind); }}
              >
                <Text style={[st.chipTxt, cid === c.company_id && { color: "#fff" }]}>{c.name}</Text>
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
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
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
});
