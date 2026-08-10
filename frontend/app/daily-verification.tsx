/**
 * Iter 420 (user request) — Daily In/Out & OT Verification Report.
 *
 * HR / Security / Supervisors physically verify one day's attendance
 * against biometric & mobile punches. Summary tiles, colour-coded rows
 * (red missing punch · orange unapproved OT · yellow late/early · blue
 * manual · green normal · grey absent/WO/holiday/leave), per-row physical
 * verification with remarks + audit trail, employee drill-down (punch
 * timeline, geo, selfie, machine, 7-day history) and Excel / CSV / PDF
 * (landscape + portrait) / Print / Email / WhatsApp exports.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator, Image, Modal, Platform, Pressable, ScrollView,
  StyleSheet, Switch, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import EmployeePhoto from "@/src/components/EmployeePhoto";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, radius, type } from "@/src/theme";

const ROW_BG: Record<string, string> = {
  red: "#FECACA", orange: "#FED7AA", yellow: "#FEF08A",
  blue: "#DBEAFE", green: "#DCFCE7", muted: "#E2E8F0",
};

type Row = {
  user_id: string; employee_code: string; name: string; department: string;
  designation: string; contractor: string; punch_in: string; punch_out: string;
  work_hours: string; ot_in: string; ot_out: string; ot_hours: string;
  approved_ot: string; unapproved_ot: string; total_hours: string;
  status: string; markers: string[]; color: string; exception: boolean;
  sources: string[]; machine_names: string[];
  verified: boolean; verified_by: string; verified_at: string; remarks: string;
};

type Summary = Record<string, any>;
type Opts = {
  departments: string[]; designations: string[]; contractors: string[];
  categories: string[]; shifts: string[]; groups: string[]; sources: string[];
  machines: { serial: string; name: string }[];
};

type Drill = {
  employee: any;
  timeline: {
    time: string; kind: string; source: string; machine: string;
    device_serial: string; status: string; lat?: number; lng?: number;
    location_name: string; selfie?: string | null;
  }[];
  history: { day: string; date: string; in: string; out: string; hours: string; ot: string }[];
};

const todayIso = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const TILES: [string, string][] = [
  ["total_employees", "Employees"], ["present", "Present"], ["absent", "Absent"],
  ["leave", "Leave"], ["weekly_off", "Weekly Off"], ["holiday", "Holiday"],
  ["missing_in", "Missing IN"], ["missing_out", "Missing OUT"],
  ["late", "Late"], ["early", "Early"], ["with_ot", "With OT"],
  ["total_ot_hours", "Total OT"], ["approved_ot_hours", "Approved OT"],
  ["unapproved_ot_hours", "Unapproved OT"],
  ["pending_verification", "Pending Verify"], ["verified", "Verified"],
];

const COLS: { key: keyof Row | "sr" | "sign"; label: string; w: number }[] = [
  { key: "sr", label: "Sr", w: 40 },
  { key: "employee_code", label: "Code", w: 62 },
  { key: "name", label: "Employee Name", w: 170 },
  { key: "department", label: "Department", w: 110 },
  { key: "designation", label: "Designation", w: 110 },
  { key: "contractor", label: "Contractor", w: 110 },
  { key: "punch_in", label: "Punch In", w: 70 },
  { key: "punch_out", label: "Punch Out", w: 70 },
  { key: "work_hours", label: "Work Hrs", w: 68 },
  { key: "ot_in", label: "OT In", w: 64 },
  { key: "ot_out", label: "OT Out", w: 64 },
  { key: "ot_hours", label: "OT Hrs", w: 60 },
  { key: "total_hours", label: "Total Duty", w: 74 },
  { key: "status", label: "Attendance Status", w: 200 },
  { key: "sign", label: "Verify", w: 170 },
];

function Sel({ label, value, onChange, options, width = 150 }: {
  label: string; value: string; onChange: (v: string) => void;
  options: { v: string; l: string }[]; width?: number;
}) {
  return (
    <View style={{ minWidth: width }}>
      <Text style={st.lbl}>{label}</Text>
      {Platform.OS === "web" ? (
        <select value={value} onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
          style={WEB_SELECT}>
          <option value="">All</option>
          {options.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
        </select>
      ) : null}
    </View>
  );
}

export default function DailyVerificationScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const { companies, selectedCompanyId } = useSelectedCompany();
  const isAdmin = user?.role === "super_admin" || user?.role === "sub_admin"
    || user?.role === "company_admin";

  const [companyId, setCompanyId] = useState(selectedCompanyId || "");
  useEffect(() => { if (selectedCompanyId) setCompanyId(selectedCompanyId); }, [selectedCompanyId]);
  const [date, setDate] = useState(todayIso());
  const [dept, setDept] = useState(""); const [desig, setDesig] = useState("");
  const [contr, setContr] = useState(""); const [cat, setCat] = useState("");
  const [shift, setShift] = useState(""); const [grp, setGrp] = useState("");
  const [empStatus, setEmpStatus] = useState("active");
  const [source, setSource] = useState(""); const [machine, setMachine] = useState("");
  const [q, setQ] = useState(""); const [exOnly, setExOnly] = useState(false);
  // Iter 479 (user request) — show only PRESENT employees (a single punch
  // counts as present).
  const [presentOnly, setPresentOnly] = useState(false);

  const [rows, setRows] = useState<Row[]>([]);
  const [summary, setSummary] = useState<Summary>({});
  const [opts, setOpts] = useState<Opts | null>(null);
  const [totalRows, setTotalRows] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drill, setDrill] = useState<Drill | null>(null);
  const [drillName, setDrillName] = useState("");
  // Iter 540 — firm attendance calculation mode (header badge)
  const [punchSeq, setPunchSeq] = useState<boolean | null>(null);
  const LIMIT = 200;

  const showMsg = (m: string) => { if (Platform.OS === "web") globalThis.alert(m); };

  const qs = useCallback((extra?: Record<string, string>) => {
    const p = new URLSearchParams();
    p.set("company_id", companyId); p.set("date", date);
    if (dept) p.set("department", dept);
    if (desig) p.set("designation", desig);
    if (contr) p.set("contractor", contr);
    if (cat) p.set("category", cat);
    if (shift) p.set("shift", shift);
    if (grp) p.set("group", grp);
    if (empStatus) p.set("status", empStatus);
    if (source) p.set("source", source);
    if (machine) p.set("machine", machine);
    if (q.trim()) p.set("q", q.trim());
    if (exOnly) p.set("exceptions_only", "true");
    if (presentOnly) p.set("present_only", "true");
    Object.entries(extra || {}).forEach(([k, v]) => p.set(k, v));
    return p.toString();
  }, [companyId, date, dept, desig, contr, cat, shift, grp, empStatus, source, machine, q, exOnly, presentOnly]);

  const load = useCallback(async (off = 0) => {
    if (!companyId || !date) return;
    setLoading(true);
    try {
      const d = await api<any>(`/admin/reports/daily-verification?${qs({
        limit: String(LIMIT), offset: String(off) })}`);
      setRows((prev) => (off > 0 ? [...prev, ...(d.rows || [])] : d.rows || []));
      setSummary(d.summary || {});
      setOpts(d.filter_options || null);
      setPunchSeq(d.punch_sequence == null ? null : !!d.punch_sequence);
      setTotalRows(d.total_rows || 0);
      setOffset(off);
    } catch (e: any) {
      showMsg(e?.message || "Failed to load report");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId, date, qs]);

  useEffect(() => { void load(0); }, [companyId]); // eslint-disable-line react-hooks/exhaustive-deps

  const verify = async (r: Row, verified: boolean) => {
    let remarks = r.remarks;
    if (Platform.OS === "web" && verified) {
      remarks = globalThis.prompt(`Remarks for ${r.name} (optional):`, r.remarks || "") ?? r.remarks;
    }
    try {
      const res = await api<any>("/admin/reports/daily-verification/verify", {
        method: "POST",
        body: { company_id: companyId, date, user_id: r.user_id, verified, remarks },
      });
      setRows((prev) => prev.map((x) => x.user_id === r.user_id
        ? { ...x, verified, verified_by: res.verified_by_name, verified_at: res.verified_at, remarks }
        : x));
      setSummary((s) => ({
        ...s,
        verified: (s.verified || 0) + (verified ? 1 : -1),
        pending_verification: (s.pending_verification || 0) + (verified ? -1 : 1),
      }));
    } catch (e: any) {
      showMsg(e?.message || "Verification failed");
    }
  };

  const openDrill = async (r: Row) => {
    setDrillName(`${r.name} (${r.employee_code})`);
    setDrill(null);
    try {
      const d = await api<Drill>(
        `/admin/reports/daily-verification/employee?company_id=${encodeURIComponent(companyId)}&date=${date}&user_id=${encodeURIComponent(r.user_id)}`);
      setDrill(d);
    } catch (e: any) {
      showMsg(e?.message || "Drill-down failed");
      setDrillName("");
    }
  };

  const download = async (ext: string, extra?: Record<string, string>, print = false) => {
    if (busy) return;
    setBusy(true);
    try {
      const res = await apiBinary(`/admin/reports/daily-verification.${ext}?${qs(extra)}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        if (print) {
          window.open(res.webBlobUrl, "_blank");
        } else {
          const a = document.createElement("a");
          a.href = res.webBlobUrl;
          a.download = `Daily_Verification_${date}.${ext}`;
          a.click();
        }
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 60000);
      }
    } catch (e: any) {
      showMsg(e?.message || "Export failed");
    } finally {
      setBusy(false);
    }
  };

  const sendEmail = async () => {
    const to = Platform.OS === "web" ? globalThis.prompt("Send report to email:") : null;
    if (!to) return;
    setBusy(true);
    try {
      const r = await api<any>("/admin/reports/daily-verification/email", {
        method: "POST", body: { company_id: companyId, date, to },
      });
      showMsg(r.message || "Emailed");
    } catch (e: any) { showMsg(e?.message || "Email failed"); } finally { setBusy(false); }
  };

  const sendWhatsApp = async () => {
    const to = Platform.OS === "web" ? globalThis.prompt("WhatsApp number (with country code):") : null;
    if (!to) return;
    setBusy(true);
    try {
      const r = await api<any>("/admin/reports/daily-verification/whatsapp", {
        method: "POST", body: { company_id: companyId, date, to },
      });
      showMsg(r.message || "Sent");
    } catch (e: any) { showMsg(e?.message || "WhatsApp failed"); } finally { setBusy(false); }
  };

  const tableW = useMemo(() => COLS.reduce((a, c) => a + c.w, 0), []);

  if (!isAdmin) {
    return (
      <SafeAreaView style={st.safe} edges={["top"]}>
        <Text style={st.sub}>Admin access only.</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.title}>Daily In/Out & OT Verification</Text>
          <Text style={st.sub}>Physically verify attendance against punch records — {date}</Text>
        </View>
        {/* Iter 540 — attendance calculation mode badge */}
        {punchSeq != null ? (
          <View style={[st.ruleBadge, punchSeq && st.ruleBadgeSeq]}
            testID="dv-rule-badge">
            <Ionicons name={punchSeq ? "git-branch-outline" : "time-outline"}
              size={12} color={punchSeq ? "#166534" : "#075985"} />
            <Text style={[st.ruleTxt, punchSeq && { color: "#166534" }]}>
              {punchSeq ? "Rule: Punch Sequence" : "Rule: Standard (Shift HRS)"}
            </Text>
          </View>
        ) : null}
      </View>

      <ScrollView style={{ flex: 1 }} contentContainerStyle={{ padding: 12, paddingBottom: 40 }}>
        {/* -------- filters -------- */}
        <View style={st.filters}>
          {user?.role === "super_admin" && (
            <View style={{ minWidth: 180 }}>
              <Text style={st.lbl}>Firm</Text>
              {Platform.OS === "web" ? (
                <select value={companyId}
                  onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
                  style={WEB_SELECT}>
                  {companies.map((c: any) => (
                    <option key={c.company_id} value={c.company_id}>{c.name}</option>
                  ))}
                </select>
              ) : null}
            </View>
          )}
          <View style={{ minWidth: 130 }}>
            <Text style={st.lbl}>Date</Text>
            {Platform.OS === "web" ? (
              <input type="date" value={date}
                onChange={(e) => setDate((e.target as HTMLInputElement).value)}
                style={WEB_SELECT} />
            ) : (
              <TextInput value={date} onChangeText={setDate} style={st.input}
                placeholder="YYYY-MM-DD" />
            )}
          </View>
          <Sel label="Department" value={dept} onChange={setDept} width={140}
            options={(opts?.departments || []).map((v) => ({ v, l: v }))} />
          <Sel label="Designation" value={desig} onChange={setDesig} width={140}
            options={(opts?.designations || []).map((v) => ({ v, l: v }))} />
          {(opts?.contractors || []).length > 0 ? (
            /* Iter 523 (user request) — Contractor filter only when the
               firm actually has contractors. */
            <Sel label="Contractor" value={contr} onChange={setContr} width={140}
              options={(opts?.contractors || []).map((v) => ({ v, l: v }))} />
          ) : null}
          <Sel label="Category" value={cat} onChange={setCat} width={120}
            options={(opts?.categories || []).map((v) => ({ v, l: v }))} />
          <Sel label="Shift" value={shift} onChange={setShift} width={120}
            options={(opts?.shifts || []).map((v) => ({ v, l: v }))} />
          <Sel label="Unit / Group" value={grp} onChange={setGrp} width={130}
            options={(opts?.groups || []).map((v) => ({ v, l: v }))} />
          <Sel label="Employee Status" value={empStatus} onChange={(v) => setEmpStatus(v || "active")}
            width={120} options={[{ v: "active", l: "Active" }, { v: "resigned", l: "Inactive" }, { v: "all", l: "All" }]} />
          <Sel label="Punch Source" value={source} onChange={setSource} width={140}
            options={(opts?.sources || []).map((v) => ({ v, l: v }))} />
          <Sel label="Punch Machine" value={machine} onChange={setMachine} width={150}
            options={(opts?.machines || []).map((m) => ({ v: m.serial, l: m.name || m.serial }))} />
          <View style={{ minWidth: 170 }}>
            <Text style={st.lbl}>Employee Code / Name</Text>
            <TextInput value={q} onChangeText={setQ} style={st.input}
              placeholder="Search…" placeholderTextColor={colors.onSurfaceTertiary} />
          </View>
          <View style={{ alignItems: "center" }}>
            <Text style={st.lbl}>Only Exceptions</Text>
            <Switch value={exOnly} onValueChange={setExOnly} />
          </View>
          <View style={{ alignItems: "center" }}>
            <Text style={st.lbl}>Only Present</Text>
            <Switch value={presentOnly} onValueChange={setPresentOnly} />
          </View>
          <Pressable style={st.applyBtn} onPress={() => load(0)} disabled={loading}>
            {loading ? <ActivityIndicator color="#fff" size="small" /> : (
              <>
                <Ionicons name="search" size={15} color="#fff" />
                <Text style={st.applyTxt}>Apply</Text>
              </>
            )}
          </Pressable>
        </View>

        {/* -------- summary tiles -------- */}
        <View style={st.tiles}>
          {TILES.map(([k, l]) => (
            <View key={k} style={st.tile}>
              <Text style={st.tileVal}>{summary[k] ?? "—"}</Text>
              <Text style={st.tileLbl}>{l}</Text>
            </View>
          ))}
        </View>

        {/* -------- export bar -------- */}
        <View style={st.exportBar}>
          {[
            ["Excel", "download-outline", () => download("xlsx")],
            ["CSV", "document-text-outline", () => download("csv")],
            ["PDF (Landscape)", "document-outline", () => download("pdf", { orientation: "landscape" })],
            ["PDF (Portrait)", "document-outline", () => download("pdf", { orientation: "portrait" })],
            ["Print", "print-outline", () => download("pdf", { orientation: "landscape" }, true)],
            ["Email", "mail-outline", sendEmail],
            ["WhatsApp", "logo-whatsapp", sendWhatsApp],
          ].map(([l, ic, fn]: any) => (
            <Pressable key={l} style={st.expBtn} onPress={fn} disabled={busy}>
              <Ionicons name={ic} size={15} color={colors.cta} />
              <Text style={st.expTxt}>{l}</Text>
            </Pressable>
          ))}
        </View>

        {/* -------- legend -------- */}
        <View style={st.legend}>
          {[["red", "Missing Punch"], ["orange", "Unapproved OT"], ["yellow", "Late / Early"],
            ["blue", "Manual"], ["green", "Normal"], ["muted", "Absent/WO/Hol/Leave"]].map(([c, l]) => (
            <View key={c} style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
              <View style={[st.dot, { backgroundColor: ROW_BG[c] }]} />
              <Text style={st.legTxt}>{l}</Text>
            </View>
          ))}
        </View>

        {/* -------- table -------- */}
        <ScrollView horizontal showsHorizontalScrollIndicator>
          <View style={{ width: tableW }}>
            <View style={st.thead}>
              {COLS.map((c) => (
                <Text key={String(c.key)} style={[st.th, { width: c.w }]}>{c.label}</Text>
              ))}
            </View>
            {rows.map((r, i) => (
              <View key={r.user_id} style={[st.tr, { backgroundColor: ROW_BG[r.color] || "#fff" }]}>
                {COLS.map((c) => {
                  if (c.key === "sr") {
                    return <Text key="sr" style={[st.td, { width: c.w }]}>{offset + i + 1}</Text>;
                  }
                  if (c.key === "name") {
                    return (
                      <Pressable
                        key="name"
                        style={{ width: c.w, flexDirection: "row", alignItems: "center", gap: 6 }}
                        onPress={() => openDrill(r)}
                      >
                        {/* Iter 494 — photo beside the name for quick visual verification */}
                        <EmployeePhoto userId={r.user_id} name={r.name} code={r.employee_code} size={28} />
                        <Text style={[st.td, st.link, { flex: 1 }]} numberOfLines={1}>{r.name}</Text>
                      </Pressable>
                    );
                  }
                  if (c.key === "status") {
                    return (
                      <Text key="st" style={[st.td, { width: c.w, fontWeight: "700" }]} numberOfLines={2}>
                        {r.status}{r.markers.length ? ` · ${r.markers.join(", ")}` : ""}
                      </Text>
                    );
                  }
                  if (c.key === "sign") {
                    return (
                      <View key="sign" style={{ width: c.w, flexDirection: "row", alignItems: "center", gap: 6 }}>
                        <Pressable
                          testID={`verify-${r.employee_code}`}
                          style={[st.chk, r.verified && st.chkOn]}
                          onPress={() => verify(r, !r.verified)}>
                          {r.verified ? <Ionicons name="checkmark" size={14} color="#fff" /> : null}
                        </Pressable>
                        <View style={{ flex: 1 }}>
                          <Text style={st.verTxt} numberOfLines={1}>
                            {r.verified ? `✓ ${r.verified_by}` : "Physically Verified?"}
                          </Text>
                          {r.verified && r.verified_at ? (
                            <Text style={st.verSub} numberOfLines={1}>
                              {String(r.verified_at).slice(0, 16).replace("T", " ")}
                              {r.remarks ? ` · ${r.remarks}` : ""}
                            </Text>
                          ) : null}
                        </View>
                      </View>
                    );
                  }
                  return (
                    <Text key={String(c.key)} style={[st.td, { width: c.w }]} numberOfLines={1}>
                      {String((r as any)[c.key] ?? "-")}
                    </Text>
                  );
                })}
              </View>
            ))}
            {!loading && rows.length === 0 && (
              <Text style={[st.sub, { padding: 20 }]}>No employees found for the selected filters.</Text>
            )}
          </View>
        </ScrollView>
        {rows.length < totalRows && (
          <Pressable style={st.moreBtn} onPress={() => load(offset + LIMIT)}>
            <Text style={st.expTxt}>Load more ({rows.length} of {totalRows})</Text>
          </Pressable>
        )}
      </ScrollView>

      {/* -------- drill-down modal -------- */}
      <Modal visible={!!drillName} transparent animationType="fade"
        onRequestClose={() => { setDrillName(""); setDrill(null); }}>
        <View style={st.mBack}>
          <View style={st.mCard}>
            <View style={{ flexDirection: "row", alignItems: "center" }}>
              <Text style={[st.title, { flex: 1 }]}>{drillName}</Text>
              <Pressable onPress={() => { setDrillName(""); setDrill(null); }} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurface} />
              </Pressable>
            </View>
            {!drill ? <ActivityIndicator style={{ margin: 30 }} /> : (
              <ScrollView style={{ maxHeight: 520 }}>
                <Text style={st.mSec}>Punch Timeline — {date}</Text>
                {drill.timeline.length === 0 && <Text style={st.sub}>No punches on this day.</Text>}
                {drill.timeline.map((p, i) => (
                  <View key={i} style={st.tlRow}>
                    {p.selfie ? (
                      <Image source={{ uri: p.selfie.startsWith("data:") ? p.selfie : `data:image/jpeg;base64,${p.selfie}` }}
                        style={st.selfie} />
                    ) : (
                      <View style={[st.selfie, { alignItems: "center", justifyContent: "center" }]}>
                        <Ionicons name="finger-print" size={18} color={colors.onSurfaceTertiary} />
                      </View>
                    )}
                    <View style={{ flex: 1 }}>
                      <Text style={st.tlMain}>
                        {p.time} — {(p.kind || "").toUpperCase()} · {p.source}
                        {p.machine ? ` · ${p.machine}` : ""}
                      </Text>
                      <Text style={st.verSub}>
                        {p.device_serial ? `SN ${p.device_serial} · ` : ""}
                        {p.location_name || (p.lat ? `${p.lat?.toFixed(5)}, ${p.lng?.toFixed(5)}` : "")}
                        {p.status ? ` · ${p.status}` : ""}
                      </Text>
                      {p.lat && Platform.OS === "web" ? (
                        <Text style={[st.link, { fontSize: type.xs }]}
                          onPress={() => window.open(`https://maps.google.com/?q=${p.lat},${p.lng}`, "_blank")}>
                          View on map
                        </Text>
                      ) : null}
                    </View>
                  </View>
                ))}
                <Text style={st.mSec}>Previous 7 Days</Text>
                <View style={st.thead}>
                  {["Date", "In", "Out", "Hours", "OT"].map((h) => (
                    <Text key={h} style={[st.th, { width: 90 }]}>{h}</Text>
                  ))}
                </View>
                {drill.history.map((h, i) => (
                  <View key={i} style={st.tr}>
                    <Text style={[st.td, { width: 90 }]}>{h.date || h.day}</Text>
                    <Text style={[st.td, { width: 90 }]}>{h.in}</Text>
                    <Text style={[st.td, { width: 90 }]}>{h.out}</Text>
                    <Text style={[st.td, { width: 90 }]}>{h.hours}</Text>
                    <Text style={[st.td, { width: 90 }]}>{h.ot}</Text>
                  </View>
                ))}
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

// Plain JS object for the web <select>/<input> DOM elements (NOT a RN style —
// keeps react-native-web from warning about CSS shorthand properties).
const WEB_SELECT: any = {
  height: 36, borderRadius: 8, border: `1px solid ${colors.border}`,
  padding: "0 8px", fontSize: 13, background: "#fff", width: "100%",
};

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: type.lg, fontWeight: "800", color: colors.onSurface },
  ruleBadge: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#E0F2FE", borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5,
  },
  ruleBadgeSeq: { backgroundColor: "#DCFCE7" },
  ruleTxt: { fontSize: 11, fontWeight: "800", color: "#075985" },
  sub: { fontSize: type.sm, color: colors.onSurfaceSecondary },
  filters: {
    flexDirection: "row", flexWrap: "wrap", gap: 10, alignItems: "flex-end",
    backgroundColor: colors.surface, borderRadius: radius.md, padding: 12,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12,
  },
  lbl: { fontSize: type.xs, color: colors.onSurfaceSecondary, marginBottom: 4, fontWeight: "700" },
  input: {
    height: 36, borderRadius: 8, borderWidth: 1, borderColor: colors.border,
    paddingHorizontal: 8, fontSize: 13, backgroundColor: "#fff", color: colors.onSurface,
  },
  applyBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.cta,
    borderRadius: 8, paddingHorizontal: 16, height: 38,
  },
  applyTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  tiles: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 12 },
  tile: {
    flexGrow: 1, minWidth: 105, backgroundColor: colors.surface, borderRadius: radius.sm,
    paddingVertical: 8, paddingHorizontal: 10, alignItems: "center",
    borderWidth: 1, borderColor: colors.border,
  },
  tileVal: { fontSize: 17, fontWeight: "900", color: colors.onSurface },
  tileLbl: { fontSize: 10, color: colors.onSurfaceSecondary, marginTop: 1, textAlign: "center" },
  exportBar: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 10 },
  expBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1,
    borderColor: colors.cta, borderRadius: 8, paddingHorizontal: 12, height: 34,
    backgroundColor: colors.surface,
  },
  expTxt: { color: colors.cta, fontWeight: "700", fontSize: 12 },
  legend: { flexDirection: "row", flexWrap: "wrap", gap: 14, marginBottom: 8 },
  dot: { width: 14, height: 14, borderRadius: 4, borderWidth: 1, borderColor: "#94A3B8" },
  legTxt: { fontSize: type.xs, color: colors.onSurfaceSecondary },
  thead: { flexDirection: "row", backgroundColor: "#1E293B", borderTopLeftRadius: 8, borderTopRightRadius: 8 },
  th: { color: "#fff", fontWeight: "800", fontSize: 11, paddingVertical: 8, paddingHorizontal: 6 },
  tr: {
    flexDirection: "row", alignItems: "center", borderBottomWidth: 1,
    borderBottomColor: "#CBD5E1", minHeight: 40,
  },
  td: { fontSize: 12, color: "#0F172A", paddingHorizontal: 6, paddingVertical: 4 },
  link: { color: "#1D4ED8", fontWeight: "700", textDecorationLine: "underline" },
  chk: {
    width: 22, height: 22, borderRadius: 5, borderWidth: 2, borderColor: "#475569",
    alignItems: "center", justifyContent: "center", backgroundColor: "#fff",
  },
  chkOn: { backgroundColor: "#16A34A", borderColor: "#16A34A" },
  verTxt: { fontSize: 11, fontWeight: "700", color: "#0F172A" },
  verSub: { fontSize: 10, color: "#475569" },
  moreBtn: {
    alignSelf: "center", marginTop: 12, borderWidth: 1, borderColor: colors.cta,
    borderRadius: 8, paddingHorizontal: 18, paddingVertical: 8,
  },
  mBack: { flex: 1, backgroundColor: "rgba(15,23,42,0.55)", alignItems: "center", justifyContent: "center", padding: 16 },
  mCard: {
    backgroundColor: colors.surface, borderRadius: radius.md, padding: 16,
    width: "100%", maxWidth: 680,
  },
  mSec: { fontSize: type.md, fontWeight: "800", color: colors.onSurface, marginTop: 14, marginBottom: 6 },
  tlRow: {
    flexDirection: "row", gap: 10, alignItems: "center", paddingVertical: 6,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  tlMain: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  selfie: { width: 44, height: 44, borderRadius: 8, backgroundColor: "#F1F5F9" },
});
