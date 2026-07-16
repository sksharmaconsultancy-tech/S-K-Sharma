/**
 * Iter 155 — Database Backup download (SUPER ADMIN only).
 */
import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, ActivityIndicator } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius } from "@/src/theme";

export default function DatabaseBackup() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  if (authLoading) return null;
  if (!user || user.role !== "super_admin") return <Redirect href="/" />;

  const download = async () => {
    if (busy) return;
    setBusy(true);
    setMsg("Preparing backup — this can take a minute for large databases…");
    try {
      const res = await apiBinary("/admin/database-backup");
      const url = URL.createObjectURL(res);
      const a = (globalThis as any).document.createElement("a");
      a.href = url;
      a.download = `SKSharma_DB_Backup_${new Date().toISOString().slice(0, 10)}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      setMsg("Backup downloaded ✓ — keep it in a safe place.");
    } catch (e: any) {
      setMsg(e?.message || "Backup failed");
    } finally { setBusy(false); }
  };

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.back}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>Database Backup</Text>
        <View style={{ width: 38 }} />
      </View>
      <View style={s.card}>
        <Ionicons name="server-outline" size={34} color={colors.brandPrimary} />
        <Text style={s.h}>Full database backup</Text>
        <Text style={s.p}>
          Downloads every collection (employees, firms, attendance, salary runs,
          documents, settings…) as a single .zip of JSON files. Super Admin only —
          every download is audit-logged.
        </Text>
        <Pressable onPress={download} disabled={busy} style={[s.btn, busy && { opacity: 0.6 }]} testID="dbb-download">
          {busy ? <ActivityIndicator color="#fff" size="small" /> : (
            <>
              <Ionicons name="download-outline" size={16} color="#fff" />
              <Text style={s.btnT}>Download backup (.zip)</Text>
            </>
          )}
        </Pressable>
        {!!msg && <Text style={s.msg}>{msg}</Text>}
      </View>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10 },
  back: { width: 38, height: 38, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, textAlign: "center", fontSize: 17, fontWeight: "700", color: colors.onSurface },
  card: {
    margin: 16, padding: 24, alignItems: "center", gap: 10,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius?.lg ?? 14,
  },
  h: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  p: { fontSize: 12.5, color: colors.onSurfaceSecondary, textAlign: "center", lineHeight: 18 },
  btn: {
    flexDirection: "row", gap: 8, alignItems: "center", marginTop: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 10,
    paddingVertical: 12, paddingHorizontal: 24,
  },
  btnT: { color: "#fff", fontWeight: "800", fontSize: 13.5 },
  msg: { fontSize: 12.5, color: colors.brandPrimary, fontWeight: "600", textAlign: "center", marginTop: 6 },
});
