/**
 * Iter 89 — PF / ESIC Challan uploads (Automation module, web-only).
 *
 * Upload a monthly challan PDF/Excel/image, list all uploads with
 * filters, download any single file in original format, or export the
 * full list to Excel.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ScrollView,
  ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary, getApiBaseUrl } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";


type Challan = {
  challan_id: string;
  company_id: string;
  portal: "pf" | "esic";
  month: string;
  amount: number;
  trrn?: string | null;
  paid_on?: string | null;
  notes?: string | null;
  file_name?: string | null;
  file_mime?: string | null;
  created_at?: string;
};


export default function ChallansScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompany } = useSelectedCompany();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  useEffect(() => {
    if (Platform.OS !== "web") router.replace("/(tabs)");
  }, [router]);

  const [companyId, setCompanyId] = useState<string | null>(
    isSuper ? (selectedCompany?.company_id || null) : (user?.company_id || null),
  );
  const [portalFilter, setPortalFilter] = useState<"all" | "pf" | "esic">("all");
  const [rows, setRows] = useState<Challan[]>([]);
  const [loading, setLoading] = useState(false);

  // Upload form
  const [uPortal, setUPortal] = useState<"pf" | "esic">("pf");
  const [uMonth, setUMonth] = useState(new Date().toISOString().slice(0, 7));
  const [uAmount, setUAmount] = useState("");
  const [uTrrn, setUTrrn] = useState("");
  const [uPaid, setUPaid] = useState("");
  const [uNotes, setUNotes] = useState("");
  const [uFile, setUFile] = useState<{ b64: string; mime: string; name: string } | null>(null);
  const [uploading, setUploading] = useState(false);

  const load = useCallback(async () => {
    if (!companyId && !isSuper) return;
    setLoading(true);
    try {
      const q: string[] = [];
      if (companyId) q.push(`company_id=${companyId}`);
      if (portalFilter !== "all") q.push(`portal=${portalFilter}`);
      const r = await api<{ challans: Challan[] }>(
        `/admin/challans${q.length ? "?" + q.join("&") : ""}`,
      );
      setRows(r.challans || []);
    } finally { setLoading(false); }
  }, [companyId, portalFilter, isSuper]);

  useEffect(() => { load(); }, [load]);

  const pickFile = () => {
    const input = (globalThis as any).document?.createElement?.("input");
    if (!input) return;
    input.type = "file";
    input.accept = "application/pdf,image/png,image/jpeg,image/webp,.xlsx,.xls,.csv";
    input.onchange = (e: any) => {
      const file = e?.target?.files?.[0];
      if (!file) return;
      if (file.size > 8 * 1024 * 1024) {
        window.alert("File must be under 8 MB.");
        return;
      }
      const reader = new (globalThis as any).FileReader();
      reader.onloadend = () => setUFile({
        b64: reader.result as string,
        mime: file.type || "application/pdf",
        name: file.name,
      });
      reader.readAsDataURL(file);
    };
    input.click();
  };

  const upload = async () => {
    if (!uFile) { window.alert("Pick a file first"); return; }
    if (uMonth.length !== 7 || uMonth[4] !== "-") { window.alert("Month must be YYYY-MM"); return; }
    setUploading(true);
    try {
      await api("/admin/challans", {
        method: "POST",
        body: {
          company_id: companyId,
          portal: uPortal,
          month: uMonth,
          amount: Number(uAmount) || 0,
          trrn: uTrrn || null,
          paid_on: uPaid || null,
          notes: uNotes || null,
          file_base64: uFile.b64,
          file_mime: uFile.mime,
          file_name: uFile.name,
        },
      });
      window.alert(`✅ ${uPortal.toUpperCase()} challan for ${uMonth} uploaded`);
      setUFile(null); setUAmount(""); setUTrrn(""); setUPaid(""); setUNotes("");
      await load();
    } catch (e: any) {
      window.alert(e?.message || "Upload failed");
    } finally { setUploading(false); }
  };

  const downloadOne = async (c: Challan) => {
    try {
      const doc = await api<{ challan: Challan & { file_base64: string } }>(
        `/admin/challans/${c.challan_id}`,
      );
      const raw = doc.challan.file_base64 || "";
      const b64 = raw.startsWith("data:") ? raw.split(",", 2)[1] : raw;
      // Convert base64 to blob and trigger download
      const bin = atob(b64);
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const blob = new Blob([bytes], { type: c.file_mime || "application/octet-stream" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = c.file_name || `${c.portal}-${c.month}`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      window.alert(e?.message || "Download failed");
    }
  };

  const exportXlsx = async () => {
    try {
      const q: string[] = [];
      if (companyId) q.push(`company_id=${companyId}`);
      if (portalFilter !== "all") q.push(`portal=${portalFilter}`);
      const r = await apiBinary(
        `/admin/challans/export.xlsx${q.length ? "?" + q.join("&") : ""}`,
      );
      if (!r.webBlobUrl) throw new Error("Download failed");
      const a = document.createElement("a");
      a.href = r.webBlobUrl;
      a.download = `challans-${new Date().toISOString().slice(0, 10)}.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(r.webBlobUrl!), 30000);
    } catch (e: any) {
      window.alert(e?.message || "Excel export failed");
    }
  };

  // Iter 95i — EPFO / ESIC portal upload files from a compliance run.
  // Iter 96c — month-wise + employee-group-wise selection (user request).
  type RunLite = { run_id: string; month: string; company_id?: string | null; employee_type?: string | null; employees_count?: number; finalized_at?: string | null };
  const [runs, setRuns] = useState<RunLite[]>([]);
  const [selRunId, setSelRunId] = useState<string>("");
  const [dlPortal, setDlPortal] = useState<string | null>(null);
  const [runMonth, setRunMonth] = useState<string>("all");
  const [runGroup, setRunGroup] = useState<string>("all");

  const filteredRuns = runs.filter(
    (r) =>
      (runMonth === "all" || r.month === runMonth) &&
      (runGroup === "all" || (r.employee_type || "All") === runGroup),
  );
  const runMonths = Array.from(new Set(runs.map((r) => r.month))).sort().reverse();
  const runGroups = Array.from(new Set(runs.map((r) => r.employee_type || "All")));
  // User directive — "All months" is only offered when every run is finalized,
  // so aggregate views never mix in unfinalized (draft) months.
  const allRunsFinalized = runs.length > 0 && runs.every((r) => !!r.finalized_at);
  useEffect(() => {
    if (!allRunsFinalized && runMonth === "all" && runMonths[0]) {
      setRunMonth(runMonths[0]);
    }
  }, [runs, allRunsFinalized]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    // keep selection valid within the current month/group filter
    if (filteredRuns.length && !filteredRuns.some((r) => r.run_id === selRunId)) {
      setSelRunId(filteredRuns[0].run_id);
    } else if (!filteredRuns.length && selRunId) {
      setSelRunId("");
    }
  }, [runMonth, runGroup, runs]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    (async () => {
      try {
        // Iter 174 (user directive) — Automation only works on FINALIZED
        // compliance data; drafts are hidden and reprocessed months are
        // deduped server-side to the newest run.
        const q = `?finalized_only=true${companyId ? `&company_id=${companyId}` : ""}`;
        const r = await api<{ runs: RunLite[] }>(`/admin/compliance-salary-runs${q}`);
        const list = (r.runs || []).slice(0, 60);
        setRuns(list);
        setSelRunId(list[0]?.run_id || "");
      } catch {
        setRuns([]);
        setSelRunId("");
      }
    })();
  }, [companyId]);

  // Iter 96e — missing statutory numbers (UAN / ESI IP) summary
  type MissRow = { user_id: string; employee_code: string; name: string; employee_type: string; uan_no: string; esi_ip_no: string };
  const [missing, setMissing] = useState<{ total: number; missing_uan: number; missing_esi: number; employees: MissRow[] } | null>(null);
  const [missOpen, setMissOpen] = useState(false);
  const [missDl, setMissDl] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const q = companyId ? `?company_id=${companyId}` : "";
        const r = await api<{ total: number; missing_uan: number; missing_esi: number; employees: MissRow[] }>(
          `/admin/challans/missing-statutory${q}`,
        );
        setMissing(r);
      } catch { setMissing(null); }
    })();
  }, [companyId]);

  const downloadMissingXlsx = async () => {
    setMissDl(true);
    try {
      const q = companyId ? `?company_id=${companyId}` : "";
      const r = await apiBinary(`/admin/challans/missing-statutory.xlsx${q}`);
      if (!r.webBlobUrl) throw new Error("Download failed");
      const a = document.createElement("a");
      a.href = r.webBlobUrl;
      a.download = "missing-statutory-numbers.xlsx";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(r.webBlobUrl!), 30000);
    } catch (e: any) {
      window.alert(e?.message || "Download failed");
    } finally { setMissDl(false); }
  };

  const downloadPortalFile = async (kind: "ecr.txt" | "ecr.xlsx" | "esic.xls" | "esic.xlsx") => {
    if (!selRunId) { window.alert("Run a Compliance Salary first, then pick the run here."); return; }
    setDlPortal(kind);
    try {
      const r = await apiBinary(`/admin/challans/${kind}?run_id=${encodeURIComponent(selRunId)}`);
      if (!r.webBlobUrl) throw new Error("Download failed");
      const month = runs.find((x) => x.run_id === selRunId)?.month || "month";
      const names: Record<string, string> = {
        "ecr.txt": `ECR_${month}.txt`,
        "ecr.xlsx": `ECR_${month}.xlsx`,
        "esic.xls": `ESIC_MC_${month}.xls`,
        "esic.xlsx": `ESIC_MC_${month}.xlsx`,
      };
      const a = document.createElement("a");
      a.href = r.webBlobUrl;
      a.download = names[kind];
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(r.webBlobUrl!), 30000);
    } catch (e: any) {
      window.alert(e?.message || "Download failed");
    } finally {
      setDlPortal(null);
    }
  };

  const doDelete = async (id: string) => {
    if (!window.confirm("Delete this challan?")) return;
    await api(`/admin/challans/${id}`, { method: "DELETE" });
    await load();
  };

  // 🤖 User directive — one-click AUTO upload of ECR / ESIC bulk sheet to the
  // government portal. Stops at challan finalisation (no bank payment).
  type UpJob = {
    job_id: string; portal: string; month?: string; file_name?: string;
    status: string; manual_reason?: string; note?: string; error?: string;
    created_at?: string; steps: { at: string; msg: string }[];
  };
  const [upJobs, setUpJobs] = useState<UpJob[]>([]);
  const [queueing, setQueueing] = useState<string | null>(null);
  // Iter 161 — on-screen data preview before portal upload.
  const [preview, setPreview] = useState<any>(null);
  const [previewBusy, setPreviewBusy] = useState<string>("");
  const loadPreview = async (kind: "epfo" | "esic") => {
    if (!selRunId) return;
    if (preview?.kind === kind) { setPreview(null); return; } // toggle off
    setPreviewBusy(kind);
    try {
      setPreview(await api<any>(`/admin/challans-portal-preview?run_id=${selRunId}&kind=${kind}`));
    } catch (e: any) {
      if (Platform.OS === "web") globalThis.alert(e?.message || "Preview failed");
    } finally { setPreviewBusy(""); }
  };

  const loadUpJobs = React.useCallback(async () => {
    try {
      const q = companyId ? `?company_id=${companyId}` : "";
      const r = await api<{ jobs: UpJob[] }>(`/admin/portal-upload-jobs${q}`);
      setUpJobs(r.jobs || []);
    } catch { setUpJobs([]); }
  }, [companyId]);
  useEffect(() => { void loadUpJobs(); }, [loadUpJobs]);
  useEffect(() => {
    if (!upJobs.some((j) => ["pending", "in_progress"].includes(j.status))) return;
    const t = setInterval(() => { void loadUpJobs(); }, 10000);
    return () => clearInterval(t);
  }, [upJobs, loadUpJobs]);

  const queueUpload = async (portal: "epfo" | "esic") => {
    if (!selRunId) { window.alert("Run a Compliance Salary first, then pick the run above."); return; }
    if (!window.confirm(
      `Queue AUTO upload to the ${portal.toUpperCase()} portal?\n\n` +
      "The robot logs in with the Firm Master credentials (AI captcha reading), " +
      "uploads the generated file and STOPS at challan finalisation.\n" +
      "Bank payment is NEVER done automatically.",
    )) return;
    setQueueing(portal);
    try {
      const r = await api<any>("/admin/portal-upload-jobs", {
        method: "POST", body: { run_id: selRunId, portal },
      });
      window.alert(`Queued ✓ — ${r.file_name} (job ${r.job_id}). Track it below.`);
      await loadUpJobs();
    } catch (e: any) { window.alert(e?.message || "Could not queue the upload"); }
    finally { setQueueing(null); }
  };

  const downloadJobFile = async (j: UpJob) => {
    try {
      const r = await apiBinary(`/admin/portal-upload-jobs/${j.job_id}/file`);
      if (!r.webBlobUrl) throw new Error("Download failed");
      const a = document.createElement("a");
      a.href = r.webBlobUrl;
      a.download = j.file_name || "upload.bin";
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(r.webBlobUrl!), 30000);
    } catch (e: any) { window.alert(e?.message || "Download failed"); }
  };

  const JOB_CHIP: Record<string, { bg: string; fg: string; label: string }> = {
    pending: { bg: "#FEF3C7", fg: "#92400E", label: "Queued" },
    in_progress: { bg: "#DBEAFE", fg: "#1D4ED8", label: "Running…" },
    completed: { bg: "#DCFCE7", fg: "#166534", label: "Uploaded ✓" },
    manual_required: { bg: "#FFEDD5", fg: "#9A3412", label: "Finish manually" },
    failed: { bg: "#FEE2E2", fg: "#B91C1C", label: "Failed" },
  };

  return (
    <View style={styles.root}>
      <View style={styles.head}>
        <Text style={styles.h1}>PF / ESIC Challan Uploads</Text>
        <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
          {isSuper ? <CompanyPicker value={companyId} onChange={(id) => setCompanyId(id)} /> : null}
          <Pressable onPress={exportXlsx} style={styles.exportBtn}>
            <Ionicons name="download-outline" size={14} color="#FFF" />
            <Text style={styles.exportBtnTxt}>Export Excel</Text>
          </Pressable>
        </View>
      </View>

      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
        {/* Iter 161 — direct access to the new PF / ESIC report hubs */}
        <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
          <Pressable
            onPress={() => router.push("/pf-reports?kind=pf" as any)}
            style={styles2.quickBtn}
            testID="quick-pf-reports"
          >
            <Ionicons name="briefcase-outline" size={15} color="#fff" />
            <Text style={styles2.quickTxt}>PF Reports (Challan + ECR)</Text>
          </Pressable>
          <Pressable
            onPress={() => router.push("/pf-reports?kind=esic" as any)}
            style={styles2.quickBtn}
            testID="quick-esic-reports"
          >
            <Ionicons name="medkit-outline" size={15} color="#fff" />
            <Text style={styles2.quickTxt}>ESIC Reports (Sheet + Challan)</Text>
          </Pressable>
        </View>
        {/* Iter 95i — EPFO / ESIC portal upload file generator */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>🏛️ Portal Upload Files (EPFO ECR / ESIC MC)</Text>
          <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, marginBottom: 6 }}>
            Generated from a saved Compliance Salary run. EPFO .txt is the exact
            6-field contribution file (UAN#~#NAME#~#EE#~#EPS#~#ER#~#REFUND); ESIC .xls
            matches your portal sheet (ESI_CODE, NAME, DAYS, SAL, RE, DATE). Employees
            missing UAN / ESIC number are skipped in portal files and highlighted in the
            check Excels.
          </Text>
          <View style={{ flexDirection: "row", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
            <View style={{ minWidth: 110 }}>
              <Text style={styles.lbl}>Month</Text>
              {Platform.OS === "web" ? (
                <select
                  value={runMonth}
                  onChange={(e: any) => setRunMonth(e.target.value)}
                  style={{ padding: 8, borderRadius: 8, border: "1px solid #D6DEE4", fontSize: 12.5, width: "100%", background: "#fff" }}
                  data-testid="portal-month-select"
                >
                  {allRunsFinalized ? <option value="all">All months</option> : null}
                  {runMonths.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              ) : null}
            </View>
            <View style={{ minWidth: 120 }}>
              <Text style={styles.lbl}>Employee Group</Text>
              {Platform.OS === "web" ? (
                <select
                  value={runGroup}
                  onChange={(e: any) => setRunGroup(e.target.value)}
                  style={{ padding: 8, borderRadius: 8, border: "1px solid #D6DEE4", fontSize: 12.5, width: "100%", background: "#fff" }}
                  data-testid="portal-group-select"
                >
                  <option value="all">All groups</option>
                  {runGroups.map((g) => <option key={g} value={g}>{g}</option>)}
                </select>
              ) : null}
            </View>
            <View style={{ minWidth: 260 }}>
              <Text style={styles.lbl}>Compliance Run</Text>
              {Platform.OS === "web" ? (
                <select
                  value={selRunId}
                  onChange={(e: any) => setSelRunId(e.target.value)}
                  style={{
                    padding: 8, borderRadius: 8, border: "1px solid #D6DEE4",
                    fontSize: 12.5, width: "100%", background: "#fff",
                  }}
                  data-testid="portal-run-select"
                >
                  {filteredRuns.length === 0 ? <option value="">No FINALIZED compliance run — finalize the month in Salary Process first</option> : null}
                  {filteredRuns.map((r) => (
                    <option key={r.run_id} value={r.run_id}>
                      {r.month} · {r.employee_type || "All"} · {r.employees_count || 0} emp{r.finalized_at ? " ✓" : ""}
                    </option>
                  ))}
                </select>
              ) : null}
            </View>
            <Pressable
              onPress={() => downloadPortalFile("ecr.txt")}
              disabled={!!dlPortal}
              style={[styles.uploadBtn, { backgroundColor: "#B91C1C" }, !!dlPortal && { opacity: 0.6 }]}
              testID="dl-ecr-txt"
            >
              {dlPortal === "ecr.txt" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="document-text-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>EPFO ECR (.txt)</Text>
            </Pressable>
            <Pressable
              onPress={() => downloadPortalFile("ecr.xlsx")}
              disabled={!!dlPortal}
              style={[styles.uploadBtn, { backgroundColor: "#15803D" }, !!dlPortal && { opacity: 0.6 }]}
              testID="dl-ecr-xlsx"
            >
              {dlPortal === "ecr.xlsx" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="grid-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>EPFO ECR (Excel)</Text>
            </Pressable>
            <Pressable
              onPress={() => downloadPortalFile("esic.xls")}
              disabled={!!dlPortal}
              style={[styles.uploadBtn, { backgroundColor: "#0369A1" }, !!dlPortal && { opacity: 0.6 }]}
              testID="dl-esic-xls"
            >
              {dlPortal === "esic.xls" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="medkit-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>ESIC Upload (.xls)</Text>
            </Pressable>
            <Pressable
              onPress={() => downloadPortalFile("esic.xlsx")}
              disabled={!!dlPortal}
              style={[styles.uploadBtn, { backgroundColor: "#64748B" }, !!dlPortal && { opacity: 0.6 }]}
              testID="dl-esic-xlsx"
            >
              {dlPortal === "esic.xlsx" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="eye-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>ESIC Check (Excel)</Text>
            </Pressable>
          </View>
        </View>

        {/* 🤖 User directive — automated portal upload (stops at challan) */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>🤖 Auto Upload to Portal (EPF Challan / ESIC Bulk Sheet)</Text>
          <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, marginBottom: 8 }}>
            Uses the run selected above. The robot logs in to the portal with the User
            ID/Password saved in Firm Master (AI reads the captcha), uploads the ECR
            .txt / ESIC bulk .xls and stops at challan finalisation — TRRN/challan
            approval and BANK PAYMENT are always left to you.
          </Text>
          <View style={{ flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
            <Pressable
              onPress={() => loadPreview("epfo")}
              disabled={!!previewBusy || !selRunId}
              style={[styles.uploadBtn, { backgroundColor: "#334155" }, !!previewBusy && { opacity: 0.6 }]}
              testID="preview-epfo"
            >
              {previewBusy === "epfo" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="eye-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>{preview?.kind === "epfo" ? "Hide EPF Data" : "Preview EPF Data"}</Text>
            </Pressable>
            <Pressable
              onPress={() => loadPreview("esic")}
              disabled={!!previewBusy || !selRunId}
              style={[styles.uploadBtn, { backgroundColor: "#475569" }, !!previewBusy && { opacity: 0.6 }]}
              testID="preview-esic"
            >
              {previewBusy === "esic" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="eye-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>{preview?.kind === "esic" ? "Hide ESIC Data" : "Preview ESIC Data"}</Text>
            </Pressable>
            <Pressable
              onPress={() => queueUpload("epfo")}
              disabled={!!queueing}
              style={[styles.uploadBtn, { backgroundColor: "#7C3AED" }, !!queueing && { opacity: 0.6 }]}
              testID="auto-upload-epfo"
            >
              {queueing === "epfo" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="cloud-upload-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>Auto-Upload EPF ECR → EPFO</Text>
            </Pressable>
            <Pressable
              onPress={() => queueUpload("esic")}
              disabled={!!queueing}
              style={[styles.uploadBtn, { backgroundColor: "#0E7490" }, !!queueing && { opacity: 0.6 }]}
              testID="auto-upload-esic"
            >
              {queueing === "esic" ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="cloud-upload-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>Auto-Upload ESIC Bulk Sheet → ESIC</Text>
            </Pressable>
          </View>
          {/* Iter 161 — data table shown BEFORE allowing portal upload */}
          {preview ? (
            <View style={{ marginTop: 10, borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 8, overflow: "hidden" }}>
              <View style={{ backgroundColor: "#F1F5F9", padding: 8 }}>
                <Text style={{ fontSize: 12, fontWeight: "800", color: colors.onSurface }}>
                  {preview.kind === "epfo" ? "EPF ECR Data" : "ESIC Upload Data"} · {preview.month} ·{" "}
                  {preview.totals.uploadable}/{preview.totals.members} members uploadable
                  {preview.kind === "epfo"
                    ? ` · EE ₹${preview.totals.epf_ee} · EPS ₹${preview.totals.eps_er} · ER ₹${preview.totals.diff_er}`
                    : ` · Wages ₹${preview.totals.wages} · EE ₹${preview.totals.ee}`}
                </Text>
              </View>
              <View style={{ flexDirection: "row", backgroundColor: "#F8FAFC", borderBottomWidth: 1, borderBottomColor: "#E2E8F0" }}>
                {(preview.kind === "epfo"
                  ? ["UAN", "Name", "Gross", "EPF Wg", "EPS Wg", "EE", "EPS", "ER", "NCP"]
                  : ["IP Number", "Name", "Days", "Wages", "EE Contri."]
                ).map((h) => (
                  <Text key={h} style={{ flex: h === "Name" ? 2 : 1, padding: 6, fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceSecondary }}>{h}</Text>
                ))}
              </View>
              {(preview.lines || []).map((x: any, i: number) => (
                <View key={i} style={{ flexDirection: "row", borderBottomWidth: 1, borderBottomColor: "#F1F5F9", backgroundColor: x.skipped ? "#FEF2F2" : undefined }}>
                  {(preview.kind === "epfo"
                    ? [x.uan || "⚠ no UAN", x.name, x.gross, x.epf_wages, x.eps_wages, x.epf_ee, x.eps_er, x.diff_er, x.ncp]
                    : [x.ip_no || "⚠ no IP", x.name, x.days, x.wages, x.ee]
                  ).map((v: any, j: number) => (
                    <Text key={j} style={{ flex: j === 1 ? 2 : 1, padding: 6, fontSize: 10.5, color: x.skipped ? "#B91C1C" : colors.onSurface }}>{String(v)}</Text>
                  ))}
                </View>
              ))}
              <Text style={{ padding: 6, fontSize: 10, color: colors.onSurfaceTertiary }}>
                Rows in red are missing UAN / IP number and will be SKIPPED by the portal upload.
                Verify this data, then use the Auto-Upload button above.
              </Text>
            </View>
          ) : null}
          {upJobs.length > 0 ? (
            <View style={{ marginTop: 10, gap: 8 }}>
              {upJobs.map((j) => {
                const chip = JOB_CHIP[j.status] || { bg: "#E2E8F0", fg: "#334155", label: j.status };
                const lastStep = j.steps?.length ? j.steps[j.steps.length - 1] : null;
                return (
                  <View key={j.job_id} style={{ borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 8, padding: 8, gap: 4 }}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                      <Text style={{ fontSize: 12.5, fontWeight: "800", color: colors.onSurface }}>
                        {j.portal === "epfo" ? "EPFO ECR" : "ESIC Bulk"} · {j.month || "—"}
                      </Text>
                      <View style={{ backgroundColor: chip.bg, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 }}>
                        <Text style={{ fontSize: 10.5, fontWeight: "800", color: chip.fg }} testID={`upjob-status-${j.job_id}`}>
                          {chip.label}
                        </Text>
                      </View>
                      <Text style={{ fontSize: 10.5, color: colors.onSurfaceTertiary }}>
                        {(j.created_at || "").slice(0, 16).replace("T", " ")}
                      </Text>
                      <Pressable onPress={() => downloadJobFile(j)} style={{ flexDirection: "row", alignItems: "center", gap: 4 }} testID={`upjob-file-${j.job_id}`}>
                        <Ionicons name="download-outline" size={13} color={colors.brandPrimary} />
                        <Text style={{ fontSize: 11, color: colors.brandPrimary, fontWeight: "700" }}>{j.file_name}</Text>
                      </Pressable>
                    </View>
                    {(j.manual_reason || j.note || lastStep?.msg) ? (
                      <Text style={{ fontSize: 11, color: colors.onSurfaceSecondary }} numberOfLines={3}>
                        {j.manual_reason || j.note || lastStep?.msg}
                      </Text>
                    ) : null}
                  </View>
                );
              })}
            </View>
          ) : null}
        </View>

        {/* Iter 96e — Missing statutory numbers */}
        <View style={styles.card}>
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 8 }}>
            <View style={{ flex: 1, minWidth: 260 }}>
              <Text style={styles.cardTitle}>🔎 Missing Statutory Numbers</Text>
              <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary }}>
                Employees without a UAN or ESI IP number are skipped in portal files.
                Fill these in the Employee Master before challan uploads.
              </Text>
            </View>
            {missing ? (
              <View style={{ flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                <View style={[styles.missPill, { backgroundColor: missing.missing_uan ? "#FEF3C7" : "#DCFCE7" }]}>
                  <Text style={[styles.missPillTxt, { color: missing.missing_uan ? "#92400E" : "#166534" }]} testID="miss-uan-count">
                    UAN missing: {missing.missing_uan}
                  </Text>
                </View>
                <View style={[styles.missPill, { backgroundColor: missing.missing_esi ? "#FEF3C7" : "#DCFCE7" }]}>
                  <Text style={[styles.missPillTxt, { color: missing.missing_esi ? "#92400E" : "#166534" }]} testID="miss-esi-count">
                    ESI IP missing: {missing.missing_esi}
                  </Text>
                </View>
                {missing.total > 0 ? (
                  <Pressable onPress={() => setMissOpen((v) => !v)} style={[styles.uploadBtn, { backgroundColor: "#475569" }]} testID="miss-toggle">
                    <Ionicons name={missOpen ? "chevron-up" : "chevron-down"} size={14} color="#FFF" />
                    <Text style={styles.uploadBtnTxt}>{missOpen ? "Hide list" : `Show ${missing.total}`}</Text>
                  </Pressable>
                ) : null}
                <Pressable onPress={downloadMissingXlsx} disabled={missDl || !missing.total}
                  style={[styles.uploadBtn, { backgroundColor: "#B45309" }, (missDl || !missing.total) && { opacity: 0.6 }]} testID="miss-export">
                  {missDl ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="download-outline" size={14} color="#FFF" />}
                  <Text style={styles.uploadBtnTxt}>Export Excel</Text>
                </Pressable>
              </View>
            ) : null}
          </View>
          {missOpen && missing && missing.total > 0 ? (
            <View style={{ marginTop: 10 }}>
              <View style={[styles.missRow, { backgroundColor: "#F1F5F9", borderTopLeftRadius: 8, borderTopRightRadius: 8 }]}>
                <Text style={[styles.missH, { width: 70 }]}>Code</Text>
                <Text style={[styles.missH, { flex: 2 }]}>Name</Text>
                <Text style={[styles.missH, { flex: 1 }]}>Group</Text>
                <Text style={[styles.missH, { flex: 1 }]}>UAN</Text>
                <Text style={[styles.missH, { flex: 1 }]}>ESI IP No</Text>
              </View>
              {missing.employees.slice(0, 200).map((r) => (
                <View key={r.user_id} style={styles.missRow}>
                  <Text style={[styles.missC, { width: 70 }]}>{r.employee_code}</Text>
                  <Text style={[styles.missC, { flex: 2 }]}>{r.name}</Text>
                  <Text style={[styles.missC, { flex: 1 }]}>{r.employee_type || "—"}</Text>
                  <Text style={[styles.missC, { flex: 1 }, !r.uan_no && styles.missBad]}>{r.uan_no || "MISSING"}</Text>
                  <Text style={[styles.missC, { flex: 1 }, !r.esi_ip_no && styles.missBad]}>{r.esi_ip_no || "MISSING"}</Text>
                </View>
              ))}
              {missing.total > 200 ? (
                <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 6 }}>
                  Showing first 200 of {missing.total} — download the Excel for the full list.
                </Text>
              ) : null}
            </View>
          ) : null}
        </View>

        {/* Upload card */}
        <View style={styles.card}>
          <Text style={styles.cardTitle}>📤 Upload New Challan</Text>
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={styles.lbl}>Portal</Text>
              <View style={{ flexDirection: "row", gap: 6 }}>
                {(["pf", "esic"] as const).map((p) => (
                  <Pressable key={p} onPress={() => setUPortal(p)}
                    style={[styles.chip, uPortal === p && styles.chipOn]}>
                    <Text style={[styles.chipTxt, uPortal === p && styles.chipTxtOn]}>{p.toUpperCase()}</Text>
                  </Pressable>
                ))}
              </View>
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.lbl}>Month (YYYY-MM)</Text>
              <TextInput value={uMonth} onChangeText={setUMonth} placeholder="2026-07" style={styles.input} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.lbl}>Amount (₹)</Text>
              <TextInput value={uAmount} onChangeText={setUAmount} keyboardType="numeric"
                placeholder="0" style={styles.input} />
            </View>
          </View>
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={styles.lbl}>TRRN (transaction ref)</Text>
              <TextInput value={uTrrn} onChangeText={setUTrrn} placeholder="Optional" style={styles.input} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.lbl}>Paid On (DD-MM-YYYY)</Text>
              <TextInput value={uPaid} onChangeText={setUPaid} placeholder="Optional" style={styles.input} />
            </View>
            <View style={{ flex: 2 }}>
              <Text style={styles.lbl}>Notes</Text>
              <TextInput value={uNotes} onChangeText={setUNotes} placeholder="Optional" style={styles.input} />
            </View>
          </View>
          <View style={{ flexDirection: "row", gap: 10, alignItems: "center", marginTop: 4 }}>
            <Pressable onPress={pickFile} style={styles.pickBtn}>
              <Ionicons name="cloud-upload-outline" size={14} color={colors.brandPrimary} />
              <Text style={styles.pickBtnTxt}>{uFile ? "Replace file" : "Choose file (PDF / Image / Excel)"}</Text>
            </Pressable>
            {uFile ? <Text style={styles.fileHint}>{uFile.name}</Text> : null}
            <View style={{ flex: 1 }} />
            <Pressable onPress={upload} disabled={uploading || !uFile}
              style={[styles.uploadBtn, (uploading || !uFile) && { opacity: 0.5 }]}>
              {uploading ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="save-outline" size={14} color="#FFF" />}
              <Text style={styles.uploadBtnTxt}>{uploading ? "Uploading..." : "Upload Challan"}</Text>
            </Pressable>
          </View>
        </View>

        {/* Filters + List */}
        <View style={styles.card}>
          <View style={{ flexDirection: "row", gap: 8, alignItems: "center", marginBottom: 8 }}>
            <Text style={styles.cardTitle}>📋 Uploaded Challans</Text>
            <View style={{ flex: 1 }} />
            {(["all", "pf", "esic"] as const).map((p) => (
              <Pressable key={p} onPress={() => setPortalFilter(p)}
                style={[styles.chip, portalFilter === p && styles.chipOn]}>
                <Text style={[styles.chipTxt, portalFilter === p && styles.chipTxtOn]}>{p.toUpperCase()}</Text>
              </Pressable>
            ))}
          </View>
          {loading ? (
            <ActivityIndicator style={{ margin: 30 }} color={colors.brandPrimary} />
          ) : rows.length === 0 ? (
            <Text style={styles.empty}>No challans uploaded yet.</Text>
          ) : (
            <View>
              <View style={styles.tHead}>
                <Text style={[styles.tHc, { flex: 1 }]}>Portal</Text>
                <Text style={[styles.tHc, { flex: 1 }]}>Month</Text>
                <Text style={[styles.tHc, { flex: 1 }]}>Amount (₹)</Text>
                <Text style={[styles.tHc, { flex: 1.5 }]}>TRRN</Text>
                <Text style={[styles.tHc, { flex: 1 }]}>Paid On</Text>
                <Text style={[styles.tHc, { flex: 1.5 }]}>File</Text>
                <Text style={[styles.tHc, { width: 130 }]}>Actions</Text>
              </View>
              {rows.map((r, idx) => (
                <View key={r.challan_id} style={[styles.tRow, idx % 2 && styles.tRowAlt]}>
                  <Text style={[styles.tC, { flex: 1, fontWeight: "700" }]}>{(r.portal || "").toUpperCase()}</Text>
                  <Text style={[styles.tC, { flex: 1 }]}>{r.month}</Text>
                  <Text style={[styles.tC, { flex: 1 }]}>₹{Number(r.amount || 0).toLocaleString()}</Text>
                  <Text style={[styles.tC, { flex: 1.5 }]}>{r.trrn || "—"}</Text>
                  <Text style={[styles.tC, { flex: 1 }]}>{r.paid_on || "—"}</Text>
                  <Text style={[styles.tC, { flex: 1.5 }]} numberOfLines={1}>{r.file_name || "—"}</Text>
                  <View style={{ width: 130, flexDirection: "row", gap: 6, alignItems: "center", padding: 6 }}>
                    <Pressable onPress={() => downloadOne(r)} hitSlop={4}>
                      <Ionicons name="download-outline" size={16} color={colors.brandPrimary} />
                    </Pressable>
                    <Pressable onPress={() => doDelete(r.challan_id)} hitSlop={4}>
                      <Ionicons name="trash-outline" size={16} color={colors.error} />
                    </Pressable>
                  </View>
                </View>
              ))}
            </View>
          )}
        </View>
      </ScrollView>
    </View>
  );
}


const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  head: {
    flexDirection: "row", justifyContent: "space-between", alignItems: "center",
    padding: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
    backgroundColor: colors.surfaceSecondary,
    gap: spacing.md, flexWrap: "wrap",
  },
  h1: { ...type.h3, color: colors.onSurface },
  exportBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  exportBtnTxt: { color: "#FFF", fontWeight: "700", fontSize: 12 },
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, gap: spacing.sm,
  },
  cardTitle: { ...type.h5, color: colors.onSurface },
  row: { flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" },
  lbl: { ...type.label, color: colors.onSurfaceSecondary, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 8,
    backgroundColor: colors.surface, color: colors.onSurface,
    fontSize: 13, minHeight: 36,
  },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandTertiary, borderColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurface, fontSize: 12, fontWeight: "600" },
  chipTxtOn: { color: colors.brandPrimary, fontWeight: "800" },
  pickBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill,
    backgroundColor: "#EEF2FF", borderWidth: 1, borderColor: "#C7D2FE",
  },
  pickBtnTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12 },
  fileHint: { ...type.caption, color: colors.onSurfaceSecondary },
  uploadBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  uploadBtnTxt: { color: "#FFF", fontWeight: "700", fontSize: 12 },
  missPill: { paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  missPillTxt: { fontSize: 12, fontWeight: "700" },
  missRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 6, paddingHorizontal: 8,
    borderBottomWidth: 1, borderBottomColor: "#EEF2F5",
  },
  missH: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  missC: { fontSize: 12, color: colors.onSurface },
  missBad: { color: "#B45309", fontWeight: "700" },
  empty: { ...type.caption, color: colors.onSurfaceTertiary, fontStyle: "italic", padding: 30, textAlign: "center" },
  tHead: {
    flexDirection: "row", backgroundColor: colors.brandTertiary,
    borderWidth: 1, borderColor: colors.border,
    borderTopLeftRadius: radius.sm, borderTopRightRadius: radius.sm,
  },
  tHc: { padding: 8, ...type.label, color: colors.onBrandTertiary, fontWeight: "800" },
  tRow: {
    flexDirection: "row", borderLeftWidth: 1, borderRightWidth: 1, borderBottomWidth: 1,
    borderColor: colors.border, alignItems: "center",
    backgroundColor: colors.surface,
  },
  tRowAlt: { backgroundColor: colors.surfaceSecondary },
  tC: { padding: 8, ...type.caption, color: colors.onSurface },
});

// Iter 161 — quick-access buttons to the PF / ESIC report hubs.
const styles2 = StyleSheet.create({
  quickBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 14,
    paddingVertical: 10, borderRadius: radius.sm,
  },
  quickTxt: { color: "#fff", fontSize: 12, fontWeight: "700" },
});
