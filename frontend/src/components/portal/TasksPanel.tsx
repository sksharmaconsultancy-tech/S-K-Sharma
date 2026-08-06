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
  company_ids?: string[]; company_names?: string[];
  assignee_id?: string | null; assignee_name?: string | null;
  assignee_role?: string | null;
  assigned_by?: string | null; assigned_by_name?: string | null;
  assigned_by_role?: string | null;
  parent_task_id?: string | null; delegated_count?: number;
  due_date?: string | null; priority: string; status: string;
  created_by?: string | null;
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
  { key: "submitted", label: "Submitted" },
  { key: "done", label: "Done" },
  { key: "approved", label: "Approved" },
];

export default function TasksPanel({
  companyId, companies, canPickFirm, canCreate = true, role = "super_admin", myUserId = "",
}: {
  companyId: string | null; companies: CompanyLite[]; canPickFirm: boolean;
  /** Iter 501/502 — creation: Super Admin + Sub Super Admins (internal). */
  canCreate?: boolean;
  role?: string;
  myUserId?: string;
}) {
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
  const [firmDdOpen, setFirmDdOpen] = useState(false);
  // Iter 502 — hierarchy: assignees + multi-company + delegation + hub stats
  const isSuper = role === "super_admin";
  const isSub = role === "sub_admin";
  const [assignees, setAssignees] = useState<any[]>([]);
  const [assigneeKind, setAssigneeKind] = useState("none");
  const [assigneeId, setAssigneeId] = useState("");
  const [assigneeDd, setAssigneeDd] = useState(false);
  const [assigneeQ, setAssigneeQ] = useState("");
  const [multiCids, setMultiCids] = useState<string[]>([]);
  const [hub, setHub] = useState<any>(null);
  const [delegateFor, setDelegateFor] = useState<Task | null>(null);
  const [delegateTo, setDelegateTo] = useState("");
  const [delegateNote, setDelegateNote] = useState("");
  const [delegateQ, setDelegateQ] = useState("");
  const [delegating, setDelegating] = useState(false);

  const loadHub = useCallback(async () => {
    try { setHub(await api("/admin/portal-tasks/hub-dashboard")); } catch { /* noop */ }
  }, []);
  useEffect(() => { loadHub(); }, [loadHub]);

  const loadAssignees = useCallback(async () => {
    try {
      const r = await api<{ assignees: any[]; kind: string }>("/admin/portal-tasks/assignees");
      setAssignees(r.assignees || []); setAssigneeKind(r.kind);
    } catch { /* noop */ }
  }, []);
  useEffect(() => { if (canCreate) loadAssignees(); }, [canCreate, loadAssignees]);
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
          company_ids: multiCids.length ? multiCids : (form.company_id ? [form.company_id] : []),
          assignee_id: assigneeId || null,
        },
      });
      setShowAdd(false);
      setForm({ title: "", description: "", due_date: "", priority: "medium", company_id: companyId || "" });
      setAssigneeId(""); setMultiCids([]);
      load(); loadHub();
    } catch (e: any) {
      const msg = e?.message || "Failed to create task";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setSaving(false);
  };

  const submitDelegate = async () => {
    if (!delegateFor || !delegateTo) return;
    setDelegating(true);
    try {
      await api(`/admin/portal-tasks/${delegateFor.task_id}/delegate`, {
        method: "POST",
        body: { assignee_id: delegateTo, note: delegateNote || null },
      });
      setDelegateFor(null); setDelegateTo(""); setDelegateNote(""); setDelegateQ("");
      load(); loadHub();
    } catch (e: any) {
      const msg = e?.message || "Delegation failed";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setDelegating(false);
  };

  const setStatus = async (t: Task, status: string) => {
    try {
      await api(`/admin/portal-tasks/${t.task_id}`, { method: "PATCH", body: { status } });
      load(); loadHub();
    } catch (e: any) {
      const msg = e?.message || "Update failed";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
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
      {/* Iter 502 — hierarchy hub stats */}
      {hub?.role === "super_admin" ? (
        <View style={[st.countRow, { marginBottom: 8 }]}>
          {[
            { label: "Companies", v: hub.total_companies, c: "#1D4ED8" },
            { label: "Sub Super Admins", v: hub.total_sub_admins, c: "#7C3AED" },
            { label: "Awaiting Review", v: hub.awaiting_review, c: "#B45309" },
            { label: "Overdue", v: hub.overdue, c: "#B91C1C" },
            { label: "Escalated (High)", v: hub.escalated, c: "#B91C1C" },
          ].map((x) => (
            <View key={x.label} style={st.countCard}>
              <Text style={[st.countVal, { color: x.c }]}>{x.v ?? 0}</Text>
              <Text style={st.countLbl}>{x.label}</Text>
            </View>
          ))}
        </View>
      ) : hub?.role === "sub_admin" ? (
        <View style={{ marginBottom: 8 }}>
          <View style={st.countRow}>
            {[
              { label: "Pending", v: hub.pending, c: "#1D4ED8" },
              { label: "Completed", v: hub.completed, c: "#16A34A" },
              { label: "High Priority", v: hub.high_priority, c: "#B91C1C" },
              { label: "Due in 7 days", v: hub.upcoming_deadlines, c: "#B45309" },
              { label: "Team Progress", v: `${hub.team_done ?? 0}/${hub.team_total ?? 0}`, c: "#7C3AED" },
            ].map((x) => (
              <View key={x.label} style={st.countCard}>
                <Text style={[st.countVal, { color: x.c }]}>{String(x.v ?? 0)}</Text>
                <Text style={st.countLbl}>{x.label}</Text>
              </View>
            ))}
          </View>
          <Text style={st.meta}>
            🏢 Your firms: {(hub.assigned_companies || []).join(" · ") || "—"}
          </Text>
        </View>
      ) : null}

      {/* counters */}
      <View style={st.countRow}>
        {[
          { k: "open", label: "Open", c: "#1D4ED8" },
          { k: "in_progress", label: "In Progress", c: "#B45309" },
          { k: "submitted", label: "Submitted", c: "#7C3AED" },
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
        <Pressable onPress={openRec} style={[st.recBtn, !canCreate && { display: "none" }]} testID="pd-task-recurring">
          <Ionicons name="repeat" size={14} color={colors.brandPrimary} />
          <Text style={st.recTxt}>Recurring</Text>
        </Pressable>
        {canCreate ? (
          <Pressable onPress={() => setShowAdd(true)} style={st.addBtn} testID="pd-task-add">
            <Ionicons name="add" size={15} color="#fff" />
            <Text style={st.addTxt}>New Task</Text>
          </Pressable>
        ) : null}
      </View>

      {loading ? (
        <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 24 }} />
      ) : tasks.length === 0 ? (
        <Text style={st.dim}>{canCreate ? "No tasks. Create one with \u201CNew Task\u201D." : "No tasks yet."}</Text>
      ) : (
        tasks.map((t) => {
          const pui = PRIORITY_UI[t.priority] || PRIORITY_UI.medium;
          const overdue = !["done", "approved"].includes(t.status) && !!t.due_date && t.due_date < today;
          const closed = ["done", "approved"].includes(t.status);
          const assignedToMeBySuper = isSub && t.assignee_id === myUserId
            && t.assigned_by_role === "super_admin";
          const firms = (t.company_names && t.company_names.length
            ? t.company_names.join(" · ")
            : t.company_name) || "";
          return (
            <View key={t.task_id} style={st.taskCard} testID={`pd-task-${t.task_id}`}>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                  <Text style={[st.taskTitle, closed && { textDecorationLine: "line-through", color: colors.onSurfaceTertiary }]}>
                    {t.title}
                  </Text>
                  {t.source_rtask_id ? (
                    <Ionicons name="repeat" size={12} color={colors.onSurfaceTertiary} />
                  ) : null}
                  {t.parent_task_id ? (
                    <Ionicons name="git-branch-outline" size={12} color={colors.onSurfaceTertiary} />
                  ) : null}
                  <Text style={[st.prioChip, { color: pui.fg, backgroundColor: pui.bg }]}>
                    {t.priority.toUpperCase()}
                  </Text>
                  {t.status === "submitted" ? (
                    <Text style={[st.prioChip, { color: "#7C3AED", backgroundColor: "#F5F3FF" }]}>SUBMITTED FOR REVIEW</Text>
                  ) : t.status === "approved" ? (
                    <Text style={[st.prioChip, { color: "#15803D", backgroundColor: "#F0FDF4" }]}>✓ APPROVED</Text>
                  ) : null}
                </View>
                {t.description ? <Text style={st.taskDesc} numberOfLines={2}>{t.description}</Text> : null}
                <View style={{ flexDirection: "row", gap: 10, marginTop: 4, flexWrap: "wrap" }}>
                  {firms ? <Text style={st.meta}>🏢 {firms}</Text> : null}
                  {t.assignee_name ? (
                    <Text style={st.meta}>
                      👤 {t.assignee_name}{t.assignee_role === "sub_admin" ? " (Sub Admin)" : ""}
                    </Text>
                  ) : null}
                  {t.assigned_by_name && t.assignee_id ? (
                    <Text style={st.meta}>by {t.assigned_by_name}</Text>
                  ) : null}
                  {(t.delegated_count || 0) > 0 ? (
                    <Text style={st.meta}>↳ delegated ×{t.delegated_count}</Text>
                  ) : null}
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
                {!closed && t.status !== "submitted" ? (
                  assignedToMeBySuper ? (
                    <Pressable onPress={() => setStatus(t, "submitted")}
                      style={[st.stBtn, { borderColor: "#7C3AED" }]} testID={`pd-task-submit-${t.task_id}`}>
                      <Text style={[st.stBtnTxt, { color: "#7C3AED" }]}>Submit for Review</Text>
                    </Pressable>
                  ) : (
                    <Pressable onPress={() => setStatus(t, "done")}
                      style={[st.stBtn, { borderColor: "#16A34A" }]} testID={`pd-task-done-${t.task_id}`}>
                      <Text style={[st.stBtnTxt, { color: "#16A34A" }]}>✓ Done</Text>
                    </Pressable>
                  )
                ) : null}
                {t.status === "submitted" ? (
                  isSuper ? (
                    <>
                      <Pressable onPress={() => setStatus(t, "approved")}
                        style={[st.stBtn, { borderColor: "#16A34A", backgroundColor: "#F0FDF4" }]}
                        testID={`pd-task-approve-${t.task_id}`}>
                        <Text style={[st.stBtnTxt, { color: "#15803D" }]}>✓ Approve & Close</Text>
                      </Pressable>
                      <Pressable onPress={() => setStatus(t, "open")} style={st.stBtn}>
                        <Text style={st.stBtnTxt}>Reopen</Text>
                      </Pressable>
                    </>
                  ) : (
                    <Text style={st.meta}>Awaiting Super Admin</Text>
                  )
                ) : null}
                {closed ? (
                  <Pressable onPress={() => setStatus(t, "open")} style={st.stBtn}>
                    <Text style={st.stBtnTxt}>Reopen</Text>
                  </Pressable>
                ) : null}
                <View style={{ flexDirection: "row", gap: 10 }}>
                  {!closed && (isSuper || isSub) ? (
                    <Pressable onPress={() => { setDelegateFor(t); loadAssignees(); }} hitSlop={8}
                      testID={`pd-task-delegate-${t.task_id}`}>
                      <Ionicons name="person-add-outline" size={15} color={colors.brandPrimary} />
                    </Pressable>
                  ) : null}
                  <Pressable onPress={() => removeTask(t)} hitSlop={8}>
                    <Ionicons name="trash-outline" size={15} color="#B91C1C" />
                  </Pressable>
                </View>
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
              {/* Iter 502 — hierarchy: assign-to */}
              {canCreate && (isSuper || isSub) ? (
                <>
                  <Text style={st.lbl}>
                    {isSuper ? "Assign to Sub Super Admin (optional)" : "Assign to team member (optional)"}
                  </Text>
                  <Pressable onPress={() => setAssigneeDd((o) => !o)} style={st.ddField}
                    testID="pd-task-assignee-dd">
                    <Text style={[st.ddValue, !assigneeId && { color: colors.onSurfaceTertiary }]} numberOfLines={1}>
                      {assignees.find((a) => a.user_id === assigneeId)?.name
                        || (isSuper ? "Not assigned — my own task" : "Not assigned — internal task")}
                    </Text>
                    <Ionicons name={assigneeDd ? "chevron-up" : "chevron-down"} size={15} color={colors.onSurfaceSecondary} />
                  </Pressable>
                  {assigneeDd ? (
                    <View style={st.ddList}>
                      {assignees.length > 8 ? (
                        <TextInput style={[st.input, { margin: 6 }]} value={assigneeQ}
                          onChangeText={setAssigneeQ} placeholder="Search name / code…"
                          placeholderTextColor={colors.onSurfaceTertiary} />
                      ) : null}
                      <ScrollView style={{ maxHeight: 180 }} nestedScrollEnabled>
                        <Pressable onPress={() => { setAssigneeId(""); setMultiCids([]); setAssigneeDd(false); }}
                          style={[st.ddOpt, !assigneeId && st.ddOptOn]}>
                          <Text style={[st.ddOptTxt, !assigneeId && st.ddOptTxtOn]}>
                            {isSuper ? "Not assigned — my own task" : "Not assigned — internal task"}
                          </Text>
                        </Pressable>
                        {assignees
                          .filter((a) => !assigneeQ.trim()
                            || `${a.name} ${a.employee_code || ""}`.toLowerCase().includes(assigneeQ.trim().toLowerCase()))
                          .slice(0, 60)
                          .map((a) => (
                            <Pressable key={a.user_id}
                              onPress={() => { setAssigneeId(a.user_id); setAssigneeDd(false); }}
                              style={[st.ddOpt, assigneeId === a.user_id && st.ddOptOn]}
                              testID={`pd-task-assignee-${a.user_id}`}>
                              <View style={{ flex: 1, marginRight: 8 }}>
                                <Text style={[st.ddOptTxt, assigneeId === a.user_id && st.ddOptTxtOn]} numberOfLines={1}>
                                  {a.name}{a.employee_code ? ` (${a.employee_code})` : ""}
                                </Text>
                                <Text style={st.meta} numberOfLines={1}>
                                  {assigneeKind === "sub_admins"
                                    ? (a.company_ids === null ? "All firms" : (a.company_names || []).join(" · ") || "No firms assigned")
                                    : a.designation || a.role}
                                </Text>
                              </View>
                              {assigneeId === a.user_id ? (
                                <Ionicons name="checkmark" size={14} color={colors.brandPrimary} />
                              ) : null}
                            </Pressable>
                          ))}
                      </ScrollView>
                    </View>
                  ) : null}
                </>
              ) : null}
              {/* Iter 502 — multi-company selection when assigning to a Sub Super Admin */}
              {isSuper && assigneeId && assigneeKind === "sub_admins" ? (
                <>
                  <Text style={st.lbl}>Companies for this task (one or many)</Text>
                  <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
                    {(() => {
                      const a = assignees.find((x) => x.user_id === assigneeId);
                      const allowed = a?.company_ids === null
                        ? companies
                        : companies.filter((c) => (a?.company_ids || []).includes(c.company_id));
                      if (!allowed.length) return <Text style={st.meta}>No firms assigned to this Sub Super Admin.</Text>;
                      return allowed.map((c) => {
                        const on = multiCids.includes(c.company_id);
                        return (
                          <Pressable key={c.company_id}
                            onPress={() => setMultiCids((m) => on ? m.filter((x) => x !== c.company_id) : [...m, c.company_id])}
                            style={[st.chip, on && st.chipOn]} testID={`pd-task-mc-${c.company_id}`}>
                            <Text style={[st.chipTxt, on && st.chipTxtOn]} numberOfLines={1}>
                              {on ? "✓ " : ""}{c.name}
                            </Text>
                          </Pressable>
                        );
                      });
                    })()}
                  </View>
                </>
              ) : canPickFirm ? (
                <>
                  <Text style={st.lbl}>Firm (optional)</Text>
                  <Pressable onPress={() => setFirmDdOpen((o) => !o)}
                    style={st.ddField} testID="pd-task-firm-dd">
                    <Text style={[st.ddValue, !form.company_id && { color: colors.onSurfaceTertiary }]}
                      numberOfLines={1}>
                      {companies.find((c) => c.company_id === form.company_id)?.name
                        || "None — general task"}
                    </Text>
                    <Ionicons name={firmDdOpen ? "chevron-up" : "chevron-down"}
                      size={15} color={colors.onSurfaceSecondary} />
                  </Pressable>
                  {firmDdOpen ? (
                    <View style={st.ddList}>
                      <ScrollView style={{ maxHeight: 190 }} nestedScrollEnabled>
                        <Pressable
                          onPress={() => { setForm({ ...form, company_id: "" }); setFirmDdOpen(false); }}
                          style={[st.ddOpt, !form.company_id && st.ddOptOn]}
                          testID="pd-task-firm-none">
                          <Text style={[st.ddOptTxt, !form.company_id && st.ddOptTxtOn]}>
                            None — general task
                          </Text>
                          {!form.company_id ? (
                            <Ionicons name="checkmark" size={14} color={colors.brandPrimary} />
                          ) : null}
                        </Pressable>
                        {companies.map((c) => (
                          <Pressable key={c.company_id}
                            onPress={() => { setForm({ ...form, company_id: c.company_id }); setFirmDdOpen(false); }}
                            style={[st.ddOpt, form.company_id === c.company_id && st.ddOptOn]}
                            testID={`pd-task-firm-${c.company_id}`}>
                            <Text style={[st.ddOptTxt, form.company_id === c.company_id && st.ddOptTxtOn]}
                              numberOfLines={1}>{c.name}</Text>
                            {form.company_id === c.company_id ? (
                              <Ionicons name="checkmark" size={14} color={colors.brandPrimary} />
                            ) : null}
                          </Pressable>
                        ))}
                      </ScrollView>
                    </View>
                  ) : null}
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
      {/* Iter 502 — delegate modal */}
      <Modal visible={!!delegateFor} transparent animationType="fade" onRequestClose={() => setDelegateFor(null)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle}>
              {isSuper ? "Assign to Sub Super Admin" : "Delegate to team member"}
            </Text>
            <Text style={st.taskDesc} numberOfLines={2}>📌 {delegateFor?.title}</Text>
            <TextInput style={[st.input, { marginTop: 10 }]} value={delegateQ}
              onChangeText={setDelegateQ} placeholder="Search name / code…"
              placeholderTextColor={colors.onSurfaceTertiary} testID="pd-delegate-search" />
            <ScrollView style={{ maxHeight: 240, marginTop: 6 }} nestedScrollEnabled>
              {assignees
                .filter((a) => !delegateQ.trim()
                  || `${a.name} ${a.employee_code || ""}`.toLowerCase().includes(delegateQ.trim().toLowerCase()))
                .slice(0, 60)
                .map((a) => (
                  <Pressable key={a.user_id} onPress={() => setDelegateTo(a.user_id)}
                    style={[st.ddOpt, delegateTo === a.user_id && st.ddOptOn]}
                    testID={`pd-delegate-${a.user_id}`}>
                    <View style={{ flex: 1, marginRight: 8 }}>
                      <Text style={[st.ddOptTxt, delegateTo === a.user_id && st.ddOptTxtOn]} numberOfLines={1}>
                        {a.name}{a.employee_code ? ` (${a.employee_code})` : ""}
                      </Text>
                      <Text style={st.meta} numberOfLines={1}>
                        {assigneeKind === "sub_admins"
                          ? (a.company_ids === null ? "All firms" : (a.company_names || []).join(" · "))
                          : a.designation || a.role}
                      </Text>
                    </View>
                    {delegateTo === a.user_id ? (
                      <Ionicons name="checkmark" size={14} color={colors.brandPrimary} />
                    ) : null}
                  </Pressable>
                ))}
            </ScrollView>
            <Text style={st.lbl}>Instructions (optional)</Text>
            <TextInput style={[st.input, { height: 56 }]} value={delegateNote} multiline
              onChangeText={setDelegateNote} placeholder="What exactly should they do?"
              placeholderTextColor={colors.onSurfaceTertiary} />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <Pressable onPress={() => { setDelegateFor(null); setDelegateTo(""); }} style={[st.mBtn, st.mBtnGhost]}>
                <Text style={st.mBtnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable onPress={submitDelegate} disabled={delegating || !delegateTo}
                style={[st.mBtn, st.mBtnPrimary, (!delegateTo || delegating) && { opacity: 0.5 }]}
                testID="pd-delegate-save">
                {delegating ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.mBtnPrimaryTxt}>Assign Task</Text>}
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
  ddField: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 9, backgroundColor: colors.background,
  },
  ddValue: { fontSize: 12.5, color: colors.onSurface, flex: 1, marginRight: 8 },
  ddList: {
    borderWidth: 1, borderColor: colors.divider, borderRadius: radius.md,
    backgroundColor: colors.surface, marginTop: 4, overflow: "hidden",
  },
  ddOpt: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 10, paddingVertical: 9,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  ddOptOn: { backgroundColor: `${colors.brandPrimary}10` },
  ddOptTxt: { fontSize: 12, color: colors.onSurface, flex: 1, marginRight: 8 },
  ddOptTxtOn: { fontWeight: "800", color: colors.brandPrimary },
  mBtn: { flex: 1, borderRadius: radius.md, paddingVertical: 11, alignItems: "center" },
  mBtnGhost: { borderWidth: 1, borderColor: colors.divider },
  mBtnGhostTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  mBtnPrimary: { backgroundColor: colors.brandPrimary },
  mBtnPrimaryTxt: { fontSize: 12.5, fontWeight: "800", color: "#fff" },
});
