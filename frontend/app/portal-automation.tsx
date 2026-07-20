/**
 * Portal Automation — Iter 60.
 *
 * Assisted Playwright automation for uploading challans to EPFO / ESIC.
 * The backend spins up a headless Chromium, logs in with the stored
 * Portal Credentials, captures a screenshot at each step, and PAUSES if
 * a captcha is detected — the super admin then completes the upload
 * manually in the same browser (or from their desk).
 *
 * This screen lets the super admin:
 *   • Queue a new automation job (portal + compliance salary run)
 *   • Watch job status live (poll every 5s)
 *   • Review the screenshot audit trail
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  Platform,
  Alert,
  Image,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type ComplianceRun = { run_id: string; month: string; company_id: string };
type JobStep = {
  name: string;
  detail?: string;
  screenshot_b64?: string;
  at: string;
};
type Job = {
  job_id: string;
  portal: "epfo" | "esic";
  company_id: string;
  compliance_salary_run_id?: string;
  month?: string;
  // Iter 89 — extended for per-employee UAN/ESIC generation jobs
  action_type?: "generate_uan" | "generate_esic" | "attendance_upload";
  employee_user_id?: string;
  employee_snapshot?: any;
  manual_reason?: string;
  status:
    | "pending"
    | "queued"
    | "running"
    | "in_progress"
    | "paused_captcha"
    | "manual_required"
    | "completed_login"
    | "completed"
    | "failed";
  steps?: JobStep[];
  error?: string;
  created_at: string;
};

function showMsg(msg: string, title = "Portal Automation") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

const STATUS_META: Record<Job["status"], { color: string; label: string; icon: keyof typeof Ionicons.glyphMap }> = {
  pending: { color: "#8A6E00", label: "Pending", icon: "time-outline" },
  queued: { color: "#8A6E00", label: "Queued", icon: "time-outline" },
  running: { color: colors.brandPrimary, label: "Running", icon: "sync-outline" },
  in_progress: { color: colors.brandPrimary, label: "In progress", icon: "sync-outline" },
  paused_captcha: { color: "#B37700", label: "Paused – captcha", icon: "pause-circle-outline" },
  manual_required: { color: "#B37700", label: "Manual completion needed", icon: "person-outline" },
  completed_login: { color: "#1F7A3A", label: "Login OK – finish manually", icon: "checkmark-circle-outline" },
  completed: { color: "#1F7A3A", label: "Completed", icon: "checkmark-circle" },
  failed: { color: "#B02A2A", label: "Failed", icon: "close-circle-outline" },
};

// Iter 89 — Inline form rendered inside the job detail card when the
// job is a per-employee UAN/ESIC generation sitting in manual_required.
// The ops admin obtained the number from the government portal (they
// solved the captcha + OTP flow themselves) and pastes it here so the
// app can write it back to the employee record.
function ManualCompleteForm({
  job,
  onCompleted,
}: {
  job: Job;
  onCompleted: () => void | Promise<void>;
}) {
  const [value, setValue] = React.useState("");
  const [saving, setSaving] = React.useState(false);
  const isUan = job.action_type === "generate_uan";
  const empName = job.employee_snapshot?.name || "employee";
  const submit = async () => {
    const digits = value.replace(/\D+/g, "");
    if (isUan && digits.length !== 12) {
      showMsg("UAN must be exactly 12 digits."); return;
    }
    if (!isUan && (digits.length < 10 || digits.length > 17)) {
      showMsg("ESIC IP number should be 10-17 digits."); return;
    }
    setSaving(true);
    try {
      await api(`/admin/portal-automation/jobs/${job.job_id}/manual-complete`, {
        method: "POST",
        body: { value: digits },
      });
      showMsg(`Saved ${isUan ? "UAN" : "ESIC IP No."} for ${empName}.`);
      setValue("");
      await onCompleted();
    } catch (e: any) {
      showMsg(e?.message || "Failed to save");
    } finally { setSaving(false); }
  };
  return (
    <View style={{ marginTop: 12, gap: 8 }}>
      <View style={{ padding: 10, borderRadius: 8, backgroundColor: "#FFF7E6", borderWidth: 1, borderColor: "#FFD591" }}>
        <Text style={{ fontSize: 12, fontWeight: "800", color: "#8A6E00" }}>
          Manual completion required
        </Text>
        <Text style={{ fontSize: 12, color: "#8A6E00", marginTop: 4 }}>
          {job.manual_reason || "Complete the portal step manually, then paste the generated number below."}
        </Text>
      </View>
      <Text style={{ fontSize: 12, color: "#555" }}>
        Employee: <Text style={{ fontWeight: "700" }}>{empName}</Text>
      </Text>
      <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <TextInput
          value={value}
          onChangeText={setValue}
          placeholder={isUan ? "12-digit UAN" : "ESIC IP number"}
          keyboardType="numeric"
          style={{
            borderWidth: 1, borderColor: colors.border, borderRadius: 8,
            paddingHorizontal: 12, paddingVertical: 10, minWidth: 260,
            backgroundColor: colors.surface, fontSize: 14,
          }}
        />
        <Pressable
          onPress={submit}
          disabled={saving}
          style={({ pressed }) => [{
            paddingHorizontal: 16, paddingVertical: 10, borderRadius: 999,
            backgroundColor: colors.brandPrimary, flexDirection: "row",
            gap: 6, alignItems: "center",
            opacity: (saving || pressed) ? 0.7 : 1,
          }]}
          testID="manual-complete-submit"
        >
          {saving ? (
            <ActivityIndicator size="small" color="#FFF" />
          ) : (
            <Ionicons name="checkmark-circle-outline" size={16} color="#FFF" />
          )}
          <Text style={{ color: "#FFF", fontWeight: "800", fontSize: 12 }}>
            {saving ? "Saving..." : `Save ${isUan ? "UAN" : "ESIC"} & Complete Job`}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

export default function PortalAutomationScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  useEffect(() => {
    if (globalCid) setCompanyId(globalCid);
  }, [globalCid]);
  const [runs, setRuns] = useState<ComplianceRun[]>([]);
  const [runId, setRunId] = useState<string>("");
  const [portal, setPortal] = useState<"epfo" | "esic">("epfo");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [queueing, setQueueing] = useState(false);

  useEffect(() => {
    if (!isSuper) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
        if (r.companies?.length && !companyId) setCompanyId(r.companies[0].company_id);
      } catch (e: any) {
        showMsg(e?.message || "Could not load companies");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isSuper]);

  const loadRunsAndJobs = useCallback(async () => {
    if (!companyId) return;
    try {
      const [rs, js] = await Promise.all([
        api<{ runs: ComplianceRun[] }>(
          `/admin/compliance-salary-runs?company_id=${encodeURIComponent(companyId)}`,
        ).catch(() => ({ runs: [] as ComplianceRun[] })),
        api<{ items: Job[] }>(
          `/admin/portal-automation/jobs?company_id=${encodeURIComponent(companyId)}`,
        ),
      ]);
      setRuns(rs.runs || []);
      setJobs(js.items || []);
      if (rs.runs?.length && !runId) setRunId(rs.runs[0].run_id);
    } catch {
      // silent
    }
  }, [companyId, runId]);

  useEffect(() => {
    void loadRunsAndJobs();
  }, [loadRunsAndJobs]);

  // Poll selected job every 5s while it's not terminal
  useEffect(() => {
    if (!selectedJobId) return;
    let stopped = false;
    const tick = async () => {
      try {
        const j = await api<Job>(`/admin/portal-automation/jobs/${selectedJobId}`);
        if (stopped) return;
        setSelectedJob(j);
        if (["completed_login", "failed", "paused_captcha"].includes(j.status)) return;
        setTimeout(tick, 5000);
      } catch {
        // stop polling on error
      }
    };
    void tick();
    return () => {
      stopped = true;
    };
  }, [selectedJobId]);

  const queueJob = async () => {
    if (!companyId || !runId) return showMsg("Pick a company + compliance run.");
    setQueueing(true);
    try {
      const j = await api<Job>("/admin/portal-automation/jobs", {
        method: "POST",
        body: {
          portal,
          company_id: companyId,
          compliance_salary_run_id: runId,
        },
      });
      setSelectedJobId(j.job_id);
      setSelectedJob(j);
      await loadRunsAndJobs();
    } catch (e: any) {
      showMsg(e?.message || "Could not queue job");
    } finally {
      setQueueing(false);
    }
  };

  if (!isSuper) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only Super Admins can access portal automation.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.h1}>Portal Automation — EPFO / ESIC</Text>
            <Text style={styles.hsub}>
              Playwright + stored credentials. Screenshots each step · pauses on captcha.
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          <View style={styles.gridRow}>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Company (Firm)</Text>
              {Platform.OS === "web" ? (
                <select
                  value={companyId}
                  onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
                >
                  <option value="">— select —</option>
                  {companies.map((c) => (
                    <option key={c.company_id} value={c.company_id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Compliance Salary Run</Text>
              {Platform.OS === "web" ? (
                <select
                  value={runId}
                  onChange={(e) => setRunId((e.target as HTMLSelectElement).value)}
                  style={styles.selectStyle as any}
                >
                  <option value="">— select —</option>
                  {runs.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.month} — {r.run_id.slice(-6)}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
            <View style={styles.gridCol}>
              <Text style={styles.label}>Portal</Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                {(["epfo", "esic"] as const).map((p) => (
                  <Pressable
                    key={p}
                    onPress={() => setPortal(p)}
                    style={[styles.chip, portal === p && styles.chipActive]}
                  >
                    <Text style={[styles.chipTxt, { color: portal === p ? "#fff" : colors.onSurfaceSecondary }]}>
                      {p.toUpperCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>
            </View>
          </View>
          <Pressable
            onPress={queueJob}
            disabled={queueing || !companyId || !runId}
            style={[styles.primaryBtn, (queueing || !companyId || !runId) && { opacity: 0.5 }]}
            testID="pa-queue"
          >
            {queueing ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="play" size={16} color="#fff" />
                <Text style={styles.primaryBtnTxt}>Queue automation job</Text>
              </>
            )}
          </Pressable>
        </View>

        {jobs.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>Recent jobs</Text>
            {jobs.map((j) => {
              const meta = STATUS_META[j.status] || STATUS_META.queued;
              return (
                <Pressable
                  key={j.job_id}
                  onPress={() => {
                    setSelectedJobId(j.job_id);
                    setSelectedJob(j);
                  }}
                  style={[
                    styles.jobRow,
                    selectedJobId === j.job_id && { backgroundColor: colors.brandTertiary },
                  ]}
                >
                  <Ionicons name={meta.icon} size={18} color={meta.color} />
                  <View style={{ flex: 1 }}>
                    <Text style={styles.rowName}>
                      {j.portal.toUpperCase()} — {j.month}
                    </Text>
                    <Text style={styles.smallHint}>
                      {j.created_at?.slice(0, 19)} · {j.job_id.slice(-6)}
                    </Text>
                  </View>
                  <View style={{ paddingHorizontal: 8, paddingVertical: 4, borderRadius: 999, backgroundColor: meta.color + "22" }}>
                    <Text style={{ color: meta.color, fontSize: 11, fontWeight: "800" }}>{meta.label}</Text>
                  </View>
                </Pressable>
              );
            })}
          </View>
        ) : null}

        {selectedJob ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>
              Job {selectedJob.job_id.slice(-6)} — {selectedJob.portal.toUpperCase()}
            </Text>
            <Text style={styles.smallHint}>
              Status: {STATUS_META[selectedJob.status]?.label || selectedJob.status}
              {selectedJob.error ? ` · ${selectedJob.error}` : ""}
            </Text>
            {selectedJob.status === "completed_login" || selectedJob.status === "paused_captcha" ? (
              <View style={styles.calloutBox}>
                <Ionicons name="information-circle-outline" size={16} color={colors.brandPrimary} />
                <Text style={styles.calloutTxt}>
                  {selectedJob.status === "paused_captcha"
                    ? "Portal captcha detected. Please open the portal manually and complete the upload from your desk. Screenshots below show what the bot saw."
                    : "Login harness completed. Manually upload the ECR/ESIC file from your desk — the portal is now expecting your session."}
                </Text>
              </View>
            ) : null}
            {/* Iter 89 — Manual Completion form. Renders when the job
                was queued for per-employee UAN/ESIC generation and is
                sitting in `manual_required`. Ops admin pastes the
                number from the portal, we POST it, the backend writes
                back to db.users AND flips job status to `completed`. */}
            {selectedJob.status === "manual_required" &&
             (selectedJob.action_type === "generate_uan" || selectedJob.action_type === "generate_esic") ? (
              <ManualCompleteForm
                job={selectedJob}
                onCompleted={async () => {
                  // refresh both the selected job + the list
                  try {
                    const j = await api<Job>(`/admin/portal-automation/jobs/${selectedJob.job_id}`);
                    setSelectedJob(j);
                  } catch { /* noop */ }
                }}
              />
            ) : null}
            {(selectedJob.steps || []).map((s, i) => (
              <View key={i} style={styles.stepCard}>
                <View style={styles.stepHeader}>
                  <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceSecondary} />
                  <Text style={styles.stepName}>{s.name}</Text>
                  <Text style={styles.stepAt}>{s.at?.slice(11, 19)}</Text>
                </View>
                {s.detail ? <Text style={styles.stepDetail}>{s.detail}</Text> : null}
                {s.screenshot_b64 ? (
                  <Image
                    source={{ uri: `data:image/jpeg;base64,${s.screenshot_b64}` }}
                    style={styles.screenshot}
                    resizeMode="contain"
                  />
                ) : null}
              </View>
            ))}
          </View>
        ) : null}

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  h1: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  hsub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  scroll: { padding: spacing.lg, maxWidth: 1080, alignSelf: "center", width: "100%" },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceSecondary, textAlign: "center" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 6,
    textTransform: "uppercase",
  },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 4 },
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800", marginBottom: 8 },
  gridRow: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  gridCol: { flex: 1, minWidth: 200 },
  selectStyle: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.borderStrong,
    borderWidth: 1,
    fontSize: 14,
    width: "100%",
  },
  chip: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700" },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 10,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
  jobRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    paddingHorizontal: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    borderRadius: 6,
  },
  rowName: { color: colors.onSurface, fontSize: 14, fontWeight: "700" },
  calloutBox: {
    flexDirection: "row",
    gap: 8,
    backgroundColor: colors.brandTertiary,
    borderRadius: 8,
    padding: 10,
    marginTop: 8,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
  },
  calloutTxt: { flex: 1, color: colors.onSurface, fontSize: 12, lineHeight: 18 },
  stepCard: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
    paddingTop: 8,
    marginTop: 8,
  },
  stepHeader: { flexDirection: "row", alignItems: "center", gap: 6 },
  stepName: { flex: 1, color: colors.onSurface, fontWeight: "700", fontSize: 13 },
  stepAt: { color: colors.onSurfaceSecondary, fontSize: 11 },
  stepDetail: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 4 },
  screenshot: {
    width: "100%",
    height: 320,
    marginTop: 8,
    borderRadius: 6,
    borderWidth: 1,
    borderColor: colors.divider,
    backgroundColor: colors.background,
  },
});
