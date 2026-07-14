import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal, TextInput,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { useUnreadNotifications } from "@/src/hooks/useUnreadNotifications";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

const AUDIENCE = ["all", "employees", "admins"] as const;

export default function NotificationsScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const isAdmin = user?.role !== "employee";

  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audience, setAudience] = useState<(typeof AUDIENCE)[number]>("all");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ notifications: any[] }>("/notifications");
      setItems(r.notifications || []);
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);
  // Iter 89 — Mark all fetched notifications as "seen" so the bell badge
  // clears the moment the user opens the inbox.
  const { markAllSeen } = useUnreadNotifications();
  useEffect(() => {
    if (!loading && items.length > 0) {
      markAllSeen();
    }
  }, [loading, items, markAllSeen]);

  const submit = async () => {
    if (!title || !body) return;
    setSubmitting(true);
    try {
      await api("/notifications", { method: "POST", body: { title, body, audience } });
      setOpen(false); setTitle(""); setBody("");
      await load();
    } finally { setSubmitting(false); }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Notifications</Text>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {loading ? <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} /> :
          items.length === 0 ? <Text style={styles.empty}>No notifications yet.</Text> :
            items.map((n) => (
              <View key={n.notification_id} style={styles.card}>
                <View style={styles.icon}>
                  <Ionicons name="megaphone-outline" size={18} color={colors.onBrandTertiary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.title}>{n.title}</Text>
                  <Text style={styles.body}>{n.body}</Text>
                  <Text style={styles.meta}>{new Date(n.created_at).toLocaleString()} · {n.audience}</Text>
                </View>
              </View>
            ))}
        <View style={{ height: 100 }} />
      </KeyboardAwareScrollView>

      {isAdmin && (
        <Pressable testID="new-notif-fab" style={styles.fab} onPress={() => setOpen(true)}>
          <Ionicons name="add" size={24} color="#fff" />
          <Text style={styles.fabTxt}>Broadcast</Text>
        </Pressable>
      )}

      <Modal transparent visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.modalRoot}>
          <Pressable style={styles.backdrop} onPress={() => setOpen(false)} />
          <View style={styles.sheet}>
            <View style={styles.sheetGrip} />
            <Text style={styles.sheetTitle}>Broadcast notification</Text>
            <Text style={styles.label}>Audience</Text>
            <View style={styles.typeRow}>
              {AUDIENCE.map((a) => (
                <Pressable key={a} onPress={() => setAudience(a)}
                  style={[styles.typeChip, audience === a && styles.typeChipActive]}>
                  <Text style={[styles.typeChipTxt, audience === a && styles.typeChipTxtActive]}>{a}</Text>
                </Pressable>
              ))}
            </View>
            <Text style={styles.label}>Title</Text>
            <TextInput value={title} onChangeText={setTitle} style={styles.input}
              placeholder="Policy update" placeholderTextColor={colors.onSurfaceTertiary} />
            <Text style={styles.label}>Body</Text>
            <TextInput value={body} onChangeText={setBody} style={[styles.input, { height: 100 }]} multiline
              placeholder="Message…" placeholderTextColor={colors.onSurfaceTertiary} />
            <Pressable style={styles.submit} onPress={submit} disabled={submitting}>
              {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.submitTxt}>Send</Text>}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  h1: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500" },
  scroll: { padding: spacing.xl },
  empty: { color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 60 },
  card: {
    flexDirection: "row", gap: spacing.md, backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, padding: spacing.md, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.sm, alignItems: "flex-start",
  },
  icon: { width: 36, height: 36, borderRadius: 18, backgroundColor: colors.brandTertiary, alignItems: "center", justifyContent: "center" },
  title: { color: colors.onSurface, fontSize: type.base, fontWeight: "500" },
  body: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  meta: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 4 },
  fab: { position: "absolute", bottom: 24, right: 24, backgroundColor: colors.brandPrimary, borderRadius: radius.pill, paddingHorizontal: 18, paddingVertical: 14, flexDirection: "row", alignItems: "center", gap: 6, elevation: 4 },
  fabTxt: { color: "#fff", fontSize: type.base, fontWeight: "500" },
  modalRoot: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: spacing.xl },
  sheetGrip: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.borderStrong, marginBottom: spacing.md },
  sheetTitle: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500", marginBottom: spacing.md },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.sm },
  typeRow: { flexDirection: "row", gap: 8, marginTop: 6 },
  typeChip: { paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary },
  typeChipActive: { backgroundColor: colors.brandPrimary },
  typeChipTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, textTransform: "capitalize" },
  typeChipTxtActive: { color: "#fff" },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, color: colors.onSurface, fontSize: type.base, marginTop: 6, backgroundColor: colors.surfaceSecondary },
  submit: { marginTop: spacing.lg, backgroundColor: colors.cta, paddingVertical: 14, borderRadius: radius.pill, alignItems: "center" },
  submitTxt: { color: "#fff", fontSize: type.lg, fontWeight: "500" },
});
