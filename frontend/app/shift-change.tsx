/**
 * Iter 104 — Employee Shift Change Request (Hospital firms only).
 * Request a different shift BEFORE punching in — needs employer approval;
 * on approval the vacated shift is compulsorily allotted to a replacement.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";

function showMsg(m: string) {
  if (Platform.OS === "web") globalThis.alert(m); else Alert.alert("Shift change", m);
}

export default function ShiftChangeScreen() {
  const router = useRouter();
  const [opts, setOpts] = useState<any>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [reqs, setReqs] = useState<any[]>([]);

  const load = useCallback(async () => {
    try {
      const [o, r] = await Promise.all([
        api<any>("/shift-change/options"),
        api<{ requests: any[] }>("/shift-change-requests"),
      ]);
      setOpts(o);
      setReqs(r.requests || []);
    } catch (e: any) { showMsg(e?.message || "Failed to load"); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const submit = async () => {
    if (!picked) { showMsg("Select the shift you want"); return; }
    setBusy(true);
    try {
      await api("/shift-change-requests", {
        method: "POST", body: { requested_shift: picked, reason: reason.trim() },
      });
      showMsg("Request sent — waiting for employer approval.");
      setPicked(null); setReason("");
      await load();
    } catch (e: any) { showMsg(e?.message || "Request failed"); }
    finally { setBusy(false); }
  };

  if (!opts) {
    return <View style={styles.center}><ActivityIndicator color={colors.brandPrimary} /></View>;
  }

  return (
    <SafeAreaView style={styles.root} edges={["top"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, paddingBottom: 60 }}>
        <View style={styles.headRow}>
          <Pressable onPress={() => router.back()} style={styles.backBtn} testID="sc-back">
            <Ionicons name="chevron-back" size={20} color={colors.onSurface} />
          </Pressable>
          <View>
            <Text style={styles.title}>Shift Change Request</Text>
            <Text style={styles.subtitle}>Request before punch-in · employer approval required</Text>
          </View>
        </View>

        {!opts.allowed ? (
          <View style={styles.card} testID="sc-not-allowed">
            <Ionicons name="information-circle-outline" size={22} color={colors.brandPrimary} />
            <Text style={[styles.hint, { fontSize: 13, marginTop: 6 }]}>
              Shift change requests are available only for Hospital firms.
            </Text>
          </View>
        ) : (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>
              Current shift: {opts.current_shift || "— not assigned —"}
            </Text>
            {opts.already_punched ? (
              <Text style={[styles.hint, { color: "#B45309", fontWeight: "700" }]}>
                You have already punched today — shift can only be changed BEFORE punch-in.
              </Text>
            ) : null}
            <Text style={styles.lbl}>Requested shift ({opts.today})</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
              {(opts.shifts || []).map((s: any) => (
                <Pressable key={s.name} onPress={() => setPicked(s.name)}
                  style={[styles.chip, picked === s.name && styles.chipOn]}
                  testID={`sc-shift-${s.name}`}>
                  <Text style={[styles.chipTxt, picked === s.name && styles.chipTxtOn]}>
                    {s.name}{s.start ? ` (${s.start}–${s.end})` : ""}
                  </Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.lbl}>Reason (optional)</Text>
            <TextInput style={styles.input} value={reason} onChangeText={setReason}
              placeholder="Why do you need this shift?" testID="sc-reason" />
            <Pressable onPress={submit} disabled={busy || opts.already_punched}
              style={[styles.primaryBtn, (busy || opts.already_punched) && { opacity: 0.6 }]}
              testID="sc-submit">
              {busy ? <ActivityIndicator color="#fff" /> : (
                <><Ionicons name="swap-horizontal" size={16} color="#fff" />
                  <Text style={styles.primaryBtnTxt}>Request Shift Change</Text></>
              )}
            </Pressable>
          </View>
        )}

        <View style={styles.card}>
          <Text style={styles.cardTitle}>My requests</Text>
          {reqs.length === 0 ? <Text style={styles.hint}>No requests yet.</Text> : reqs.map((r) => (
            <View key={r.request_id} style={styles.reqRow}>
              <Ionicons
                name={r.status === "approved" ? "checkmark-circle" : r.status === "rejected" ? "close-circle" : "time-outline"}
                size={16}
                color={r.status === "approved" ? "#16A34A" : r.status === "rejected" ? "#DC2626" : "#D97706"} />
              <View style={{ flex: 1 }}>
                <Text style={{ fontWeight: "700", color: colors.onSurface, fontSize: 13 }}>
                  {r.date}: {r.current_shift || "—"} → {r.requested_shift}
                </Text>
                <Text style={styles.hint}>
                  {r.status.toUpperCase()}{r.replacement_name ? ` · replaced by ${r.replacement_name}` : ""}{r.note ? ` · ${r.note}` : ""}
                </Text>
              </View>
            </View>
          ))}
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  headRow: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: spacing.md },
  backBtn: {
    width: 36, height: 36, borderRadius: 10, backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center", borderWidth: 1, borderColor: colors.divider,
  },
  title: { ...type.h2, color: colors.onSurface, fontWeight: "800" },
  subtitle: { color: colors.onSurfaceTertiary, fontSize: 12, marginTop: 2 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.lg,
    borderWidth: 1, borderColor: colors.divider, marginBottom: spacing.md,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 3 },
  lbl: {
    fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary,
    marginTop: 12, marginBottom: 6, textTransform: "uppercase",
  },
  chip: {
    paddingHorizontal: 12, paddingVertical: 9, borderRadius: 999,
    borderWidth: 1, borderColor: colors.divider, backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface },
  chipTxtOn: { color: "#fff" },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 13.5,
    color: colors.onSurface, backgroundColor: colors.background,
  },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, paddingVertical: 13, borderRadius: radius.md,
    marginTop: spacing.md,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  reqRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 9, borderBottomWidth: 1, borderColor: colors.divider,
  },
});
