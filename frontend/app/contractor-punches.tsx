// Iter 175 — Contractor Punch approvals (daily, contractor-wise).
// Contractual employees' punches are PENDING until the company approves or
// rejects them here. The approver can also re-assign the contractor for an
// individual day. Approved punches then flow into the normal attendance
// policy computation.
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  ScrollView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Row = {
  user_id: string;
  name?: string;
  employee_code?: string;
  contractor_name?: string;
  in_hhmm?: string | null;
  out_hhmm?: string | null;
  punch_count: number;
  status: "pending" | "approved" | "rejected" | "mixed";
};
type Group = { contractor: string; rows: Row[] };
type Report = {
  date: string;
  contractors: string[];
  contractual_employees: number;
  groups: Group[];
  summary: { pending: number; approved: number; rejected: number };
};

const STATUS_UI: Record<string, { label: string; bg: string; fg: string }> = {
  pending: { label: "PENDING", bg: "#FFFBEB", fg: "#B45309" },
  approved: { label: "APPROVED", bg: "#F0FDF4", fg: "#16A34A" },
  rejected: { label: "REJECTED", bg: "#FEF2F2", fg: "#B91C1C" },
  mixed: { label: "MIXED", bg: "#EFF6FF", fg: "#1D4ED8" },
};

export default function ContractorPunchesScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const canAct =
    user?.role === "super_admin" || user?.role === "company_admin" || user?.role === "sub_admin";

  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busyRow, setBusyRow] = useState<string | null>(null);
  const [pickFor, setPickFor] = useState<string | null>(null); // user_id with contractor picker open

  const load = useCallback(async () => {
    if (!selectedCompanyId) { setReport(null); return; }
    setLoading(true);
    setError(null);
    try {
      const r = await api<Report>(
        `/admin/contractor-punches?company_id=${encodeURIComponent(selectedCompanyId)}&date=${date}`,
      );
      setReport(r);
    } catch (e: any) {
      setError(e?.message || "Failed to load");
    } finally { setLoading(false); }
  }, [selectedCompanyId, date]);

  useEffect(() => { load(); }, [load]);

  const decide = async (row: Row, action: "approve" | "reject" | null, contractor?: string) => {
    if (!selectedCompanyId) return;
    setBusyRow(row.user_id);
    try {
      await api("/admin/contractor-punches/decide", {
        method: "POST",
        body: {
          company_id: selectedCompanyId,
          user_id: row.user_id,
          date,
          ...(action ? { action } : {}),
          ...(contractor ? { contractor_name: contractor } : {}),
        },
      });
      setPickFor(null);
      await load();
    } catch (e: any) {
      const msg = e?.message || "Failed";
      if (Platform.OS === "web") globalThis.alert(msg);
    } finally { setBusyRow(null); }
  };

  if (!canAct) {
    return (
      <View style={st.root}>
        <View style={st.center}><Text style={st.dim}>Admins only.</Text></View>
      </View>
    );
  }

  return (
    <View style={st.root} testID="contractor-punches-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={st.head}>
          <Pressable onPress={() => router.back()} hitSlop={10}>
            <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={st.title}>Contractor Punches</Text>
            <Text style={st.sub}>
              Daily approval of contractual employees&apos; punches — contractor-wise.
              Approved punches count in attendance as per the firm&apos;s policy.
            </Text>
          </View>
        </View>
        <View style={st.bar}>
          <DateField value={date} onChangeISO={setDate} label="Date" compact testID="cp-date" />
          <Pressable onPress={load} style={st.showBtn} testID="cp-refresh">
            <Ionicons name="refresh-outline" size={14} color="#fff" />
            <Text style={st.showTxt}>Refresh</Text>
          </Pressable>
          {report ? (
            <View style={{ flexDirection: "row", gap: 6 }}>
              <Text style={[st.sumChip, { backgroundColor: "#FFFBEB", color: "#B45309" }]}>
                Pending {report.summary.pending}
              </Text>
              <Text style={[st.sumChip, { backgroundColor: "#F0FDF4", color: "#16A34A" }]}>
                Approved {report.summary.approved}
              </Text>
              <Text style={[st.sumChip, { backgroundColor: "#FEF2F2", color: "#B91C1C" }]}>
                Rejected {report.summary.rejected}
              </Text>
            </View>
          ) : null}
        </View>
      </SafeAreaView>

      {!selectedCompanyId ? (
        <View style={st.center}><Text style={st.dim}>Select a firm first (top of screen).</Text></View>
      ) : loading ? (
        <View style={st.center}><ActivityIndicator color={colors.brandPrimary} /></View>
      ) : error ? (
        <View style={st.center}><Text style={[st.dim, { color: colors.error }]}>{error}</Text></View>
      ) : !report || report.contractual_employees === 0 ? (
        <View style={st.center}>
          <Ionicons name="briefcase-outline" size={38} color={colors.onSurfaceTertiary} />
          <Text style={st.dim}>
            No contractual employees in this firm. Mark employees as Contractual in
            Employee Master (needs Contractor Employees enabled in Firm Master → Policy 2).
          </Text>
        </View>
      ) : report.groups.length === 0 ? (
        <View style={st.center}>
          <Ionicons name="calendar-outline" size={38} color={colors.onSurfaceTertiary} />
          <Text style={st.dim}>No punches from contractual employees on this date.</Text>
        </View>
      ) : (
        <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 60 }}>
          {report.groups.map((g) => (
            <View key={g.contractor} style={st.card}>
              <View style={st.gHead}>
                <Ionicons name="briefcase" size={15} color={colors.brandPrimary} />
                <Text style={st.gTitle}>{g.contractor}</Text>
                <Text style={st.gCount}>{g.rows.length} employee{g.rows.length === 1 ? "" : "s"}</Text>
              </View>
              <View style={st.tHead}>
                <Text style={[st.tCell, st.tHeadTxt, { flex: 1.6 }]}>Employee</Text>
                <Text style={[st.tCell, st.tHeadTxt, { width: 52 }]}>In</Text>
                <Text style={[st.tCell, st.tHeadTxt, { width: 52 }]}>Out</Text>
                <Text style={[st.tCell, st.tHeadTxt, { width: 78 }]}>Status</Text>
                <Text style={[st.tCell, st.tHeadTxt, { flex: 1.5 }]}>Contractor (this day)</Text>
                <Text style={[st.tCell, st.tHeadTxt, { width: 150 }]}>Action</Text>
              </View>
              {g.rows.map((r) => {
                const sui = STATUS_UI[r.status] || STATUS_UI.pending;
                const busy = busyRow === r.user_id;
                return (
                  <View key={r.user_id}>
                    <View style={st.tRow}>
                      <Text style={[st.tCell, { flex: 1.6, fontWeight: "700" }]} numberOfLines={1}>
                        {r.name}{r.employee_code ? ` (#${r.employee_code})` : ""}
                      </Text>
                      <Text style={[st.tCell, { width: 52 }]}>{r.in_hhmm || "—"}</Text>
                      <Text style={[st.tCell, { width: 52 }]}>{r.out_hhmm || "—"}</Text>
                      <View style={{ width: 78 }}>
                        <Text style={[st.statusChip, { backgroundColor: sui.bg, color: sui.fg }]}>
                          {sui.label}
                        </Text>
                      </View>
                      <Pressable
                        style={[st.tCell, { flex: 1.5, flexDirection: "row", alignItems: "center", gap: 4 }]}
                        onPress={() => setPickFor(pickFor === r.user_id ? null : r.user_id)}
                        testID={`cp-contractor-${r.user_id}`}
                      >
                        <Text style={{ fontSize: 12, color: colors.brandPrimary, fontWeight: "700" }} numberOfLines={1}>
                          {r.contractor_name || "Unassigned"}
                        </Text>
                        <Ionicons name="chevron-down" size={12} color={colors.brandPrimary} />
                      </Pressable>
                      <View style={{ width: 150, flexDirection: "row", gap: 6 }}>
                        {busy ? (
                          <ActivityIndicator size="small" color={colors.brandPrimary} />
                        ) : (
                          <>
                            <Pressable
                              onPress={() => decide(r, "approve")}
                              style={[st.actBtn, { backgroundColor: "#16A34A" }]}
                              testID={`cp-approve-${r.user_id}`}
                            >
                              <Text style={st.actTxt}>Approve</Text>
                            </Pressable>
                            <Pressable
                              onPress={() => decide(r, "reject")}
                              style={[st.actBtn, { backgroundColor: "#B91C1C" }]}
                              testID={`cp-reject-${r.user_id}`}
                            >
                              <Text style={st.actTxt}>Reject</Text>
                            </Pressable>
                          </>
                        )}
                      </View>
                    </View>
                    {pickFor === r.user_id ? (
                      <View style={st.pickBox}>
                        <Text style={st.pickTitle}>Change contractor for {date.split("-").reverse().join("-")}:</Text>
                        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                          {(report.contractors.length ? report.contractors : ["Unassigned"]).map((c) => (
                            <Pressable
                              key={c}
                              onPress={() => decide(r, null, c)}
                              style={[st.pickChip, r.contractor_name === c && st.pickChipOn]}
                              testID={`cp-pick-${r.user_id}-${c}`}
                            >
                              <Text style={[st.pickChipTxt, r.contractor_name === c && { color: "#fff" }]}>{c}</Text>
                            </Pressable>
                          ))}
                        </View>
                      </View>
                    ) : null}
                  </View>
                );
              })}
            </View>
          ))}
        </ScrollView>
      )}
    </View>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  head: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.md, paddingVertical: 10,
  },
  title: { ...type.h3, color: colors.onSurface },
  sub: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  bar: {
    flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap",
    paddingHorizontal: spacing.md, paddingBottom: 10,
  },
  showBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 8,
  },
  showTxt: { color: "#fff", fontSize: 12, fontWeight: "700" },
  sumChip: {
    fontSize: 11, fontWeight: "800", borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5, overflow: "hidden",
  },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 30, gap: 8 },
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary, textAlign: "center", maxWidth: 420 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: 12, marginBottom: spacing.md, borderWidth: 1, borderColor: colors.divider,
  },
  gHead: { flexDirection: "row", alignItems: "center", gap: 6, marginBottom: 8 },
  gTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, flex: 1 },
  gCount: { fontSize: 11, color: colors.onSurfaceTertiary },
  tHead: {
    flexDirection: "row", alignItems: "center", paddingVertical: 5,
    borderBottomWidth: 1, borderBottomColor: colors.divider, gap: 6,
  },
  tHeadTxt: { fontWeight: "800", fontSize: 10.5, color: colors.onSurfaceSecondary },
  tRow: {
    flexDirection: "row", alignItems: "center", paddingVertical: 7,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider, gap: 6,
  },
  tCell: { fontSize: 12, color: colors.onSurface },
  statusChip: {
    fontSize: 9.5, fontWeight: "800", borderRadius: 6,
    paddingHorizontal: 6, paddingVertical: 3, overflow: "hidden", textAlign: "center",
  },
  actBtn: { borderRadius: radius.sm, paddingHorizontal: 10, paddingVertical: 6 },
  actTxt: { color: "#fff", fontSize: 11, fontWeight: "800" },
  pickBox: {
    backgroundColor: colors.background, borderRadius: radius.md,
    padding: 10, marginVertical: 6,
  },
  pickTitle: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 6 },
  pickChip: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 6,
  },
  pickChipOn: { backgroundColor: colors.brandPrimary },
  pickChipTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
});
