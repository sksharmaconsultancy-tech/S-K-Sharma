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
  created_by_name?: string | null; source_rtask_id?: string | null;
};
type RTask = {
  rtask_id: string; title: string; company_id?: string | null;
  company_name?: string | null; all_firms?: boolean;
  day_of_month: number; priority: string; active: boolean;
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
  // recurring
  const [showRec, setShowRec] = useState(false);
  const [recs, setRecs] = useState<RTask[]>([]);
  const [recLoading, setRecLoading] = useState(false);
  const [recSaving, setRecSaving] = useState(false);
  const [showRecAdd, setShowRecAdd] = useState(false);
  const [recForm, setRecForm] = useState({
    title: "", day_of_month: "15", priority: "medium",
    company_id: companyId || "", all_firms: !companyId && canPickFirm,
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

  // ----- recurring templates -----
  const loadRecs = async () => {
    setRecLoading(true);
    try {
      const r = await api<{ recurring_tasks: RTask[] }>("/admin/portal-recurring-tasks");
      setRecs(r.recurring_tasks);
    } catch { /* noop */ }
    setRecLoading(false);
  };

  const openRec = () => { setShowRec(true); loadRecs(); };

  const seedStatutory = async () => {
    setRecSaving(true);
    try {
      await api("/admin/portal-recurring-tasks/seed-statutory", { method: "POST" });
      await loadRecs(); load();
    } catch { /* noop */ }
    setRecSaving(false);
  };

  const createRec = async () => {
    if (!recForm.title.trim()) return;
    const day = parseInt(recForm.day_of_month, 10);
    if (!day || day < 1 || day > 31) {
      const msg = "Due day must be between 1 and 31.";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Invalid day", msg);
      return;
    }
    setRecSaving(true);
    try {
      await api("/admin/portal-recurring-tasks", {
        method: "POST",
        body: {
          title: recForm.title, day_of_month: day, priority: recForm.priority,
          all_firms: recForm.all_firms,
          company_id: recForm.all_firms ? null : recForm.company_id || null,
        },
      });
      setShowRecAdd(false);
      setRecForm({ title: "", day_of_month: "15", priority: "medium", company_id: companyId || "", all_firms: !companyId && canPickFirm });
      await loadRecs(); load();
    } catch (e: any) {
      const msg = e?.message || "Failed to create recurring task";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setRecSaving(false);
  };

  const toggleRec = async (r: RTask) => {
    try {
      await api(`/admin/portal-recurring-tasks/${r.rtask_id}`, {
        method: "PATCH", body: { active: !r.active } });
      await loadRecs(); load();
    } catch { /* noop */ }
  };

  const removeRec = async (r: RTask) => {
    const go = async () => {
      try { await api(`/admin/portal-recurring-tasks/${r.rtask_id}`, { method: "DELETE" }); loadRecs(); } catch { /* noop */ }
    };
    if (Platform.OS === "web") {
      if (window.confirm(`Delete recurring "${r.title}"? (already-created tasks stay)`)) go();
    } else {
      Alert.alert("Delete recurring task", r.title, [
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
        <Pressable onPress={openRec} style={st.recBtn} testID="pd-task-recurring">
          <Ionicons name="repeat" size={14} color={colors.brandPrimary} />
          <Text style={st.recTxt}>Recurring</Text>
        </Pressable>
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
                  {t.source_rtask_id ? (
                    <Ionicons name="repeat" size={12} color={colors.onSurfaceTertiary} />
                  ) : null}
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
      {/* Recurring templates modal */}
      <Modal visible={showRec} transparent animationType="fade" onRequestClose={() => setShowRec(false)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
              <Text style={st.modalTitle}>🔁 Recurring Monthly Tasks</Text>
              <Pressable onPress={() => setShowRec(false)} hitSlop={10} testID="pd-rec-close">
                <Ionicons name="close" size={18} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            <Text style={st.recHint}>
              These auto-create a task every month (per firm) on the chosen day. No more re-adding statutory to-dos.
            </Text>
            <View style={{ flexDirection: "row", gap: 8, marginBottom: 10 }}>
              <Pressable onPress={seedStatutory} disabled={recSaving}
                style={[st.recBtn, { flex: 1, justifyContent: "center" }]} testID="pd-rec-seed">
                <Ionicons name="shield-checkmark-outline" size={13} color={colors.brandPrimary} />
                <Text style={st.recTxt}>Add Statutory Presets (PF · ESIC · TDS · PT)</Text>
              </Pressable>
              <Pressable onPress={() => setShowRecAdd(true)} style={st.addBtn} testID="pd-rec-add">
                <Ionicons name="add" size={15} color="#fff" />
                <Text style={st.addTxt}>Custom</Text>
              </Pressable>
            </View>
            {recLoading ? (
              <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 20 }} />
            ) : recs.length === 0 ? (
              <Text style={st.dim}>No recurring tasks yet. Use the statutory presets to start.</Text>
            ) : (
              <ScrollView style={{ maxHeight: 340 }}>
                {recs.map((r) => (
                  <View key={r.rtask_id} style={st.recRow} testID={`pd-rec-${r.rtask_id}`}>
                    <View style={{ flex: 1 }}>
                      <Text style={[st.taskTitle, !r.active && { color: colors.onSurfaceTertiary }]}
                        numberOfLines={1}>{r.title}</Text>
                      <Text style={st.meta}>
                        Day {r.day_of_month} · {r.priority} · {r.all_firms ? "All firms" : r.company_name || "—"}
                      </Text>
                    </View>
                    <Pressable onPress={() => toggleRec(r)}
                      style={[st.recToggle, r.active && st.recToggleOn]}
                      testID={`pd-rec-toggle-${r.rtask_id}`}>
                      <Text style={[st.recToggleTxt, r.active && { color: "#fff" }]}>
                        {r.active ? "ON" : "OFF"}
                      </Text>
                    </Pressable>
                    <Pressable onPress={() => removeRec(r)} hitSlop={8} style={{ marginLeft: 8 }}>
                      <Ionicons name="trash-outline" size={15} color="#B91C1C" />
                    </Pressable>
                  </View>
                ))}
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>

      {/* Add recurring modal */}
      <Modal visible={showRecAdd} transparent animationType="fade" onRequestClose={() => setShowRecAdd(false)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle}>New Recurring Task</Text>
            <ScrollView style={{ maxHeight: 400 }}>
              <Text style={st.lbl}>Title *</Text>
              <TextInput style={st.input} value={recForm.title}
                onChangeText={(v) => setRecForm({ ...recForm, title: v })}
                placeholder="e.g. Submit muster roll to labour office"
                placeholderTextColor={colors.onSurfaceTertiary} testID="pd-rec-title-input" />
              <Text style={st.lbl}>Due day of month (1–31)</Text>
              <TextInput style={st.input} value={recForm.day_of_month} keyboardType="number-pad"
                onChangeText={(v) => setRecForm({ ...recForm, day_of_month: v.replace(/[^0-9]/g, "") })}
                placeholder="15" placeholderTextColor={colors.onSurfaceTertiary}
                testID="pd-rec-day-input" />
              <Text style={st.lbl}>Priority</Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                {["low", "medium", "high"].map((p) => (
                  <Pressable key={p} onPress={() => setRecForm({ ...recForm, priority: p })}
                    style={[st.chip, recForm.priority === p && st.chipOn]}>
                    <Text style={[st.chipTxt, recForm.priority === p && st.chipTxtOn]}>{p}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={st.lbl}>Applies to</Text>
              <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                {canPickFirm ? (
                  <Pressable onPress={() => setRecForm({ ...recForm, all_firms: true, company_id: "" })}
                    style={[st.chip, recForm.all_firms && st.chipOn]} testID="pd-rec-allfirms">
                    <Text style={[st.chipTxt, recForm.all_firms && st.chipTxtOn]}>All firms</Text>
                  </Pressable>
                ) : null}
                {companies.map((c) => (
                  <Pressable key={c.company_id}
                    onPress={() => setRecForm({ ...recForm, all_firms: false, company_id: c.company_id })}
                    style={[st.chip, !recForm.all_firms && recForm.company_id === c.company_id && st.chipOn]}>
                    <Text style={[st.chipTxt, !recForm.all_firms && recForm.company_id === c.company_id && st.chipTxtOn]}
                      numberOfLines={1}>{c.name}</Text>
                  </Pressable>
                ))}
              </View>
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <Pressable onPress={() => setShowRecAdd(false)} style={[st.mBtn, st.mBtnGhost]}>
                <Text style={st.mBtnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable onPress={createRec} disabled={recSaving || !recForm.title.trim()}
                style={[st.mBtn, st.mBtnPrimary, (!recForm.title.trim() || recSaving) && { opacity: 0.5 }]}
                testID="pd-rec-save">
                {recSaving ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.mBtnPrimaryTxt}>Create Recurring</Text>}
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
  recBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1,
    borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 11, paddingVertical: 8, backgroundColor: colors.surface,
  },
  recTxt: { fontSize: 11, fontWeight: "800", color: colors.brandPrimary },
  recHint: { fontSize: 10.5, color: colors.onSurfaceSecondary, marginBottom: 10 },
  recRow: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  recToggle: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 4,
  },
  recToggleOn: { backgroundColor: "#16A34A", borderColor: "#16A34A" },
  recToggleTxt: { fontSize: 9.5, fontWeight: "800", color: colors.onSurfaceSecondary },
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
