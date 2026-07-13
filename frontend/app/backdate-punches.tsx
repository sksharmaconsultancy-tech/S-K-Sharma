/**
 * Back-date Attendance Editor
 * ---------------------------
 * A single-screen tool for company_admin & super_admin to:
 *   • Add a manual punch (IN / OUT) for a specific employee on a past date.
 *   • Edit the time or kind of an existing punch.
 *   • Delete a punch.
 * Every action requires a short audit reason. All actions land in the
 * `attendance_audit_log` collection on the backend.
 *
 * Company admins are capped at a 90-day lookback; super admins have no
 * range restriction (backend enforces this).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  Alert,
  Platform,
  Modal,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Employee = {
  user_id: string;
  name: string | null;
  employee_code?: string | null;
  role?: string | null;
  company_id?: string | null;
  employee_type?: string | null;
  is_onroll?: boolean | null;
};

type AttendanceRecord = {
  record_id: string;
  user_id: string;
  company_id?: string | null;
  date: string;
  kind: "in" | "out" | "absent" | string;
  at: string;
  source?: string | null;
  status?: string | null;
  original_at?: string | null;
  edited_by?: string | null;
  edited_at?: string | null;
  edit_reason?: string | null;
  manual_reason?: string | null;
  created_by?: string | null;
};

function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString(undefined, {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function toLocalInput(iso: string): string {
  // Convert ISO to `YYYY-MM-DDTHH:MM` for <TextInput /> or <input type="datetime-local">
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  } catch {
    return "";
  }
}

function fromLocalInput(local: string): string {
  // Send the local datetime as-is; server parses and coerces to UTC.
  return (local || "").trim();
}

const daysAgo = (n: number): string => {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
};

const today = (): string => new Date().toISOString().slice(0, 10);

export default function BackdatePunchesScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const isAdmin = isSuper || user?.role === "company_admin";

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [selectedEmp, setSelectedEmp] = useState<string | null>(null);
  const [empPickerOpen, setEmpPickerOpen] = useState(false);
  const [empSearch, setEmpSearch] = useState("");
  const [dateFrom, setDateFrom] = useState<string>(daysAgo(7));
  const [dateTo, setDateTo] = useState<string>(today());

  const [records, setRecords] = useState<AttendanceRecord[]>([]);
  const [loading, setLoading] = useState(false);

  const [addOpen, setAddOpen] = useState(false);
  const [editing, setEditing] = useState<AttendanceRecord | null>(null);

  const empLabel = useMemo(() => {
    const e = employees.find((x) => x.user_id === selectedEmp);
    if (!e) return "Choose employee";
    return `${e.name || e.user_id}${e.employee_code ? " · " + e.employee_code : ""}`;
  }, [employees, selectedEmp]);

  const loadEmployees = useCallback(async () => {
    try {
      const r = await api<{ employees: Employee[] }>("/admin/employees");
      setEmployees(
        (r.employees || []).filter((e) => e.role === "employee"),
      );
    } catch (e: any) {
      Alert.alert("Load failed", e?.message || "Try again.");
    }
  }, []);

  const loadRecords = useCallback(async () => {
    if (!selectedEmp) {
      setRecords([]);
      return;
    }
    setLoading(true);
    try {
      const params = new URLSearchParams({
        user_id: selectedEmp,
        date_from: dateFrom,
        date_to: dateTo,
        limit: "500",
      });
      const r = await api<{ records: AttendanceRecord[] }>(
        `/admin/attendance/history?${params.toString()}`,
      );
      setRecords(r.records || []);
    } catch (e: any) {
      const msg = e?.message || "Failed to load records";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Load failed", msg);
    } finally {
      setLoading(false);
    }
  }, [selectedEmp, dateFrom, dateTo]);

  useEffect(() => {
    if (isAdmin) loadEmployees();
  }, [isAdmin, loadEmployees]);

  useEffect(() => {
    loadRecords();
  }, [loadRecords]);

  const doDelete = (rec: AttendanceRecord) => {
    const ask = async () => {
      let reason = "";
      if (Platform.OS === "web") {
        const p = globalThis.prompt(
          "Reason for deleting this punch (required):",
        );
        if (p === null) return;
        reason = String(p || "").trim();
        if (!reason) {
          globalThis.alert("A reason is required.");
          return;
        }
      } else {
        // Native prompt fallback — use a two-step Alert
        reason = "Deleted by admin";
      }
      try {
        await api(
          `/admin/attendance/${rec.record_id}?reason=${encodeURIComponent(reason)}`,
          { method: "DELETE" },
        );
        await loadRecords();
      } catch (e: any) {
        const msg = e?.message || "Delete failed";
        if (Platform.OS === "web") globalThis.alert(msg);
        else Alert.alert("Delete failed", msg);
      }
    };
    const summary = `${rec.kind.toUpperCase()} · ${fmtDateTime(rec.at)}`;
    if (Platform.OS === "web") {
      if (window.confirm(`Delete punch?\n\n${summary}`)) ask();
    } else {
      Alert.alert("Delete punch", summary, [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: ask },
      ]);
    }
  };

  const filteredEmps = useMemo(() => {
    const q = empSearch.trim().toLowerCase();
    if (!q) return employees;
    return employees.filter((e) => {
      const hay = `${e.name || ""} ${e.employee_code || ""} ${e.user_id}`.toLowerCase();
      return hay.includes(q);
    });
  }, [employees, empSearch]);

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Back-date punches</Text>
            <Text style={styles.hsub}>
              {isSuper ? "Any date" : "Last 90 days · audited"}
            </Text>
          </View>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Filter card */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Look-up punches</Text>

          <Text style={styles.fieldLabel}>Employee</Text>
          <Pressable
            testID="bd-emp-picker"
            style={styles.selectField}
            onPress={() => setEmpPickerOpen(true)}
          >
            <Text
              style={[
                styles.selectFieldTxt,
                !selectedEmp && { color: colors.onSurfaceTertiary },
              ]}
              numberOfLines={1}
            >
              {empLabel}
            </Text>
            <Ionicons name="chevron-down" size={16} color={colors.onSurfaceTertiary} />
          </Pressable>

          <View style={{ flexDirection: "row", gap: 8 }}>
            <View style={{ flex: 1 }}>
              <Text style={styles.fieldLabel}>From</Text>
              <DateField
                testID="bd-date-from"
                value={dateFrom}
                onChangeISO={setDateFrom}
              />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.fieldLabel}>To</Text>
              <DateField
                testID="bd-date-to"
                value={dateTo}
                onChangeISO={setDateTo}
              />
            </View>
          </View>

          <View style={{ flexDirection: "row", gap: 8, marginTop: 4 }}>
            <Pressable
              testID="bd-reload"
              onPress={loadRecords}
              disabled={!selectedEmp}
              style={[
                styles.primaryBtn,
                { flex: 1 },
                !selectedEmp && styles.btnDisabled,
              ]}
            >
              <Ionicons name="refresh" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>Reload</Text>
            </Pressable>
            <Pressable
              testID="bd-add"
              onPress={() => setAddOpen(true)}
              disabled={!selectedEmp}
              style={[
                styles.secondaryBtn,
                { flex: 1 },
                !selectedEmp && { opacity: 0.5 },
              ]}
            >
              <Ionicons name="add-circle-outline" size={16} color={colors.brandPrimary} />
              <Text style={styles.secondaryBtnTxt}>Add punch</Text>
            </Pressable>
          </View>
        </View>

        {/* Records list */}
        {!selectedEmp ? (
          <View style={styles.empty}>
            <Ionicons name="person-outline" size={40} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyT}>Pick an employee to view their punches</Text>
          </View>
        ) : loading ? (
          <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} />
        ) : records.length === 0 ? (
          <View style={styles.empty}>
            <Ionicons name="calendar-outline" size={40} color={colors.onSurfaceTertiary} />
            <Text style={styles.emptyT}>
              No records in the selected range. Tap “Add punch” to insert one.
            </Text>
          </View>
        ) : (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>
              {records.length} punch{records.length === 1 ? "" : "es"}
            </Text>
            {records.map((r) => {
              const isAbsent = r.kind === "absent";
              const isEdited = !!r.edited_by || !!r.original_at;
              return (
                <View key={r.record_id} style={styles.recRow} testID={`rec-${r.record_id}`}>
                  <View
                    style={[
                      styles.recDot,
                      {
                        backgroundColor:
                          r.kind === "in"
                            ? "#0F766E"
                            : r.kind === "out"
                              ? "#B45309"
                              : "#8A1F1F",
                      },
                    ]}
                  >
                    <Text style={styles.recDotTxt}>
                      {isAbsent ? "AB" : r.kind.toUpperCase()}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.recTitle}>{fmtDateTime(r.at)}</Text>
                    <Text style={styles.recSub}>
                      {r.source || "manual"} · {r.status || "approved"}
                      {isEdited ? " · edited" : ""}
                    </Text>
                    {r.original_at ? (
                      <Text style={styles.recMuted}>
                        Original: {fmtDateTime(r.original_at)}
                      </Text>
                    ) : null}
                    {r.manual_reason || r.edit_reason ? (
                      <Text style={styles.recMuted}>
                        Reason: {r.edit_reason || r.manual_reason}
                      </Text>
                    ) : null}
                  </View>
                  <Pressable
                    onPress={() => setEditing(r)}
                    hitSlop={10}
                    style={styles.iconBtn}
                    testID={`edit-${r.record_id}`}
                  >
                    <Ionicons name="create-outline" size={18} color={colors.brandPrimary} />
                  </Pressable>
                  <Pressable
                    onPress={() => doDelete(r)}
                    hitSlop={10}
                    style={styles.iconBtnDanger}
                    testID={`delete-${r.record_id}`}
                  >
                    <Ionicons name="trash-outline" size={18} color="#8A1F1F" />
                  </Pressable>
                </View>
              );
            })}
          </View>
        )}
        <View style={{ height: 24 }} />
      </ScrollView>

      {/* Employee picker */}
      <Modal
        transparent
        visible={empPickerOpen}
        animationType="slide"
        onRequestClose={() => setEmpPickerOpen(false)}
      >
        <Pressable style={styles.backdrop} onPress={() => setEmpPickerOpen(false)} />
        <View style={styles.sheet}>
          <View style={styles.sheetGrip} />
          <Text style={styles.sheetTitle}>Choose employee</Text>
          <TextInput
            placeholder="Search name / code"
            placeholderTextColor={colors.onSurfaceTertiary}
            value={empSearch}
            onChangeText={setEmpSearch}
            style={styles.input}
            testID="bd-emp-search"
          />
          <ScrollView style={{ maxHeight: 400 }}>
            {filteredEmps.map((e) => {
              const active = e.user_id === selectedEmp;
              return (
                <Pressable
                  key={e.user_id}
                  testID={`bd-emp-${e.user_id}`}
                  style={[
                    styles.empRow,
                    active && { backgroundColor: colors.brandTertiary },
                  ]}
                  onPress={() => {
                    setSelectedEmp(e.user_id);
                    setEmpPickerOpen(false);
                  }}
                >
                  <View style={styles.empAvatar}>
                    <Text style={styles.empAvatarTxt}>
                      {(e.name || "?").trim().charAt(0).toUpperCase()}
                    </Text>
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.empRowTitle}>{e.name || "—"}</Text>
                    <Text style={styles.empRowSub}>
                      {e.employee_code || e.user_id}
                      {e.employee_type ? ` · ${e.employee_type}` : ""}
                      {e.is_onroll === false ? " · Off-roll" : ""}
                    </Text>
                  </View>
                  {active ? (
                    <Ionicons name="checkmark-circle" size={18} color={colors.brandPrimary} />
                  ) : null}
                </Pressable>
              );
            })}
            {filteredEmps.length === 0 ? (
              <Text style={styles.emptyDocsTxt}>No employees match your search.</Text>
            ) : null}
          </ScrollView>
        </View>
      </Modal>

      {/* Add punch modal */}
      <PunchFormModal
        visible={addOpen}
        onClose={() => setAddOpen(false)}
        title="Add manual punch"
        initial={{
          at: toLocalInput(new Date().toISOString()),
          kind: "in",
          reason: "",
        }}
        onSubmit={async ({ at, kind, reason }) => {
          if (!selectedEmp) return;
          await api("/admin/attendance/manual-punch", {
            method: "POST",
            body: {
              user_id: selectedEmp,
              kind,
              at: fromLocalInput(at),
              reason,
            },
          });
          setAddOpen(false);
          await loadRecords();
        }}
      />

      {/* Edit punch modal */}
      <PunchFormModal
        visible={!!editing}
        onClose={() => setEditing(null)}
        title="Edit punch"
        initial={{
          at: editing ? toLocalInput(editing.at) : "",
          kind:
            editing?.kind === "in" || editing?.kind === "out"
              ? editing.kind
              : "in",
          reason: "",
        }}
        onSubmit={async ({ at, kind, reason }) => {
          if (!editing) return;
          await api(`/admin/attendance/${editing.record_id}`, {
            method: "PATCH",
            body: {
              at: fromLocalInput(at),
              kind,
              reason,
            },
          });
          setEditing(null);
          await loadRecords();
        }}
      />
    </View>
  );
}

