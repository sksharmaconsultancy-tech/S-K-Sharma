// Iter 508 (user spec) — OVERDUE LOGIN GATE for Sub Super Admins.
// Tasks allotted to a sub admin come with a 24-hour window (default due:
// next day). If a task is still pending past its due date, the next time
// the sub admin opens the app they MUST first record why the task was not
// completed on time — only then can they continue working. Every reason is
// stored on the task + audit trail so the Super Admin sees it.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, TextInput, Pressable,
  ActivityIndicator, ScrollView, Platform, Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type BlockedTask = {
  task_id: string; title: string; due_date?: string | null;
  priority?: string; company_name?: string | null; company_names?: string[];
};

export default function OverdueGate() {
  const { user } = useAuth();
  const [tasks, setTasks] = useState<BlockedTask[]>([]);
  const [reasons, setReasons] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [checked, setChecked] = useState(false);

  const check = useCallback(async () => {
    if (!user || user.role !== "sub_admin") { setTasks([]); setChecked(true); return; }
    try {
      const r = await api<{ tasks: BlockedTask[] }>("/admin/portal-tasks/overdue-block");
      setTasks(r.tasks || []);
    } catch { /* fail-open: never lock the app on a network error */ }
    setChecked(true);
  }, [user]);

  useEffect(() => { void check(); }, [check]);

  const submit = async (t: BlockedTask) => {
    const reason = (reasons[t.task_id] || "").trim();
    if (!reason) return;
    setSaving(t.task_id);
    try {
      await api(`/admin/portal-tasks/${t.task_id}/overdue-reason`, {
        method: "POST", body: { reason },
      });
      setTasks((prev) => prev.filter((x) => x.task_id !== t.task_id));
    } catch (e: any) {
      const msg = e?.message || "Failed to save the reason";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setSaving(null);
  };

  if (!checked || !tasks.length) return null;

  return (
    <Modal visible transparent animationType="fade" onRequestClose={() => {}}>
      <View style={st.overlay}>
        <View style={st.card} testID="overdue-gate">
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            <Ionicons name="alert-circle" size={22} color="#B91C1C" />
            <Text style={st.title}>Overdue tasks need a reason</Text>
          </View>
          <Text style={st.sub}>
            {tasks.length} task{tasks.length > 1 ? "s were" : " was"} not completed
            within the allowed time. Enter the reason for each to continue —
            the Super Admin will see your reasons.
          </Text>
          <ScrollView style={{ maxHeight: 420 }}>
            {tasks.map((t) => (
              <View key={t.task_id} style={st.item} testID={`overdue-item-${t.task_id}`}>
                <Text style={st.itemTitle} numberOfLines={2}>{t.title}</Text>
                <Text style={st.itemMeta}>
                  {(t.company_names || []).join(" · ") || t.company_name || "All firms"}
                  {t.due_date ? `  ·  was due ${t.due_date}` : ""}
                </Text>
                <TextInput
                  style={st.input}
                  value={reasons[t.task_id] || ""}
                  onChangeText={(v) => setReasons((r) => ({ ...r, [t.task_id]: v }))}
                  placeholder="Why was this not completed on time?"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  multiline
                  testID={`overdue-reason-${t.task_id}`}
                />
                <Pressable
                  onPress={() => submit(t)}
                  disabled={saving === t.task_id || !(reasons[t.task_id] || "").trim()}
                  style={[st.btn, !(reasons[t.task_id] || "").trim() && { opacity: 0.5 }]}
                  testID={`overdue-submit-${t.task_id}`}
                >
                  {saving === t.task_id
                    ? <ActivityIndicator color="#fff" size="small" />
                    : <Text style={st.btnTxt}>Submit reason</Text>}
                </Pressable>
              </View>
            ))}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const st = StyleSheet.create({
  overlay: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.72)",
    justifyContent: "center", padding: spacing.md,
  },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, gap: 8, maxWidth: 560, width: "100%", alignSelf: "center",
  },
  title: { fontSize: 15.5, fontWeight: "800", color: "#B91C1C" },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary },
  item: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    padding: 10, marginTop: 8, gap: 4, backgroundColor: "#FFFBEB",
  },
  itemTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  itemMeta: { fontSize: 11, color: "#B45309", fontWeight: "700" },
  input: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    padding: 8, fontSize: 13, color: colors.onSurface, minHeight: 56,
    textAlignVertical: "top", backgroundColor: colors.surface, marginTop: 4,
  },
  btn: {
    backgroundColor: "#B91C1C", borderRadius: radius.md, paddingVertical: 9,
    alignItems: "center", marginTop: 6, minHeight: 38, justifyContent: "center",
  },
  btnTxt: { color: "#fff", fontSize: 12.5, fontWeight: "800" },
});
