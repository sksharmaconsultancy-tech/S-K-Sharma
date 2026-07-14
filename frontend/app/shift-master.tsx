/**
 * Shift Master (Global) — Iter 76.
 *
 * Dedicated admin page for the *global* shift catalogue that every firm's
 * Attendance Policy and every Employee's shift override picks from.
 *
 * Backend: /api/shift-masters (GET all, super_admin only for POST/PATCH/DELETE)
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  TextInput,
  Modal,
  Alert,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

type Shift = {
  shift_id: string;
  name: string;
  start: string;
  end: string;
  description?: string | null;
  updated_at?: string;
};

const showMsg = (msg: string, title = "Shift Master") => {
  if (Platform.OS === "web") window.alert(`${title}\n\n${msg}`);
  else Alert.alert(title, msg);
};

function computeDuration(start: string, end: string): string {
  try {
    const [sh, sm] = start.split(":").map(Number);
    const [eh, em] = end.split(":").map(Number);
    if ([sh, sm, eh, em].some((n) => Number.isNaN(n))) return "";
    let mins = eh * 60 + em - (sh * 60 + sm);
    if (mins <= 0) mins += 24 * 60;
    const h = Math.floor(mins / 60);
    const m = mins % 60;
    return `${h}h${m ? ` ${m}m` : ""}`;
  } catch {
    return "";
  }
}

export default function ShiftMasterScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const canView =
    user?.role === "super_admin" ||
    user?.role === "company_admin" ||
    user?.role === "sub_admin";

  const [shifts, setShifts] = useState<Shift[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState<Shift | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    if (!canView) return;
    setLoading(true);
    setErr(null);
    try {
      const res = await api<{ shifts: Shift[] }>("/shift-masters");
      setShifts(res.shifts || []);
    } catch (e: any) {
      setErr(e?.message || "Could not load shifts");
    } finally {
      setLoading(false);
    }
  }, [canView]);

  useEffect(() => { load(); }, [load]);

  const remove = async (s: Shift) => {
    const ok = Platform.OS === "web"
      ? window.confirm(
          `Delete shift "${s.name}"?\n\nThis is a GLOBAL catalogue entry — deletion affects every firm.`,
        )
      : await new Promise<boolean>((resolve) =>
          Alert.alert("Delete shift?", `"${s.name}"`, [
            { text: "Cancel", style: "cancel", onPress: () => resolve(false) },
            { text: "Delete", style: "destructive", onPress: () => resolve(true) },
          ]),
        );
    if (!ok) return;
    try {
      await api(`/shift-masters/${s.shift_id}`, { method: "DELETE" });
      await load();
    } catch (e: any) {
      showMsg(e?.message || "Delete failed");
    }
  };

  if (!canView) {
    return (
      <SafeAreaView style={styles.centerScreen}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.brand} />
        <Text style={styles.errTitle}>Admins only</Text>
        <Pressable
          onPress={() => router.replace("/(tabs)" as any)}
          style={styles.retryBtn}
        >
          <Text style={styles.retryBtnTxt}>Back to dashboard</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.headerRow}>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Shift Master</Text>
            <Text style={styles.subtitle}>
              Global catalogue of shifts used across every firm and every
              employee. Once defined here, shifts show up as pick-list options
              in the Attendance Policy and Employee Master screens.
            </Text>
          </View>
          {isSuper && (
            <Pressable
              style={styles.cta}
              onPress={() => setCreating(true)}
              testID="shm-add-btn"
            >
              <Ionicons name="add" size={18} color={colors.onCta} />
              <Text style={styles.ctaText}>New shift</Text>
            </Pressable>
          )}
        </View>

        {loading ? (
          <View style={{ padding: 40, alignItems: "center" }}>
            <ActivityIndicator color={colors.brand} size="large" />
          </View>
        ) : err ? (
          <View style={styles.errBox}>
            <Ionicons name="alert-circle" size={16} color={colors.error} />
            <Text style={styles.errText}>{err}</Text>
          </View>
        ) : shifts.length === 0 ? (
          <View style={styles.emptyCard}>
            <Ionicons name="time-outline" size={32} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyTitle}>No shifts yet</Text>
            <Text style={styles.emptyBody}>
              {isSuper
                ? "Add your first shift — it will be usable across every firm."
                : "Ask your Super Admin to create shifts in this catalogue."}
            </Text>
          </View>
        ) : (
          shifts.map((s) => (
            <View key={s.shift_id} style={styles.card} testID={`shm-${s.name}`}>
              <View style={{ flex: 1 }}>
                <Text style={styles.cardTitle}>{s.name}</Text>
                <Text style={styles.cardSub}>
                  {s.start} – {s.end} · Duration {computeDuration(s.start, s.end)}
                </Text>
                {s.description ? (
                  <Text style={styles.cardDesc}>{s.description}</Text>
                ) : null}
              </View>
              {isSuper && (
                <View style={styles.actions}>
                  <Pressable
                    onPress={() => setEditing(s)}
                    style={styles.iconBtn}
                    testID={`shm-edit-${s.name}`}
                  >
                    <Ionicons name="create-outline" size={18} color={colors.brandPrimary} />
                  </Pressable>
                  <Pressable
                    onPress={() => remove(s)}
                    style={styles.iconBtn}
                    testID={`shm-del-${s.name}`}
                  >
                    <Ionicons name="trash-outline" size={18} color={colors.error} />
                  </Pressable>
                </View>
              )}
            </View>
          ))
        )}
      </ScrollView>

      <ShiftEditor
        visible={creating || !!editing}
        initial={editing}
        onClose={() => { setCreating(false); setEditing(null); }}
        onSaved={async () => { setCreating(false); setEditing(null); await load(); }}
      />
    </SafeAreaView>
  );
}

function ShiftEditor({
  visible,
  initial,
  onClose,
  onSaved,
}: {
  visible: boolean;
  initial: Shift | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState("");
  const [start, setStart] = useState("09:00");
  const [end, setEnd] = useState("18:00");
  const [desc, setDesc] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (visible) {
      setName(initial?.name || "");
      setStart(initial?.start || "09:00");
      setEnd(initial?.end || "18:00");
      setDesc(initial?.description || "");
    }
  }, [visible, initial]);

  const save = async () => {
    if (!name.trim()) { showMsg("Shift name is required"); return; }
    setSaving(true);
    try {
      const body = {
        name: name.trim(),
        start,
        end,
        description: desc.trim() || null,
      };
      if (initial) {
        await api(`/shift-masters/${initial.shift_id}`, { method: "PATCH", body });
      } else {
        await api("/shift-masters", { method: "POST", body });
      }
      onSaved();
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <View style={styles.modalRoot}>
        <Pressable style={styles.modalBackdrop} onPress={onClose} />
        <View style={styles.modalSheet}>
          <View style={styles.modalHead}>
            <Text style={styles.modalTitle}>
              {initial ? `Edit ${initial.name}` : "New shift"}
            </Text>
            <Pressable onPress={onClose} hitSlop={8}>
              <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>
          <Text style={styles.fieldLabel}>Name</Text>
          <TextInput
            value={name}
            onChangeText={setName}
            placeholder="e.g. Day Shift"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
          />
          <View style={styles.rowSplit}>
            <View style={{ flex: 1 }}>
              <Text style={styles.fieldLabel}>Start (HH:MM)</Text>
              <TextInput
                value={start}
                onChangeText={setStart}
                placeholder="09:00"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
              />
            </View>
            <View style={{ width: 12 }} />
            <View style={{ flex: 1 }}>
              <Text style={styles.fieldLabel}>End (HH:MM)</Text>
              <TextInput
                value={end}
                onChangeText={setEnd}
                placeholder="18:00"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
              />
            </View>
          </View>
          <Text style={styles.fieldLabel}>Description (optional)</Text>
          <TextInput
            value={desc}
            onChangeText={setDesc}
            placeholder="Short note"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.input}
          />
          <Text style={styles.durTxt}>
            Duration: {computeDuration(start, end) || "—"}
          </Text>
          <Pressable
            onPress={save}
            disabled={saving}
            style={[styles.saveBtn, saving && { opacity: 0.6 }]}
            testID="shm-save-btn"
          >
            {saving ? (
              <ActivityIndicator color={colors.onCta} size="small" />
            ) : (
              <Text style={styles.saveBtnTxt}>
                {initial ? "Save changes" : "Add to catalogue"}
              </Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.surface },
  centerScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
    gap: spacing.sm,
    backgroundColor: colors.surface,
  },
  errTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  retryBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.brand,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
  },
  retryBtnTxt: { color: colors.onBrandPrimary, fontWeight: "700" },
  scroll: {
    padding: spacing.lg,
    gap: spacing.md,
    maxWidth: 900,
    width: "100%",
    alignSelf: "center",
    paddingBottom: 80,
  },
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: spacing.md,
    flexWrap: "wrap",
  },
  title: { fontSize: type.h1, fontWeight: "800", color: colors.onSurface },
  subtitle: {
    color: colors.onSurfaceSecondary,
    marginTop: 4,
    lineHeight: 20,
    fontSize: type.base,
  },
  cta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.cta,
    paddingVertical: 10,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
    ...shadow.cta,
  },
  ctaText: { color: colors.onCta, fontWeight: "700" },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEE2E2",
    padding: spacing.sm,
    borderRadius: radius.md,
  },
  errText: { color: colors.error, flex: 1 },
  emptyCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    alignItems: "center",
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
  },
  emptyTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  emptyBody: { color: colors.onSurfaceSecondary, textAlign: "center" },
  card: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    ...shadow.card,
  },
  cardTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  cardSub: { color: colors.onSurfaceSecondary, marginTop: 4 },
  cardDesc: { color: colors.onSurfaceTertiary, marginTop: 4, fontSize: type.sm },
  actions: { flexDirection: "row", gap: 6 },
  iconBtn: {
    width: 36, height: 36, borderRadius: 18,
    alignItems: "center", justifyContent: "center",
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.divider,
  },

  modalRoot: { flex: 1, justifyContent: "center", padding: spacing.lg },
  modalBackdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.4)" },
  modalSheet: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    maxWidth: 460,
    width: "100%",
    alignSelf: "center",
    gap: 10,
    ...shadow.card,
  },
  modalHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  modalTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  fieldLabel: {
    color: colors.onSurfaceTertiary, fontWeight: "600",
    fontSize: type.sm, marginTop: 4,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 10,
    paddingHorizontal: spacing.sm,
    color: colors.onSurface,
    backgroundColor: colors.surface,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  rowSplit: { flexDirection: "row", alignItems: "flex-start" },
  durTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    fontStyle: "italic",
    marginTop: 4,
  },
  saveBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.cta,
    paddingVertical: 14,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  saveBtnTxt: { color: colors.onCta, fontWeight: "800" },
});
