/**
 * Iter 566 — Employee Self-Service Form 16.
 * Logged-in employees see and download ONLY their own Form 16 PDFs.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Platform, Pressable, ScrollView, StyleSheet, Text, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type F16 = {
  record_id: string; fy: string; version?: number; generated_at?: string;
  traces_locked?: boolean; gross?: number; tds?: number;
};

export default function MyForm16Screen() {
  const router = useRouter();
  const [forms, setForms] = useState<F16[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setErr("");
    try {
      const r = await api<{ forms: F16[] }>("/employee/form16/list");
      setForms(r.forms || []);
    } catch (x: any) { setErr(x?.message || "Failed to load"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const download = async (f: F16) => {
    try {
      const r = await apiBinary(`/employee/form16/${f.record_id}.pdf`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl;
        a.download = `Form16_${f.fy}.pdf`;
        a.click();
      }
    } catch (x: any) { setErr(x?.message || "Download failed"); }
  };

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8}>
          <Ionicons name="chevron-back" size={24} color={colors.onSurface} />
        </Pressable>
        <Text style={st.h1}>My Form 16</Text>
        <Pressable onPress={load} hitSlop={8}>
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>
      {err ? <Text style={st.err}>{err}</Text> : null}
      <ScrollView contentContainerStyle={{ padding: 12, paddingBottom: 60 }}>
        {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} /> :
          forms.length === 0 ? (
            <View style={st.emptyBox}>
              <Ionicons name="document-text-outline" size={40} color={colors.onSurfaceTertiary} />
              <Text style={st.empty}>No Form 16 issued yet. Please contact HR once the financial year&apos;s TDS is finalized.</Text>
            </View>
          ) : forms.map((f) => (
            <View key={f.record_id} style={st.card} testID={`myf16-${f.fy}`}>
              <View style={{ flex: 1 }}>
                <Text style={st.fy}>FY {f.fy} {f.traces_locked ? "· TRACES ✓" : ""}</Text>
                <Text style={st.meta}>
                  Gross ₹{(f.gross || 0).toLocaleString()} · TDS ₹{(f.tds || 0).toLocaleString()}
                  {f.version ? ` · v${f.version}` : ""}
                </Text>
                <Text style={st.meta}>Issued {String(f.generated_at || "").slice(0, 10)}</Text>
              </View>
              <Pressable onPress={() => download(f)} style={st.dlBtn} testID={`myf16-dl-${f.fy}`}>
                <Ionicons name="download-outline" size={16} color="#fff" />
                <Text style={st.dlTxt}>PDF</Text>
              </Pressable>
            </View>
          ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 14, paddingVertical: 10, backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  h1: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  err: { color: "#DC2626", fontSize: 12, paddingHorizontal: 14, paddingTop: 8 },
  card: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.divider, padding: 14, marginBottom: 10,
  },
  fy: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  meta: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 2 },
  dlBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 14,
    paddingVertical: 9, borderRadius: radius.md,
  },
  dlTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  emptyBox: { alignItems: "center", gap: 10, marginTop: 60, paddingHorizontal: 30 },
  empty: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center" },
});
