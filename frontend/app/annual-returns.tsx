/**
 * Annual Returns Management (Phase C).
 * Compliance dashboard + statutory returns auto-prepared from FY payroll:
 * Minimum Wages, Payment of Wages, Bonus, Equal Remuneration, Employment
 * Statistics, Social Security, LWF, PT. PDF/Excel per return.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Platform,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import RegisterTable, {
  ExportButtons,
  shared,
} from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

export default function AnnualReturnsScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const fys = useMemo(() => {
    const y =
      new Date().getMonth() >= 3
        ? new Date().getFullYear()
        : new Date().getFullYear() - 1;
    return [0, 1, 2, 3, 4].map((i) => y - i);
  }, []);
  const [fy, setFy] = useState(fys[0]);
  const [kind, setKind] = useState("dashboard");
  const [data, setData] = useState<any>(null);
  const [returns, setReturns] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const companyId =
    user?.role === "company_admin" ? user.company_id : selectedCompanyId;

  useEffect(() => {
    api<any>("/admin/annual-returns/list")
      .then((r) => setReturns(r.returns || []))
      .catch(() => {});
  }, []);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<any>(
        `/admin/annual-returns/${kind}?company_id=${companyId}&fy_start_year=${fy}`,
      );
      setData(r);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, kind, fy]);

  useEffect(() => {
    void load();
  }, [load]);

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="ar-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>Annual Returns</Text>
        {kind !== "dashboard" && companyId ? (
          <ExportButtons
            basePath={`/admin/annual-returns/${kind}?company_id=${companyId}&fy_start_year=${fy}`}
            fileBase={`${kind}_FY${fy}`}
          />
        ) : (
          <View style={{ width: 40 }} />
        )}
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        <View style={shared.row}>
          {Platform.OS === "web" && (
            <select
              data-testid="ar-fy"
              value={fy}
              onChange={(e) =>
                setFy(Number((e.target as HTMLSelectElement).value))
              }
              style={{
                padding: 8,
                borderRadius: 8,
                borderColor: "#CBD5E1",
                borderWidth: 1,
                fontSize: 13,
              } as any}
            >
              {fys.map((y) => (
                <option key={y} value={y}>
                  FY {y}-{String(y + 1).slice(-2)}
                </option>
              ))}
            </select>
          )}
        </View>
        <View style={[shared.tabs, { marginTop: 8 }]}>
          <Pressable
            onPress={() => setKind("dashboard")}
            style={[shared.tab, kind === "dashboard" && shared.tabActive]}
            testID="ar-tab-dashboard"
          >
            <Text
              style={[
                shared.tabTxt,
                kind === "dashboard" && shared.tabTxtActive,
              ]}
            >
              Compliance Dashboard
            </Text>
          </Pressable>
          {returns.map((r) => (
            <Pressable
              key={r.kind}
              onPress={() => setKind(r.kind)}
              style={[shared.tab, kind === r.kind && shared.tabActive]}
              testID={`ar-tab-${r.kind}`}
            >
              <Text
                style={[shared.tabTxt, kind === r.kind && shared.tabTxtActive]}
              >
                {r.title.replace(" Annual Return", "").replace(" Return", "")}
              </Text>
            </Pressable>
          ))}
        </View>

        {loading && <ActivityIndicator style={{ marginVertical: 24 }} />}

        {!loading && kind === "dashboard" && data && (
          <>
            <View style={st.scoreRow}>
              <View style={st.scoreCard}>
                <Text style={st.scoreVal}>{data.compliance_pct}%</Text>
                <Text style={st.scoreLbl}>FY Data Readiness</Text>
              </View>
              <View style={st.scoreCard}>
                <Text style={st.scoreVal}>{data.months_ready}/12</Text>
                <Text style={st.scoreLbl}>Months with Salary Runs</Text>
              </View>
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>⚠ Auto-Validation Before Filing</Text>
              {(data.validations || []).map((v: string, i: number) => (
                <Text key={i} style={st.valLine}>
                  • {v}
                </Text>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Returns Status</Text>
              {(data.returns || []).map((r: any) => (
                <Pressable
                  key={r.kind}
                  style={st.retRow}
                  onPress={() => setKind(r.kind)}
                >
                  <Text style={st.retTitle}>{r.title}</Text>
                  <Text
                    style={[
                      st.retStatus,
                      r.status !== "READY" && { color: "#B91C1C" },
                    ]}
                  >
                    {r.status} · due {r.due}
                  </Text>
                </Pressable>
              ))}
            </View>
          </>
        )}

        {!loading && kind !== "dashboard" && data && (
          <View style={shared.card}>
            <Text style={shared.cardTitle}>
              {data.title} — FY {data.fy_start_year}-
              {String((data.fy_start_year || 0) + 1).slice(-2)}
            </Text>
            <RegisterTable
              columns={data.columns}
              rows={data.rows}
              totals={data.totals}
            />
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  scoreRow: { flexDirection: "row", gap: 10, marginBottom: 12, marginTop: 8 },
  scoreCard: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 14,
    alignItems: "center",
  },
  scoreVal: { fontSize: 22, fontWeight: "800", color: colors.brandPrimary },
  scoreLbl: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 3 },
  valLine: { fontSize: 12.5, color: "#B45309", marginBottom: 4 },
  retRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 8,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border,
  },
  retTitle: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  retStatus: { fontSize: 11.5, color: "#15803D", fontWeight: "700" },
});
