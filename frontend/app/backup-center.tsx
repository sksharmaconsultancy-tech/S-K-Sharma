/**
 * Backup Center (Iter 366).
 * Lists the daily MongoDB backups on the server with one-click download,
 * and shows how to auto-download them to the user's own PC nightly.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Platform,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { shared } from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { colors } from "@/src/theme";

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL || "";

export default function BackupCenterScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [data, setData] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  // User decides where backups land on their own computer.
  const [pcDir, setPcDir] = useState("C:\\SKSBackups");

  const load = useCallback(async () => {
    setBusy(true);
    try {
      setData(await api<any>("/admin/backups"));
    } catch (e: any) {
      setData({ error: e?.message || "Failed to load backups" });
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const dl = (name: string) => {
    if (Platform.OS !== "web" || !data?.token) return;
    const a = document.createElement("a");
    a.href = `${BASE}/api/admin/backups/download/${name}?token=${data.token}`;
    a.download = name;
    a.click();
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const latestUrl = data?.token
    ? `${BASE}/api/admin/backups/latest?token=${data.token}`
    : "";

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="bk-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>Backup Center</Text>
        <Pressable onPress={load} hitSlop={10} testID="bk-refresh">
          <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
        </Pressable>
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        {busy && <ActivityIndicator style={{ marginVertical: 20 }} />}
        {!busy && data && (
          <>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>
                🗄 Daily Database Backups
                {data.configured ? ` (${data.files?.length || 0})` : ""}
              </Text>
              {!data.configured && (
                <Text style={[shared.meta, { color: "#B45309" }]}>
                  {data.note ||
                    "Backup folder not found on this server. Run the "
                    + "daily-backup setup script (deploy365.sh) on the VPS."}
                </Text>
              )}
              {data.error ? (
                <Text style={[shared.meta, { color: "#B91C1C" }]}>
                  {data.error}
                </Text>
              ) : null}
              {(data.files || []).map((f: any) => (
                <View key={f.name} style={st.row}>
                  <Ionicons
                    name={f.name.startsWith("mongo_")
                      ? "server-outline" : "document-outline"}
                    size={16} color={colors.brandPrimary} />
                  <View style={{ flex: 1 }}>
                    <Text style={st.name}>{f.name}</Text>
                    <Text style={shared.meta}>
                      {f.size_h} · {f.modified}
                    </Text>
                  </View>
                  <Pressable onPress={() => dl(f.name)} style={st.dlBtn}
                    testID={`bk-dl-${f.name}`}>
                    <Ionicons name="download-outline" size={15}
                      color="#fff" />
                    <Text style={st.dlTxt}>Download</Text>
                  </Pressable>
                </View>
              ))}
              {data.configured && !(data.files || []).length && (
                <Text style={shared.meta}>
                  No backup files yet — the first one is created at 2:00 AM
                  tonight, or run the backup script manually on the VPS.
                </Text>
              )}
            </View>

            <View style={shared.card}>
              <Text style={shared.cardTitle}>
                💻 Auto-download to YOUR computer (nightly)
              </Text>
              <Text style={shared.meta}>
                Set this up once on your Windows PC and every night the
                latest backup is saved to your chosen folder automatically:
              </Text>
              <Text style={st.stepH}>
                Backup folder on YOUR computer (you decide):
              </Text>
              <TextInput
                style={[shared.input, { maxWidth: 420 }]}
                value={pcDir}
                onChangeText={setPcDir}
                placeholder="e.g. D:\PortalBackups"
                testID="bk-pc-dir"
              />
              <Text style={st.stepH}>1. Create the folder</Text>
              <Text style={st.code} selectable>{`mkdir ${pcDir}`}</Text>
              <Text style={st.stepH}>
                2. Save this as {pcDir}\get_backup.bat
              </Text>
              <Text style={st.code} selectable>
                {`@echo off\nset D=%date:~-4%-%date:~4,2%-%date:~7,2%\ncurl -L -o "${pcDir}\\mongo_%D%.gz" "${latestUrl}"\nforfiles /P ${pcDir} /M mongo_*.gz /D -30 /C "cmd /c del @path" 2>nul`}
              </Text>
              <Text style={st.stepH}>
                3. Schedule it (run once in Command Prompt)
              </Text>
              <Text style={st.code} selectable>
                {`schtasks /Create /TN "SKS Portal Backup" /TR "${pcDir}\\get_backup.bat" /SC DAILY /ST 03:00`}
              </Text>
              <Text style={[shared.meta, { marginTop: 6 }]}>
                Done — every day at 3:00 AM (after the 2 AM server backup)
                the newest backup lands in your chosen folder, and copies
                older than 30 days are cleaned up automatically. You can
                also just press the Download button above anytime.
              </Text>
              <Text style={[shared.meta, { marginTop: 4 }]}>
                Server-side location is also your choice: set BACKUP_DIR=…
                in backend/.env on the VPS (default /home/sksharma/backups)
                and adjust BK_DIR in backup_mongo_daily.sh to match.
              </Text>
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border,
  },
  name: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  dlBtn: {
    flexDirection: "row",
    gap: 5,
    alignItems: "center",
    backgroundColor: colors.brandPrimary,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  dlTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  stepH: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.onSurface,
    marginTop: 10,
    marginBottom: 3,
  },
  code: {
    fontFamily: Platform.OS === "web" ? "monospace" : undefined,
    fontSize: 11.5,
    color: "#0F172A",
    backgroundColor: "#F1F5F9",
    borderRadius: 8,
    padding: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
});
