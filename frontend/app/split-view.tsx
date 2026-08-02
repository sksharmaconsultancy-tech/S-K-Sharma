/**
 * Iter 294 — Split-Screen Comparison (web only).
 *
 * Two side-by-side panes, each loading any portal screen via an iframe
 * with ?embed=1 (the admin shell hides its sidebar/topbar in embed mode).
 * Perfect for comparing two months' reports or two screens at once.
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, Platform, ScrollView } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

const SCREEN_CHOICES: { route: string; label: string }[] = [
  { route: "/attendance-grid", label: "Attendance Report" },
  { route: "/inout-ot-matrix", label: "In/Out & OT Matrix" },
  { route: "/reports?tab=salary", label: "Actual Salary Report" },
  { route: "/reports?tab=compliance", label: "Compliance Report" },
  { route: "/bank-sheet", label: "Bank Sheet" },
  { route: "/salary-day-sheet", label: "Day-wise Salary Sheet" },
  { route: "/daily-present-report", label: "Day-wise Present Count" },
  { route: "/admin", label: "Employee Master" },
  { route: "/pf-reports?kind=pf", label: "PF Reports" },
  { route: "/pf-reports?kind=esic", label: "ESIC Reports" },
  { route: "/challans", label: "PF / ESIC Upload" },
  { route: "/portal-dashboard", label: "Dashboard" },
];

function Pane({ side, route, onPick }: {
  side: "left" | "right";
  route: string | null;
  onPick: (r: string) => void;
}) {
  const [pickerOpen, setPickerOpen] = useState(!route);
  const origin = Platform.OS === "web" ? window.location.origin : "";
  const src = route
    ? `${origin}${route}${route.includes("?") ? "&" : "?"}embed=1`
    : null;
  return (
    <View style={styles.pane}>
      <View style={styles.paneBar}>
        <Text style={styles.paneBarTxt}>
          {SCREEN_CHOICES.find((s) => s.route === route)?.label || "Pick a screen"}
        </Text>
        <Pressable onPress={() => setPickerOpen((v) => !v)} style={styles.paneBtn}
          testID={`split-pick-${side}`}>
          <Ionicons name="swap-horizontal" size={13} color="#2563EB" />
          <Text style={styles.paneBtnTxt}>Change</Text>
        </Pressable>
      </View>
      {pickerOpen ? (
        <ScrollView style={styles.pickList}>
          {SCREEN_CHOICES.map((s) => (
            <Pressable key={s.route}
              onPress={() => { onPick(s.route); setPickerOpen(false); }}
              style={styles.pickItem} testID={`split-opt-${side}-${s.label.slice(0, 8)}`}>
              <Ionicons name="chevron-forward" size={13} color="#2563EB" />
              <Text style={styles.pickItemTxt}>{s.label}</Text>
            </Pressable>
          ))}
        </ScrollView>
      ) : src && Platform.OS === "web" ? (
        <iframe src={src} style={{ flex: 1, border: "none", width: "100%", height: "100%" }}
          title={`split-${side}`} />
      ) : (
        <View style={styles.empty}>
          <Text style={styles.emptyTxt}>Split view is available on the web portal.</Text>
        </View>
      )}
    </View>
  );
}

export default function SplitViewScreen() {
  const [left, setLeft] = useState<string | null>("/attendance-grid");
  const [right, setRight] = useState<string | null>("/reports?tab=salary");
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Split View", headerShown: false }} />
      <View style={styles.head}>
        <Text style={styles.title}>🪟 Split-Screen Comparison</Text>
        <Text style={styles.sub}>View any two screens side-by-side — e.g. two months&apos; reports.</Text>
      </View>
      <View style={styles.row}>
        <Pane side="left" route={left} onPick={setLeft} />
        <View style={styles.divider} />
        <Pane side="right" route={right} onPick={setRight} />
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F8FAFC" },
  head: { paddingHorizontal: 16, paddingTop: 12, paddingBottom: 8 },
  title: { fontSize: 17, fontWeight: "800", color: "#1F2937" },
  sub: { fontSize: 11.5, color: "#64748B", marginTop: 2 },
  row: { flex: 1, flexDirection: "row", padding: 10, gap: 0 },
  divider: { width: 8 },
  pane: {
    flex: 1, backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#E2E8F0",
    borderRadius: 12, overflow: "hidden",
  },
  paneBar: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 8, backgroundColor: "#0F172A",
  },
  paneBarTxt: { color: "#fff", fontSize: 12, fontWeight: "700" },
  paneBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "#EFF6FF",
    borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4,
  },
  paneBtnTxt: { fontSize: 11, fontWeight: "700", color: "#2563EB" },
  pickList: { flex: 1, padding: 8 },
  pickItem: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingHorizontal: 10,
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#F1F5F9",
  },
  pickItemTxt: { fontSize: 13, color: "#1F2937", fontWeight: "600" },
  empty: { flex: 1, alignItems: "center", justifyContent: "center" },
  emptyTxt: { fontSize: 12, color: "#94A3B8" },
});
