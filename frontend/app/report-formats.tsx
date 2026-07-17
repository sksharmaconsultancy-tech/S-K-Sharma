/**
 * Iter 162/163 — Utilities → PDF Report Formats (SUPER ADMIN ONLY).
 * One place to edit the saved layout/format of regular PDF reports.
 * Supports: Compliance Salary Register (dedicated editor) + PF ECR,
 * PF Challan, ESIC Contribution Sheet and ESIC Challan (generic editor:
 * columns / order / headings / widths / title / orientation / font size).
 */
import React, { useCallback, useEffect, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, RefreshControl } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { api } from "@/src/api/client";
import RegisterLayoutEditor from "@/src/components/RegisterLayoutEditor";
import ReportFormatEditor from "@/src/components/ReportFormatEditor";
import { colors, radius, spacing, type } from "@/src/theme";

type ReportItem = {
  report_id: string; label: string; group: string;
  has_columns: boolean; saved: boolean;
  updated_at?: string; updated_by_name?: string;
};

const GROUP_ICONS: Record<string, any> = {
  "PF Reports": "shield-checkmark-outline",
  "ESIC Reports": "medkit-outline",
};

export default function ReportFormatsScreen() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const [openRegister, setOpenRegister] = useState(false);
  const [reports, setReports] = useState<ReportItem[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [editing, setEditing] = useState<ReportItem | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api<{ reports: ReportItem[] }>("/admin/report-formats");
      setReports(r.reports || []);
    } catch { /* list stays empty */ }
    finally { setListLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return null;
  // STRICT super-admin gate (sub-admins NOT allowed — user directive).
  if (!user || user.role !== "super_admin" || (user as any).is_sub_admin) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 4 }} testID="rf-back">
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.title}>PDF Report Formats</Text>
        <View style={styles.badge}><Text style={styles.badgeTxt}>SUPER ADMIN ONLY</Text></View>
      </View>
      <ScrollView
        contentContainerStyle={{ padding: spacing.lg }}
        refreshControl={<RefreshControl refreshing={false} onRefresh={load} />}
      >
        <Text style={styles.hint}>
          Set the format of regular PDF reports ONE TIME here — every future
          download automatically uses your saved format.
        </Text>

        <Text style={styles.group}>COMPLIANCE SALARY</Text>
        <Pressable style={styles.card} onPress={() => setOpenRegister(true)} testID="rf-register">
          <Ionicons name="grid-outline" size={22} color={colors.brandPrimary} />
          <View style={{ flex: 1 }}>
            <Text style={styles.cardTitle}>Compliance Salary Register (PDF Option 2)</Text>
            <Text style={styles.cardSub}>
              Choose columns · order · rename headings · column widths ·
              employees per page · row height
            </Text>
          </View>
          <Ionicons name="create-outline" size={20} color={colors.onSurfaceSecondary} />
        </Pressable>

        {listLoading ? (
          <ActivityIndicator style={{ marginTop: 24 }} color={colors.brandPrimary} />
        ) : (
          ["PF Reports", "ESIC Reports"].map((grp) => {
            const items = reports.filter((r) => r.group === grp);
            if (!items.length) return null;
            return (
              <View key={grp}>
                <Text style={styles.group}>{grp.toUpperCase()}</Text>
                {items.map((r) => (
                  <Pressable key={r.report_id} style={styles.card}
                    onPress={() => setEditing(r)} testID={`rf-${r.report_id}`}>
                    <Ionicons name={GROUP_ICONS[grp] || "document-text-outline"}
                      size={22} color={colors.brandPrimary} />
                    <View style={{ flex: 1 }}>
                      <Text style={styles.cardTitle}>{r.label}</Text>
                      <Text style={styles.cardSub}>
                        {r.has_columns
                          ? "Columns · order · headings · widths · title · orientation · font size"
                          : "Fixed statutory layout — title · orientation · font size"}
                      </Text>
                      {r.saved ? (
                        <View style={styles.savedRow}>
                          <Ionicons name="checkmark-circle" size={13} color="#059669" />
                          <Text style={styles.savedTxt}>
                            Custom format saved
                            {r.updated_by_name ? ` by ${r.updated_by_name}` : ""}
                            {r.updated_at ? ` · ${String(r.updated_at).slice(0, 10)}` : ""}
                          </Text>
                        </View>
                      ) : (
                        <Text style={styles.defaultTxt}>Using default format</Text>
                      )}
                    </View>
                    <Ionicons name="create-outline" size={20} color={colors.onSurfaceSecondary} />
                  </Pressable>
                ))}
              </View>
            );
          })
        )}
      </ScrollView>

      <RegisterLayoutEditor visible={openRegister} onClose={() => setOpenRegister(false)} />
      {editing ? (
        <ReportFormatEditor
          visible={!!editing}
          reportId={editing.report_id}
          reportLabel={editing.label}
          onClose={() => setEditing(null)}
          onSaved={load}
        />
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.lg, paddingVertical: 12,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: type.h3, fontWeight: "700", color: colors.onSurface, flex: 1 },
  badge: { backgroundColor: "#FEF3C7", paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  badgeTxt: { fontSize: 10, fontWeight: "800", color: "#92400E" },
  hint: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: 14 },
  group: {
    fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceTertiary,
    letterSpacing: 0.8, marginTop: 12, marginBottom: 6,
  },
  card: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: spacing.lg, marginBottom: 10,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "700", color: colors.onSurface },
  cardSub: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  savedRow: { flexDirection: "row", alignItems: "center", gap: 4, marginTop: 4 },
  savedTxt: { fontSize: 10.5, fontWeight: "700", color: "#059669" },
  defaultTxt: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 4 },
});
