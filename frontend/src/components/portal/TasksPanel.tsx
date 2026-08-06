// Phase 2 — Task Management panel for the portal dashboard.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, Modal,
  ActivityIndicator, ScrollView, Alert, Platform, Image,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";

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
  attachments_count?: number;
  due_date?: string | null; priority: string; status: string;
  created_by?: string | null;
  created_by_name?: string | null; source_rtask_id?: string | null;
  // Iter 505 — content-edit tracking
  edited_count?: number; last_edited_by_name?: string | null;
  last_edited_at?: string | null;
  // Iter 508 — Later + overdue-reason workflow
  later_reason?: string | null; later_by_name?: string | null;
  last_overdue_reason?: string | null;
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
  { key: "later", label: "Later" },
  { key: "overdue", label: "Overdue" },
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
  const [firmQ, setFirmQ] = useState("");
  // Iter 507 — filter box for the assignee-scoped firm multi-select.
  const [mcQ, setMcQ] = useState("");
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

  // Iter 508 — "Later" (with mandatory reason) modal state.
  const [laterFor, setLaterFor] = useState<Task | null>(null);
  const [laterReason, setLaterReason] = useState("");
  const [laterSaving, setLaterSaving] = useState(false);

  const submitLater = async () => {
    if (!laterFor || !laterReason.trim()) return;
    setLaterSaving(true);
    try {
      await api(`/admin/portal-tasks/${laterFor.task_id}/later`, {
        method: "POST", body: { reason: laterReason.trim() },
      });
      setLaterFor(null); setLaterReason("");
      load(); loadHub();
    } catch (e: any) {
      const msg = e?.message || "Failed to mark Later";
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setLaterSaving(false);
  };

  // Iter 505 — edit-task modal state + per-task edit history viewer.
  const [editFor, setEditFor] = useState<Task | null>(null);
  const [historyFor, setHistoryFor] = useState<Task | null>(null);
  const [historyItems, setHistoryItems] = useState<any[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const createTask = async () => {
    if (!form.title.trim()) return;
    setSaving(true);
    try {
      if (editFor) {
        // Iter 505 (user request) — EDIT task content; backend keeps a
        // field-by-field edit log in the task audit trail.
        await api(`/admin/portal-tasks/${editFor.task_id}`, {
          method: "PATCH",
          body: {
            title: form.title, description: form.description || "",
            due_date: form.due_date || "", priority: form.priority,
            company_id: form.company_id || "",
          },
        });
      } else {
        // Iter 506 (user bug — "Not able to assign task from PWA"):
        // when assigning to a scoped Sub Super Admin, NEVER silently fall
        // back to the currently selected firm (it may be outside the
        // assignee's scope → backend 400). Send only the picked firms.
        const scopedAssign = !!assigneeId && assigneeKind === "sub_admins";
        await api("/admin/portal-tasks", {
          method: "POST",
          body: {
            title: form.title, description: form.description || null,
            due_date: form.due_date || null, priority: form.priority,
            company_id: scopedAssign ? null : (form.company_id || null),
            company_ids: scopedAssign
              ? multiCids
              : (multiCids.length ? multiCids : (form.company_id ? [form.company_id] : [])),
            assignee_id: assigneeId || null,
          },
        });
      }
      setShowAdd(false); setEditFor(null);
      setForm({ title: "", description: "", due_date: "", priority: "medium", company_id: companyId || "" });
      setAssigneeId(""); setMultiCids([]);
      load(); loadHub();
    } catch (e: any) {
      const msg = e?.message || (editFor ? "Failed to save changes" : "Failed to create task");
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Error", msg);
    }
    setSaving(false);
  };

  // Iter 505 — edit-task modal helpers.
  const openEdit = (t: Task) => {
    setEditFor(t);
    setForm({
      title: t.title || "", description: t.description || "",
      due_date: t.due_date || "", priority: t.priority || "medium",
      company_id: t.company_id || "",
    });
    setShowAdd(true);
  };

  const openHistory = async (t: Task) => {
    setHistoryFor(t); setHistoryItems([]); setHistoryLoading(true);
    try {
      const r = await api<{ audit: any[] }>(`/admin/portal-tasks/${t.task_id}/audit`);
      setHistoryItems(r.audit || []);
    } catch { /* noop */ }
    setHistoryLoading(false);
  };

  // Iter 503 — attachments (photo / PDF evidence)
  const [attFor, setAttFor] = useState<Task | null>(null);
  const [attList, setAttList] = useState<any[]>([]);
  const [attLoading, setAttLoading] = useState(false);
  const [attUploading, setAttUploading] = useState(false);
  const [attPreview, setAttPreview] = useState<{ name: string; uri: string } | null>(null);

  const openAttachments = async (t: Task) => {
    setAttFor(t); setAttList([]); setAttLoading(true);
    try {
      const r = await api<{ attachments: any[] }>(`/admin/portal-tasks/${t.task_id}/attachments`);
      setAttList(r.attachments || []);
    } catch { /* noop */ }
    setAttLoading(false);
  };

  const uploadAttachment = async () => {
    if (!attFor) return;
    const res = await DocumentPicker.getDocumentAsync({
      type: ["image/*", "application/pdf"], copyToCacheDirectory: true,
    });
    if (res.canceled || !res.assets?.length) return;
    const asset = res.assets[0];
    if ((asset.size || 0) > 10 * 1024 * 1024) {
      const m = "File exceeds the 10 MB limit";
      if (Platform.OS === "web") window.alert(m); else Alert.alert("Error", m);
      return;
    }
    setAttUploading(true);
    try {
      const blob = await (await fetch(asset.uri)).blob();
      const b64 = await new Promise<string>((resolve, reject) => {
        const fr = new FileReader();
        fr.onload = () => { const s = String(fr.result || ""); resolve(s.includes(",") ? s.split(",")[1] : s); };
        fr.onerror = reject;
        fr.readAsDataURL(blob);
      });
      await api(`/admin/portal-tasks/${attFor.task_id}/attachments`, {
        method: "POST",
        body: { filename: asset.name, mime: asset.mimeType || blob.type || "application/octet-stream", file_base64: b64 },
      });
      await openAttachments(attFor);
      load();
    } catch (e: any) {
      const m = e?.message || "Upload failed";
      if (Platform.OS === "web") window.alert(m); else Alert.alert("Error", m);
    }
    setAttUploading(false);
  };

  const viewAttachment = async (a: any) => {
    try {
      const r = await api<any>(`/admin/portal-tasks/attachments/${a.att_id}`);
      const uri = `data:${r.mime};base64,${r.file_base64}`;
      if ((r.mime || "").startsWith("image/")) {
        setAttPreview({ name: r.filename, uri });
      } else if (Platform.OS === "web") {
        const bytes = atob(r.file_base64);
        const arr = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
        const url = URL.createObjectURL(new Blob([arr], { type: r.mime }));
        const link = document.createElement("a");
        link.href = url; link.download = r.filename; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      }
    } catch { /* noop */ }
  };

  const deleteAttachment = async (a: any) => {
    try {
      await api(`/admin/portal-tasks/attachments/${a.att_id}`, { method: "DELETE" });
      if (attFor) await openAttachments(attFor);
      load();
    } catch (e: any) {
      const m = e?.message || "Delete failed";
      if (Platform.OS === "web") window.alert(m); else Alert.alert("Error", m);
    }
  };

  const submitForReview = (t: Task) => {
    // Nudge for evidence before submitting to the Super Admin.
    if (!(t.attachments_count || 0)) {
      const msg = "No proof attached yet. Attach a photo / PDF as evidence before submitting?";
      if (Platform.OS === "web") {
        if (window.confirm(msg)) { openAttachments(t); return; }
      }
    }
    setStatus(t, "submitted");
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
      {/* Iter 502 — hierarchy hub stats (Iter 508: counts are tappable and
          open the matching task list below) */}
      {hub?.role === "super_admin" ? (
        <View style={[st.countRow, { marginBottom: 8 }]}>
          {[
            { label: "Companies", v: hub.total_companies, c: "#1D4ED8" },
            { label: "Sub Super Admins", v: hub.total_sub_admins, c: "#7C3AED" },
            { label: "Awaiting Review", v: hub.awaiting_review, c: "#B45309", f: "submitted" },
            { label: "Overdue", v: hub.overdue, c: "#B91C1C", f: "overdue" },
            { label: "Escalated (High)", v: hub.escalated, c: "#B91C1C", f: "overdue" },
          ].map((x: any) => (
            <Pressable key={x.label} style={st.countCard}
              disabled={!x.f} onPress={() => x.f && setFilter(x.f)}
              testID={`pd-hub-${x.label.replace(/\W+/g, "-").toLowerCase()}`}>
              <Text style={[st.countVal, { color: x.c }]}>{x.v ?? 0}</Text>
              <Text style={st.countLbl}>{x.label}</Text>
            </Pressable>
          ))}
        </View>
      ) : hub?.role === "sub_admin" ? (
        <View style={{ marginBottom: 8 }}>
          <View style={st.countRow}>
            {[
              { label: "Pending", v: hub.pending, c: "#1D4ED8", f: "open" },
              { label: "Completed", v: hub.completed, c: "#16A34A", f: "done" },
              { label: "High Priority", v: hub.high_priority, c: "#B91C1C" },
              { label: "Due in 7 days", v: hub.upcoming_deadlines, c: "#B45309" },
              { label: "Team Progress", v: `${hub.team_done ?? 0}/${hub.team_total ?? 0}`, c: "#7C3AED" },
            ].map((x: any) => (
              <Pressable key={x.label} style={st.countCard}
                disabled={!x.f} onPress={() => x.f && setFilter(x.f)}
                testID={`pd-hub-${x.label.replace(/\W+/g, "-").toLowerCase()}`}>
                <Text style={[st.countVal, { color: x.c }]}>{String(x.v ?? 0)}</Text>
                <Text style={st.countLbl}>{x.label}</Text>
              </Pressable>
            ))}
          </View>
          <Text style={st.meta}>
            🏢 Your firms: {(hub.assigned_companies || []).join(" · ") || "—"}
          </Text>
        </View>
      ) : null}

      {/* counters — Iter 508: tap a number to open that list */}
      <View style={st.countRow}>
        {[
          { k: "open", label: "Open", c: "#1D4ED8" },
          { k: "in_progress", label: "In Progress", c: "#B45309" },
          { k: "later", label: "Later", c: "#6B7280" },
          { k: "submitted", label: "Submitted", c: "#7C3AED" },
          { k: "done", label: "Done", c: "#16A34A" },
          { k: "overdue", label: "Overdue", c: "#B91C1C" },
        ].map((x) => (
          <Pressable key={x.k} onPress={() => setFilter(x.k)}
            style={[st.countCard, filter === x.k && { borderColor: x.c, borderWidth: 1.5 }]}
            testID={`pd-count-${x.k}`}>
            <Text style={[st.countVal, { color: x.c }]}>{counts[x.k] ?? 0}</Text>
            <Text style={st.countLbl}>{x.label}</Text>
          </Pressable>
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
          <Pressable onPress={() => {
            setEditFor(null);
            setForm({ title: "", description: "", due_date: "", priority: "medium", company_id: companyId || "" });
            setShowAdd(true);
          }} style={st.addBtn} testID="pd-task-add">
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
                  ) : t.status === "later" ? (
                    <Text style={[st.prioChip, { color: "#374151", backgroundColor: "#F3F4F6" }]}>⏸ LATER</Text>
                  ) : null}
                </View>
                {t.description ? <Text style={st.taskDesc} numberOfLines={2}>{t.description}</Text> : null}
                {/* Iter 508 — reasons visible to the Super Admin */}
                {t.status === "later" && t.later_reason ? (
                  <Text style={[st.meta, { color: "#374151", marginTop: 2 }]} numberOfLines={2}>
                    ⏸ Later{t.later_by_name ? ` (${t.later_by_name})` : ""}: {t.later_reason}
                  </Text>
                ) : null}
                {t.last_overdue_reason ? (
                  <Text style={[st.meta, { color: "#B45309", marginTop: 2 }]} numberOfLines={2}>
                    ⚠ Late reason: {t.last_overdue_reason}
                  </Text>
                ) : null}
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
                  {/* Iter 505 — edited badge → tap for the full edit log */}
                  {(t.edited_count || 0) > 0 ? (
                    <Pressable onPress={() => openHistory(t)} hitSlop={6}
                      testID={`pd-task-history-${t.task_id}`}>
                      <Text style={[st.meta, { color: "#B45309", fontWeight: "800" }]}>
                        ✎ edited ×{t.edited_count} — view log
                      </Text>
                    </Pressable>
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
                    <Pressable onPress={() => submitForReview(t)}
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
                {/* Iter 508 — allotted Sub Admin: Done OR Later w/ reason */}
                {!closed && t.status !== "submitted" && t.status !== "later"
                  && isSub && t.assignee_id === myUserId ? (
                  <Pressable onPress={() => { setLaterFor(t); setLaterReason(""); }}
                    style={st.stBtn} testID={`pd-task-later-${t.task_id}`}>
                    <Text style={st.stBtnTxt}>⏸ Later…</Text>
                  </Pressable>
                ) : null}
                {t.status === "later" && (isSuper || t.assignee_id === myUserId) ? (
                  <Pressable onPress={() => setStatus(t, "in_progress")}
                    style={st.stBtn} testID={`pd-task-resume-${t.task_id}`}>
                    <Text style={st.stBtnTxt}>▶ Resume</Text>
                  </Pressable>
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
                  {/* Iter 505 (user request) — EDIT task content any time */}
                  <Pressable onPress={() => openEdit(t)} hitSlop={8}
                    testID={`pd-task-edit-${t.task_id}`}>
                    <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
                  </Pressable>
                  <Pressable onPress={() => openAttachments(t)} hitSlop={8}
                    testID={`pd-task-att-${t.task_id}`}
                    style={{ flexDirection: "row", alignItems: "center", gap: 2 }}>
                    <Ionicons name="attach-outline" size={16} color={colors.brandPrimary} />
                    {(t.attachments_count || 0) > 0 ? (
                      <Text style={[st.meta, { color: colors.brandPrimary, fontWeight: "800" }]}>
                        {t.attachments_count}
                      </Text>
                    ) : null}
                  </Pressable>
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

      {/* Add / Edit modal */}
      <Modal visible={showAdd} transparent animationType="fade"
        onRequestClose={() => { setShowAdd(false); setEditFor(null); }}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle}>{editFor ? "Edit Task" : "New Task"}</Text>
            {editFor ? (
              <Text style={[st.meta, { marginBottom: 6 }]}>
                Changes are saved to the task&apos;s edit log (who / when / what).
              </Text>
            ) : null}
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
              {/* Iter 502 — hierarchy: assign-to (creation only) */}
              {!editFor && canCreate && (isSuper || isSub) ? (
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
                        <Pressable onPress={() => { setAssigneeId(""); setMultiCids([]); setMcQ(""); setAssigneeDd(false); }}
                          testID="pd-task-assignee-none"
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
                              onPress={() => {
                                setAssigneeId(a.user_id); setAssigneeDd(false); setMcQ("");
                                // Iter 506 — auto-preselect firms inside the
                                // assignee's scope so Create can't 400.
                                if (isSuper && assigneeKind === "sub_admins") {
                                  if (a.company_ids === null) {
                                    setMultiCids(form.company_id ? [form.company_id] : []);
                                  } else if (form.company_id && (a.company_ids || []).includes(form.company_id)) {
                                    setMultiCids([form.company_id]);
                                  } else {
                                    setMultiCids((a.company_ids || []).slice(0, 1));
                                  }
                                }
                              }}
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
              {/* Iter 502/507 — firm selection when assigning to a Sub Super
                  Admin: switches to a searchable multi-select restricted to
                  THAT sub admin's assigned firms (user: "After the Selection
                  of Sub Super Admin Firm Selection Option May Change"). */}
              {!editFor && isSuper && assigneeId && assigneeKind === "sub_admins" ? (
                (() => {
                  const a = assignees.find((x) => x.user_id === assigneeId);
                  const allowed = a?.company_ids === null
                    ? companies
                    : companies.filter((c) => (a?.company_ids || []).includes(c.company_id));
                  const shown = allowed.filter((c) => !mcQ.trim()
                    || c.name.toLowerCase().includes(mcQ.trim().toLowerCase()));
                  return (
                    <>
                      <Text style={st.lbl}>
                        Firms for this task — {a?.name || "assignee"}&apos;s firms only
                        {multiCids.length ? `  (${multiCids.length} selected)` : ""}
                      </Text>
                      {!allowed.length ? (
                        <Text style={st.meta}>No firms assigned to this Sub Super Admin.</Text>
                      ) : (
                        <View style={st.mcBox}>
                          <View style={{ flexDirection: "row", gap: 6, alignItems: "center", padding: 6 }}>
                            {allowed.length > 6 ? (
                              <TextInput style={[st.input, { flex: 1, marginVertical: 0 }]} value={mcQ}
                                onChangeText={setMcQ} placeholder="🔍 Filter firms…"
                                placeholderTextColor={colors.onSurfaceTertiary}
                                testID="pd-task-mc-filter" />
                            ) : <View style={{ flex: 1 }} />}
                            <Pressable
                              onPress={() => setMultiCids(
                                multiCids.length === allowed.length ? [] : allowed.map((c) => c.company_id))}
                              style={[st.chip, multiCids.length === allowed.length && st.chipOn]}
                              testID="pd-task-mc-all">
                              <Text style={[st.chipTxt, multiCids.length === allowed.length && st.chipTxtOn]}>
                                {multiCids.length === allowed.length ? "✓ All" : `All (${allowed.length})`}
                              </Text>
                            </Pressable>
                          </View>
                          <ScrollView style={{ maxHeight: 170 }} nestedScrollEnabled>
                            {shown.map((c) => {
                              const on = multiCids.includes(c.company_id);
                              return (
                                <Pressable key={c.company_id}
                                  onPress={() => setMultiCids((m) => on
                                    ? m.filter((x) => x !== c.company_id) : [...m, c.company_id])}
                                  style={[st.ddOpt, on && st.ddOptOn]}
                                  testID={`pd-task-mc-${c.company_id}`}>
                                  <Ionicons name={on ? "checkbox" : "square-outline"} size={16}
                                    color={on ? colors.brandPrimary : colors.onSurfaceTertiary} />
                                  <Text style={[st.ddOptTxt, { flex: 1, marginLeft: 8 }, on && st.ddOptTxtOn]}
                                    numberOfLines={1}>
                                    {c.name}
                                  </Text>
                                </Pressable>
                              );
                            })}
                            {!shown.length ? (
                              <Text style={[st.meta, { padding: 10 }]}>No firm matches “{mcQ}”.</Text>
                            ) : null}
                          </ScrollView>
                        </View>
                      )}
                    </>
                  );
                })()
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
                      {/* Iter 503 (user request) — filter/search firms */}
                      <TextInput
                        style={[st.input, { margin: 6 }]}
                        value={firmQ}
                        onChangeText={setFirmQ}
                        placeholder="🔍 Filter firms…"
                        placeholderTextColor={colors.onSurfaceTertiary}
                        testID="pd-task-firm-filter"
                      />
                      <ScrollView style={{ maxHeight: 190 }} nestedScrollEnabled>
                        <Pressable
                          onPress={() => { setForm({ ...form, company_id: "" }); setFirmDdOpen(false); setFirmQ(""); }}
                          style={[st.ddOpt, !form.company_id && st.ddOptOn]}
                          testID="pd-task-firm-none">
                          <Text style={[st.ddOptTxt, !form.company_id && st.ddOptTxtOn]}>
                            None — general task
                          </Text>
                          {!form.company_id ? (
                            <Ionicons name="checkmark" size={14} color={colors.brandPrimary} />
                          ) : null}
                        </Pressable>
                        {companies
                          .filter((c) => !firmQ.trim()
                            || c.name.toLowerCase().includes(firmQ.trim().toLowerCase()))
                          .map((c) => (
                          <Pressable key={c.company_id}
                            onPress={() => { setForm({ ...form, company_id: c.company_id }); setFirmDdOpen(false); setFirmQ(""); }}
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
              <Pressable onPress={() => { setShowAdd(false); setEditFor(null); }} style={[st.mBtn, st.mBtnGhost]}>
                <Text style={st.mBtnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable onPress={createTask} disabled={saving || !form.title.trim()}
                style={[st.mBtn, st.mBtnPrimary, (!form.title.trim() || saving) && { opacity: 0.5 }]}
                testID="pd-task-save">
                {saving ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.mBtnPrimaryTxt}>{editFor ? "Save Changes" : "Create Task"}</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
      {/* Iter 508 — Mark as Later (reason required) */}
      <Modal visible={!!laterFor} transparent animationType="fade"
        onRequestClose={() => setLaterFor(null)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle} numberOfLines={1}>
              ⏸ Mark as Later — {laterFor?.title}
            </Text>
            <Text style={st.lbl}>Reason (required — the Super Admin will see this)</Text>
            <TextInput
              style={[st.input, { minHeight: 70, textAlignVertical: "top" }]}
              value={laterReason} onChangeText={setLaterReason} multiline
              placeholder="e.g. Awaiting client documents / senior approval…"
              placeholderTextColor={colors.onSurfaceTertiary}
              testID="pd-later-reason"
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <Pressable onPress={() => setLaterFor(null)} style={[st.mBtn, st.mBtnGhost]}>
                <Text style={st.mBtnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable onPress={submitLater} disabled={laterSaving || !laterReason.trim()}
                style={[st.mBtn, st.mBtnPrimary, (!laterReason.trim() || laterSaving) && { opacity: 0.5 }]}
                testID="pd-later-save">
                {laterSaving ? <ActivityIndicator color="#fff" size="small" />
                  : <Text style={st.mBtnPrimaryTxt}>Mark Later</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
      {/* Iter 505 — edit-log / history modal */}
      <Modal visible={!!historyFor} transparent animationType="fade" onRequestClose={() => setHistoryFor(null)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle} numberOfLines={1}>
              Edit Log — {historyFor?.title}
            </Text>
            {historyLoading ? (
              <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 20 }} />
            ) : (
              <ScrollView style={{ maxHeight: 420 }}>
                {historyItems.length === 0 ? (
                  <Text style={st.dim}>No history recorded yet.</Text>
                ) : historyItems.map((h) => (
                  <View key={h.audit_id} style={{
                    borderBottomWidth: StyleSheet.hairlineWidth,
                    borderBottomColor: colors.divider, paddingVertical: 8, gap: 2,
                  }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <Text style={[st.prioChip, {
                        color: h.action === "edited" ? "#B45309" : colors.brandPrimary,
                        backgroundColor: h.action === "edited" ? "#FFFBEB" : "#EFF6FF",
                      }]}>
                        {String(h.action || "").toUpperCase()}
                      </Text>
                      <Text style={st.meta}>
                        {h.actor_name} · {(h.at || "").slice(0, 16).replace("T", " ")}
                      </Text>
                    </View>
                    {h.details ? (
                      <Text style={{ fontSize: 11.5, color: colors.onSurfaceSecondary }}>
                        {h.details}
                      </Text>
                    ) : null}
                  </View>
                ))}
              </ScrollView>
            )}
            <Pressable onPress={() => setHistoryFor(null)}
              style={[st.mBtn, st.mBtnGhost, { marginTop: 12 }]} testID="pd-history-close">
              <Text style={st.mBtnGhostTxt}>Close</Text>
            </Pressable>
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

      {/* Iter 503 — attachments modal */}
      <Modal visible={!!attFor} transparent animationType="fade" onRequestClose={() => setAttFor(null)}>
        <View style={st.overlay}>
          <View style={st.modal}>
            <Text style={st.modalTitle}>📎 Attachments — Proof / Evidence</Text>
            <Text style={st.taskDesc} numberOfLines={2}>📌 {attFor?.title}</Text>
            {attLoading ? (
              <ActivityIndicator style={{ marginVertical: 24 }} color={colors.brandPrimary} />
            ) : (
              <ScrollView style={{ maxHeight: 280, marginTop: 10 }} nestedScrollEnabled>
                {attList.length === 0 ? (
                  <Text style={[st.meta, { paddingVertical: 14 }]}>
                    No attachments yet. Upload a photo or PDF as proof of completion.
                  </Text>
                ) : attList.map((a) => (
                  <View key={a.att_id} style={st.attRow}>
                    <Ionicons
                      name={(a.mime || "").startsWith("image/") ? "image-outline" : "document-text-outline"}
                      size={18} color={colors.brandPrimary} />
                    <View style={{ flex: 1, marginHorizontal: 8 }}>
                      <Text style={st.ddOptTxt} numberOfLines={1}>{a.filename}</Text>
                      <Text style={st.meta} numberOfLines={1}>
                        {Math.round((a.size || 0) / 1024)} KB · {a.uploaded_by_name} · {(a.at || "").slice(0, 16).replace("T", " ")}
                      </Text>
                    </View>
                    <Pressable onPress={() => viewAttachment(a)} hitSlop={8} style={{ marginRight: 10 }}
                      testID={`pd-att-view-${a.att_id}`}>
                      <Ionicons name={(a.mime || "").startsWith("image/") ? "eye-outline" : "download-outline"}
                        size={16} color={colors.brandPrimary} />
                    </Pressable>
                    <Pressable onPress={() => deleteAttachment(a)} hitSlop={8}
                      testID={`pd-att-del-${a.att_id}`}>
                      <Ionicons name="trash-outline" size={15} color="#B91C1C" />
                    </Pressable>
                  </View>
                ))}
              </ScrollView>
            )}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 14 }}>
              <Pressable onPress={() => setAttFor(null)} style={[st.mBtn, st.mBtnGhost]}>
                <Text style={st.mBtnGhostTxt}>Close</Text>
              </Pressable>
              <Pressable onPress={uploadAttachment} disabled={attUploading}
                style={[st.mBtn, st.mBtnPrimary, attUploading && { opacity: 0.5 }]}
                testID="pd-att-upload">
                {attUploading ? <ActivityIndicator color="#fff" size="small" /> : (
                  <Text style={st.mBtnPrimaryTxt}>+ Upload Photo / PDF</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* image preview */}
      <Modal visible={!!attPreview} transparent animationType="fade" onRequestClose={() => setAttPreview(null)}>
        <Pressable style={[st.overlay, { justifyContent: "center" }]} onPress={() => setAttPreview(null)}>
          <View style={{ alignItems: "center", padding: 10 }}>
            {attPreview ? (
              <Image source={{ uri: attPreview.uri }}
                style={{ width: 640, height: 480, maxWidth: "96%", borderRadius: 10, backgroundColor: "#000" }}
                resizeMode="contain" />
            ) : null}
            <Text style={{ color: "#fff", fontSize: 12, fontWeight: "700", marginTop: 8 }}>
              {attPreview?.name} — tap anywhere to close
            </Text>
          </View>
        </Pressable>
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
  // Iter 507 — container for the assignee-scoped firm multi-select.
  mcBox: {
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
  attRow: {
    flexDirection: "row", alignItems: "center", paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  mBtn: { flex: 1, borderRadius: radius.md, paddingVertical: 11, alignItems: "center" },
  mBtnGhost: { borderWidth: 1, borderColor: colors.divider },
  mBtnGhostTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  mBtnPrimary: { backgroundColor: colors.brandPrimary },
  mBtnPrimaryTxt: { fontSize: 12.5, fontWeight: "800", color: "#fff" },
});
