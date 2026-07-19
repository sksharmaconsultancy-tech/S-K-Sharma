/**
 * Statutory & Management Reports — Iter 202.
 *
 * PT (state-wise), LWF (state-wise), Gratuity, Full & Final, Advance/Loan
 * register and Management MIS — each downloadable as Excel or PDF.
 */
import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Platform,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { apiBinary } from "@/src/api/client";
import MonthPicker from "@/src/components/MonthPicker";
import { colors } from "@/src/theme";

const REPORTS: {
  key: string;
  path: string;
  title: string;
  desc: string;
  icon: any;
  needsMonth?: boolean;
  monthOptional?: boolean;
  firmOptional?: boolean;
}[] = [
  {
    key: "pt", path: "pt", title: "Professional Tax (PT)", needsMonth: true,
    desc: "State-wise PT slabs applied to each employee's monthly gross.",
    icon: "receipt-outline",
  },
  {
    key: "lwf", path: "lwf", title: "Labour Welfare Fund (LWF)", needsMonth: true,
    desc: "State-wise EE/ER contributions with due-month handling.",
    icon: "heart-outline",
  },
  {
    key: "gratuity", path: "gratuity", title: "Gratuity Report",
    desc: "15/26 × last Basic × completed years — eligibility & accrual per employee.",
    icon: "medal-outline",
  },
  {
    key: "fnf", path: "fnf", title: "Full & Final (F&F)", monthOptional: true,
    desc: "Settlement sheet for exited employees: earned salary + gratuity − advances.",
    icon: "briefcase-outline",
  },
  {
    key: "advance", path: "advance-loan", title: "Advance / Loan Register",
    desc: "All advances with EMI, recovered amount and outstanding balance.",
    icon: "wallet-outline",
  },
  {
    key: "mis", path: "mis", title: "Management MIS", needsMonth: true, firmOptional: true,
    desc: "Per-firm headcount, joins/exits, man-days, payroll & statutory summary.",
    icon: "stats-chart-outline",
  },
];

export default function StatutoryReportsScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const [month, setMonth] = useState<string>(() => new Date().toISOString().slice(0, 7));
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const download = useCallback(
    async (rep: (typeof REPORTS)[number], fmt: "xlsx" | "pdf") => {
      setError(null);
      if (!selectedCompanyId && !rep.firmOptional) {
        setError("Select a firm from the top bar first.");
        return;
      }
      if (rep.needsMonth && !month) {
        setError("Pick a month first.");
        return;
      }
      setBusy(`${rep.key}:${fmt}`);
      try {
        const params: string[] = [`fmt=${fmt}`];
        if (selectedCompanyId) params.push(`company_id=${encodeURIComponent(selectedCompanyId)}`);
        if ((rep.needsMonth || rep.monthOptional) && month) params.push(`month=${encodeURIComponent(month)}`);
        const { webBlobUrl } = await apiBinary(`/admin/reports/${rep.path}?${params.join("&")}`);
        if (Platform.OS === "web" && webBlobUrl) {
          const a = document.createElement("a");
          a.href = webBlobUrl;
          a.download = `${rep.title.replace(/[^A-Za-z0-9]+/g, "_")}_${month || "all"}.${fmt}`;
          a.click();
          setTimeout(() => URL.revokeObjectURL(webBlobUrl), 30000);
        }
      } catch (e: any) {
        setError(e?.message || "Download failed.");
      } finally {
        setBusy(null);
      }
    },
    [selectedCompanyId, month],
  );

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  const firmName = companies.find((c: any) => c.company_id === selectedCompanyId)?.name;

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <Text style={st.title}>Statutory & Management Reports</Text>
        <Text style={st.subtitle}>
          PT · LWF · Gratuity · Full &amp; Final · Advance/Loan · MIS — Excel or PDF.
          Firm: <Text style={{ fontWeight: "700" }}>{firmName || "— select from top bar —"}</Text>
        </Text>

        <View style={st.monthCard}>
          <Text style={st.monthLbl}>Report month</Text>
          <MonthPicker value={month} onChange={setMonth} />
        </View>

        {error ? (
          <View style={st.errorBox}>
            <Ionicons name="alert-circle" size={16} color="#DC2626" />
            <Text style={st.errorTxt}>{error}</Text>
          </View>
        ) : null}

        {REPORTS.map((r) => (
          <View key={r.key} style={st.card}>
            <View style={st.iconWrap}>
              <Ionicons name={r.icon} size={22} color={colors.brandPrimary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={st.cardTitle}>{r.title}</Text>
              <Text style={st.cardDesc}>{r.desc}</Text>
            </View>
            <View style={st.btnCol}>
              {(["xlsx", "pdf"] as const).map((fmt) => (
                <Pressable
                  key={fmt}
                  style={[st.dlBtn, fmt === "pdf" && st.dlBtnPdf]}
                  onPress={() => download(r, fmt)}
                  disabled={busy !== null}
                >
                  {busy === `${r.key}:${fmt}` ? (
                    <ActivityIndicator size="small" color={fmt === "pdf" ? "#DC2626" : colors.brandPrimary} />
                  ) : (
                    <>
                      <Ionicons
                        name={fmt === "pdf" ? "document-outline" : "grid-outline"}
                        size={14}
                        color={fmt === "pdf" ? "#DC2626" : colors.brandPrimary}
                      />
                      <Text style={[st.dlTxt, fmt === "pdf" && { color: "#DC2626" }]}>
                        {fmt === "pdf" ? "PDF" : "Excel"}
                      </Text>
                    </>
                  )}
                </Pressable>
              ))}
            </View>
          </View>
        ))}

        <Text style={st.footNote}>
          PT &amp; LWF slabs follow commonly-published state notifications — verify
          with the latest notification before filing. The firm&apos;s state comes from
          the Firm Master address.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F6F8FA" },
  wrap: { padding: 16, paddingBottom: 48, maxWidth: 900, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: "#0F172A" },
  subtitle: { fontSize: 13, color: "#64748B", marginTop: 4, marginBottom: 12 },
  monthCard: {
    backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 12,
    borderWidth: 1, borderColor: "#E2E8F0", flexDirection: "row",
    alignItems: "center", gap: 12,
  },
  monthLbl: { fontSize: 13, fontWeight: "700", color: "#334155" },
  errorBox: {
    flexDirection: "row", alignItems: "center", gap: 8, padding: 10,
    backgroundColor: "#FEF2F2", borderRadius: 8, borderWidth: 1,
    borderColor: "#FECACA", marginBottom: 12,
  },
  errorTxt: { color: "#991B1B", fontSize: 13, flex: 1 },
  card: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: "#fff", borderRadius: 12, padding: 14, marginBottom: 10,
    borderWidth: 1, borderColor: "#E2E8F0",
  },
  iconWrap: {
    width: 42, height: 42, borderRadius: 10, backgroundColor: "#EFF6FF",
    alignItems: "center", justifyContent: "center",
  },
  cardTitle: { fontSize: 14.5, fontWeight: "700", color: "#0F172A" },
  cardDesc: { fontSize: 12.5, color: "#64748B", marginTop: 2 },
  btnCol: { flexDirection: "row", gap: 8 },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 9, minHeight: 40,
  },
  dlBtnPdf: { borderColor: "#FCA5A5" },
  dlTxt: { fontSize: 12.5, fontWeight: "700", color: colors.brandPrimary },
  footNote: { fontSize: 11.5, color: "#94A3B8", marginTop: 10, fontStyle: "italic" },
});
