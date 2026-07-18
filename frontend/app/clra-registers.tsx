/**
 * CLRA Registers — Contract Labour (R&A) Central Rules, 1971.
 * Downloads Form XII (Register of Contractors), Form XIII (Register of
 * Workmen), Form XIV (Employment Cards) and Form XV (Wage Register).
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
import { colors, radius } from "@/src/theme";

const FORMS: {
  key: string;
  file: string;
  title: string;
  desc: string;
  icon: any;
  needsMonth?: boolean;
}[] = [
  { key: "xii", file: "form-xii", title: "Form XII — Register of Contractors",
    desc: "Rule 74 · maintained by the principal employer.", icon: "people-outline" },
  { key: "xiii", file: "form-xiii", title: "Form XIII — Register of Workmen",
    desc: "Rule 75 · workmen employed by each contractor.", icon: "list-outline" },
  { key: "xiv", file: "form-xiv", title: "Form XIV — Employment Cards",
    desc: "Rule 76 · one card per workman.", icon: "id-card-outline" },
  { key: "xv", file: "form-xv", title: "Form XV — Register of Wages",
    desc: "Rule 78 · per wage period (pick a month).", icon: "cash-outline", needsMonth: true },
];

export default function ClraRegistersScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [month, setMonth] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const download = useCallback(
    async (form: (typeof FORMS)[number]) => {
      setError(null);
      if (!selectedCompanyId) {
        setError("Select a firm from the top bar first.");
        return;
      }
      if (form.needsMonth && !month) {
        setError("Pick a wage month for Form XV.");
        return;
      }
      setBusy(form.key);
      try {
        const q =
          `?company_id=${encodeURIComponent(selectedCompanyId)}` +
          (form.needsMonth ? `&month=${encodeURIComponent(month)}` : "");
        const { webBlobUrl } = await apiBinary(
          `/admin/clra-registers/${form.file}.pdf${q}`,
        );
        if (Platform.OS === "web" && webBlobUrl) {
          const a = document.createElement("a");
          a.href = webBlobUrl;
          a.download = `CLRA_${form.file}.pdf`;
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

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <Text style={st.title}>CLRA Registers</Text>
        <Text style={st.subtitle}>
          Contract Labour (Regulation &amp; Abolition) Central Rules, 1971. Workmen
          are grouped by contractor from the Employee Master.
        </Text>

        <View style={st.monthCard}>
          <Text style={st.monthLbl}>Wage month (for Form XV)</Text>
          <MonthPicker value={month} onChange={setMonth} allowEmpty emptyLabel="Pick month" />
        </View>

        {error ? (
          <View style={st.errorBox}>
            <Ionicons name="alert-circle" size={16} color="#DC2626" />
            <Text style={st.errorTxt}>{error}</Text>
          </View>
        ) : null}

        {FORMS.map((f) => (
          <View key={f.key} style={st.card}>
            <View style={st.iconWrap}>
              <Ionicons name={f.icon} size={22} color={colors.brandPrimary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={st.cardTitle}>{f.title}</Text>
              <Text style={st.cardDesc}>{f.desc}</Text>
            </View>
            <Pressable
              style={[st.dlBtn, busy === f.key && st.disabled]}
              onPress={() => download(f)}
              disabled={busy !== null}
              testID={`clra-dl-${f.key}`}
            >
              {busy === f.key ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Ionicons name="download-outline" size={16} color="#fff" />
              )}
              <Text style={st.dlBtnTxt}>PDF</Text>
            </Pressable>
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  wrap: { padding: 20, gap: 12, maxWidth: 760, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 13, color: colors.textSecondary, lineHeight: 19 },
  monthCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 14, gap: 8,
    zIndex: 10,
  },
  monthLbl: { fontSize: 12, fontWeight: "800", color: colors.textSecondary },
  errorBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FEE2E2", borderRadius: 10, padding: 12,
  },
  errorTxt: { color: "#991B1B", fontSize: 13, flex: 1 },
  card: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 14,
  },
  iconWrap: {
    width: 44, height: 44, borderRadius: 12, alignItems: "center",
    justifyContent: "center", backgroundColor: colors.brandPrimary + "16",
  },
  cardTitle: { fontSize: 14.5, fontWeight: "800", color: colors.textPrimary },
  cardDesc: { fontSize: 12, color: colors.textSecondary, marginTop: 2 },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 8,
    paddingVertical: 10, paddingHorizontal: 14, minHeight: 42,
  },
  disabled: { opacity: 0.7 },
  dlBtnTxt: { color: "#fff", fontSize: 13.5, fontWeight: "800" },
});