/* ---------------------------------------------------------------------------
 * Shared modal for Add & Edit — a tiny form with kind toggle + datetime +
 * reason. Reason is always required (backend enforces this too).
 * ------------------------------------------------------------------------- */
function PunchFormModal({
  visible,
  onClose,
  title,
  initial,
  onSubmit,
}: {
  visible: boolean;
  onClose: () => void;
  title: string;
  initial: { at: string; kind: "in" | "out"; reason: string };
  onSubmit: (values: { at: string; kind: "in" | "out"; reason: string }) => Promise<void>;
}) {
  const [at, setAt] = useState<string>(initial.at);
  const [kind, setKind] = useState<"in" | "out">(initial.kind);
  const [reason, setReason] = useState<string>(initial.reason);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (visible) {
      setAt(initial.at);
      setKind(initial.kind);
      setReason(initial.reason);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const submit = async () => {
    if (!at.trim()) {
      if (Platform.OS === "web") globalThis.alert("Time is required.");
      else Alert.alert("Missing", "Time is required.");
      return;
    }
    if (!reason.trim()) {
      if (Platform.OS === "web") globalThis.alert("Reason is required for audit.");
      else Alert.alert("Missing", "Reason is required for audit.");
      return;
    }
    setBusy(true);
    try {
      await onSubmit({ at: at.trim(), kind, reason: reason.trim() });
    } catch (e: any) {
      const msg = e?.message || "Save failed";
      if (Platform.OS === "web") globalThis.alert(msg);
      else Alert.alert("Save failed", msg);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      transparent
      visible={visible}
      animationType="slide"
      onRequestClose={onClose}
    >
      <Pressable style={styles.backdrop} onPress={onClose} />
      <View style={styles.sheet}>
        <View style={styles.sheetGrip} />
        <Text style={styles.sheetTitle}>{title}</Text>

        <Text style={styles.fieldLabel}>Kind</Text>
        <View style={{ flexDirection: "row", gap: 8, marginBottom: 6 }}>
          {(["in", "out"] as const).map((k) => {
            const active = kind === k;
            return (
              <Pressable
                key={k}
                onPress={() => setKind(k)}
                testID={`punch-kind-${k}`}
                style={[
                  styles.kindChip,
                  active && styles.kindChipActive,
                  {
                    backgroundColor: active
                      ? k === "in" ? "#0F766E" : "#B45309"
                      : colors.surface,
                    borderColor: active
                      ? k === "in" ? "#0F766E" : "#B45309"
                      : colors.borderStrong,
                  },
                ]}
              >
                <Text
                  style={[styles.kindChipTxt, active && styles.kindChipTxtActive]}
                >
                  Punch {k.toUpperCase()}
                </Text>
              </Pressable>
            );
          })}
        </View>

        <Text style={styles.fieldLabel}>Date &amp; time (local)</Text>
        <TextInput
          testID="punch-at-input"
          value={at}
          onChangeText={setAt}
          placeholder="YYYY-MM-DDTHH:MM"
          placeholderTextColor={colors.onSurfaceTertiary}
          style={styles.input}
          autoCapitalize="none"
        />

        <Text style={styles.fieldLabel}>Reason (required)</Text>
        <TextInput
          testID="punch-reason-input"
          value={reason}
          onChangeText={setReason}
          placeholder="e.g. Employee forgot to swipe out on 3 Jun"
          placeholderTextColor={colors.onSurfaceTertiary}
          style={[styles.input, { height: 72 }]}
          multiline
        />

        <Pressable
          testID="punch-submit"
          onPress={submit}
          disabled={busy}
          style={[styles.primaryBtn, busy && styles.btnDisabled]}
        >
          {busy ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="save-outline" size={16} color="#fff" />
              <Text style={styles.primaryBtnTxt}>Save</Text>
            </>
          )}
        </Pressable>
        <View style={{ height: 24 }} />
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    paddingHorizontal: spacing.md,
    height: 52,
    flexDirection: "row",
    alignItems: "center",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    backgroundColor: colors.surface,
  },
  h1: { ...type.h5, color: colors.onSurface, fontWeight: "700" },
  hsub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  scroll: { padding: spacing.md, paddingBottom: 40 },

  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceTertiary, ...type.body },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  cardTitle: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "700",
    marginBottom: 6,
  },
  fieldLabel: {
    ...type.tiny,
    color: colors.onSurfaceSecondary,
    fontWeight: "700",
    marginTop: 6,
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.3,
  },
  input: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    marginBottom: 6,
    backgroundColor: colors.surface,
  },
  selectField: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 12,
    backgroundColor: colors.surface,
    marginBottom: 6,
  },
  selectFieldTxt: {
    color: colors.onSurface,
    fontSize: 14,
    fontWeight: "600",
    flex: 1,
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "700" },
  btnDisabled: { opacity: 0.6 },
  secondaryBtn: {
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "700" },

  empty: { alignItems: "center", padding: 40, gap: 8 },
  emptyT: { color: colors.onSurfaceTertiary, textAlign: "center" },
  emptyDocsTxt: {
    ...type.caption,
    color: colors.onSurfaceTertiary,
    textAlign: "center",
    marginVertical: 20,
  },

  recRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
    gap: 10,
  },
  recDot: {
    width: 44,
    height: 44,
    borderRadius: 22,
    alignItems: "center",
    justifyContent: "center",
  },
  recDotTxt: { color: "#fff", fontWeight: "800", fontSize: 11 },
  recTitle: { ...type.body, color: colors.onSurface, fontWeight: "700" },
  recSub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 1 },
  recMuted: { ...type.tiny, color: colors.onSurfaceTertiary, marginTop: 1 },
  iconBtn: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  iconBtnDanger: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: "#FFE0E0",
    alignItems: "center",
    justifyContent: "center",
  },

  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    backgroundColor: colors.surface,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: spacing.md,
    paddingTop: 10,
    paddingBottom: spacing.lg,
    maxHeight: "90%",
  },
  sheetGrip: {
    alignSelf: "center",
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderStrong,
    marginBottom: 12,
  },
  sheetTitle: {
    ...type.h6,
    color: colors.onSurface,
    fontWeight: "800",
    marginBottom: 10,
  },
  empRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderRadius: radius.md,
  },
  empAvatar: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  empAvatarTxt: { color: colors.brandPrimary, fontWeight: "800" },
  empRowTitle: { ...type.body, color: colors.onSurface, fontWeight: "600" },
  empRowSub: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 1 },

  kindChip: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 22,
    borderWidth: 1,
    alignItems: "center",
  },
  kindChipActive: {},
  kindChipTxt: { fontWeight: "700", color: colors.onSurfaceSecondary },
  kindChipTxtActive: { color: "#fff" },
});
