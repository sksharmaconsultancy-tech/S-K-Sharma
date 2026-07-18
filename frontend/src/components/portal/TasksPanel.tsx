// Phase 2 — Task Management panel for the portal dashboard.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, Modal,
  ActivityIndicator, ScrollView, Alert, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

type Task = {
  task_id: string; title: string; description?: string | null;
  company_id?: string | null; company_name?: string | null;
  due_date?: string | null; priority: string; status: string;
  created_by_name?: string | null;
};
type CompanyLite = { company_id: string; name: string };

const PRIORITY_UI: Record<string, { fg: string; bg: string }> = {
  high: { fg: "#B91C1C", bg: "#FEF2F2" },
  medium: { fg: "#B45309", bg: "#FFFBEB" },
  low: { fg: "#0369A1", bg: "#F0F9FF" },
};
const FILTERS = [
  { key: "all", label: "All" },
  { key: "open", label: "Open" },
  { key: "in_progress", label: "In Progress" },
  { key: "done", label: "Done" },
];

export default function TasksPanel({
  companyId, companies, canPickFirm,
}: { companyId: string | null; companies: CompanyLite[]; canPickFirm: boolean }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("all");
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    title: "", description: "", due_date: "", priority: "medium",
    company_id: companyId || "",
  });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (filter !== "all") p.set("status", filter);
      if (companyId) p.set("company_id", companyId);
      const r = await api<{ tasks: Task[]; counts: Record<string, number> }>(
        `/admin/portal-tasks?${p.toString()}`);
      setTasks(r.tasks); setCounts(r.counts);
    } catch { /* noop */ }
    setLoading(false);
  }, [filter, companyId]);

  useEffect(() => { load(); }, [load]);

  const createTask = async () => {
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      await api("/admin/portal-tasks", {
        method: "POST",
        body: {
          title: form.title, description: form.description || null,
          due_date: form.due_date || null, priority: form.priority,
          company_id: form.company_id || null,
        },
      });
      setShowAdd(false);
      setForm({ title: "", description: "", due_date: "", priority: "medium", company_id: companyId || "" });
      load();
    } catch (e: any) {
      const msg = e?.message || "Failed to create task";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setSaving(false);
  };

  const setStatus = async (t: Task, status: string) => {
    try {
      await api(`/admin/portal-tasks/${t.task_id}`, { method: "PATCH", body: { status } });
      load();
    } catch { /* noop */ }
  };

  const removeTask = async (t: Task) => {
    const go = async () => {
      try { await api(`/admin/portal-tasks/${t.task_id}`, { method: "DELETE" }); load(); } catch { /* noop */ }
    };
    if (Platform.OS === "web") {
      if (window.confirm(`Delete task "${t.title}"?`)) go();
    } else {
      Alert.alert("Delete task", t.title, [
        { text: "Cancel" }, { text: "Delete", style: "destructive", onPress: go }]);
    }
  };

  const today = new Date().toISOString().slice(0, 10);

  return (
    <View testID="pd-tasks-panel">
      {/* counters */}
      <View style={st.countRow}>
        {[
          { k: "open", label: "Open", c: "#1D4ED8" },
          { k: "in_progress", label: "In Progress", c: "#B45309" },
          { k: "done", label: "Done", c: "#16A34A" },
          { k: "overdue", label: "Overdue", c: "#B91C1C" },
        ].map((x) => (
          <View key={x.k} style={st.countCard}>
            <Text style={[st.countVal, { color: x.c }]}>{counts[x.k] ?? 0}</Text>
            <Text style={st.countLbl}>{x.label}</Text>
          </View>
        ))}
      </View>

      <View style={st.toolbar}>
        <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap", flex: 1 }}>
          {FILTERS.map((f) => (
            <Pressable key={f.key} onPress={() => setFilter(f.key)}
              style={[st.chip, filter === f.key && st.chipOn]}
              testID={`pd-task-filter-${f.key}`}>
              <Text style={[st.chipTxt, filter === f.key && st.chipTxtOn]}>{f.label}</Text>
            </Pressable>
          ))}
        </View>
        <Pressable onPress={() => setShowAdd(true)} style={st.addBtn} testID="pd-task-add">
          <Ionicons name="add" size={15} color="#fff" />
          <Text style={st.addTxt}>New Task</Text>
        </Pressable>
      </View>

      {loading ? (
        <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 24 }} />
      ) : tasks.length === 0 ? (
        <Text style={st.dim}>No tasks. Create one with &quot;New Task&quot;.</Text>
      ) : (
        tasks.map((t) => {
          const pui = PRIORITY_UI[t.priority] || PRIORITY_UI.medium;
          const overdue = t.status !== "done" && !!t.due_date && t.due_date < today;
          return (
            <View key={t.task_id} style={st.taskCard} testID={`pd-task-${t.task_id}`}>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <Text style={[st.taskTitle, t.status === "done" && { textDecorationLine: "line-through", color: colors.onSurfaceTertiary }]}>
                    {t.title}
                  </Text>
                  <Text style={[st.prioChip, { color: pui.fg, backgroundColor: pui.bg }]}>
                    {t.priority.toUpperCase()}
                  </Text>
                </View>
                {t.description ? <Text style={st.taskDesc} numberOfLines={2}>{t.description}</Text> : null}
                <View style={{ flexDirection: "row", gap: 10, marginTop: 4, flexWrap: "wrap" }}>
                  {t.company_name ? <Text style={st.meta}>🏢 {t.company_name}</Text> : null}
                  {t.due_date ? (
                    <Text style={[st.meta, overdue && { color: "#B91C1C", fontWeight: "800" }]}>
                      📅 {t.due_date}{overdue ? " (overdue)" : ""}
                    </Text>
                  ) : null}
                </View>
              </View>
              <View style={{ gap: 6, alignItems: "flex-end" }}>
                {t.status === "open" ? (
                  <Pressable onPress={() => setStatus(t, "in_progress")} style={st.stBtn}>
                    <Text style={st.stBtnTxt}>Start</Text>
                  </Pressable>
                ) : null}
                {t.status !== "done" ? (
                  <Pressable onPress={() => setStatus(t, "done")}
                    style={[st.stBtn, { borderColor: "#16A34A" }]} testID={`pd-task-done-${t.task_id}`}>
                    <Text style={[st.stBtnTxt, { color: "#16A34A" }]}>✓ Done</Text>
                  </Pressable>
                ) : (
                  <Pressable onPress={() => setStatus(t, "open")} style={st.stBtn}>
                    <Text style={st.stBtnTxt}>Reopen</Text>
                  </Pressable>
                )}
                <Pressable onPress={() => removeTask(t)} hitSlop={8}>
                  <Ionicons name="trash-outline" size={15} color="#B91C1C" />
                </Pressable>
              </View>
            </View>
          );
        })
      )}

      {/* Add modal */}
      <Modal visible={showAdd} transparent animationType="fade" onRequestClose={() => setShowAdd(false)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle}>New Task</Text>
            <ScrollView style={{ maxHeight: 420 }}>
              <Text style={st.lbl}>Title *</Text>
              <TextInput style={st.input} value={form.title}
                onChangeText={(v) => setForm({ ...form, title: v })}
                placeholder="e.g. File PF ECR for June" placeholderTextColor={colors.onSurfaceTertiary}
                testID="pd-task-title-input" />
              <Text style={st.lbl}>Description</Text>
              <TextInput style={[st.input, { height: 64 }]} value={form.description} multiline
                onChangeText={(v) => setForm({ ...form, description: v })}
                placeholder="Optional details" placeholderTextColor={colors.onSurfaceTertiary} />
              <Text style={st.lbl}>Due date (YYYY-MM-DD)</Text>
              <TextInput style={st.input} value={form.due_date}
                onChangeText={(v) => setForm({ ...form, due_date: v })}
                placeholder="2026-06-30" placeholderTextColor={colors.onSurfaceTertiary}
                testID="pd-task-due-input" />
              <Text style={st.lbl}>Priority</Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                {["low", "medium", "high"].map((p) => (
                  <Pressable key={p} onPress={() => setForm({ ...form, priority: p })}
                    style={[st.chip, form.priority === p && st.chipOn]}>
                    <Text style={[st.chipTxt, form.priority === p && st.chipTxtOn]}>{p}</Text>
                  </Pressable>
                ))}
              </View>
              {canPickFirm ? (
                <>
                  <Text style={st.lbl}>Firm (optional)</Text>
                  <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                    <Pressable onPress={() => setForm({ ...form, company_id: "" })}
                      style={[st.chip, !form.company_id && st.chipOn]}>
                      <Text style={[st.chipTxt, !form.company_id && st.chipTxtOn]}>None</Text>
                    </Pressable>
                    {companies.map((c) => (
                      <Pressable key={c.company_id}
                        onPress={() => setForm({ ...form, company_id: c.company_id })}
                        style={[st.chip, form.company_id === c.company_id && st.chipOn]}>
                        <Text style={[st.chipTxt, form.company_id === c.company_id && st.chipTxtOn]}
                          numberOfLines={1}>{c.name}</Text>
                      </Pressable>
                    ))}
                  </View>
                </>
              ) : null}
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <Pressable onPress={() => setShowAdd(false)} style={[st.mBtn, st.mBtnGhost]}>
                <Text style={st.mBtnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable onPress={createTask} disabled={saving || !form.title.trim()}
                style={[st.mBtn, st.mBtnPrimary, (!form.title.trim() || saving) && { opacity: 0.5 }]}
                testID="pd-task-save">
                {saving ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.mBtnPrimaryTxt}>Create Task</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const st = StyleSheet.create({
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 16, textAlign: "center" },
  countRow: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  countCard: {
    flex: 1, minWidth: 110, backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.divider, padding: 10, alignItems: "center",
  },
  countVal: { fontSize: 20, fontWeight: "800" },
  countLbl: { fontSize: 10, color: colors.onSurfaceSecondary, marginTop: 2 },
  toolbar: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 12, marginBottom: 10 },
  chip: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: 999,
    paddingHorizontal: 11, paddingVertical: 6, backgroundColor: colors.surface, maxWidth: 180,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: colors.brandPrimary,
    borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8,
  },
  addTxt: { fontSize: 11.5, fontWeight: "800", color: "#fff" },
  taskCard: {
    flexDirection: "row", gap: 10, backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.divider, padding: 12, marginBottom: 8,
  },
  taskTitle: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  taskDesc: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 2 },
  meta: { fontSize: 10.5, color: colors.onSurfaceSecondary },
  prioChip: {
    fontSize: 8.5, fontWeight: "800", borderRadius: 5, overflow: "hidden",
    paddingHorizontal: 6, paddingVertical: 2,
  },
  stBtn: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 5,
  },
  stBtnTxt: { fontSize: 10.5, fontWeight: "800", color: colors.brandPrimary },
  overlay: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.45)", alignItems: "center",
    justifyContent: "center", padding: spacing.md,
  },
  modal: {
    width: "100%", maxWidth: 460, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: 16,
  },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  lbl: { fontSize: 10.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 12.5, color: colors.onSurface,
    backgroundColor: colors.background,
  },
  mBtn: { flex: 1, borderRadius: radius.md, paddingVertical: 11, alignItems: "center" },
  mBtnGhost: { borderWidth: 1, borderColor: colors.divider },
  mBtnGhostTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  mBtnPrimary: { backgroundColor: colors.brandPrimary },
  mBtnPrimaryTxt: { fontSize: 12.5, fontWeight: "800", color: "#fff" },
});
