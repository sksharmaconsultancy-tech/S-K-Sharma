/**
 * PunchRepairModal — Iter 233 (user request).
 *
 * Opened by tapping ANY day cell on the Attendance Grid (IN/OUT report).
 * Lets the admin repair that exact employee-day directly:
 *   • see every recorded punch (time, IN/OUT, source),
 *   • add the missing IN or OUT punch,
 *   • edit a wrong punch time/kind,
 *   • delete a stray punch.
 * Backend: existing manual-punch endpoints (full audit trail preserved).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

type Punch = {
  record_id: string;
  kind: "in" | "out";
  at: string;
  source?: string;
  status?: string;
  manual_reason?: string;
};

const fmtDateDmy = (iso: string): string => {
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
};

const srcLabel = (s?: string): string => {
  const v = (s || "").toLowerCase();
  if (v.startsWith("zkteco") || v.startsWith("import") || v.includes("bio")) return "Machine";
  if (v.startsWith("manual")) return "Manual";
  return "App";
};

export default function PunchRepairModal({
  userId,
  empName,
  dateIso,
  onClose,
  onSaved,
}: {
  userId: string;
  empName: string;
  dateIso: string; // YYYY-MM-DD
  onClose: (changed: boolean) => void;
  onSaved?: () => void; // live grid refresh after every save/delete
}) {
  const [punches, setPunches] = useState<Punch[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [changed, setChanged] = useState(false);

  // Add / edit form
  const [formOpen, setFormOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [kind, setKind] = useState<"in" | "out">("in");
  const [time, setTime] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ records: Punch[] }>(
        `/admin/attendance/history?user_id=${userId}&date_from=${dateIso}&date_to=${dateIso}&limit=100`,
      );
      // Show real punches only (hide rejected / auto-ignored noise).
      const visible = (r.records || []).filter(
        (p) => !["rejected", "auto_ignored"].includes(String(p.status || "")),
      );
      setPunches(visible.sort((a, b) => (a.at || "").localeCompare(b.at || "")));
    } catch {
      setPunches([]);
    } finally {
      setLoading(false);
    }
  }, [userId, dateIso]);

  useEffect(() => {
    load();
  }, [load]);

  const hasIn = punches.some((p) => p.kind === "in");
  const hasOut = punches.some((p) => p.kind === "out");

  const openAdd = (k: "in" | "out") => {
    setEditId(null);
    setKind(k);
    setTime("");
    setReason("Missing punch repair");
    setErr("");
    setFormOpen(true);
  };
  const openEdit = (p: Punch) => {
    setEditId(p.record_id);
    setKind(p.kind);
    setTime((p.at || "").slice(11, 16));
    setReason("Punch correction");
    setErr("");
    setFormOpen(true);
  };

  const fmtTimeInput = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, 4);
    setTime(digits.length > 2 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits);
  };

  const save = async () => {
    if (!/^\d{2}:\d{2}$/.test(time)) {
      setErr("Enter time as HH:MM (24-hour), e.g. 09:05");
      return;
    }
    const [hh, mm] = time.split(":").map(Number);
    if (hh > 23 || mm > 59) {
      setErr("Invalid time");
      return;
    }
    if (!reason.trim()) {
      setErr("Reason is required for audit");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const at = `${dateIso}T${time}:00`;
      if (editId) {
        await api(`/admin/attendance/${editId}`, {
          method: "PATCH",
          body: { at, kind, reason: reason.trim() },
        });
      } else {
        await api(`/admin/attendance/manual-punch`, {
          method: "POST",
          body: { user_id: userId, kind, at, reason: reason.trim() },
        });
      }
      setChanged(true);
      setFormOpen(false);
      await load();
      onSaved?.(); // refresh the grid behind the modal immediately
    } catch (e: any) {
      setErr(e?.message || "Failed to save punch");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: Punch) => {
    const doDelete = async () => {
      setBusy(true);
      try {
        await api(
          `/admin/attendance/${p.record_id}?reason=${encodeURIComponent("Deleted via grid repair")}`,
          { method: "DELETE" },
        );
        setChanged(true);
        await load();
        onSaved?.(); // refresh the grid behind the modal immediately
      } catch (e: any) {
        const msg = e?.message || "Failed to delete";
        if (Platform.OS === "web") window.alert(msg);
        else Alert.alert("Error", msg);
      } finally {
        setBusy(false);
      }
    };
    const q = `Delete ${p.kind.toUpperCase()} punch at ${(p.at || "").slice(11, 16)}?`;
    if (Platform.OS === "web") {
      if (window.confirm(q)) doDelete();
    } else {
      Alert.alert("Delete punch", q, [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: doDelete },
      ]);
    }
  };

  return (
    <Modal transparent animationType="fade" onRequestClose={() => onClose(changed)}>
      <View style={st.backdrop}>
        <View style={st.card}>
          {/* Header */}
          <View style={st.header}>
            <View style={{ flex: 1 }}>
              <Text style={st.title} numberOfLines={1}>🩺 Repair Punches</Text>
              <Text style={st.subtitle} numberOfLines={1}>
                {empName} · {fmtDateDmy(dateIso)}
              </Text>
            </View>
            <Pressable onPress={() => onClose(changed)} hitSlop={10} style={st.closeBtn}>
              <Ionicons name="close" size={20} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>

          <ScrollView
            style={st.body}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator
          >
          {/* Missing-punch banner */}
          {!loading && punches.length > 0 && hasIn !== hasOut && (
            <View style={st.warnBanner}>
              <Text style={st.warnTxt}>
                ⚠ Missing {hasIn ? "OUT" : "IN"} punch — add it below to fix the duty hours.
              </Text>
            </View>
          )}
          {!loading && punches.length === 0 && (
            <View style={st.warnBanner}>
              <Text style={st.warnTxt}>No punches recorded this day. Add IN and OUT below.</Text>
            </View>
          )}

          {/* Punch list */}
          {loading ? (
            <ActivityIndicator style={{ marginVertical: 24 }} color={colors.primary} />
          ) : (
            <View>
              {punches.map((p) => (
                <View key={p.record_id} style={st.punchRow}>
                  <View style={[st.kindBadge, p.kind === "in" ? st.kindIn : st.kindOut]}>
                    <Text style={st.kindTxt}>{p.kind.toUpperCase()}</Text>
                  </View>
                  <Text style={st.timeTxt}>{(p.at || "").slice(11, 16)}</Text>
                  <Text style={st.srcTxt}>{srcLabel(p.source)}</Text>
                  <View style={{ flex: 1 }} />
                  <Pressable onPress={() => openEdit(p)} hitSlop={8} style={st.iconBtn} disabled={busy}>
                    <Ionicons name="pencil" size={16} color={colors.primary} />
                  </Pressable>
                  <Pressable onPress={() => remove(p)} hitSlop={8} style={st.iconBtn} disabled={busy}>
                    <Ionicons name="trash-outline" size={16} color="#DC2626" />
                  </Pressable>
                </View>
              ))}
            </View>
          )}

          {/* Add buttons */}
          {!formOpen && (
            <View style={st.addRow}>
              <Pressable style={[st.addBtn, { backgroundColor: "#DCFCE7" }]} onPress={() => openAdd("in")}>
                <Ionicons name="add" size={16} color="#15803D" />
                <Text style={[st.addBtnTxt, { color: "#15803D" }]}>Add IN</Text>
              </Pressable>
              <Pressable style={[st.addBtn, { backgroundColor: "#FEE2E2" }]} onPress={() => openAdd("out")}>
                <Ionicons name="add" size={16} color="#B91C1C" />
                <Text style={[st.addBtnTxt, { color: "#B91C1C" }]}>Add OUT</Text>
              </Pressable>
            </View>
          )}

          {/* Add / edit form */}
          {formOpen && (
            <View style={st.form}>
              <Text style={st.formTitle}>{editId ? "Edit punch" : `Add ${kind.toUpperCase()} punch`}</Text>
              <View style={st.formRow}>
                <View style={st.kindToggle}>
                  {(["in", "out"] as const).map((k) => (
                    <Pressable
                      key={k}
                      onPress={() => setKind(k)}
                      style={[st.kindOpt, kind === k && (k === "in" ? st.kindOptInActive : st.kindOptOutActive)]}
                    >
                      <Text style={[st.kindOptTxt, kind === k && { color: "#fff" }]}>{k.toUpperCase()}</Text>
                    </Pressable>
                  ))}
                </View>
                <TextInput
                  style={st.timeInput}
                  value={time}
                  onChangeText={fmtTimeInput}
                  placeholder="HH:MM"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="number-pad"
                  maxLength={5}
                  autoFocus
                />
              </View>
              <TextInput
                style={st.reasonInput}
                value={reason}
                onChangeText={setReason}
                placeholder="Reason (audit)"
                placeholderTextColor={colors.onSurfaceTertiary}
              />
              {err ? <Text style={st.errTxt}>{err}</Text> : null}
              <View style={st.formActions}>
                <Pressable style={st.cancelBtn} onPress={() => setFormOpen(false)} disabled={busy}>
                  <Text style={st.cancelTxt}>Cancel</Text>
                </Pressable>
                <Pressable style={[st.saveBtn, busy && { opacity: 0.6 }]} onPress={save} disabled={busy}>
                  {busy ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={16} color="#fff" />
                      <Text style={st.saveTxt}>Save Punch</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          )}

          {/* Footer — Save & Close (applies changes + refreshes the grid) */}
          {!formOpen && (
            <Pressable
              style={[st.doneBtn, busy && { opacity: 0.6 }]}
              onPress={() => onClose(changed)}
              disabled={busy}
            >
              <Ionicons name="checkmark" size={18} color="#fff" />
              <Text style={st.doneTxt}>{changed ? "Save & Close" : "Close"}</Text>
            </Pressable>
          )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const st = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 420,
    maxHeight: "88%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  header: { flexDirection: "row", alignItems: "center", marginBottom: spacing.sm },
  body: { flexGrow: 0 },
  title: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  closeBtn: { padding: 4 },
  warnBanner: {
    backgroundColor: "rgba(245,158,11,0.12)",
    borderRadius: radius.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  warnTxt: { fontSize: 12, color: "#B45309", fontWeight: "700" },
  punchRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    gap: 10,
  },
  kindBadge: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  kindIn: { backgroundColor: "#DCFCE7" },
  kindOut: { backgroundColor: "#FEE2E2" },
  kindTxt: { fontSize: 11, fontWeight: "800", color: colors.onSurface },
  timeTxt: { fontSize: 14, fontWeight: "800", color: colors.onSurface, minWidth: 46 },
  srcTxt: { fontSize: 11, color: colors.onSurfaceTertiary },
  iconBtn: { padding: 6 },
  addRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  addBtnTxt: { fontSize: 13, fontWeight: "800" },
  form: {
    marginTop: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  formTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm },
  formRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  kindToggle: {
    flexDirection: "row",
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  kindOpt: { paddingHorizontal: 14, paddingVertical: 8, backgroundColor: colors.surface },
  kindOptInActive: { backgroundColor: "#15803D" },
  kindOptOutActive: { backgroundColor: "#B91C1C" },
  kindOptTxt: { fontSize: 12, fontWeight: "800", color: colors.onSurfaceSecondary },
  timeInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 15,
    fontWeight: "700",
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  reasonInput: {
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 13,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  errTxt: { color: "#DC2626", fontSize: 12, fontWeight: "700", marginTop: 6 },
  formActions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  cancelBtn: {
    flex: 1,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelTxt: { fontSize: 14, fontWeight: "800", color: colors.onSurfaceSecondary },
  saveBtn: {
    flex: 1,
    flexDirection: "row",
    gap: 6,
    backgroundColor: "#15803D",
    borderRadius: radius.md,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  saveTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
  doneBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: spacing.lg, backgroundColor: "#15803D", borderRadius: radius.md,
    paddingVertical: 12,
  },
  doneTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
});
