/**
 * Master Data report — Iter 91 (Reports section).
 *
 * READ-ONLY view over the Employee Master. No editing here by design —
 * the data is shown "blocked" (locked) and can only be exported to
 * Excel. Three views: Active (working now), Left (resign date set on
 * master) and All. Filters: name/code/phone search, Employee Type /
 * Group, firm (super admin), On-roll / Off-roll.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MasterSelect from "@/src/components/MasterSelect";
import { colors, radius, spacing } from "@/src/theme";

type Col = { key: string; label: string };
type Row = Record<string, any>;

const STATUS_TABS = [
  { key: "active", label: "Active Employees" },
  { key: "left", label: "Left Employees" },
  { key: "all", label: "All Data" },
] as const;

export default function MasterDataReportScreen() {
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const isAdmin = ["company_admin", "super_admin", "sub_admin"].includes(user?.role || "");
  const [status, setStatus] = useState<"active" | "left" | "all">("active");
  const [q, setQ] = useState("");
  const [empType, setEmpType] = useState("");
  const [rollFilter, setRollFilter] = useState<"all" | "on" | "off">("all");
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [cols, setCols] = useState<Col[]>([]);
  const [rows, setRows] = useState<Row[]>([]);

  const buildQs = useCallback(() => {
    const p = new URLSearchParams();
    p.set("status", status);
    if (q.trim()) p.set("q", q.trim());
    if (empType) p.set("employee_type", empType);
    if (rollFilter !== "all") p.set("is_onroll", rollFilter === "on" ? "true" : "false");
    if (selectedCompanyId) p.set("company_id", selectedCompanyId);
    return p.toString();
  }, [status, q, empType, rollFilter, selectedCompanyId]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ columns: Col[]; rows: Row[] }>(
        `/admin/reports/master-data?${buildQs()}`,
      );
      setCols(r.columns || []);
      setRows(r.rows || []);
    } catch {
      setRows([]);
    } finally { setLoading(false); }
  }, [buildQs]);

  useEffect(() => { if (isAdmin) load(); }, [isAdmin, load]);

  const exportXlsx = async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const res = await apiBinary(`/admin/reports/master-data.xlsx?${buildQs()}`);
      if (Platform.OS === "web" && (res as any).webBlobUrl) {
        const a = document.createElement("a");
        a.href = (res as any).webBlobUrl;
        a.download = `MasterData_${status}.xlsx`;
        a.click();
      }
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Export failed");
    } finally { setExporting(false); }
  };

  if (authLoading) {
    return (
      <View style={styles.root}>
        <View style={styles.center}>
          <ActivityIndicator color={colors.brandPrimary} />
        </View>
      </View>
    );
  }

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <View style={styles.center}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.dimTxt}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Master Data</Text>
            <Text style={styles.hsub}>Employee Master · read-only · export to Excel</Text>
          </View>
          <Pressable onPress={exportXlsx} style={styles.exportBtn} testID="mdr-export">
            {exporting ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <>
                <Ionicons name="grid-outline" size={14} color="#fff" />
                <Text style={styles.exportTxt}>Excel</Text>
              </>
            )}
          </Pressable>
        </View>
      </SafeAreaView>

      {/* Status tabs */}
      <View style={styles.tabs}>
        {STATUS_TABS.map((t) => (
          <Pressable
            key={t.key}
            onPress={() => setStatus(t.key)}
            style={[styles.tabBtn, status === t.key && styles.tabBtnOn]}
            testID={`mdr-tab-${t.key}`}
          >
            <Text style={[styles.tabTxt, status === t.key && styles.tabTxtOn]}>{t.label}</Text>
          </Pressable>
        ))}
      </View>

      {/* Filters */}
      <View style={styles.filters}>
        <View style={styles.searchBox}>
          <Ionicons name="search" size={14} color={colors.onSurfaceTertiary} />
          <TextInput
            value={q}
            onChangeText={setQ}
            placeholder="Search name / code / phone…"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.searchInput}
            onSubmitEditing={load}
            testID="mdr-search"
          />
        </View>
        <View style={{ minWidth: 220, zIndex: 40 }}>
          <MasterSelect
            label=""
            masterType="group"
            companyId={selectedCompanyId}
            value={empType}
            onChange={setEmpType}
            placeholder="Group"
            testID="mdr-type"
          />
        </View>
        <View style={{ flexDirection: "row", gap: 4 }}>
          {(["all", "on", "off"] as const).map((rf) => (
            <Pressable
              key={rf}
              onPress={() => setRollFilter(rf)}
              style={[styles.rollChip, rollFilter === rf && styles.rollChipOn]}
            >
              <Text style={[styles.rollTxt, rollFilter === rf && styles.rollTxtOn]}>
                {rf === "all" ? "All" : rf === "on" ? "On-roll" : "Off-roll"}
              </Text>
            </Pressable>
          ))}
        </View>
        <Pressable onPress={load} style={styles.showBtn} testID="mdr-show">
          <Text style={styles.showTxt}>Show</Text>
        </Pressable>
        <View style={styles.lockBadge}>
          <Ionicons name="lock-closed" size={11} color="#92400E" />
          <Text style={styles.lockTxt}>READ-ONLY</Text>
        </View>
      </View>

      {/* Data grid */}
      {loading ? (
        <ActivityIndicator style={{ margin: 40 }} color={colors.brandPrimary} />
      ) : (
        <ScrollView horizontal style={{ flex: 1 }}>
          <ScrollView contentContainerStyle={{ paddingBottom: 40 }}>
            <View style={styles.gridHead}>
              <Text style={[styles.hCell, { width: 44 }]}>SN</Text>
              {cols.map((c) => (
                <Text key={c.key} style={[styles.hCell, { width: colWidth(c.key) }]}>
                  {c.label}
                </Text>
              ))}
            </View>
            {rows.map((r, i) => (
              <View key={r.user_id || i} style={[styles.gridRow, i % 2 === 1 && { backgroundColor: "#F8FAFC" }]}>
                <Text style={[styles.cell, { width: 44 }]}>{i + 1}</Text>
                {cols.map((c) => (
                  <Text key={c.key} style={[styles.cell, { width: colWidth(c.key) }]} numberOfLines={2}>
                    {c.key === "is_onroll"
                      ? (r[c.key] === false ? "Off-roll" : "On-roll")
                      : String(r[c.key] ?? "—")}
                  </Text>
                ))}
              </View>
            ))}
            {rows.length === 0 ? (
              <View style={styles.center}>
                <Ionicons name="file-tray-outline" size={34} color={colors.onSurfaceTertiary} />
                <Text style={styles.dimTxt}>No employees match this view.</Text>
              </View>
            ) : null}
          </ScrollView>
        </ScrollView>
      )}
      <View style={styles.footer}>
        <Text style={styles.footTxt}>{rows.length} record(s) · data locked (view &amp; export only)</Text>
      </View>
    </View>
  );
}

