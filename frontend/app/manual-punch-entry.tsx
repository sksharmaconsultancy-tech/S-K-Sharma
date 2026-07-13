/**
 * Iter 83 — Manual Punch Entry (Missing Punch Editor)
 * ---------------------------------------------------
 * Admin-only screen to input / edit / delete attendance punches manually
 * when an employee misses one on the biometric device. Reason field is
 * mandatory (audit-logged server side).
 *
 * Flow:
 *   1. (Super admin) pick a company.
 *   2. Pick an employee (search).
 *   3. Pick a date (single day) OR month.
 *   4. Existing punches for the selected day/month are listed with
 *      Edit / Delete controls.
 *   5. "Add IN" / "Add OUT" opens a modal to enter time + reason.
 *
 * Backend endpoints:
 *   POST    /api/admin/attendance/manual-punch     {user_id, kind, at, reason}
 *   PATCH   /api/admin/attendance/{record_id}      {at?, kind?, reason}
 *   DELETE  /api/admin/attendance/{record_id}?reason=...
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  ScrollView,
  Alert,
  Platform,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import DateField from "@/src/components/DateField";

type Company = { company_id: string; name: string };
type Employee = { user_id: string; name?: string; employee_code?: string };
type Punch = {
  record_id: string;
  user_id: string;
  kind: "in" | "out";
  at: string;
  source?: string;
  manual_reason?: string;
};

// ---------------------------------------------------------------------------
export default function ManualPunchEntryScreen() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const { selectedCompanyId } = useSelectedCompany();

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>(
    !isSuper ? (user?.company_id || "") : (selectedCompanyId || ""),
  );

  const [employees, setEmployees] = useState<Employee[]>([]);
  const [empSearch, setEmpSearch] = useState("");
  const [empId, setEmpId] = useState<string>("");

  const [date, setDate] = useState<string>(() => {
    const d = new Date();
    return d.toISOString().slice(0, 10);
  });
  const [mode, setMode] = useState<"day" | "month">("day");

  const [punches, setPunches] = useState<Punch[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  // Modal state for add/edit
  const [modalKind, setModalKind] = useState<"in" | "out">("in");
  const [modalRecordId, setModalRecordId] = useState<string | null>(null);
  const [modalAt, setModalAt] = useState<string>(""); // "HH:MM"

  // Iter 94 — auto-format time input as HH:MM while typing. Overflow
  // keeps the MOST RECENT digits (typing over a full value never
  // swallows keystrokes); minutes clamp to 59.
  const formatHHMM = (raw: string): string => {
    let d = raw.replace(/[^0-9]/g, "");
    if (d.length > 4) d = d.slice(-4);
    if (d.length >= 1 && Number(d[0]) > 2) d = `0${d}`.slice(0, 4);
    if (d.length >= 2 && Number(d.slice(0, 2)) > 23) d = `23${d.slice(2)}`;
    if (d.length === 3 && Number(d[2]) > 5) d = `${d.slice(0, 2)}0${d[2]}`;
    if (d.length >= 4 && Number(d.slice(2, 4)) > 59) d = `${d.slice(0, 2)}59`;
    return d.length > 2 ? `${d.slice(0, 2)}:${d.slice(2)}` : d;
  };
  const [modalDate, setModalDate] = useState<string>("");
  const [modalReason, setModalReason] = useState<string>("");
  const [modalOpen, setModalOpen] = useState(false);

  // ---- Load companies (super_admin) --------------------------------------
  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        const res = await api<{ companies: Company[] }>("/admin/companies");
        setCompanies(res.companies || []);
        if (!companyId && (res.companies || []).length > 0) {
          setCompanyId(res.companies[0].company_id);
        }
      } catch (e: any) {
        showError(e?.message || "Failed to load companies");
      }
    })();
  }, [isSuper]);

  // ---- Load employees for chosen company ---------------------------------
  useEffect(() => {
    if (!companyId) return;
    (async () => {
      try {
        const res = await api<{ employees: Employee[] }>(
          `/admin/companies/${companyId}/employees`,
        );
        setEmployees(res.employees || []);
      } catch (e: any) {
        showError(e?.message || "Failed to load employees");
      }
    })();
  }, [companyId]);

  const filteredEmps = useMemo(() => {
    const s = empSearch.trim().toLowerCase();
    if (!s) return employees.slice(0, 30);
    return employees
      .filter(
        (e) =>
          (e.name || "").toLowerCase().includes(s) ||
          (e.employee_code || "").toLowerCase().includes(s),
      )
      .slice(0, 30);
  }, [employees, empSearch]);

  // ---- Load punches for the selected day/month ---------------------------
  const loadPunches = useCallback(async () => {
    if (!empId) return;
    setLoading(true);
    try {
      let fromD: string;
      let toD: string;
      if (mode === "day") {
        fromD = date;
        toD = date;
      } else {
        fromD = `${date.slice(0, 7)}-01`;
        const parts = date.split("-").map(Number);
        const last = new Date(parts[0], parts[1], 0).getDate();
        toD = `${date.slice(0, 7)}-${String(last).padStart(2, "0")}`;
      }
      const res = await api<{ items: Punch[] }>(
        `/admin/attendance/records?user_id=${empId}&from=${fromD}&to=${toD}`,
      );
      setPunches(
        (res.items || []).sort((a, b) => (a.at || "").localeCompare(b.at || "")),
      );
    } catch (e: any) {
      showError(e?.message || "Failed to load punches");
    } finally {
      setLoading(false);
    }
  }, [empId, date, mode]);

  useEffect(() => {
    if (empId) loadPunches();
  }, [empId, date, mode, loadPunches]);

  // ---- Helpers ----------------------------------------------------------
  const showError = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Error", msg);
  };
  const showInfo = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Success", msg);
  };

  const openAdd = (kind: "in" | "out") => {
    setModalKind(kind);
    setModalRecordId(null);
    setModalDate(date);
    setModalAt("");
    setModalReason("");
    setModalOpen(true);
  };
  const openEdit = (p: Punch) => {
    setModalKind(p.kind);
    setModalRecordId(p.record_id);
    setModalDate((p.at || "").slice(0, 10));
    setModalAt((p.at || "").slice(11, 16));
    setModalReason("");
    setModalOpen(true);
  };

  const submitModal = async () => {
    if (!modalAt || !/^\d{2}:\d{2}$/.test(modalAt)) {
      showError("Enter time as HH:MM (24-hour).");
      return;
    }
    if (!modalReason.trim()) {
      showError("Reason is required for audit.");
      return;
    }
    setBusy("modal");
    try {
      const at = `${modalDate}T${modalAt}:00`;
      if (modalRecordId) {
        await api(`/admin/attendance/${modalRecordId}`, {
          method: "PATCH",
          body: { at, kind: modalKind, reason: modalReason.trim() },
        });
      } else {
        await api(`/admin/attendance/manual-punch`, {
          method: "POST",
          body: {
            user_id: empId,
            kind: modalKind,
            at,
            reason: modalReason.trim(),
          },
        });
      }
      setModalOpen(false);
      await loadPunches();
      showInfo("Punch saved.");
    } catch (e: any) {
      showError(e?.message || "Failed to save punch");
    } finally {
      setBusy(null);
    }
  };

  const deletePunch = async (p: Punch) => {
    const reason = Platform.OS === "web"
      ? window.prompt("Delete this punch — reason (audit)?", "Duplicate entry")
      : "Deleted via manual entry";
    if (!reason || !reason.trim()) return;
    setBusy(p.record_id);
    try {
      await api(
        `/admin/attendance/${p.record_id}?reason=${encodeURIComponent(reason.trim())}`,
        { method: "DELETE" },
      );
      await loadPunches();
      showInfo("Punch deleted.");
    } catch (e: any) {
      showError(e?.message || "Failed to delete");
    } finally {
      setBusy(null);
    }
  };

  const empRow = employees.find((e) => e.user_id === empId);

  // ---- Render -----------------------------------------------------------
  return (
    <SafeAreaView style={styles.safe}>
      <ScrollView contentContainerStyle={styles.container}>
        <View style={styles.hero}>
          <Ionicons name="finger-print-outline" size={22} color={colors.brand} />
          <View style={{ flex: 1 }}>
            <Text style={styles.heroTitle}>Missing Punch / Manual Entry</Text>
            <Text style={styles.heroSubtitle}>
              Add, edit or remove IN / OUT punches when an employee misses a punch on the biometric device. All changes are audit-logged.
            </Text>
          </View>
        </View>

        {/* Company selector */}
        {isSuper && (
          <View style={styles.card}>
            <Text style={styles.label}>Firm</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 6 }}>
              {companies.map((c) => (
                <Pressable
                  key={c.company_id}
                  onPress={() => {
                    setCompanyId(c.company_id);
                    setEmpId("");
                    setPunches([]);
                  }}
                  style={[
                    styles.chip,
                    c.company_id === companyId && styles.chipActive,
                  ]}
                >
                  <Text style={[
                    styles.chipTxt,
                    c.company_id === companyId && styles.chipTxtActive,
                  ]}>
                    {c.name}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
          </View>
        )}

        {/* Employee picker */}
        <View style={styles.card}>
          <Text style={styles.label}>Employee</Text>
          <TextInput
            style={styles.input}
            placeholder="Search by name or code"
            value={empSearch}
            onChangeText={setEmpSearch}
          />
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginTop: 8 }}>
            {filteredEmps.map((e) => (
              <Pressable
                key={e.user_id}
                onPress={() => setEmpId(e.user_id)}
                style={[
                  styles.chip,
                  e.user_id === empId && styles.chipActive,
                ]}
              >
                <Text style={[
                  styles.chipTxt,
                  e.user_id === empId && styles.chipTxtActive,
                ]}>
                  {(e.employee_code ? e.employee_code + " · " : "") + (e.name || "")}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
          {empRow && (
            <Text style={styles.empPickedTxt}>
              Selected: <Text style={{ fontWeight: "700" }}>{empRow.name}</Text> {empRow.employee_code ? `(#${empRow.employee_code})` : ""}
            </Text>
          )}
        </View>

        {/* Date + mode */}
        <View style={styles.card}>
          <Text style={styles.label}>Date / Mode</Text>
          <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
            <Pressable
              onPress={() => setMode("day")}
              style={[styles.modeBtn, mode === "day" && styles.modeBtnActive]}
            >
              <Text style={[styles.modeBtnTxt, mode === "day" && styles.modeBtnTxtActive]}>
                Single Day
              </Text>
            </Pressable>
            <Pressable
              onPress={() => setMode("month")}
              style={[styles.modeBtn, mode === "month" && styles.modeBtnActive]}
            >
              <Text style={[styles.modeBtnTxt, mode === "month" && styles.modeBtnTxtActive]}>
                Whole Month
              </Text>
            </Pressable>
          </View>
          <TextInput
            style={[styles.input, { marginTop: 8 }]}
            value={date}
            onChangeText={setDate}
            placeholder={mode === "day" ? "YYYY-MM-DD" : "YYYY-MM-01"}
          />
          <Text style={styles.hint}>
            {mode === "day"
              ? "Showing punches for this single date."
              : `Showing punches for the entire month of ${date.slice(0, 7)}.`}
          </Text>
        </View>

        {/* Action buttons */}
        {empId ? (
          <View style={styles.row}>
            <Pressable
              style={[styles.actionBtn, { backgroundColor: colors.success }]}
              onPress={() => openAdd("in")}
            >
              <Ionicons name="log-in-outline" size={18} color="#FFF" />
              <Text style={styles.actionBtnTxt}>Add IN punch</Text>
            </Pressable>
            <Pressable
              style={[styles.actionBtn, { backgroundColor: colors.warning }]}
              onPress={() => openAdd("out")}
            >
              <Ionicons name="log-out-outline" size={18} color="#FFF" />
              <Text style={styles.actionBtnTxt}>Add OUT punch</Text>
            </Pressable>
            <Pressable
              style={[styles.actionBtn, { backgroundColor: colors.brand }]}
              onPress={loadPunches}
            >
              <Ionicons name="refresh-outline" size={18} color="#FFF" />
              <Text style={styles.actionBtnTxt}>Reload</Text>
            </Pressable>
          </View>
        ) : null}

        {/* Punches list */}
        {empId ? (
          <View style={styles.card}>
            <Text style={styles.label}>Punches ({punches.length})</Text>
            {loading ? (
              <ActivityIndicator style={{ marginTop: 16 }} />
            ) : punches.length === 0 ? (
              <Text style={styles.empty}>No punches recorded. Use &quot;Add IN / OUT&quot; above.</Text>
            ) : (
              punches.map((p) => (
                <View key={p.record_id} style={styles.punchRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.punchTime}>
                      <Text style={{
                        color: p.kind === "in" ? colors.success : colors.warning,
                        fontWeight: "700",
                      }}>
                        {p.kind.toUpperCase()}
                      </Text>
                      {"  "}
                      {(p.at || "").replace("T", " ").slice(0, 16)}
                    </Text>
                    <Text style={styles.punchMeta}>
                      {p.source || "unknown"}{p.manual_reason ? ` · ${p.manual_reason}` : ""}
                    </Text>
                  </View>
                  <Pressable
                    style={styles.iconBtn}
                    onPress={() => openEdit(p)}
                    disabled={busy === p.record_id}
                  >
                    <Ionicons name="create-outline" size={18} color={colors.brand} />
                  </Pressable>
                  <Pressable
                    style={styles.iconBtn}
                    onPress={() => deletePunch(p)}
                    disabled={busy === p.record_id}
                  >
                    {busy === p.record_id ? (
                      <ActivityIndicator size="small" />
                    ) : (
                      <Ionicons name="trash-outline" size={18} color={colors.error} />
                    )}
                  </Pressable>
                </View>
              ))
            )}
          </View>
        ) : (
          <Text style={styles.empty}>Pick a firm and employee to view / edit punches.</Text>
        )}
      </ScrollView>

      {/* Add / Edit modal */}
      <Modal
        visible={modalOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setModalOpen(false)}
      >
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>
              {modalRecordId ? "Edit punch" : `Add ${modalKind.toUpperCase()} punch`}
            </Text>
            <Text style={styles.label}>Kind</Text>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 6 }}>
              <Pressable
                onPress={() => setModalKind("in")}
                style={[styles.modeBtn, modalKind === "in" && styles.modeBtnActive]}
              >
                <Text style={[
                  styles.modeBtnTxt,
                  modalKind === "in" && styles.modeBtnTxtActive,
                ]}>IN</Text>
              </Pressable>
              <Pressable
                onPress={() => setModalKind("out")}
                style={[styles.modeBtn, modalKind === "out" && styles.modeBtnActive]}
              >
                <Text style={[
                  styles.modeBtnTxt,
                  modalKind === "out" && styles.modeBtnTxtActive,
                ]}>OUT</Text>
              </Pressable>
            </View>
            <Text style={[styles.label, { marginTop: 10 }]}>Date</Text>
            <DateField
              value={modalDate}
              onChangeISO={setModalDate}
              testID="mpe-date"
            />
            <Text style={[styles.label, { marginTop: 10 }]}>Time (24-hour, HH:MM)</Text>
            <TextInput
              style={styles.input}
              value={modalAt}
              onChangeText={(v) => setModalAt(formatHHMM(v))}
              placeholder="08:00"
              selectTextOnFocus
              testID="mpe-modal-time"
            />
            <Text style={[styles.label, { marginTop: 10 }]}>Reason (audit)</Text>
            <TextInput
              style={[styles.input, { minHeight: 56 }]}
              value={modalReason}
              onChangeText={setModalReason}
              placeholder="e.g. Employee forgot to punch OUT"
              multiline
            />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <Pressable
                style={[styles.actionBtn, { backgroundColor: colors.surfaceTertiary, flex: 1 }]}
                onPress={() => setModalOpen(false)}
              >
                <Text style={[styles.actionBtnTxt, { color: colors.onSurface }]}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.actionBtn, { backgroundColor: colors.brand, flex: 1 }]}
                onPress={submitModal}
                disabled={busy === "modal"}
              >
                {busy === "modal" ? (
                  <ActivityIndicator color="#FFF" />
                ) : (
                  <Text style={styles.actionBtnTxt}>Save</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  container: { padding: spacing.md, paddingBottom: 40, gap: spacing.md },
  hero: {
    flexDirection: "row",
    gap: 12,
    padding: spacing.md,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.lg,
    ...shadow.card,
  },
  heroTitle: { ...type.h2, color: colors.brand },
  heroSubtitle: { ...type.body, color: colors.onSurfaceSecondary, marginTop: 2 },
  card: {
    padding: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    ...shadow.card,
  },
  label: { ...type.label, color: colors.onSurfaceSecondary, fontWeight: "700" },
  input: {
    marginTop: 6,
    borderWidth: 1,
    borderColor: colors.surfaceTertiary,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    backgroundColor: "#FFFFFF",
    color: colors.onSurface,
  },
  hint: { ...type.caption, color: colors.onSurfaceTertiary, marginTop: 6 },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.surfaceTertiary,
    marginRight: 8,
    backgroundColor: "#FFF",
  },
  chipActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  chipTxt: { color: colors.onSurfaceSecondary, fontWeight: "500" },
  chipTxtActive: { color: "#FFF", fontWeight: "700" },
  empPickedTxt: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 8 },
  modeBtn: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.surfaceTertiary,
    backgroundColor: "#FFF",
  },
  modeBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  modeBtnTxt: { color: colors.onSurfaceSecondary, fontWeight: "600" },
  modeBtnTxtActive: { color: "#FFF" },
  row: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.md,
    minWidth: 130,
  },
  actionBtnTxt: { color: "#FFF", fontWeight: "700" },
  empty: {
    ...type.caption,
    color: colors.onSurfaceTertiary,
    textAlign: "center",
    marginTop: 12,
    fontStyle: "italic",
  },
  punchRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 10,
    borderTopWidth: 1,
    borderTopColor: colors.surfaceTertiary,
  },
  punchTime: { ...type.body, color: colors.onSurface, fontWeight: "600" },
  punchMeta: { ...type.caption, color: colors.onSurfaceTertiary },
  iconBtn: {
    padding: 8,
    borderRadius: radius.sm,
    backgroundColor: "#F5F5F5",
  },
  modalBg: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.4)",
    justifyContent: "center",
    padding: spacing.md,
  },
  modalCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    gap: 8,
  },
  modalTitle: { ...type.h2, color: colors.brand, marginBottom: 4 },
});
