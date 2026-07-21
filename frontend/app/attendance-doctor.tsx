/**
 * Iter 232 — ATTENDANCE DOCTOR (user request: blank "Total Duty HRS").
 *
 * Shows, for a firm + month, every employee-day whose Duty HRS is blank
 * with the EXACT reason (pending approval / missing IN / missing OUT /
 * pairing failed) and the full punch chain (time, kind, source, status).
 * Includes the "Auto Repair Attendance" tool: preview → apply → undo.
 * Repairs only normalise MACHINE punches (noise → auto_ignored, night
 * OUTs re-dated); manual & mobile punches are never modified. Payroll,
 * salary runs and leave data are untouched.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius } from "@/src/theme";
import { confirmYesNo } from "@/src/utils/confirm";

function showMsg(msg: string) {
  if (Platform.OS === "web") (globalThis as any).alert?.(msg);
  else Alert.alert("Attendance Doctor", msg);
}

type DocPunch = { time: string; date: string; kind: string; source?: string; status?: string };
type DocRow = {
  user_id: string; employee_code?: string; name?: string; bio_code?: string;
  date: string; punches: DocPunch[];
  pairs: { in: string; out: string; minutes: number }[];
  duty_hhmm?: string | null; duty_blank: boolean; reasons: string[];
  pending_count: number; ignored_count: number;
};

const REASON_LABEL: Record<string, string> = {
  pending_approval: "Punches AWAITING APPROVAL — approve them in Punch Approval",
  no_approved_punches: "No approved punches (rejected / ignored only)",
  missing_out: "Missing OUT punch",
  missing_in: "Missing IN punch",
  no_punches: "No punches",
  pairing_failed: "Pairing failed",
  ok: "OK",
};

export default function AttendanceDoctorScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId, companies } = useSelectedCompany() as any;
  const [firmId, setFirmId] = useState<string>(selectedCompanyId || "");
  const [month, setMonth] = useState<string>(() => new Date().toISOString().slice(0, 7));
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<DocRow[]>([]);
  const [problemCount, setProblemCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [repairBusy, setRepairBusy] = useState(false);

  useEffect(() => {
    if (!firmId && selectedCompanyId) setFirmId(selectedCompanyId);
  }, [selectedCompanyId, firmId]);

  const diagnose = useCallback(async () => {
    if (!firmId || !/^\d{4}-\d{2}$/.test(month)) {
      showMsg("Pick a firm and enter the month as YYYY-MM.");
      return;
    }
    setLoading(true);
    try {
      const j = await api<{ rows: DocRow[]; total_problem_days: number }>(
        `/admin/attendance-doctor?company_id=${firmId}&month=${month}`,
      );
      setRows(j.rows || []);
      setProblemCount(j.total_problem_days || 0);
    } catch (e: any) {
      showMsg(e?.message || "Diagnosis failed");
    } finally {
      setLoading(false);
    }
  }, [firmId, month]);

  const repair = useCallback(async (preview: boolean) => {
    if (!firmId) return;
    if (!preview) {
      const ok = await confirmYesNo(
        "Apply AUTO REPAIR?\nNoise machine punches will be marked ignored and night OUT punches re-dated to the shift's start day.\nManual/mobile punches and payroll data are NOT touched. You can Undo.",
      );
      if (!ok) return;
    }
    setRepairBusy(true);
    try {
      const j = await api<{ to_ignore: number; to_redate: number; changes: any[] }>(
        "/admin/attendance-doctor/repair",
        { method: "POST", body: { company_id: firmId, month, preview } },
      );
      if (preview) {
        showMsg(
          `Auto Repair preview:\n• punches to ignore (noise): ${j.to_ignore}\n• night OUTs to re-date: ${j.to_redate}\n\nPress "Apply Repair" to apply.`,
        );
      } else {
        showMsg(`Auto Repair applied ✓\nIgnored: ${j.to_ignore} · Re-dated: ${j.to_redate}`);
        diagnose();
      }
    } catch (e: any) {
      showMsg(e?.message || "Repair failed");
    } finally {
      setRepairBusy(false);
    }
  }, [firmId, month, diagnose]);

  const undoRepair = useCallback(async () => {
    const ok = await confirmYesNo("Undo all Auto Repairs for this firm + month?");
    if (!ok) return;
    setRepairBusy(true);
    try {
      const j = await api<{ restored: number }>(
        "/admin/attendance-doctor/repair/undo",
        { method: "POST", body: { company_id: firmId, month, preview: false } },
      );
      showMsg(`Restored ${j.restored} ignored punches back to approved.`);
      diagnose();
    } catch (e: any) {
      showMsg(e?.message || "Undo failed");
    } finally {
      setRepairBusy(false);
    }
  }, [firmId, month, diagnose]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      String(r.name || "").toLowerCase().includes(q)
      || String(r.employee_code || "").includes(q)
      || String(r.bio_code || "").includes(q));
  }, [rows, query]);

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} style={styles.backBtn} testID="ad-back">
          <Ionicons name="arrow-back" size={20} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>Attendance Doctor</Text>
      </View>
      <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 60 }}>
        <View style={styles.card}>
          <Text style={styles.cardTitle}>Diagnose blank Duty HRS</Text>
          {user?.role !== "company_admin" ? (
            <>
              <Text style={styles.label}>Firm</Text>
              <View style={styles.chipStrip}>
                {(companies || []).map((c: any) => (
                  <Pressable
                    key={c.company_id}
                    onPress={() => setFirmId(c.company_id)}
                    style={[styles.chip, firmId === c.company_id && styles.chipOn]}
                  >
                    <Text style={[styles.chipTxt, firmId === c.company_id && styles.chipTxtOn]} numberOfLines={1}>
                      {c.name}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </>
          ) : null}
          <Text style={styles.label}>Month (YYYY-MM)</Text>
          <TextInput
            style={[styles.input, { maxWidth: 140 }]}
            value={month}
            onChangeText={setMonth}
            placeholder="2026-07"
            placeholderTextColor={colors.onSurfaceTertiary}
            testID="ad-month"
          />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
            <Pressable onPress={diagnose} style={styles.primaryBtn} disabled={loading} testID="ad-diagnose">
              {loading ? <ActivityIndicator size="small" color="#fff" /> : <Ionicons name="medkit-outline" size={15} color="#fff" />}
              <Text style={styles.primaryBtnTxt}>Diagnose</Text>
            </Pressable>
            <Pressable onPress={() => repair(true)} style={styles.secBtn} disabled={repairBusy} testID="ad-repair-preview">
              <Ionicons name="construct-outline" size={15} color={colors.brandPrimary} />
              <Text style={styles.secBtnTxt}>Repair Preview</Text>
            </Pressable>
            <Pressable onPress={() => repair(false)} style={styles.secBtn} disabled={repairBusy} testID="ad-repair-apply">
              <Ionicons name="hammer-outline" size={15} color={colors.brandPrimary} />
              <Text style={styles.secBtnTxt}>Apply Repair</Text>
            </Pressable>
            <Pressable onPress={undoRepair} style={styles.secBtn} disabled={repairBusy} testID="ad-repair-undo">
              <Ionicons name="arrow-undo-outline" size={15} color={colors.brandPrimary} />
              <Text style={styles.secBtnTxt}>Undo Repair</Text>
            </Pressable>
          </View>
        </View>

        {rows.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.cardTitle}>
              Problem days: {problemCount}
            </Text>
            <TextInput
              style={styles.input}
              value={query}
              onChangeText={setQuery}
              placeholder="Search employee name / code / bio…"
              placeholderTextColor={colors.onSurfaceTertiary}
              testID="ad-search"
            />
            {filtered.map((r) => (
              <View key={`${r.user_id}_${r.date}`} style={styles.dayRow}>
                <View style={{ flexDirection: "row", justifyContent: "space-between", flexWrap: "wrap" }}>
                  <Text style={styles.dayEmp}>
                    {r.employee_code || "—"} · {r.name || ""} {r.bio_code ? `(bio ${r.bio_code})` : ""}
                  </Text>
                  <Text style={styles.dayDate}>{r.date}</Text>
                </View>
                <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 4 }}>
                  {r.reasons.map((reason) => (
                    <View key={reason} style={[styles.reasonPill, reason === "ok" && { backgroundColor: "#DCFCE7" }]}>
                      <Text style={[styles.reasonTxt, reason === "ok" && { color: "#166534" }]}>
                        {REASON_LABEL[reason] || reason}
                      </Text>
                    </View>
                  ))}
                </View>
                <Text style={styles.punchChain}>
                  {r.punches.map((p) =>
                    `${p.time} ${p.kind.toUpperCase()}${p.status !== "approved" ? ` [${p.status}]` : ""}`,
                  ).join("  →  ")}
                </Text>
                {r.pairs.length ? (
                  <Text style={styles.pairTxt}>
                    Pairs: {r.pairs.map((p) => `${p.in}→${p.out} (${Math.floor(p.minutes / 60)}:${String(p.minutes % 60).padStart(2, "0")})`).join(", ")}
                    {r.duty_hhmm ? `  ·  Duty ${r.duty_hhmm}` : ""}
                  </Text>
                ) : null}
              </View>
            ))}
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 10,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  backBtn: { padding: 6 },
  headerTitle: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 14,
  },
  cardTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  label: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 8, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 9, fontSize: 13, color: colors.onSurface,
    backgroundColor: colors.background, marginBottom: 4,
  },
  chipStrip: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    paddingVertical: 7, paddingHorizontal: 12, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface, maxWidth: 240,
  },
  chipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  chipTxtOn: { color: "#fff" },
  primaryBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 16,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  secBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 14, backgroundColor: colors.surface,
  },
  secBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  dayRow: {
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.border,
    paddingVertical: 10,
  },
  dayEmp: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  dayDate: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  reasonPill: {
    backgroundColor: "#FEE2E2", borderRadius: 999,
    paddingVertical: 3, paddingHorizontal: 10,
  },
  reasonTxt: { fontSize: 11, fontWeight: "800", color: "#B91C1C" },
  punchChain: { fontSize: 12, color: colors.onSurface, marginTop: 6 },
  pairTxt: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginTop: 3 },
});
