/**
 * Iter 294 — BI & Data Feed (Power BI / Excel live connection).
 *
 * Per-firm secret feed key + dataset URLs. Paste a URL into Power BI's
 * Web connector or Excel → Get Data → From Web for auto-refreshing
 * dashboards fed by live portal data.
 */
import React, { useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api, getApiBaseUrl } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { radius, spacing } from "@/src/theme";

const DATASETS = [
  { key: "employees", label: "Employees", desc: "Employee master (code, name, designation, department, group, DOJ, status)", monthly: false },
  { key: "attendance", label: "Attendance", desc: "Day-wise IN/OUT times and work hours", monthly: true },
  { key: "salary", label: "Actual Salary", desc: "Latest actual salary run rows (gross, net, OT)", monthly: true },
  { key: "compliance", label: "Compliance Salary", desc: "PF / ESI / net from the compliance run", monthly: true },
];

export default function BiFeedScreen() {
  const { selectedCompanyId } = useSelectedCompany();
  const [info, setInfo] = useState<{ key: string | null; firm_name?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);
  const base = useMemo(() => getApiBaseUrl(), []);
  const thisMonth = useMemo(() => {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }, []);

  const load = async () => {
    if (!selectedCompanyId) return;
    try {
      const r = await api<{ key: string | null; firm_name: string }>(
        `/admin/bi-feed/info?company_id=${encodeURIComponent(selectedCompanyId)}`);
      setInfo(r);
    } catch { setInfo(null); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [selectedCompanyId]);

  const rotate = async () => {
    if (!selectedCompanyId) return;
    setBusy(true);
    try {
      await api("/admin/bi-feed/rotate-key", { method: "POST", body: { company_id: selectedCompanyId } });
      await load();
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Failed");
    } finally { setBusy(false); }
  };

  const urlFor = (ds: { key: string; monthly: boolean }) =>
    `${base}/api/bi-feed/${ds.key}?key=${info?.key || "YOUR_KEY"}${ds.monthly ? `&month=${thisMonth}` : ""}`;

  const copy = (txt: string, tag: string) => {
    if (Platform.OS === "web" && navigator?.clipboard) {
      navigator.clipboard.writeText(txt);
      setCopied(tag);
      setTimeout(() => setCopied(null), 1500);
    }
  };

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "BI & Data Feed", headerShown: false }} />
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>📊 BI &amp; Data Feed — Power BI / Excel</Text>
        <Text style={styles.sub}>
          Connect Power BI or Excel directly to live portal data
          {info?.firm_name ? ` for ${info.firm_name}` : ""}. Dashboards refresh automatically.
        </Text>

        {/* Key management */}
        <View style={styles.keyCard}>
          <View style={{ flex: 1, minWidth: 220 }}>
            <Text style={styles.lbl}>FEED SECRET KEY</Text>
            {info?.key ? (
              <Pressable onPress={() => copy(info.key!, "key")} testID="bif-copy-key">
                <Text style={styles.keyTxt} numberOfLines={1}>{info.key}</Text>
                <Text style={styles.copyHint}>{copied === "key" ? "✓ Copied!" : "Tap to copy"}</Text>
              </Pressable>
            ) : (
              <Text style={styles.noKey}>No key generated yet — press Generate to enable the feed.</Text>
            )}
          </View>
          <Pressable onPress={rotate} disabled={busy || !selectedCompanyId}
            style={[styles.rotBtn, (busy || !selectedCompanyId) && { opacity: 0.5 }]}
            testID="bif-rotate">
            {busy ? <ActivityIndicator size="small" color="#fff" />
              : <Ionicons name={info?.key ? "refresh" : "key-outline"} size={15} color="#fff" />}
            <Text style={styles.rotBtnTxt}>{info?.key ? "Rotate Key" : "Generate Key"}</Text>
          </Pressable>
        </View>
        {!selectedCompanyId ? (
          <Text style={styles.err}>Select a firm from the top bar first.</Text>
        ) : null}
        {info?.key ? (
          <Text style={styles.warn}>
            🔐 Anyone with a feed URL can read this firm&apos;s data — treat it like a password.
            Rotating the key invalidates all old URLs.
          </Text>
        ) : null}

        {/* Dataset URLs */}
        <Text style={[styles.lbl, { marginTop: 18 }]}>DATASET FEED URLS</Text>
        {DATASETS.map((ds) => (
          <View key={ds.key} style={styles.dsCard}>
            <View style={{ flex: 1 }}>
              <Text style={styles.dsName}>{ds.label}{ds.monthly ? "  ·  &month=YYYY-MM" : ""}</Text>
              <Text style={styles.dsDesc}>{ds.desc}</Text>
              <Text style={styles.dsUrl} numberOfLines={1}>{urlFor(ds)}</Text>
            </View>
            <Pressable onPress={() => copy(urlFor(ds), ds.key)} style={styles.copyBtn}
              testID={`bif-copy-${ds.key}`}>
              <Ionicons name={copied === ds.key ? "checkmark" : "copy-outline"} size={14}
                color={copied === ds.key ? "#22C55E" : "#2563EB"} />
              <Text style={styles.copyBtnTxt}>{copied === ds.key ? "Copied" : "Copy URL"}</Text>
            </Pressable>
          </View>
        ))}

        {/* Instructions */}
        <View style={styles.howRow}>
          <View style={styles.howCard}>
            <Text style={styles.howTitle}>📈 Connect from Power BI</Text>
            {["Open Power BI Desktop → Get Data → Web",
              "Paste a dataset URL above → OK",
              "In the navigator, expand Record → rows → To Table",
              "Expand the column into fields → Close & Apply",
              "Set Scheduled Refresh in Power BI Service for auto-updates"].map((s, i) => (
              <Text key={i} style={styles.howStep}>{i + 1}. {s}</Text>
            ))}
          </View>
          <View style={styles.howCard}>
            <Text style={styles.howTitle}>📗 Connect from Excel</Text>
            {["Excel → Data tab → Get Data → From Other Sources → From Web",
              "Paste a dataset URL above → OK",
              "Power Query opens: Record → rows → To Table → expand column",
              "Close & Load — data lands in your sheet",
              "Right-click the table → Refresh anytime for live data"].map((s, i) => (
              <Text key={i} style={styles.howStep}>{i + 1}. {s}</Text>
            ))}
          </View>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F8FAFC" },
  scroll: { padding: spacing.lg, paddingBottom: 60 },
  title: { fontSize: 20, fontWeight: "800", color: "#1F2937" },
  sub: { fontSize: 12.5, color: "#64748B", marginTop: 4, marginBottom: 14, maxWidth: 720 },
  lbl: { fontSize: 11, fontWeight: "800", color: "#64748B", letterSpacing: 0.4, marginBottom: 8 },
  keyCard: {
    flexDirection: "row", alignItems: "center", gap: 14, flexWrap: "wrap",
    backgroundColor: "#0F172A", borderRadius: radius.md, padding: 16,
  },
  keyTxt: { color: "#93C5FD", fontSize: 13, fontWeight: "700", fontFamily: Platform.OS === "web" ? "monospace" : undefined },
  copyHint: { color: "#64748B", fontSize: 10, marginTop: 3 },
  noKey: { color: "#94A3B8", fontSize: 12 },
  rotBtn: {
    flexDirection: "row", alignItems: "center", gap: 7, backgroundColor: "#2563EB",
    borderRadius: 10, paddingHorizontal: 16, paddingVertical: 10,
  },
  rotBtnTxt: { color: "#fff", fontSize: 12.5, fontWeight: "800" },
  err: { color: "#EF4444", fontSize: 12, marginTop: 8, fontWeight: "600" },
  warn: { color: "#B45309", fontSize: 11.5, marginTop: 8 },
  dsCard: {
    flexDirection: "row", alignItems: "center", gap: 12, backgroundColor: "#FFFFFF",
    borderWidth: 1, borderColor: "#E2E8F0", borderRadius: radius.md,
    padding: 12, marginBottom: 8,
  },
  dsName: { fontSize: 13, fontWeight: "800", color: "#1F2937" },
  dsDesc: { fontSize: 11, color: "#64748B", marginTop: 2 },
  dsUrl: { fontSize: 10.5, color: "#2563EB", marginTop: 5 },
  copyBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1,
    borderColor: "#BFDBFE", backgroundColor: "#EFF6FF", borderRadius: 8,
    paddingHorizontal: 10, paddingVertical: 7,
  },
  copyBtnTxt: { fontSize: 11, fontWeight: "700", color: "#2563EB" },
  howRow: { flexDirection: "row", gap: 12, flexWrap: "wrap", marginTop: 16 },
  howCard: {
    flex: 1, minWidth: 280, backgroundColor: "#FFFFFF", borderWidth: 1,
    borderColor: "#E2E8F0", borderRadius: radius.md, padding: 14,
  },
  howTitle: { fontSize: 13.5, fontWeight: "800", color: "#1F2937", marginBottom: 8 },
  howStep: { fontSize: 12, color: "#334155", marginBottom: 5, lineHeight: 17 },
});
