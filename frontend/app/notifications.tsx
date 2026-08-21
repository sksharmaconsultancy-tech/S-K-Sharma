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
import { NOTIF_CATEGORIES, catOf, PRIORITY_COLORS, loadPrefs, savePrefs, type NotifPrefs } from "@/src/utils/notifHelpers";

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
  // Iter 666 — search, filters & settings.
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState<string>("all");
  const [prefs, setPrefs] = useState<NotifPrefs>(loadPrefs());
  const [showSettings, setShowSettings] = useState(false);
  const setPref = (patch: Partial<NotifPrefs>) => {
    const next = { ...prefs, ...patch };
    setPrefs(next); savePrefs(next);
  };

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
  const { markAllSeen, markRead } = useUnreadNotifications();
  useEffect(() => {
    if (!loading && items.length > 0) {
      markAllSeen();
    }
  }, [loading, items, markAllSeen]);

  const visible = items.filter((n) => {
    if (filter === "unread" && n.read) return false;
    if (filter !== "all" && filter !== "unread" && String(n.category || "announcement") !== filter) return false;
    if (q.trim()) {
      const hay = `${n.title || ""} ${n.body || ""} ${n.message || ""}`.toLowerCase();
      if (!hay.includes(q.trim().toLowerCase())) return false;
    }
    return true;
  });

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
          <Pressable onPress={() => setShowSettings((s) => !s)} hitSlop={8} testID="notif-settings-btn">
            <Ionicons name="settings-outline" size={20} color={colors.onSurfaceSecondary} />
          </Pressable>
        </View>
      </SafeAreaView>

      {/* Iter 666 — search + category filters + mark-all-read */}
      <View style={{ paddingHorizontal: spacing.lg, gap: 8 }}>
        <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
          <TextInput value={q} onChangeText={setQ} style={[styles.input, { flex: 1, marginTop: 0 }]}
            placeholder="Search notifications…" placeholderTextColor={colors.onSurfaceTertiary} />
          <Pressable onPress={() => { markRead("all"); setItems((p) => p.map((n) => ({ ...n, read: true }))); }}
            style={styles.markAllBtn} testID="notif-page-mark-all">
            <Ionicons name="checkmark-done-outline" size={14} color="#fff" />
            <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700" }}>Mark All Read</Text>
          </Pressable>
        </View>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
          {["all", "unread", ...Object.keys(NOTIF_CATEGORIES)].map((f) => (
            <Pressable key={f} onPress={() => setFilter(f)}
              style={[styles.typeChip, { paddingVertical: 5 }, filter === f && styles.typeChipActive]}>
              <Text style={[styles.typeChipTxt, { fontSize: 11 }, filter === f && styles.typeChipTxtActive]}>
                {f === "all" ? "All" : f === "unread" ? "Unread" : NOTIF_CATEGORIES[f].label}
              </Text>
            </Pressable>
          ))}
        </View>
        {showSettings ? (
          <View style={styles.settingsBox}>
            <Text style={{ fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 6 }}>Notification Settings (this device)</Text>
            {[["Toast Notifications", "toasts"], ["Notification Sound", "sound"]].map(([lbl, k]) => (
              <Pressable key={k} style={styles.setRow}
                onPress={() => setPref({ [k]: !(prefs as any)[k] } as any)}>
                <Text style={styles.setLbl}>{lbl}</Text>
                <Text style={[styles.setVal, (prefs as any)[k] && { color: "#059669" }]}>{(prefs as any)[k] ? "ON" : "OFF"}</Text>
              </Pressable>
            ))}
            {Object.entries(NOTIF_CATEGORIES).map(([k, c]) => (
              <Pressable key={k} style={styles.setRow}
                onPress={() => setPref({ categories: { ...prefs.categories, [k]: !(prefs.categories[k] !== false) } })}>
                <Text style={styles.setLbl}>{c.label} Notifications</Text>
                <Text style={[styles.setVal, prefs.categories[k] !== false && { color: "#059669" }]}>
                  {prefs.categories[k] !== false ? "ON" : "OFF"}
                </Text>
              </Pressable>
            ))}
          </View>
        ) : null}
      </View>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {loading ? <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} /> :
          visible.length === 0 ? <Text style={styles.empty}>No notifications found.</Text> :
            visible.map((n) => {
              const cat = catOf(n);
              const pr = PRIORITY_COLORS[String(n.priority || "normal")] || "transparent";
              return (
                <Pressable key={n.notification_id}
                  style={[styles.card,
                    !n.read && { backgroundColor: "#F0F7FF", borderColor: "#BFDBFE" },
                    pr !== "transparent" && { borderLeftWidth: 4, borderLeftColor: pr }]}
                  onPress={() => {
                    if (n.notification_id && !n.read) {
                      markRead([n.notification_id]);
                      setItems((p) => p.map((x) => x.notification_id === n.notification_id ? { ...x, read: true } : x));
                    }
                    if (n.action_url) router.push(n.action_url as any);
                  }}>
                  <View style={[styles.icon, { backgroundColor: `${cat.color}22` }]}>
                    <Ionicons name={cat.icon} size={18} color={cat.color} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.title, !n.read && { fontWeight: "800" }]}>{n.title}</Text>
                    <Text style={styles.body}>{n.body || n.message}</Text>
                    <Text style={styles.meta}>
                      {cat.label} · {new Date(n.created_at).toLocaleString()} · {n.audience}
                      {n.priority === "critical" ? "  ⚠ CRITICAL" : n.priority === "important" ? "  • Important" : ""}
                    </Text>
                  </View>
                  {n.action_url ? <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} /> : null}
                </Pressable>
              );
            })}
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
  markAllBtn: { flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: colors.brandPrimary, paddingHorizontal: 12, paddingVertical: 9, borderRadius: radius.pill },
  settingsBox: { backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md },
  setRow: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 6, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  setLbl: { fontSize: 13, color: colors.onSurfaceSecondary },
  setVal: { fontSize: 13, fontWeight: "800", color: colors.onSurfaceTertiary },
});