function colWidth(key: string): number {
  switch (key) {
    case "name": return 170;
    case "father_name": return 150;
    case "address": return 220;
    case "company_name": return 150;
    case "designation": case "department": return 130;
    case "bank_name": return 130;
    case "bank_account": return 140;
    case "aadhaar_no": case "uan_no": return 130;
    default: return 110;
  }
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  h1: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  hsub: { fontSize: 11, color: colors.onSurfaceTertiary },
  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: "#15803D",
    paddingHorizontal: 12, paddingVertical: 8,
    borderRadius: radius.md,
  },
  exportTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  tabs: { flexDirection: "row", gap: 8, paddingHorizontal: spacing.md, paddingTop: 10 },
  tabBtn: {
    paddingHorizontal: 14, paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  filters: {
    flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap",
    paddingHorizontal: spacing.md, paddingVertical: 10, zIndex: 30,
  },
  searchBox: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 10,
    backgroundColor: colors.surface,
    minWidth: 240, height: 40,
  },
  searchInput: { flex: 1, fontSize: 13, color: colors.onSurface },
  rollChip: {
    paddingHorizontal: 10, paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  rollChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  rollTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  rollTxtOn: { color: "#fff" },
  showBtn: {
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 16, paddingVertical: 9,
    borderRadius: radius.md,
  },
  showTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  lockBadge: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#FEF3C7",
    paddingHorizontal: 8, paddingVertical: 5,
    borderRadius: radius.pill,
  },
  lockTxt: { fontSize: 10, fontWeight: "900", color: "#92400E", letterSpacing: 0.4 },
  gridHead: {
    flexDirection: "row",
    backgroundColor: "#1E3A8A",
    paddingVertical: 8, paddingHorizontal: spacing.md,
  },
  hCell: { color: "#fff", fontSize: 11, fontWeight: "800", paddingHorizontal: 6 },
  gridRow: {
    flexDirection: "row",
    paddingVertical: 7, paddingHorizontal: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  cell: { fontSize: 11, color: colors.onSurface, paddingHorizontal: 6 },
  center: { alignItems: "center", gap: 8, padding: 40 },
  dimTxt: { color: colors.onSurfaceTertiary, fontSize: 13 },
  footer: {
    padding: 8, alignItems: "center",
    borderTopWidth: 1, borderTopColor: colors.divider,
    backgroundColor: colors.surface,
  },
  footTxt: { fontSize: 11, color: colors.onSurfaceTertiary },
});
