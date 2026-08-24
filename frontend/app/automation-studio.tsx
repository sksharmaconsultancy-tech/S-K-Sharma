/**
 * Compliance Automation Studio — Iter 234/235.
 *
 * Runs government-portal automations (EPFO / ESIC / …) on the server and
 * STREAMS a live view into the payroll: every click, field highlight,
 * typing and scroll is visible. CAPTCHA / OTP pause and ask the user for
 * input from inside this screen. Full controls: Start / Pause / Resume /
 * Retry / Skip / Previous / Stop / Emergency Stop.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary, getApiBaseUrl, readAuthToken } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing } from "@/src/theme";

type Flow = {
  key: string;
  label: string;
  portals: string[];
  needs_employee: boolean;
  needs_run: boolean;
};
type Portal = { key: string; label: string; url: string };
type Employee = { user_id: string; name?: string; employee_code?: string };
type Run = { run_id: string; month: string; status?: string };

const MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];
// "2026-05" → "May 2026" (falls back to the raw value).
function fmtMonth(m: string): string {
  const p = /^(\d{4})-(\d{2})$/.exec(m || "");
  if (!p) return m || "";
  const idx = parseInt(p[2], 10) - 1;
  return MONTH_NAMES[idx] ? `${MONTH_NAMES[idx]} ${p[1]}` : m;
}

type Session = {
  session_id: string;
  status: string;
  message: string;
  progress: number;
  current_step: number;
  current_url?: string | null;
  network?: string;
  browser?: string;
  frame_b64?: string | null;
  captcha_b64?: string | null;
  input_needed?: { kind: string; prompt: string } | null;
  steps: { index: number; name: string; status: string }[];
  logs: { t: string; msg: string; level: string }[];
  elapsed_sec: number;
  eta_sec?: number | null;
  portal_label?: string;
  flow_label?: string;
  company_name?: string;
  employee?: { name?: string } | null;
  run_month?: string | null;
  validation?: any;
  downloads?: { tag: string; file: string }[];
  job_id?: string;
  video?: string | null;
  error?: string | null;
};

const STATUS_COLOR: Record<string, string> = {
  running: "#16A34A",
  paused: "#D97706",
  completed: "#16A34A",
  failed: "#DC2626",
  stopped: "#6B7280",
};

const fmtDuration = (s?: number | null) => {
  if (!s || s < 0) return "0s";
  const m = Math.floor(s / 60);
  const ss = s % 60;
  return m > 0 ? `${m}m ${ss}s` : `${ss}s`;
};

export default function AutomationStudioScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";
  const { selectedCompanyId, setSelectedCompanyId } = useSelectedCompany() as any;
  // Iter 317 — firm selection is MANDATORY: treat "all"/empty as NO firm so
  // no automation (server RPA or PC-runner) can start without a real firm.
  const rawCid = isSuper ? selectedCompanyId : user?.company_id;
  const companyId = rawCid && rawCid !== "all" ? rawCid : "";

  const [flows, setFlows] = useState<Flow[]>([]);
  const [portals, setPortals] = useState<Portal[]>([]);
  const [portal, setPortal] = useState<string>("epfo");
  const [flow, setFlow] = useState<string>("login");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [empId, setEmpId] = useState<string>("");
  const [empSearch, setEmpSearch] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [runId, setRunId] = useState<string>("");
  // Iter 698 — month dropdown open/closed.
  const [monthDdOpen, setMonthDdOpen] = useState(false);
  const [validation, setValidation] = useState<any>(null);

  const [session, setSession] = useState<Session | null>(null);
  const [sid, setSid] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [inputVal, setInputVal] = useState("");
  const [tab, setTab] = useState<"run" | "history">("run");
  const [history, setHistory] = useState<any[]>([]);
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  // Iter 320 — manual override (mouse + keyboard on the portal) + fullscreen.
  const [manual, setManual] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [kbVal, setKbVal] = useState("");
  const { width: winW, height: winH } = useWindowDimensions();

  const pollRef = useRef<any>(null);

  useEffect(() => {
    setBaseUrl(getApiBaseUrl());
    readAuthToken().then((t) => setToken(t || ""));
  }, []);

  // ---- Catalog + selectors ----------------------------------------------
  useEffect(() => {
    api<{ portals: Portal[]; flows: Flow[] }>("/rpa/catalog")
      .then((r) => {
        setPortals(r.portals || []);
        setFlows(r.flows || []);
      })
      .catch(() => {});
  }, []);

  const portalFlows = flows.filter((f) => f.portals.includes(portal));
  const activeFlow = flows.find((f) => f.key === flow);

  useEffect(() => {
    // Ensure the selected flow is valid for the current portal.
    if (portalFlows.length && !portalFlows.find((f) => f.key === flow)) {
      setFlow(portalFlows[0].key);
    }
  }, [portal, flows]); // eslint-disable-line react-hooks/exhaustive-deps

  // Load employees when a flow needs one.
  useEffect(() => {
    if (!companyId || !activeFlow?.needs_employee) return;
    api<{ employees: Employee[] }>(
      `/admin/employees?company_id=${companyId}&limit=2000`,
    )
      .then((r) => setEmployees(r.employees || []))
      .catch(() => setEmployees([]));
  }, [companyId, activeFlow?.needs_employee]);

  // Load compliance runs when a flow needs one.
  useEffect(() => {
    if (!companyId || !activeFlow?.needs_run) return;
    api<{ runs: Run[] }>(`/rpa/runs?company_id=${companyId}`)
      .then((r) => setRuns(r.runs || []))
      .catch(() => setRuns([]));
  }, [companyId, activeFlow?.needs_run]);

  // Pre-flight validation preview.
  useEffect(() => {
    setValidation(null);
    if (!companyId || !activeFlow?.needs_run || !runId) return;
    api<{ report: any; month: string }>("/rpa/validate", {
      method: "POST",
      body: { company_id: companyId, portal, run_id: runId },
    })
      .then((r) => setValidation({ ...r.report, month: r.month }))
      .catch(() => {});
  }, [companyId, portal, runId, activeFlow?.needs_run]);

  // ---- Session polling ---------------------------------------------------
  const poll = useCallback(async (id: string) => {
    try {
      const s = await api<Session>(`/rpa/session/${id}`);
      setSession(s);
      if (["completed", "failed", "stopped"].includes(s.status)) {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = null;
      }
    } catch {
      /* keep polling */
    }
  }, []);

  // Iter 691 — 🔐 Open EPFO Portal on the operator's PC via ChromeDriver.
  // OPEN-ONLY: no username / password / captcha / OTP is filled, no login
  // automation — the user enters everything manually in the Chrome window.
  const pcPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [pcStatus, setPcStatus] = useState<string>("");
  const [pcBusy, setPcBusy] = useState<string>("");
  // Iter 694 — duplicate EPFO login detected across firms → one-click fix.
  const [dupWarn, setDupWarn] = useState<string>("");
  // Iter 701 — challan PDF saved for the selected month → download button.
  const [challanReady, setChallanReady] = useState(false);
  const [challanTrrn, setChallanTrrn] = useState("");

  useEffect(() => { setDupWarn(""); setPcStatus(""); }, [companyId]);

  useEffect(() => {
    setChallanReady(false); setChallanTrrn("");
    if (!runId) return;
    (async () => {
      try {
        const s = await api<any>(`/admin/compliance-salary-runs/${runId}/pf-challan-status`);
        setChallanReady(!!s?.exists);
        setChallanTrrn(s?.trrn || "");
      } catch { /* no challan yet */ }
    })();
  }, [runId]);

  const downloadChallan = async () => {
    try {
      const r = await apiBinary(`/admin/compliance-salary-runs/${runId}/pf-challan.pdf`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl;
        a.download = `PF_Challan_${challanTrrn || runId}.pdf`;
        document.body.appendChild(a); a.click(); a.remove();
      }
    } catch (e: any) {
      setPcStatus(`❌ ${e?.message || "Challan PDF not available yet."}`);
    }
  };

  const fixDupLogin = async () => {
    const ok = Platform.OS === "web"
      ? (globalThis as any).confirm(
          "Please confirm: this EPFO login belongs ONLY to the currently selected firm?\n\n" +
          "It will be REMOVED from every other firm where it was copied by mistake. " +
          "The selected firm's login stays unchanged.")
      : true;
    if (!ok) return;
    setPcBusy("fixdup");
    try {
      const r = await api<any>("/admin/portal-automation/claim-epfo-login", {
        method: "POST",
        body: JSON.stringify({ company_id: companyId }),
      });
      const cleaned = (r?.cleaned || []).join(", ");
      setDupWarn("");
      setPcStatus(cleaned
        ? `🧹 Done! The login stays on "${r?.kept_firm || "the selected firm"}" and was REMOVED from: ${cleaned}. Every firm will now fill its own correct login.`
        : "✅ No duplicates found — every firm already has its own separate login.");
    } catch (e: any) {
      setPcStatus(`❌ ${e?.message || "Cleanup failed — please try again."}`);
    } finally {
      setPcBusy("");
    }
  };

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      if (pcPollRef.current) clearInterval(pcPollRef.current);
    };
  }, []);

  const openEpfoPc = async (action?: string, flowLabel?: string, runIdArg?: string, portalKey: "epfo" | "esic" = "epfo") => {
    const P = portalKey.toUpperCase();
    if (Platform.OS !== "web") {
      setPcStatus("Open the portal on a computer (Chrome/Edge) to use this.");
      return;
    }
    if (!companyId) {
      setPcStatus(`Select a firm above first, then click Open ${P} Portal.`);
      return;
    }
    if (pcPollRef.current) { clearInterval(pcPollRef.current); pcPollRef.current = null; }
    setPcBusy("open");
    setPcStatus("Starting Chrome...");
    try {
      // Mint a fresh token bound to the CURRENTLY selected firm so the
      // Runner auto-fills THIS firm's EPFO login (not the one baked at
      // download time). Passed to the local Runner via ?token=.
      let launchTok = "";
      let credsUser = "";
      let credsWarn = "";
      try {
        const lt = await api<any>("/admin/portal-automation/launch-token", {
          method: "POST",
          body: JSON.stringify({ company_id: companyId, run_id: runIdArg || undefined, portal: portalKey }),
        });
        launchTok = lt?.token || "";
        // Iter 692 — the backend now pre-checks THIS firm's EPFO login and
        // returns the EXACT reason when it can't be used. Show it right
        // here and STOP — opening Chrome without a login wastes the user's
        // time and only shows a generic message.
        if (lt && lt.creds_found === false) {
          const firm = lt.creds_firm_name ? ` (${lt.creds_firm_name})` : "";
          setPcStatus(`❌ ${P} login problem${firm}: ${lt.creds_diagnosis || "no saved login found."}`);
          setPcBusy("");
          return;
        }
        if (lt && lt.creds_found === true) {
          credsUser = lt.creds_user_id || "";
          credsWarn = lt.creds_warning || "";
          setDupWarn(credsWarn);
          setPcStatus(
            `✅ ${P} login found${lt.creds_firm_name ? ` for ${lt.creds_firm_name}` : ""}: ${credsUser} (${lt.creds_source}). Opening Chrome...`
            + (credsWarn ? `\n${credsWarn}` : ""));
        }
      } catch (e: any) {
        // Iter 693 (user bug — WRONG firm's login was filled): NEVER fall
        // back to the runner's baked download-time token. That token is
        // bound to whichever firm was selected when the ZIP was downloaded,
        // so the fallback silently filled ANOTHER firm's credentials.
        setPcStatus(
          `❌ Could not create this firm's secure token — server said: "${e?.message || "network error"}". ` +
          "The process was stopped here so the WRONG firm's login is never filled. " +
          "Please refresh the page, log in again, then click the button.");
        setPcBusy("");
        return;
      }
      if (!launchTok) {
        setPcStatus("❌ Firm token missing — refresh the page and try again.");
        setPcBusy("");
        return;
      }
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 3000);
      const url = `http://127.0.0.1:8765/login?portal=${portalKey}_open`
        + `&token=${encodeURIComponent(launchTok)}`
        + (action ? `&action=${encodeURIComponent(action)}` : "")
        + (runIdArg ? `&run_id=${encodeURIComponent(runIdArg)}` : "");
      const r = await fetch(url, { signal: ctrl.signal });
      clearTimeout(timer);
      // Warn if the PC Runner is running old code (needs a restart/reboot
      // to self-update). Non-blocking — the launch still proceeds.
      try {
        const pg = await fetch("http://127.0.0.1:8765/ping");
        const pj: any = await pg.json();
        const build = parseInt(String(pj?.build || "0"), 10);
        if (build && build < 19) {
          setPcStatus(
            `⚠ Your PC Runner is OUTDATED (v${build}). It's running old code — ` +
            "please REBOOT this PC once (or end all python tasks in Task Manager " +
            "and re-run install_autostart.bat) so it updates, then click again.");
          setPcBusy("");
          return;
        }
        if (action && build && build < 22) {
          setPcStatus(
            `⚠ Runner v${build} will only do the LOGIN — to auto-open the "${flowLabel || action}" page ` +
            "the Runner needs an update: run install_autostart.bat once again " +
            "(or restart the PC), then click this button again. Login is still proceeding...");
        }
      } catch {
        // ping without build → old runner; fall through, user will see result
      }
      const j: any = await r.json().catch(() => ({}));
      if (!r.ok || !j?.ok) throw new Error("runner not ok");
      const job = j?.job || "";
      if (!job) {
        setPcStatus(
          "Opening EPFO Portal... (restart run_listener.bat once to get live status — it self-updates)");
        return;
      }
      const who = credsUser ? ` (${credsUser})` : "";
      const act = flowLabel ? `"${flowLabel}"` : "page";
      const MAP: Record<string, string> = {
        starting: "Starting Chrome...",
        opening: `Opening ${P} Portal...`,
        retrying: `⏳ ${P} server busy — auto-retrying, please wait...`,
        await_captcha: `⌨ Login filled ✓${who} — type the CAPTCHA now, ${portalKey === "esic" ? "Login" : "Sign In"} will click automatically`,
        signed_in: `✅ ${portalKey === "esic" ? "Login" : "Sign In"} clicked — check the portal`,
        wait_login: "⏳ Waiting for the login to complete — type the OTP too if the portal asks...",
        navigating: `✅ Logged in — opening ${act}...`,
        action_open: `✅ ${act} is OPEN — continue in the Chrome window`,
        action_manual: `✅ Logged in — ${act} did not auto-open, please open it from the top menu`,
        ecr_fetch: "⏳ Downloading this month's PF ECR file...",
        ecr_attached: "✅ ECR file ATTACHED — review and click Upload; the TRRN will be captured automatically after you upload",
        ecr_manual: "⚠ Page open but the ECR file could not be auto-attached — the Runner window shows the file location; attach it manually",
        open: `✅ ${P} Portal Open — login filled${who}, enter CAPTCHA & ${portalKey === "esic" ? "Login" : "Sign In"}`,
        open_nocreds: portalKey === "esic"
          ? "⚠ Portal opened but NO ESIC login is saved for THIS firm. Go to Firm Master → ESI Registration → fill ESI User ID + ESI Password → Save, then click again."
          : "⚠ Portal opened but NO EPFO login is saved for THIS firm. Go to Firm Master → EPF Registration → fill EPF User ID + EPF Password → Save, then click again.",
        open_nofield:
          "⚠ Portal opened but the login boxes weren't filled (page was still loading or a popup blocked it). Type login manually, or reload & retry.",
        closed: "Browser Closed",
      };
      pcPollRef.current = setInterval(async () => {
        try {
          const s = await fetch(`http://127.0.0.1:8765/status?job=${encodeURIComponent(job)}`);
          const sj: any = await s.json();
          const stx = String(sj?.status || "");
          if (stx.startsWith("trrn:")) {
            const trrn = stx.slice(5);
            setPcStatus(`🎫 TRRN captured: ${trrn} — saved in the app. Waiting for the challan PDF download (click/print the challan on the portal)...`);
            return; // keep polling — the challan PDF may follow
          }
          if (stx === "challan_saved") {
            setPcStatus("📄 Challan PDF saved in the app — use the Download Challan PDF button (next to the month) anytime for payroll.");
            setChallanReady(true);
            if (pcPollRef.current) clearInterval(pcPollRef.current);
            pcPollRef.current = null;
            return;
          }
          const base = MAP[stx] || stx || "…";
          setPcStatus(credsWarn ? `${base}\n${credsWarn}` : base);
          if (stx === "closed" || stx.startsWith("error") || stx.startsWith("busy")
              || (stx === "action_open" && action !== "ecr" && action !== "contrib")
              || (stx === "action_manual" && action !== "ecr" && action !== "contrib")
              || (stx === "signed_in" && !action)) {
            if (pcPollRef.current) clearInterval(pcPollRef.current);
            pcPollRef.current = null;
          }
        } catch {
          if (pcPollRef.current) clearInterval(pcPollRef.current);
          pcPollRef.current = null;
        }
      }, 1500);
    } catch {
      setPcStatus(
        "⚠ SKS Runner is not running on this PC. Download the ChromeDriver setup below (once), " +
        "unzip to C:\\SKS-AutoLogin and double-click install_autostart.bat — it starts the Runner " +
        "now AND silently on every Windows boot. Then click this button again.");
    } finally {
      setPcBusy("");
    }
  };

  const downloadRunner = async () => {
    if (Platform.OS !== "web") {
      setPcStatus("Open this page on a computer (Chrome/Edge) to download the setup.");
      return;
    }
    if (!companyId) {
      setPcStatus("Select a firm above first, then download the ChromeDriver setup.");
      return;
    }
    setPcBusy("runner");
    try {
      const origin = (globalThis as any).location?.origin || "";
      const res = await apiBinary(
        `/admin/portal-automation/runner-download?api_base=${encodeURIComponent(origin)}&company_id=${encodeURIComponent(companyId)}`,
      );
      if (res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = "sks-autologin-pc.zip";
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
        setPcStatus(
          "✅ Setup downloaded. Unzip to C:\\SKS-AutoLogin → double-click " +
          "install_autostart.bat ONCE. The Runner then starts silently with " +
          "Windows forever — you never open anything again. Then click 🔐 Open EPFO Portal.");
      }
    } catch (e: any) {
      setPcStatus(e?.message || "Download failed");
    } finally {
      setPcBusy("");
    }
  };

  // Iter 693 (user request) — EVERY EPFO action now uses the SAME verified
  // PC-Chrome login process (open portal → auto-fill this firm's login →
  // you type CAPTCHA → auto Sign In), then auto-opens the action's page.
  // The OLD server-side EPFO automation is retired.
  const EPFO_PC_ACTION: Record<string, string> = {
    login: "",
    epfo_generate_uan: "uan",
    epfo_ecr_upload: "ecr",
    epfo_member_search: "member_search",
    epfo_establishment: "establishment",
  };

  // Iter 701 (user request) — ESIC pages auto-open after login, like EPFO.
  const ESIC_PC_ACTION: Record<string, string> = {
    login: "",
    esic_ip_register: "ip_register",
    esic_contribution_upload: "contrib",
    esic_contribution_history: "contrib_history",
    esic_dashboard: "",
  };

  const start = async () => {
    if (!companyId) {
      setErr("Firm selection is mandatory. Please select a firm from the “Firm (required)” selector above before starting any process.");
      return;
    }
    setErr("");
    if (portal === "epfo" || portal === "esic") {
      // New unified path: run on the operator's PC Chrome via the Runner.
      // Iter 700 — ESIC uses the SAME process (fill Username/LIN + Password
      // from Firm Master → ESI Registration; user types CAPTCHA; auto Login).
      const act = portal === "epfo" ? (EPFO_PC_ACTION[flow] ?? "") : (ESIC_PC_ACTION[flow] ?? "");
      // Iter 699/704 — ECR Upload & ESIC Contribution need the month so the
      // runner can fetch/attach files and file the challan on that month.
      const needsMonth = act === "ecr" || act === "contrib";
      if (needsMonth && activeFlow?.needs_run && !runId) {
        setErr("Select the month (Compliance Process) first.");
        return;
      }
      await openEpfoPc(act, activeFlow?.label || flow, needsMonth ? runId : undefined, portal);
      return;
    }
    setBusy(true);
    setSession(null);
    try {
      const r = await api<{ session_id: string }>("/rpa/start", {
        method: "POST",
        body: {
          company_id: companyId,
          portal,
          flow,
          employee_id: activeFlow?.needs_employee ? empId : undefined,
          run_id: activeFlow?.needs_run ? runId : undefined,
          speed: "fast",
        },
      });
      setSid(r.session_id);
      await poll(r.session_id);
      pollRef.current = setInterval(() => poll(r.session_id), 900);
    } catch (e: any) {
      setErr(e?.message || "Failed to start automation");
    } finally {
      setBusy(false);
    }
  };

  const downloadDriver = async () => {
    if (Platform.OS !== "web") {
      setPcStatus("Open this page on a computer (Chrome/Edge) to download ChromeDriver.");
      return;
    }
    setPcBusy("driver");
    try {
      const r = await api<any>("/admin/portal-automation/chromedriver-url?platform=win64");
      if (r?.url) {
        const a = document.createElement("a");
        a.href = r.url;
        a.rel = "noopener";
        a.click();
        setPcStatus(
          `✅ ChromeDriver v${r.version} (Windows 64-bit) is downloading. Unzip it and place ` +
          "chromedriver.exe inside C:\\SKS-AutoLogin. (Normally NOT needed — the Runner " +
          "auto-installs the matching driver; use this only if auto-install fails.)");
      }
    } catch (e: any) {
      setPcStatus(e?.message || "Could not fetch the ChromeDriver download link");
    } finally {
      setPcBusy("");
    }
  };

  const control = async (action: string) => {
    if (!sid) return;
    try {
      await api(`/rpa/session/${sid}/control`, { method: "POST", body: { action } });
      if (action === "stop" || action === "emergency_stop") {
        // keep polling; runner flips to stopped
      } else if (!pollRef.current && !["completed", "failed", "stopped"].includes(session?.status || "")) {
        pollRef.current = setInterval(() => poll(sid), 900);
      }
    } catch (e: any) {
      setErr(e?.message || "Control failed");
    }
  };

  const submitInput = async () => {
    if (!sid || !inputVal.trim()) return;
    try {
      await api(`/rpa/session/${sid}/input`, {
        method: "POST",
        body: { value: inputVal.trim() },
      });
      setInputVal("");
    } catch (e: any) {
      setErr(e?.message || "Failed to submit");
    }
  };

  // Iter 320 — MANUAL OVERRIDE: forward the user's own clicks / typing on
  // the live view into the automated browser (mouse + keyboard on portal).
  const sendTap = async (x: number, y: number) => {
    if (!sid) return;
    try {
      await api(`/rpa/session/${sid}/interact`, {
        method: "POST",
        body: { kind: "click", x, y },
      });
      setTimeout(() => poll(sid), 350);
    } catch (e: any) {
      setErr(e?.message || "Manual click failed");
    }
  };

  const sendType = async () => {
    if (!sid || !kbVal) return;
    try {
      await api(`/rpa/session/${sid}/interact`, {
        method: "POST",
        body: { kind: "type", text: kbVal },
      });
      setKbVal("");
      setTimeout(() => poll(sid), 350);
    } catch (e: any) {
      setErr(e?.message || "Manual typing failed");
    }
  };

  const sendKey = async (key: string) => {
    if (!sid) return;
    try {
      await api(`/rpa/session/${sid}/interact`, {
        method: "POST",
        body: { kind: "key", key },
      });
      setTimeout(() => poll(sid), 350);
    } catch (e: any) {
      setErr(e?.message || "Manual key failed");
    }
  };

  const loadHistory = useCallback(() => {
    const q = companyId ? `?company_id=${companyId}` : "";
    api<{ jobs: any[] }>(`/rpa/history${q}`)
      .then((r) => setHistory(r.jobs || []))
      .catch(() => setHistory([]));
  }, [companyId]);

  useEffect(() => {
    if (tab === "history") loadHistory();
  }, [tab, loadHistory]);

  const isLive = session && !["completed", "failed", "stopped"].includes(session.status);
  const needsInput = !!session?.input_needed;

  const filteredEmps = employees
    .filter(
      (e) =>
        !empSearch ||
        (e.name || "").toLowerCase().includes(empSearch.toLowerCase()) ||
        (e.employee_code || "").toLowerCase().includes(empSearch.toLowerCase()),
    )
    .slice(0, 30);

  const mediaUrl = (file: string) =>
    `${baseUrl}/rpa/media/${session?.job_id}/${file}?token=${encodeURIComponent(token)}`;

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      {/* Header */}
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={8} style={st.iconBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Compliance Automation Studio</Text>
          <Text style={st.subtitle}>Live government-portal automation</Text>
        </View>
        <View style={st.tabRow}>
          {(["run", "history"] as const).map((t) => (
            <Pressable
              key={t}
              onPress={() => setTab(t)}
              style={[st.tab, tab === t && st.tabActive]}
            >
              <Text style={[st.tabTxt, tab === t && st.tabTxtActive]}>
                {t === "run" ? "Run" : "History"}
              </Text>
            </Pressable>
          ))}
        </View>
      </View>

      {isSuper && (
        <View style={st.pickerWrap}>
          <CompanyPicker
            value={selectedCompanyId || "all"}
            onChange={(v) => setSelectedCompanyId(v === "all" ? null : v)}
            allowAll={false}
            label="Firm (required)"
          />
        </View>
      )}

      {tab === "history" ? (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.lg }}>
          <Pressable style={st.refreshBtn} onPress={loadHistory}>
            <Ionicons name="refresh" size={16} color={colors.primary} />
            <Text style={st.refreshTxt}>Refresh</Text>
          </Pressable>
          {history.length === 0 ? (
            <Text style={st.muted}>No automation jobs yet.</Text>
          ) : (
            history.map((j) => (
              <View key={j.job_id} style={st.histCard}>
                <View style={st.histTop}>
                  <Text style={st.histTitle}>
                    {j.portal_label} · {j.flow_label}
                  </Text>
                  <View
                    style={[
                      st.statusPill,
                      { backgroundColor: (STATUS_COLOR[j.status] || "#6B7280") + "22" },
                    ]}
                  >
                    <Text style={[st.statusTxt, { color: STATUS_COLOR[j.status] || "#6B7280" }]}>
                      {j.status}
                    </Text>
                  </View>
                </View>
                <Text style={st.histMeta}>
                  {j.company_name || j.company_id} · {j.run_month || j.employee?.name || "—"}
                </Text>
                <Text style={st.histMeta}>
                  {(j.started_at || "").slice(0, 16).replace("T", " ")} · by {j.started_by || "—"}
                </Text>
                {j.error ? <Text style={st.histErr}>{j.error}</Text> : null}
                <View style={st.histFiles}>
                  {(j.downloads || []).length > 0 && (
                    <Text style={st.histFileTxt}>
                      ⬇ {(j.downloads || []).length} file(s)
                    </Text>
                  )}
                  {(j.screens || []).length > 0 && (
                    <Text style={st.histFileTxt}>📸 {(j.screens || []).length} shot(s)</Text>
                  )}
                  {j.video && <Text style={st.histFileTxt}>🎬 video</Text>}
                </View>
              </View>
            ))
          )}
        </ScrollView>
      ) : (
        <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: spacing.lg }}>
          {/* Firm selection is MANDATORY before any automation can be set up. */}
          {!companyId && (
            <View style={st.gate}>
              <Ionicons name="business-outline" size={40} color={colors.onSurfaceTertiary} />
              <Text style={st.gateTitle}>Select a firm to continue</Text>
              <Text style={st.gateBody}>
                Choose the firm you want to run the government-portal automation for
                using the “Firm (required)” selector above.
              </Text>
            </View>
          )}
          {/* --- Configuration (hidden while live) --- */}
          {!!companyId && !isLive && (
            <View style={st.card}>
              <Text style={st.cardTitle}>1. Choose Portal</Text>
              <View style={st.chipRow}>
                {portals.map((p) => (
                  <Pressable
                    key={p.key}
                    onPress={() => setPortal(p.key)}
                    style={[st.chip, portal === p.key && st.chipActive]}
                  >
                    <Text style={[st.chipTxt, portal === p.key && st.chipTxtActive]}>
                      {p.key.toUpperCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <Text style={[st.cardTitle, { marginTop: spacing.md }]}>2. Choose Action</Text>
              <View style={st.flowList}>
                {portalFlows.map((f) => (
                  <Pressable
                    key={f.key}
                    onPress={() => setFlow(f.key)}
                    style={[st.flowItem, flow === f.key && st.flowItemActive]}
                  >
                    <Ionicons
                      name={flow === f.key ? "radio-button-on" : "radio-button-off"}
                      size={18}
                      color={flow === f.key ? "#8B5E34" : colors.onSurfaceTertiary}
                    />
                    <Text style={[st.flowTxt, flow === f.key && { color: "#7A4A18", fontWeight: "700" }]}>
                      {f.label}
                    </Text>
                  </Pressable>
                ))}
              </View>

              {activeFlow?.needs_employee && (
                <View style={{ marginTop: spacing.md }}>
                  <Text style={st.cardTitle}>3. Select Employee</Text>
                  <TextInput
                    style={st.search}
                    value={empSearch}
                    onChangeText={setEmpSearch}
                    placeholder="Search name / code…"
                    placeholderTextColor={colors.onSurfaceTertiary}
                  />
                  <View style={st.empList}>
                    {filteredEmps.map((e) => (
                      <Pressable
                        key={e.user_id}
                        onPress={() => setEmpId(e.user_id)}
                        style={[st.empItem, empId === e.user_id && st.empItemActive]}
                      >
                        <Text style={[st.empTxt, empId === e.user_id && { color: "#7A4A18", fontWeight: "700" }]} numberOfLines={1}>
                          {e.employee_code ? `${e.employee_code} · ` : ""}
                          {e.name}
                        </Text>
                        {empId === e.user_id && (
                          <Ionicons name="checkmark-circle" size={18} color="#8B5E34" />
                        )}
                      </Pressable>
                    ))}
                  </View>
                </View>
              )}

              {activeFlow?.needs_run && (
                <View style={{ marginTop: spacing.md }}>
                  <Text style={st.cardTitle}>3. Select Month (Compliance Process)</Text>
                  {/* Iter 698 (user request) — month selection as a dropdown
                      list instead of a long chip row. */}
                  {runs.length === 0 ? (
                    <Text style={st.muted}>No compliance salary processes found.</Text>
                  ) : (
                    <View>
                      <Pressable
                        style={st.ddField}
                        onPress={() => setMonthDdOpen((v) => !v)}
                        testID="as-month-dd"
                      >
                        <Ionicons name="calendar-outline" size={16} color="#8B5E34" />
                        <Text style={[st.ddValue, !runId && { color: "#9CA3AF" }]}>
                          {runId
                            ? fmtMonth(runs.find((r) => r.run_id === runId)?.month || "")
                            : "Select month..."}
                        </Text>
                        <Ionicons
                          name={monthDdOpen ? "chevron-up" : "chevron-down"}
                          size={16}
                          color="#8B5E34"
                        />
                      </Pressable>
                      {monthDdOpen && (
                        <View style={st.ddList}>
                          <ScrollView style={{ maxHeight: 240 }} nestedScrollEnabled>
                            {runs.map((r) => (
                              <Pressable
                                key={r.run_id}
                                onPress={() => { setRunId(r.run_id); setMonthDdOpen(false); }}
                                style={[st.ddItem, runId === r.run_id && st.ddItemActive]}
                              >
                                <Text style={[st.ddItemTxt, runId === r.run_id && { color: "#8B5E34", fontWeight: "800" }]}>
                                  {fmtMonth(r.month)}
                                </Text>
                                {runId === r.run_id && (
                                  <Ionicons name="checkmark" size={16} color="#8B5E34" />
                                )}
                              </Pressable>
                            ))}
                          </ScrollView>
                        </View>
                      )}
                      {/* Iter 701 — uploaded challan stays on record; download
                          the PDF anytime for payroll. */}
                      {challanReady && (
                        <Pressable
                          style={[st.pcBtn, { backgroundColor: "#7C3AED", marginTop: 8, alignSelf: "flex-start" }]}
                          onPress={downloadChallan}
                          testID="as-download-challan"
                        >
                          <Ionicons name="document-text-outline" size={14} color="#fff" />
                          <Text style={st.pcBtnTxt}>
                            Download Challan PDF{challanTrrn ? ` (TRRN ${challanTrrn})` : ""}
                          </Text>
                        </Pressable>
                      )}
                    </View>
                  )}
                  {validation && (
                    <View style={st.valBox}>
                      <Text style={st.valTitle}>Pre-flight Validation</Text>
                      <Text style={st.valRow}>
                        ✅ {validation.included} of {validation.employee_count} employees included
                      </Text>
                      <Text style={st.valRow}>
                        💰 Wages ₹{Number(validation.total_wages || 0).toLocaleString("en-IN")} ·
                        Contribution ₹{Number(validation.total_contribution || 0).toLocaleString("en-IN")}
                      </Text>
                      {(validation.missing_ids || []).length > 0 && (
                        <Text style={[st.valRow, { color: "#DC2626" }]}>
                          ⚠ {validation.missing_ids.length} missing ID(s) — will be skipped
                        </Text>
                      )}
                      {(validation.duplicate_ids || []).length > 0 && (
                        <Text style={[st.valRow, { color: "#DC2626" }]}>
                          ⚠ {validation.duplicate_ids.length} duplicate ID(s)
                        </Text>
                      )}
                    </View>
                  )}
                </View>
              )}

              {err ? <Text style={st.errTxt}>{err}</Text> : null}

              <Pressable
                style={[st.startBtn, busy && { opacity: 0.6 }]}
                onPress={start}
                disabled={busy}
              >
                {busy ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="play" size={18} color="#fff" />
                    <Text style={st.startTxt}>Start Automation</Text>
                  </>
                )}
              </Pressable>

              {/* Iter 691 — 🔐 Open EPFO Portal (ChromeDriver, OPEN-ONLY) */}
              {(portal === "epfo" || portal === "esic") && (
                <View style={st.pcBox}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Ionicons name="logo-chrome" size={16} color="#059669" />
                    <Text style={st.pcTitle}>PC Chrome (ChromeDriver)</Text>
                  </View>
                  <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
                    <Pressable
                      style={[st.pcBtn, pcBusy === "open" && { opacity: 0.6 }]}
                      onPress={() => openEpfoPc(undefined, undefined, undefined, portal as "epfo" | "esic")}
                      disabled={pcBusy === "open"}
                      testID="as-open-epfo-pc"
                    >
                      {pcBusy === "open" ? (
                        <ActivityIndicator size="small" color="#fff" />
                      ) : (
                        <Ionicons name="lock-closed" size={14} color="#fff" />
                      )}
                      <Text style={st.pcBtnTxt}>Open {portal.toUpperCase()} Portal</Text>
                    </Pressable>
                    <Pressable
                      style={[st.pcBtn, { backgroundColor: "#B45309" }, pcBusy === "runner" && { opacity: 0.6 }]}
                      onPress={downloadRunner}
                      disabled={pcBusy === "runner"}
                      testID="as-download-chromedriver"
                    >
                      {pcBusy === "runner" ? (
                        <ActivityIndicator size="small" color="#fff" />
                      ) : (
                        <Ionicons name="download-outline" size={14} color="#fff" />
                      )}
                      <Text style={st.pcBtnTxt}>Download ChromeDriver Setup</Text>
                    </Pressable>
                    <Pressable
                      style={[st.pcBtn, { backgroundColor: "#2563EB" }, pcBusy === "driver" && { opacity: 0.6 }]}
                      onPress={downloadDriver}
                      disabled={pcBusy === "driver"}
                      testID="as-download-driver-exe"
                    >
                      {pcBusy === "driver" ? (
                        <ActivityIndicator size="small" color="#fff" />
                      ) : (
                        <Ionicons name="hardware-chip-outline" size={14} color="#fff" />
                      )}
                      <Text style={st.pcBtnTxt}>ChromeDriver (driver only)</Text>
                    </Pressable>
                  </View>
                  {pcStatus ? <Text style={st.pcStatus}>{pcStatus}</Text> : null}
                  {/* Iter 694 — duplicate EPFO login found on other firms:
                      one-click cleanup keeps it on THIS firm only. */}
                  {dupWarn ? (
                    <View style={st.dupBox}>
                      <Text style={st.dupTxt}>{dupWarn}</Text>
                      <Pressable
                        style={[st.dupBtn, pcBusy === "fixdup" && { opacity: 0.6 }]}
                        onPress={fixDupLogin}
                        disabled={pcBusy === "fixdup"}
                        testID="as-fix-dup-login"
                      >
                        {pcBusy === "fixdup" ? (
                          <ActivityIndicator size="small" color="#fff" />
                        ) : (
                          <Ionicons name="trash-outline" size={14} color="#fff" />
                        )}
                        <Text style={st.pcBtnTxt}>
                          This login belongs ONLY to this firm — REMOVE from other firms
                        </Text>
                      </Pressable>
                    </View>
                  ) : null}
                  <Text style={st.pcHint}>
                    <Text style={{ fontWeight: "800" }}>One-time setup (no more manual steps):</Text> click
                    Download ChromeDriver Setup → unzip to C:\SKS-AutoLogin → double-click{" "}
                    <Text style={{ fontWeight: "800" }}>install_autostart.bat</Text> once. After that the
                    Runner starts silently every time Windows boots — you never open anything again, and{" "}
                    <Text style={{ fontWeight: "800" }}>Open EPFO Portal</Text> just works: a new Chrome
                    window (ChromeDriver) opens the EPFO portal, clicks the alert&apos;s OK, and auto-fills
                    this firm&apos;s Login ID &amp; Password from Firm Master → Portal Logins. You only enter
                    the CAPTCHA (and OTP if asked) and click Sign In — CAPTCHA/OTP are never bypassed. Use <Text style={{ fontWeight: "800" }}>ChromeDriver (driver only)</Text> only
                    if the auto-install ever fails.
                  </Text>
                </View>
              )}
            </View>
          )}

          {/* --- LIVE MONITOR --- */}
          {session && (
            <View style={st.card}>
              <View style={st.monitorHead}>
                <View
                  style={[
                    st.statusPill,
                    { backgroundColor: (STATUS_COLOR[session.status] || "#D97706") + "22" },
                  ]}
                >
                  <View
                    style={[
                      st.liveDot,
                      { backgroundColor: STATUS_COLOR[session.status] || "#D97706" },
                    ]}
                  />
                  <Text style={[st.statusTxt, { color: STATUS_COLOR[session.status] || "#D97706" }]}>
                    {session.status.replace("_", " ")}
                  </Text>
                </View>
                <Text style={st.monitorMeta}>
                  {session.portal_label} · {session.flow_label}
                </Text>
                {isLive && (
                  <Pressable style={st.stopTop} onPress={() => control("stop")}>
                    <Ionicons name="stop-circle" size={16} color="#fff" />
                    <Text style={st.stopTopTxt}>Stop</Text>
                  </Pressable>
                )}
              </View>

              {/* Progress */}
              <View style={st.progressTrack}>
                <View style={[st.progressFill, { width: `${session.progress}%` }]} />
              </View>
              <View style={st.metaRow}>
                <Text style={st.metaTxt}>Step {session.current_step + 1}/{session.steps.length}</Text>
                <Text style={st.metaTxt}>{session.progress}%</Text>
                <Text style={st.metaTxt}>⏱ {fmtDuration(session.elapsed_sec)}</Text>
                {session.eta_sec != null && (
                  <Text style={st.metaTxt}>ETA {fmtDuration(session.eta_sec)}</Text>
                )}
              </View>
              <Text style={st.currentMsg}>{session.message}</Text>

              {/* Live frame — clickable when Manual Control is ON */}
              <View style={st.frameWrap}>
                <InteractiveFrame
                  b64={session.frame_b64}
                  manual={manual}
                  onTap={sendTap}
                  style={st.frame}
                />
              </View>
              <View style={st.frameBar}>
                <Pressable
                  style={[st.frameBarBtn, manual && st.frameBarBtnOn]}
                  onPress={() => setManual(!manual)}
                >
                  <Ionicons name="hand-left" size={14} color={manual ? "#fff" : colors.primary} />
                  <Text style={[st.frameBarTxt, manual && { color: "#fff" }]}>
                    {manual ? "Manual Control ON" : "Manual Control"}
                  </Text>
                </Pressable>
                <Pressable style={st.frameBarBtn} onPress={() => setFullscreen(true)}>
                  <Ionicons name="expand" size={14} color={colors.primary} />
                  <Text style={st.frameBarTxt}>Full Screen</Text>
                </Pressable>
              </View>
              {manual && (
                <View style={st.kbBox}>
                  <Text style={st.kbHint}>
                    🖱 Click directly on the live view above to click on the portal.
                    Use the box below to type on the portal.
                  </Text>
                  <View style={st.inputRow}>
                    <TextInput
                      style={st.kbInput}
                      value={kbVal}
                      onChangeText={setKbVal}
                      placeholder="Type text to send to the portal…"
                      placeholderTextColor={colors.onSurfaceTertiary}
                      onSubmitEditing={sendType}
                    />
                    <Pressable style={st.kbSendBtn} onPress={sendType}>
                      <Text style={st.inputBtnTxt}>Type</Text>
                    </Pressable>
                  </View>
                  <View style={st.kbKeys}>
                    {([
                      ["Enter", "⏎ Enter"],
                      ["Tab", "⇥ Tab"],
                      ["Backspace", "⌫ Back"],
                      ["Escape", "Esc"],
                      ["ArrowUp", "↑"],
                      ["ArrowDown", "↓"],
                    ] as const).map(([k, label]) => (
                      <Pressable key={k} style={st.kbKey} onPress={() => sendKey(k)}>
                        <Text style={st.kbKeyTxt}>{label}</Text>
                      </Pressable>
                    ))}
                  </View>
                </View>
              )}

              {/* Fullscreen live portal view */}
              <Modal
                visible={fullscreen}
                animationType="fade"
                onRequestClose={() => setFullscreen(false)}
              >
                <View style={st.fsRoot}>
                  <View style={st.fsHead}>
                    <Text style={st.fsTitle} numberOfLines={1}>
                      {session.portal_label} — Live Portal
                    </Text>
                    <Pressable
                      style={[st.frameBarBtn, st.fsBarBtn, manual && st.frameBarBtnOn]}
                      onPress={() => setManual(!manual)}
                    >
                      <Ionicons name="hand-left" size={14} color={manual ? "#fff" : "#93C5FD"} />
                      <Text style={[st.frameBarTxt, { color: manual ? "#fff" : "#93C5FD" }]}>
                        {manual ? "Manual ON" : "Manual"}
                      </Text>
                    </Pressable>
                    <Pressable style={st.fsClose} onPress={() => setFullscreen(false)}>
                      <Ionicons name="contract" size={16} color="#fff" />
                      <Text style={st.fsCloseTxt}>Exit Full Screen</Text>
                    </Pressable>
                  </View>
                  <View style={st.fsBody}>
                    <InteractiveFrame
                      b64={session.frame_b64}
                      manual={manual}
                      onTap={sendTap}
                      style={{
                        width: Math.min(winW - 8, (winH - (manual ? 190 : 110)) * 1.6),
                        aspectRatio: 1280 / 800,
                        backgroundColor: "#000",
                      }}
                    />
                  </View>
                  {manual && (
                    <View style={st.fsKb}>
                      <TextInput
                        style={[st.kbInput, { backgroundColor: "#1E293B", color: "#fff", borderColor: "#334155" }]}
                        value={kbVal}
                        onChangeText={setKbVal}
                        placeholder="Type text to send to the portal…"
                        placeholderTextColor="#64748B"
                        onSubmitEditing={sendType}
                      />
                      <Pressable style={st.kbSendBtn} onPress={sendType}>
                        <Text style={st.inputBtnTxt}>Type</Text>
                      </Pressable>
                      {([["Enter", "⏎"], ["Tab", "⇥"], ["Backspace", "⌫"]] as const).map(([k, label]) => (
                        <Pressable key={k} style={[st.kbKey, { borderColor: "#334155" }]} onPress={() => sendKey(k)}>
                          <Text style={[st.kbKeyTxt, { color: "#93C5FD" }]}>{label}</Text>
                        </Pressable>
                      ))}
                    </View>
                  )}
                </View>
              </Modal>
              {session.current_url ? (
                <Text style={st.urlTxt} numberOfLines={1}>
                  🌐 {session.current_url}
                </Text>
              ) : null}

              {/* CAPTCHA / OTP / confirm input */}
              {needsInput && (
                <View style={st.inputBox}>
                  <Text style={st.inputPrompt}>{session.input_needed?.prompt}</Text>
                  {session.captcha_b64 ? (
                    <Image
                      source={{ uri: `data:image/png;base64,${session.captcha_b64}` }}
                      style={st.captchaImg}
                      resizeMode="contain"
                    />
                  ) : null}
                  <View style={st.inputRow}>
                    <TextInput
                      style={st.input}
                      value={inputVal}
                      onChangeText={setInputVal}
                      placeholder={
                        session.input_needed?.kind === "confirm"
                          ? "Type YES to continue"
                          : "Enter value…"
                      }
                      placeholderTextColor={colors.onSurfaceTertiary}
                      autoCapitalize="characters"
                      autoFocus
                      onSubmitEditing={submitInput}
                    />
                    <Pressable style={st.inputBtn} onPress={submitInput}>
                      <Text style={st.inputBtnTxt}>Submit</Text>
                    </Pressable>
                  </View>
                </View>
              )}

              {/* Controls */}
              <View style={st.controls}>
                {session.status === "paused" ? (
                  <CtrlBtn icon="play" label="Resume" color="#16A34A" onPress={() => control("resume")} />
                ) : (
                  <CtrlBtn icon="pause" label="Pause" color="#D97706" onPress={() => control("pause")} disabled={!isLive} />
                )}
                <CtrlBtn icon="refresh" label="Retry" color={colors.primary} onPress={() => control("retry")} disabled={!isLive} />
                <CtrlBtn icon="play-skip-forward" label="Skip" color={colors.primary} onPress={() => control("skip")} disabled={!isLive} />
                <CtrlBtn icon="play-skip-back" label="Prev" color={colors.primary} onPress={() => control("previous")} disabled={!isLive} />
                <CtrlBtn icon="stop" label="Stop" color="#6B7280" onPress={() => control("stop")} disabled={!isLive} />
                <CtrlBtn icon="warning" label="E-Stop" color="#DC2626" onPress={() => control("emergency_stop")} disabled={!isLive} />
              </View>

              {/* Steps */}
              <View style={st.steps}>
                {session.steps.map((s) => (
                  <View key={s.index} style={st.stepRow}>
                    <Ionicons
                      name={
                        s.status === "done"
                          ? "checkmark-circle"
                          : s.status === "running"
                          ? "sync"
                          : s.status === "failed"
                          ? "close-circle"
                          : s.status === "skipped"
                          ? "arrow-redo-circle"
                          : "ellipse-outline"
                      }
                      size={16}
                      color={
                        s.status === "done"
                          ? "#16A34A"
                          : s.status === "running"
                          ? colors.primary
                          : s.status === "failed"
                          ? "#DC2626"
                          : colors.onSurfaceTertiary
                      }
                    />
                    <Text
                      style={[
                        st.stepTxt,
                        s.status === "running" && { fontWeight: "800", color: colors.onSurface },
                      ]}
                    >
                      {s.name}
                    </Text>
                  </View>
                ))}
              </View>

              {/* Downloads */}
              {(session.downloads || []).length > 0 && (
                <View style={st.dlBox}>
                  <Text style={st.dlTitle}>Documents</Text>
                  {(session.downloads || []).map((d, i) => (
                    <Pressable
                      key={i}
                      onPress={() => {
                        if (Platform.OS === "web") window.open(mediaUrl(d.file), "_blank");
                      }}
                    >
                      <Text style={st.dlLink}>⬇ {d.file.split("/").pop()}</Text>
                    </Pressable>
                  ))}
                </View>
              )}

              {/* Live log */}
              <View style={st.logBox}>
                <Text style={st.logTitle}>Live Log</Text>
                {(session.logs || []).slice(-30).reverse().map((l, i) => (
                  <Text
                    key={i}
                    style={[
                      st.logLine,
                      l.level === "error" && { color: "#DC2626" },
                      l.level === "warn" && { color: "#D97706" },
                    ]}
                  >
                    {l.t} · {l.msg}
                  </Text>
                ))}
              </View>

              {!isLive && (
                <Pressable style={st.newBtn} onPress={() => { setSession(null); setSid(""); }}>
                  <Ionicons name="add" size={18} color={colors.primary} />
                  <Text style={st.newTxt}>New Automation</Text>
                </Pressable>
              )}
            </View>
          )}
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

/**
 * Iter 320 — Interactive live frame. When manual mode is ON, taps on the
 * streamed image are converted to normalised (0–1) coordinates and sent
 * to the automated browser so the user can click anywhere on the portal.
 */
function InteractiveFrame({
  b64, manual, onTap, style,
}: {
  b64?: string | null;
  manual: boolean;
  onTap: (x: number, y: number) => void;
  style?: any;
}) {
  const [dim, setDim] = useState({ w: 0, h: 0 });
  return (
    <Pressable
      disabled={!manual || !b64}
      onLayout={(e) =>
        setDim({ w: e.nativeEvent.layout.width, h: e.nativeEvent.layout.height })
      }
      onPress={(e: any) => {
        const ne = e?.nativeEvent || {};
        const lx = ne.locationX ?? ne.offsetX;
        const ly = ne.locationY ?? ne.offsetY;
        if (dim.w > 0 && dim.h > 0 && lx != null && ly != null) {
          onTap(lx / dim.w, ly / dim.h);
        }
      }}
      style={[style, manual && b64 ? st.frameManual : null]}
    >
      {b64 ? (
        <Image
          source={{ uri: `data:image/jpeg;base64,${b64}` }}
          style={{ width: "100%", height: "100%" }}
          resizeMode="stretch"
        />
      ) : (
        <View style={[{ width: "100%", height: "100%" }, st.frameEmpty]}>
          <ActivityIndicator color={colors.primary} />
          <Text style={st.muted}>Waiting for the live view…</Text>
        </View>
      )}
    </Pressable>
  );
}

function CtrlBtn({
  icon, label, color, onPress, disabled,
}: {
  icon: any; label: string; color: string; onPress: () => void; disabled?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={[st.ctrl, { borderColor: color }, disabled && { opacity: 0.4 }]}
    >
      <Ionicons name={icon} size={18} color={color} />
      <Text style={[st.ctrlTxt, { color }]}>{label}</Text>
    </Pressable>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    gap: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
  },
  iconBtn: { padding: 4 },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceSecondary },
  tabRow: { flexDirection: "row", backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: 3 },
  tab: { paddingHorizontal: 14, paddingVertical: 6, borderRadius: radius.sm },
  tabActive: { backgroundColor: colors.surface },
  tabTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtActive: { color: colors.primary },
  pickerWrap: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    marginBottom: spacing.lg,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  chipActive: { backgroundColor: "#FBECD6", borderColor: "#8B5E34" },
  chipTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary, textTransform: "capitalize" },
  chipTxtActive: { color: "#7A4A18" },
  flowList: { gap: 4 },
  flowItem: { flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 9 },
  flowItemActive: {},
  flowTxt: { fontSize: 13.5, color: colors.onSurfaceSecondary, flex: 1 },
  search: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 14, color: colors.onSurface,
    backgroundColor: colors.surface, marginBottom: spacing.sm,
  },
  empList: { gap: 2 },
  empItem: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 10, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary, marginBottom: 4,
  },
  empItemActive: { backgroundColor: "#FBECD6" },
  empTxt: { fontSize: 13.5, color: colors.onSurface, flex: 1 },
  gate: { alignItems: "center", paddingVertical: 48, paddingHorizontal: spacing.lg, gap: 10 },
  gateTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  gateBody: { fontSize: 13, color: colors.onSurfaceSecondary, textAlign: "center", lineHeight: 19 },
  valBox: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  valTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  valRow: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginBottom: 3 },
  errTxt: { color: "#DC2626", fontSize: 13, fontWeight: "700", marginTop: spacing.md },
  startBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#15803D", borderRadius: radius.md, paddingVertical: 13,
    marginTop: spacing.md,
  },
  startTxt: { fontSize: 15, fontWeight: "800", color: "#fff" },
  monitorHead: { flexDirection: "row", alignItems: "center", gap: spacing.sm, marginBottom: spacing.sm },
  monitorMeta: { fontSize: 12.5, color: colors.onSurfaceSecondary, flex: 1 },
  stopTop: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: "#DC2626", borderRadius: radius.pill,
    paddingHorizontal: 14, paddingVertical: 7,
  },
  stopTopTxt: { fontSize: 13, fontWeight: "800", color: "#fff" },
  statusPill: { flexDirection: "row", alignItems: "center", gap: 6, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 20 },
  liveDot: { width: 8, height: 8, borderRadius: 4 },
  statusTxt: { fontSize: 12, fontWeight: "800", textTransform: "capitalize" },
  progressTrack: { height: 8, backgroundColor: colors.surfaceSecondary, borderRadius: 4, overflow: "hidden", marginTop: 4 },
  progressFill: { height: "100%", backgroundColor: colors.primary, borderRadius: 4 },
  metaRow: { flexDirection: "row", flexWrap: "wrap", gap: 12, marginTop: 8 },
  metaTxt: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "600" },
  currentMsg: { fontSize: 13.5, color: colors.onSurface, fontWeight: "700", marginTop: 8 },
  frameWrap: {
    marginTop: spacing.md, borderRadius: radius.md, overflow: "hidden",
    backgroundColor: "#111", borderWidth: 1, borderColor: colors.border,
  },
  frame: { width: "100%", aspectRatio: 1280 / 800, backgroundColor: "#000" },
  frameManual: Platform.OS === "web" ? ({ cursor: "crosshair" } as any) : {},
  frameEmpty: { alignItems: "center", justifyContent: "center", gap: 8 },
  frameBar: { flexDirection: "row", gap: 8, marginTop: 8, flexWrap: "wrap" },
  frameBarBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1.5,
    borderColor: colors.primary, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  frameBarBtnOn: { backgroundColor: "#15803D", borderColor: "#15803D" },
  frameBarTxt: { fontSize: 12.5, fontWeight: "800", color: colors.primary },
  kbBox: {
    marginTop: spacing.sm, backgroundColor: "#EFF6FF", borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: "#93C5FD",
  },
  kbHint: { fontSize: 12, color: "#1D4ED8", fontWeight: "600", marginBottom: 8, lineHeight: 17 },
  kbInput: {
    flex: 1, borderWidth: 1, borderColor: "#93C5FD", borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 9, fontSize: 14, color: "#111",
    backgroundColor: "#fff",
  },
  kbSendBtn: { backgroundColor: "#1D4ED8", borderRadius: radius.md, paddingHorizontal: 16, justifyContent: "center" },
  kbKeys: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  kbKey: {
    borderWidth: 1, borderColor: "#93C5FD", borderRadius: radius.sm,
    paddingHorizontal: 12, paddingVertical: 7, backgroundColor: "#fff",
  },
  kbKeyTxt: { fontSize: 12.5, fontWeight: "800", color: "#1D4ED8" },
  fsRoot: { flex: 1, backgroundColor: "#0B1120" },
  fsHead: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 10,
  },
  fsTitle: { flex: 1, fontSize: 14, fontWeight: "800", color: "#fff" },
  fsBarBtn: { borderColor: "#334155" },
  fsClose: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: "#DC2626", borderRadius: radius.md,
    paddingHorizontal: 14, paddingVertical: 8,
  },
  fsCloseTxt: { fontSize: 13, fontWeight: "800", color: "#fff" },
  fsBody: { flex: 1, alignItems: "center", justifyContent: "center", padding: 4 },
  fsKb: {
    flexDirection: "row", gap: 8, paddingHorizontal: 14, paddingVertical: 10,
    alignItems: "center",
  },
  urlTxt: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 6 },
  inputBox: {
    marginTop: spacing.md, backgroundColor: "#FEF9C3", borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: "#FACC15",
  },
  inputPrompt: { fontSize: 13.5, fontWeight: "800", color: "#854D0E", marginBottom: spacing.sm },
  captchaImg: { width: 220, height: 70, alignSelf: "center", marginBottom: spacing.sm, backgroundColor: "#fff", borderRadius: 6 },
  inputRow: { flexDirection: "row", gap: 8 },
  input: {
    flex: 1, borderWidth: 1, borderColor: "#FACC15", borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: 15, fontWeight: "700",
    color: "#111", backgroundColor: "#fff",
  },
  inputBtn: { backgroundColor: "#CA8A04", borderRadius: radius.md, paddingHorizontal: 18, justifyContent: "center" },
  inputBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 14 },
  controls: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: spacing.md },
  ctrl: {
    flexDirection: "row", alignItems: "center", gap: 5, borderWidth: 1.5,
    borderRadius: radius.md, paddingHorizontal: 12, paddingVertical: 8,
  },
  ctrlTxt: { fontSize: 12.5, fontWeight: "800" },
  steps: { marginTop: spacing.md, gap: 2 },
  stepRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 4 },
  stepTxt: { fontSize: 13, color: colors.onSurfaceSecondary },
  dlBox: { marginTop: spacing.md, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.md },
  dlTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  dlLink: { fontSize: 13, color: colors.primary, fontWeight: "700", paddingVertical: 4 },
  logBox: { marginTop: spacing.md, backgroundColor: "#0F172A", borderRadius: radius.md, padding: spacing.md, maxHeight: 220 },
  logTitle: { fontSize: 12, fontWeight: "800", color: "#94A3B8", marginBottom: 6 },
  logLine: { fontSize: 11.5, color: "#CBD5E1", fontFamily: Platform.OS === "ios" ? "Menlo" : "monospace", marginBottom: 2 },
  newBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: spacing.md, paddingVertical: 11, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.primary,
  },
  newTxt: { fontSize: 14, fontWeight: "800", color: colors.primary },
  muted: { fontSize: 13, color: colors.onSurfaceTertiary },
  refreshBtn: { flexDirection: "row", alignItems: "center", gap: 6, alignSelf: "flex-end", marginBottom: spacing.sm },
  refreshTxt: { fontSize: 13, fontWeight: "700", color: colors.primary },
  histCard: {
    backgroundColor: colors.surface, borderRadius: radius.md, padding: spacing.md,
    marginBottom: spacing.sm, borderWidth: StyleSheet.hairlineWidth, borderColor: colors.border,
  },
  histTop: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  histTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface, flex: 1 },
  histMeta: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 3 },
  histErr: { fontSize: 12, color: "#DC2626", marginTop: 4 },
  histFiles: { flexDirection: "row", gap: 14, marginTop: 6 },
  histFileTxt: { fontSize: 12, color: colors.onSurfaceSecondary, fontWeight: "600" },
  pcBox: {
    marginTop: spacing.md, backgroundColor: "#05966910", borderRadius: radius.md,
    padding: spacing.md, borderWidth: 1, borderColor: "#05966940",
  },
  pcTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  pcBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: "#059669",
    paddingVertical: 10, paddingHorizontal: 14, borderRadius: radius.md, minHeight: 44,
  },
  pcBtnTxt: { fontSize: 13, fontWeight: "800", color: "#fff" },
  pcStatus: { fontSize: 13, fontWeight: "700", color: "#059669", marginTop: 8 },
  dupBox: {
    marginTop: 8, padding: 10, borderRadius: 8, backgroundColor: "#FEF2F2",
    borderWidth: 1, borderColor: "#FCA5A5", gap: 8,
  },
  dupTxt: { fontSize: 12.5, fontWeight: "700", color: "#B91C1C", lineHeight: 18 },
  ddField: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: "#E5D9C9", borderRadius: 10,
    backgroundColor: "#FFFDF9", paddingHorizontal: 12, minHeight: 44,
    marginTop: 6,
  },
  ddValue: { flex: 1, fontSize: 14, fontWeight: "700", color: "#3F3428" },
  ddList: {
    borderWidth: 1, borderColor: "#E5D9C9", borderRadius: 10,
    backgroundColor: "#fff", marginTop: 4, overflow: "hidden",
  },
  ddItem: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 14, minHeight: 44,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: "#F0E8DC",
  },
  ddItemActive: { backgroundColor: "#FBF4EA" },
  ddItemTxt: { fontSize: 14, color: "#3F3428", fontWeight: "600" },
  dupBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center",
    gap: 6, backgroundColor: "#DC2626", borderRadius: 8,
    paddingVertical: 10, paddingHorizontal: 12, minHeight: 44,
  },
  pcHint: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 8, lineHeight: 16 },
});
