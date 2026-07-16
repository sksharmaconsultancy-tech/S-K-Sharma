/**
 * Iter 154 — Day-wise Present Count report (Attendance Report section).
 *
 * For a month (1–31): each day's PRESENT employee count + OT count
 * (employees with a 2nd IN→OUT pair). Tapping a count opens the full
 * employee list for that day (/daily-attendance deep link).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, FlatList, Pressable, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius } from "@/src/theme";

function fmtDay(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return { dd: String(d).padStart(2, "0"), wd: dt.toLocaleDateString("en-IN", { weekday: "short" }) };
}

export default function DailyPresentReport() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;

  const [month, setMonth] = useState(() => new Date().toISOString().slice(0, 7));
  const [companyId, setCompanyId] = useState<string | "all">(
    role === "company_admin" ? (user?.company_id || "all") : (selectedCompanyId || "all"),
  );
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = companyId && companyId !== "all" ? `&company_id=${companyId}` : "";
      setData(await api(`/admin/attendance-report/day-counts?month=${month}${q}`));
    } catch { setData(null); }
    finally { setLoading(false); }
  }, [month, companyId]);
  useEffect(() => { load(); }, [load]);

  const shiftMonth = (delta: number) => {
    const [y, m] = month.split("-").map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  };

  const openDay = (date: string) => {
    router.push({ pathname: "/daily-attendance", params: { date } } as any);
  };

  const monthLabel = (() => {
    const [y, m] = month.split("-").map(Number);
    return new Date(y, m - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  })();

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.back}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>Day-wise Present Count</Text>
        <View style={{ width: 38 }} />
      </View>

      <View style={s.monthRow}>
        <Pressable onPress={() => shiftMonth(-1)} style={s.arrow} testID="dpr-prev">
          <Ionicons name="chevron-back" size={20} color={colors.brandPrimary} />
        </Pressable>
        <Text style={s.monthT}>{monthLabel}</Text>
        <Pressable onPress={() => shiftMonth(1)} style={s.arrow} testID="dpr-next">
          <Ionicons name="chevron-forward" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>

      {role !== "company_admin" && (
        <View style={{ marginHorizontal: 16, marginBottom: 8 }}>
          <CompanyPicker value={companyId} onChange={setCompanyId} label="Firm" compact testID="dpr-firm" />
        </View>
      )}

      {data && (
        <View style={s.totRow}>
          <Text style={s.totT}>
            Month totals — Present man-days: <Text style={{ fontWeight: "800" }}>{data.total_present_mandays}</Text>
            {"   "}· OT man-days: <Text style={{ fontWeight: "800" }}>{data.total_ot_mandays}</Text>
          </Text>
        </View>
      )}

      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
      ) : (
        <FlatList
          data={data?.days || []}
          keyExtractor={(d: any) => d.date}
          contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 40 }}
          ListHeaderComponent={
            <View style={s.hr}>
              <Text style={[s.hc, { width: 76 }]}>Date</Text>
              <Text style={[s.hc, { width: 50 }]}>Day</Text>
              <Text style={[s.hc, s.num, { flex: 1 }]}>Present</Text>
              <Text style={[s.hc, s.num, { flex: 1 }]}>OT</Text>
            </View>
          }
          renderItem={({ item, index }) => {
            const f = fmtDay(item.date);
            const sunday = f.wd === "Sun";
            return (
              <View style={[s.tr, index % 2 === 0 && s.trAlt]}>
                <Text style={[s.cell, { width: 76, fontWeight: "700" }]}>{f.dd}-{month.slice(5)}-{month.slice(0, 4)}</Text>
                <Text style={[s.cell, { width: 50 }, sunday && { color: "#b91c1c", fontWeight: "800" }]}>{f.wd}</Text>
                <Pressable style={{ flex: 1, alignItems: "flex-end" }} disabled={!item.present}
                  onPress={() => openDay(item.date)} testID={`dpr-present-${item.date}`}>
                  <Text style={[s.count, !item.present && s.zero]}>{item.present}</Text>
                </Pressable>
                <Pressable style={{ flex: 1, alignItems: "flex-end" }} disabled={!item.ot_count}
                  onPress={() => openDay(item.date)} testID={`dpr-ot-${item.date}`}>
                  <Text style={[s.count, { color: "#b45309", backgroundColor: "#fef3c7" }, !item.ot_count && s.zero]}>
                    {item.ot_count}
                  </Text>
                </Pressable>
              </View>
            );
          }}
        />
      )}
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10 },
  back: { width: 38, height: 38, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, textAlign: "center", fontSize: 17, fontWeight: "700", color: colors.onSurface },
  monthRow: {
    flexDirection: "row", alignItems: "center", marginHorizontal: 16, marginBottom: 10,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius?.lg ?? 14, paddingVertical: 6,
  },
  arrow: { width: 44, height: 40, alignItems: "center", justifyContent: "center" },
  monthT: { flex: 1, textAlign: "center", fontSize: 15, fontWeight: "800", color: colors.onSurface },
  totRow: { marginHorizontal: 16, marginBottom: 8 },
  totT: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  hr: { flexDirection: "row", borderBottomWidth: 1, borderColor: colors.border, paddingBottom: 6, marginBottom: 2 },
  hc: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary, textTransform: "uppercase" },
  num: { textAlign: "right" },
  tr: { flexDirection: "row", alignItems: "center", paddingVertical: 7, minHeight: 40 },
  trAlt: { backgroundColor: colors.surfaceSecondary },
  cell: { fontSize: 12.5, color: colors.onSurface },
  count: {
    fontSize: 13, fontWeight: "800", color: colors.brandPrimary,
    backgroundColor: "#eef2ff", borderRadius: 8, overflow: "hidden",
    paddingVertical: 4, paddingHorizontal: 12, textAlign: "center", minWidth: 46,
  },
  zero: { color: colors.onSurfaceTertiary, backgroundColor: "transparent", fontWeight: "600" },
});
