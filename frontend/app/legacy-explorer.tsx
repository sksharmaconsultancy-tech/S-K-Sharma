/**
 * Iter 299 — Legacy SQL Explorer (read-only).
 *
 * Browse the old payroll software's SQL Server data (restored on the VPS
 * via legacy_setup.sh) BEFORE deciding what to import. Databases →
 * tables (with row counts) → paginated row viewer with search.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  TextInput, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

type Db = { name: string; size_mb: number };
type TableInfo = { schema_name: string; table_name: string; row_count: number };

const PAGE = 50;

export default function LegacyExplorerScreen() {
  const [status, setStatus] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [db, setDb] = useState<string>("");
  const [tables, setTables] = useState<TableInfo[]>([]);
  const [tablesBusy, setTablesBusy] = useState(false);
  const [tableSearch, setTableSearch] = useState("");
  const [table, setTable] = useState<string>("");
  const [data, setData] = useState<any>(null);
  const [rowsBusy, setRowsBusy] = useState(false);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [err, setErr] = useState("");
  // Iter 299b — smart Firms & Employees discovery.
  const [disc, setDisc] = useState<any>(null);
  const [discBusy, setDiscBusy] = useState(false);
  const runDiscover = async (name: string) => {
    setDiscBusy(true); setErr("");
    try {
      const r = await api<any>(`/admin/legacy/discover?db=${encodeURIComponent(name)}`);
      setDisc(r);
    } catch (e: any) {
      setErr(e?.message || "Scan failed");
    } finally { setDiscBusy(false); }
  };

  useEffect(() => {
    (async () => {
      try {
        const s = await api<any>("/admin/legacy/status");
        setStatus(s);
        if ((s.databases || []).length === 1) selectDb(s.databases[0].name);
      } catch (e: any) {
        setErr(e?.message || "Failed to reach the server");
      } finally { setLoading(false); }
    })();
  }, []);

  const selectDb = async (name: string) => {
    setDb(name); setTable(""); setData(null); setDisc(null); setTablesBusy(true); setErr("");
    try {
      const r = await api<{ tables: TableInfo[] }>(`/admin/legacy/tables?db=${encodeURIComponent(name)}`);
      setTables(r.tables || []);
    } catch (e: any) {
      setErr(e?.message || "Failed to list tables");
      setTables([]);
    } finally { setTablesBusy(false); }
  };

  const loadRows = async (tbl: string, pg: number, q: string) => {
    setTable(tbl); setPage(pg); setRowsBusy(true); setErr("");
    try {
      const r = await api<any>(
        `/admin/legacy/rows?db=${encodeURIComponent(db)}&table=${encodeURIComponent(tbl)}` +
        `&skip=${pg * PAGE}&limit=${PAGE}${q ? `&search=${encodeURIComponent(q)}` : ""}`,
      );
      setData(r);
    } catch (e: any) {
      setErr(e?.message || "Failed to load rows");
    } finally { setRowsBusy(false); }
  };

  const filteredTables = useMemo(() => {
    const q = tableSearch.trim().toLowerCase();
    if (!q) return tables;
    return tables.filter((t) => t.table_name.toLowerCase().includes(q));
  }, [tables, tableSearch]);

  const colNames: string[] = useMemo(
    () => (data?.columns || []).map((c: any) => c.name),
    [data],
  );

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Legacy SQL Explorer" }} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
        <Text style={st.h1}>Legacy SQL Explorer</Text>
        <Text style={st.sub}>
          Read-only view of your old payroll software&apos;s database — check the
          data here before we import anything into the portal.
        </Text>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : !status?.configured || !status?.connected ? (
          <View style={st.card}>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Ionicons name="server-outline" size={18} color="#B45309" />
              <Text style={st.cardTitle}>
                {status?.configured ? "Legacy server not reachable" : "Not set up yet"}
              </Text>
            </View>
            {status?.error ? <Text style={st.errTxt}>{String(status.error)}</Text> : null}
            <Text style={st.step}>To set it up on your VPS:</Text>
            <Text style={st.mono}>1) Copy your backup ZIP to /home/sksharma/legacy/ (WinSCP)</Text>
            <Text style={st.mono}>
              2) wget -O legacy_setup.sh &quot;https://YOUR-PORTAL/api/temp-code-bundle?token=sks-deploy-7391&amp;kind=legacy&quot; &amp;&amp; bash legacy_setup.sh
            </Text>
            <Text style={st.step}>
              The script installs SQL Server Express (free), restores every .bak
              inside the ZIP and connects this screen automatically.
            </Text>
          </View>
        ) : (
          <>
            {/* Databases */}
            <View style={st.card}>
              <Text style={st.cardTitle}>Databases ({(status.databases || []).length})</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 8 }}>
                {(status.databases || []).map((d: Db) => (
                  <Pressable
                    key={d.name}
                    onPress={() => selectDb(d.name)}
                    style={[st.chip, db === d.name && st.chipOn]}
                  >
                    <Ionicons name="server-outline" size={13} color={db === d.name ? "#fff" : colors.brandPrimary} />
                    <Text style={[st.chipTxt, db === d.name && { color: "#fff" }]}>
                      {d.name}  ·  {d.size_mb} MB
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>

            {/* Iter 299b — Firms & Employees smart scan */}
            {db ? (
              <View style={st.card}>
                <Text style={st.cardTitle}>Check Firms &amp; Employees</Text>
                <Text style={st.sub}>
                  One click — finds the company &amp; employee tables in the old
                  data and marks which firms already exist in this portal.
                </Text>
                <Pressable
                  onPress={() => runDiscover(db)}
                  style={st.findBtn}
                  disabled={discBusy}
                >
                  {discBusy ? (
                    <ActivityIndicator color="#fff" size="small" />
                  ) : (
                    <Ionicons name="search-circle-outline" size={18} color="#fff" />
                  )}
                  <Text style={st.findBtnTxt}>Find Firms &amp; Employees</Text>
                </Pressable>
                {disc ? (
                  <>
                    <Text style={st.secTitle}>
                      Companies found in old data ({(disc.companies_found || []).length})
                    </Text>
                    {(disc.companies_found || []).length === 0 ? (
                      <Text style={st.sub}>
                        No company-name column detected automatically — browse the
                        tables below and tell me which one holds the firm names.
                      </Text>
                    ) : (
                      (disc.companies_found || []).map((c: any) => (
                        <View key={c.name} style={st.compRow}>
                          <Ionicons
                            name={c.in_portal ? "checkmark-circle" : "alert-circle-outline"}
                            size={15}
                            color={c.in_portal ? "#16a34a" : "#B45309"}
                          />
                          <Text style={st.compName} numberOfLines={1}>{c.name}</Text>
                          <Text style={[st.compTag, { color: c.in_portal ? "#16a34a" : "#B45309" }]}>
                            {c.in_portal ? `✓ in portal (${c.portal_firm})` : "not in portal"}
                          </Text>
                        </View>
                      ))
                    )}
                    <Text style={st.secTitle}>
                      Employee tables found ({(disc.employee_tables || []).length}) — tap to open
                    </Text>
                    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                      {(disc.employee_tables || []).map((t: any) => (
                        <Pressable
                          key={t.table}
                          onPress={() => { setSearch(""); loadRows(t.table, 0, ""); }}
                          style={st.tblChip}
                        >
                          <Text style={st.chipTxt} numberOfLines={1}>{t.table}</Text>
                          <Text style={st.cnt}>
                            {Number(t.row_count || 0).toLocaleString("en-IN")} rows · match {t.score}/9
                          </Text>
                        </Pressable>
                      ))}
                    </View>
                  </>
                ) : null}
              </View>
            ) : null}

            {/* Tables */}
            {db ? (
              <View style={st.card}>
                <Text style={st.cardTitle}>Tables in {db}</Text>
                <TextInput
                  value={tableSearch}
                  onChangeText={setTableSearch}
                  placeholder="Search table name…"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={st.input}
                />
                {tablesBusy ? (
                  <ActivityIndicator style={{ marginVertical: 20 }} color={colors.brandPrimary} />
                ) : (
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 }}>
                    {filteredTables.map((t) => (
                      <Pressable
                        key={`${t.schema_name}.${t.table_name}`}
                        onPress={() => { setSearch(""); loadRows(t.table_name, 0, ""); }}
                        style={[st.tblChip, table === t.table_name && st.chipOn]}
                      >
                        <Text style={[st.chipTxt, table === t.table_name && { color: "#fff" }]} numberOfLines={1}>
                          {t.table_name}
                        </Text>
                        <Text style={[st.cnt, table === t.table_name && { color: "#E0E7FF" }]}>
                          {Number(t.row_count || 0).toLocaleString("en-IN")} rows
                        </Text>
                      </Pressable>
                    ))}
                    {filteredTables.length === 0 ? (
                      <Text style={st.sub}>No tables match.</Text>
                    ) : null}
                  </View>
                )}
              </View>
            ) : null}

            {/* Rows */}
            {table ? (
              <View style={st.card}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <Text style={[st.cardTitle, { flex: 1, minWidth: 160 }]}>
                    {table}
                    {data ? `  ·  ${Number(data.total || 0).toLocaleString("en-IN")} rows` : ""}
                  </Text>
                  <TextInput
                    value={search}
                    onChangeText={setSearch}
                    onSubmitEditing={() => loadRows(table, 0, search)}
                    placeholder="Search text in this table… (Enter)"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={[st.input, { marginTop: 0, minWidth: 220, flexGrow: 1 }]}
                  />
                  <Pressable style={st.goBtn} onPress={() => loadRows(table, 0, search)}>
                    <Ionicons name="search" size={14} color="#fff" />
                  </Pressable>
                </View>
                {rowsBusy ? (
                  <ActivityIndicator style={{ marginVertical: 24 }} color={colors.brandPrimary} />
                ) : data ? (
                  <>
                    <ScrollView horizontal style={{ marginTop: 10 }}>
                      <View>
                        <View style={[st.tr, st.trHead]}>
                          {colNames.map((c) => (
                            <Text key={c} style={[st.td, st.th]} numberOfLines={1}>{c}</Text>
                          ))}
                        </View>
                        {(data.rows || []).map((r: any, i: number) => (
                          <View key={i} style={[st.tr, i % 2 ? st.trOdd : null]}>
                            {colNames.map((c) => (
                              <Text key={c} style={st.td} numberOfLines={1}>
                                {r[c] === null || r[c] === undefined ? "—" : String(r[c])}
                              </Text>
                            ))}
                          </View>
                        ))}
                      </View>
                    </ScrollView>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 10, marginTop: 10 }}>
                      <Pressable
                        disabled={page === 0}
                        onPress={() => loadRows(table, page - 1, search)}
                        style={[st.pgBtn, page === 0 && { opacity: 0.4 }]}
                      >
                        <Ionicons name="chevron-back" size={14} color={colors.brandPrimary} />
                        <Text style={st.pgTxt}>Prev</Text>
                      </Pressable>
                      <Text style={st.sub}>
                        Page {page + 1} of {Math.max(1, Math.ceil((data.total || 0) / PAGE))}
                      </Text>
                      <Pressable
                        disabled={(page + 1) * PAGE >= (data.total || 0)}
                        onPress={() => loadRows(table, page + 1, search)}
                        style={[st.pgBtn, (page + 1) * PAGE >= (data.total || 0) && { opacity: 0.4 }]}
                      >
                        <Text style={st.pgTxt}>Next</Text>
                        <Ionicons name="chevron-forward" size={14} color={colors.brandPrimary} />
                      </Pressable>
                    </View>
                  </>
                ) : null}
              </View>
            ) : null}
          </>
        )}

        {err ? <Text style={st.errTxt}>{err}</Text> : null}
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
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  tblChip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 6, maxWidth: 240,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  cnt: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 2 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 8 : 6,
    fontSize: 12.5, color: colors.onSurface, marginTop: 8, backgroundColor: colors.surface,
  },
  goBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9,
  },
  findBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#B45309", borderRadius: radius.md,
    paddingVertical: 11, marginTop: 10,
  },
  findBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  secTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface, marginTop: 14, marginBottom: 6 },
  compRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 6, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  compName: { flex: 1, fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  compTag: { fontSize: 11, fontWeight: "700" },
  tr: { flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border },
  trHead: { backgroundColor: colors.brandPrimary, borderTopLeftRadius: 6, borderTopRightRadius: 6 },
  trOdd: { backgroundColor: colors.surfaceSecondary },
  th: { color: "#fff", fontWeight: "800" },
  td: { width: 140, fontSize: 11, color: colors.onSurface, paddingHorizontal: 6, paddingVertical: 6 },
  pgBtn: { flexDirection: "row", alignItems: "center", gap: 4, padding: 6 },
  pgTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  step: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 10, lineHeight: 17 },
  mono: {
    fontFamily: Platform.OS === "web" ? "monospace" : "Courier", fontSize: 11,
    color: colors.onSurface, backgroundColor: colors.surfaceSecondary,
    padding: 8, borderRadius: 6, marginTop: 6,
  },
  errTxt: { color: "#DC2626", fontSize: 12, marginTop: 10 },
});
