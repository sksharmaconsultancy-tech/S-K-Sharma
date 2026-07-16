/**
 * Iter 153 — Sheet Verification (OCR) — Utility.
 *
 * Upload a handwritten daily attendance sheet → OCR extracts rows →
 * review/correct → match against system punches → MIS verdict table with
 * per-employee "Fix with OCR" / "Leave existing" actions.
 * Sub-admin fixes queue for Super Admin approval (approval panel below).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import DateField from "@/src/components/DateField";
import { colors, radius } from "@/src/theme";

type SheetRow = {
  code: string | null; name: string;
  in_time: string | null; out_time: string | null;
  ot_hours?: number | null; signature_present: boolean;
};
type MisRow = {
  user_id: string | null; employee_code?: string | null; name?: string;
  sheet: SheetRow | null;
  system_in?: string | null; system_out?: string | null;
  delta_in_min?: number | null; delta_out_min?: number | null;
  verdict: string; no_signature: boolean; resolution?: string | null;
};

const VERDICT_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  MATCHED: { bg: "#dcfce7", fg: "#15803d", label: "MATCHED" },
  TIME_MISMATCH: { bg: "#fef3c7", fg: "#b45309", label: "TIME MISMATCH" },
  NOT_IN_SYSTEM: { bg: "#fee2e2", fg: "#b91c1c", label: "NOT IN SYSTEM" },
  NOT_ON_SHEET: { bg: "#fde68a", fg: "#92400e", label: "NOT ON SHEET" },
  UNMATCHED_ROW: { bg: "#e5e7eb", fg: "#374151", label: "UNMATCHED" },
};

export default function SheetVerification() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;
  const isSuper = role === "super_admin";

  const [companyId, setCompanyId] = useState<string | "all">(
    role === "company_admin" ? (user?.company_id || "all") : (selectedCompanyId || "all"),
  );
  const [date, setDate] = useState<string>(new Date().toISOString().slice(0, 10));
  const [tolerance, setTolerance] = useState("15");
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const [sheetRows, setSheetRows] = useState<SheetRow[]>([]);
  const [run, setRun] = useState<any>(null);
  const [fixReqs, setFixReqs] = useState<any[]>([]);

  const loadFixReqs = useCallback(async () => {
    if (role !== "super_admin" && role !== "sub_admin") return;
    try {
      const r = await api<{ requests: any[] }>("/admin/sheet-fix-requests");
      setFixReqs(r.requests || []);
    } catch {}
  }, [role]);
  useEffect(() => { loadFixReqs(); }, [loadFixReqs]);

  // ---- Step 1: pick file(s) + OCR ----------------------------------------
  const compress = (dataUrl: string): Promise<string> =>
    new Promise((resolve) => {
      const img = new (globalThis as any).Image();
      img.onload = () => {
        try {
          const MAX = 2000; // sheets need more detail than ID cards
          let { width, height } = img;
          const s = Math.min(1, MAX / Math.max(width, height));
          const canvas = (globalThis as any).document.createElement("canvas");
          canvas.width = Math.round(width * s);
          canvas.height = Math.round(height * s);
          canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
          const out = canvas.toDataURL("image/jpeg", 0.85);
          resolve(out.length < dataUrl.length ? out : dataUrl);
        } catch { resolve(dataUrl); }
      };
      img.onerror = () => resolve(dataUrl);
      img.src = dataUrl;
    });

  const pickAndOcr = () => {
    if (Platform.OS !== "web") return;
    const input = (globalThis as any).document.createElement("input");
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp,application/pdf";
    input.multiple = true;
    input.onchange = async (e: any) => {
      const files: File[] = Array.from(e?.target?.files || []).slice(0, 4) as File[];
      if (!files.length) return;
      setBusy("ocr");
      setMsg("Reading the handwritten sheet with OCR — this can take 20–60 seconds…");
      try {
        const pages: any[] = [];
        for (const f of files) {
          const raw: string = await new Promise((res) => {
            const rd = new (globalThis as any).FileReader();
            rd.onloadend = () => res(rd.result as string);
            rd.readAsDataURL(f);
          });
          const isPdf = (f.type || "").includes("pdf");
          pages.push({
            document_base64: isPdf ? raw : await compress(raw),
            mime_type: isPdf ? "application/pdf" : "image/jpeg",
          });
        }
        const r = await api<any>("/admin/sheet-verification/ocr", {
          method: "POST", body: { pages },
        });
        setSheetRows(r.rows || []);
        if (r.sheet_date) setDate(r.sheet_date);
        setStep(2);
        setMsg(`${(r.rows || []).length} rows read (confidence: ${r.confidence || "n/a"}). Correct any misread cells, then Match.`);
      } catch (err: any) {
        setMsg(err?.message || "Sheet OCR failed");
      } finally { setBusy(null); }
    };
    input.click();
  };

  // ---- Step 2 → 3: match --------------------------------------------------
  const doMatch = async () => {
    if (!companyId || companyId === "all") { setMsg("Please select a firm first."); return; }
    setBusy("match");
    setMsg("");
    try {
      const r = await api<any>("/admin/sheet-verification/match", {
        method: "POST",
        body: { company_id: companyId, date, tolerance_min: Number(tolerance) || 15, rows: sheetRows },
      });
      setRun(r.run);
      setStep(3);
    } catch (e: any) { setMsg(e?.message || "Match failed"); }
    finally { setBusy(null); }
  };

  // ---- Step 3: per-row actions --------------------------------------------
  const act = async (row: MisRow, action: "fix" | "leave") => {
    if (!row.user_id || !run) return;
    setBusy(`${action}-${row.user_id}`);
    try {
      const r = await api<any>("/admin/sheet-verification/apply", {
        method: "POST", body: { run_id: run.run_id, user_id: row.user_id, action },
      });
      setRun((prev: any) => ({
        ...prev,
        rows: prev.rows.map((x: MisRow) =>
          x.user_id === row.user_id ? { ...x, resolution: r.resolution } : x),
      }));
      if (r.resolution === "pending_approval") setMsg("Fix sent to Super Admin for approval ✓");
      loadFixReqs();
    } catch (e: any) { setMsg(e?.message || "Action failed"); }
    finally { setBusy(null); }
  };

  const decideReq = async (req: any, decision: "approve" | "reject") => {
    setBusy(`req-${req.request_id}`);
    try {
      await api(`/admin/sheet-fix-requests/${req.request_id}`, {
        method: "PATCH", body: { decision },
      });
      loadFixReqs();
      setMsg(`Request ${decision}d ✓`);
    } catch (e: any) { setMsg(e?.message || "Decision failed"); }
    finally { setBusy(null); }
  };

  if (authLoading) return null;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.back}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>Sheet Verification (OCR)</Text>
        <View style={{ width: 38 }} />
      </View>
      <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 60 }}>
        {/* Controls */}
        <View style={s.card}>
          {role !== "company_admin" && (
            <CompanyPicker value={companyId} onChange={setCompanyId} label="Firm" allowAll={false} compact testID="shv-firm" />
          )}
          <View style={{ flexDirection: "row", gap: 10, marginTop: 10, alignItems: "flex-end" }}>
            <View style={{ flex: 1 }}>
              <Text style={s.lbl}>Sheet date</Text>
              <DateField value={date} onChangeISO={setDate} />
            </View>
            <View style={{ width: 110 }}>
              <Text style={s.lbl}>Tolerance (min)</Text>
              <TextInput value={tolerance} onChangeText={(v) => setTolerance(v.replace(/[^0-9]/g, ""))}
                keyboardType="numeric" style={s.input} testID="shv-tol" />
            </View>
          </View>
          <Pressable onPress={pickAndOcr} disabled={busy === "ocr"} style={[s.btn, { marginTop: 12 }]} testID="shv-upload">
            {busy === "ocr" ? <ActivityIndicator color="#fff" size="small" /> : (
              <>
                <Ionicons name="cloud-upload-outline" size={16} color="#fff" />
                <Text style={s.btnT}>Upload handwritten sheet (photo / PDF)</Text>
              </>
            )}
          </Pressable>
          {!!msg && <Text style={s.msg}>{msg}</Text>}
        </View>

        {/* Step 2 — review extracted rows */}
        {step >= 2 && (
          <View style={s.card}>
            <Text style={s.h2}>Step 2 · Review extracted rows ({sheetRows.length})</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator>
              <View>
                <View style={s.hr}>
                  {[["Code", 64], ["Name", 170], ["In", 64], ["Out", 64], ["Sign", 48]].map(([t, w]) => (
                    <Text key={String(t)} style={[s.hc, { width: Number(w) }]}>{String(t)}</Text>
                  ))}
                </View>
                {sheetRows.map((r, i) => (
                  <View key={i} style={[s.tr, i % 2 === 0 && s.trAlt]}>
                    {(["code", "name", "in_time", "out_time"] as const).map((k, ci) => (
                      <TextInput key={k}
                        value={String(r[k] ?? "")}
                        onChangeText={(v) => setSheetRows((prev) =>
                          prev.map((x, xi) => xi === i ? { ...x, [k]: v || null } : x))}
                        style={[s.cellIn, { width: [64, 170, 64, 64][ci] }]}
                        placeholder={ci >= 2 ? "HH:MM" : "—"}
                        placeholderTextColor={colors.onSurfaceTertiary}
                        testID={`shv-r${i}-${k}`}
                      />
                    ))}
                    <Pressable
                      onPress={() => setSheetRows((prev) =>
                        prev.map((x, xi) => xi === i ? { ...x, signature_present: !x.signature_present } : x))}
                      style={{ width: 48, alignItems: "center", justifyContent: "center" }}
                    >
                      <Ionicons name={r.signature_present ? "checkmark-circle" : "close-circle"}
                        size={18} color={r.signature_present ? "#15803d" : "#b91c1c"} />
                    </Pressable>
                  </View>
                ))}
              </View>
            </ScrollView>
            <Pressable onPress={doMatch} disabled={busy === "match"} style={[s.btn, { marginTop: 12 }]} testID="shv-match">
              {busy === "match" ? <ActivityIndicator color="#fff" size="small" /> : (
                <>
                  <Ionicons name="git-compare-outline" size={16} color="#fff" />
                  <Text style={s.btnT}>Match with system punches</Text>
                </>
              )}
            </Pressable>
          </View>
        )}

        {/* Step 3 — MIS verdicts */}
        {step === 3 && run && (
          <View style={s.card}>
            <Text style={s.h2}>Step 3 · MIS Report — {run.date}</Text>
            <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
              {Object.entries(run.summary || {}).map(([k, v]: any) => {
                const st = VERDICT_STYLE[k] || VERDICT_STYLE.UNMATCHED_ROW;
                return (
                  <View key={k} style={[s.chip, { backgroundColor: st.bg }]}>
                    <Text style={[s.chipT, { color: st.fg }]}>{st.label}: {v}</Text>
                  </View>
                );
              })}
            </View>
            <ScrollView horizontal showsHorizontalScrollIndicator>
              <View>
                <View style={s.hr}>
                  {[["Code", 56], ["Name", 160], ["Sheet In", 62], ["Sheet Out", 66], ["Sys In", 56], ["Sys Out", 60],
                    ["Verdict", 118], ["Sign", 44], ["Action", 170]].map(([t, w]) => (
                    <Text key={String(t)} style={[s.hc, { width: Number(w) }]}>{String(t)}</Text>
                  ))}
                </View>
                {(run.rows as MisRow[]).map((r, i) => {
                  const st = VERDICT_STYLE[r.verdict] || VERDICT_STYLE.UNMATCHED_ROW;
                  const canFix = !!r.user_id && !!r.sheet &&
                    (r.verdict === "TIME_MISMATCH" || r.verdict === "NOT_IN_SYSTEM");
                  return (
                    <View key={i} style={[s.tr, i % 2 === 0 && s.trAlt]}>
                      <Text style={[s.cell, { width: 56 }]}>{r.employee_code || r.sheet?.code || "—"}</Text>
                      <Text style={[s.cell, { width: 160, fontWeight: "600" }]} numberOfLines={1}>{r.name || "—"}</Text>
                      <Text style={[s.cell, { width: 62 }]}>{r.sheet?.in_time || "—"}</Text>
                      <Text style={[s.cell, { width: 66 }]}>{r.sheet?.out_time || "—"}</Text>
                      <Text style={[s.cell, { width: 56 }]}>{r.system_in || "—"}</Text>
                      <Text style={[s.cell, { width: 60 }]}>{r.system_out || "—"}</Text>
                      <View style={{ width: 118, justifyContent: "center" }}>
                        <Text style={[s.vBadge, { backgroundColor: st.bg, color: st.fg }]}>{st.label}</Text>
                      </View>
                      <View style={{ width: 44, alignItems: "center", justifyContent: "center" }}>
                        <Ionicons name={r.no_signature ? "close-circle" : "checkmark-circle"}
                          size={16} color={r.no_signature ? "#b91c1c" : "#15803d"} />
                      </View>
                      <View style={{ width: 170, flexDirection: "row", gap: 5, alignItems: "center" }}>
                        {r.resolution ? (
                          <Text style={s.resT}>
                            {r.resolution === "fixed" ? "✓ Fixed" :
                             r.resolution === "left" ? "Kept existing" : "⏳ Awaiting Super Admin"}
                          </Text>
                        ) : canFix ? (
                          <>
                            <Pressable onPress={() => act(r, "fix")}
                              disabled={busy === `fix-${r.user_id}`}
                              style={[s.miniBtn, { backgroundColor: colors.brandPrimary }]}
                              testID={`shv-fix-${i}`}>
                              <Text style={s.miniBtnT}>Fix with OCR</Text>
                            </Pressable>
                            <Pressable onPress={() => act(r, "leave")}
                              disabled={busy === `leave-${r.user_id}`}
                              style={[s.miniBtn, { backgroundColor: "#6b7280" }]}
                              testID={`shv-leave-${i}`}>
                              <Text style={s.miniBtnT}>Leave</Text>
                            </Pressable>
                          </>
                        ) : (
                          <Text style={s.resT}>—</Text>
                        )}
                      </View>
                    </View>
                  );
                })}
              </View>
            </ScrollView>
          </View>
        )}

        {/* Super Admin approval queue / sub-admin's own pending */}
        {fixReqs.length > 0 && (
          <View style={s.card}>
            <Text style={s.h2}>
              {isSuper ? "Pending sheet-fix approvals" : "Your fixes awaiting Super Admin"} ({fixReqs.length})
            </Text>
            {fixReqs.map((q) => (
              <View key={q.request_id} style={s.reqRow}>
                <View style={{ flex: 1 }}>
                  <Text style={{ fontWeight: "700", fontSize: 13, color: colors.onSurface }}>
                    {q.employee_name} ({q.employee_code || "—"}) · {q.date}
                  </Text>
                  <Text style={{ fontSize: 11.5, color: colors.onSurfaceTertiary }}>
                    Sheet {q.sheet_in || "—"}–{q.sheet_out || "—"} vs System {q.system_in || "—"}–{q.system_out || "—"} · by {q.requested_by_name || "sub-admin"}
                  </Text>
                </View>
                {isSuper && (
                  <View style={{ flexDirection: "row", gap: 6 }}>
                    <Pressable onPress={() => decideReq(q, "approve")}
                      style={[s.miniBtn, { backgroundColor: "#15803d" }]} testID={`shv-appr-${q.request_id}`}>
                      <Text style={s.miniBtnT}>Approve</Text>
                    </Pressable>
                    <Pressable onPress={() => decideReq(q, "reject")}
                      style={[s.miniBtn, { backgroundColor: "#b91c1c" }]} testID={`shv-rej-${q.request_id}`}>
                      <Text style={s.miniBtnT}>Reject</Text>
                    </Pressable>
                  </View>
                )}
              </View>
            ))}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", paddingHorizontal: 12, paddingVertical: 10 },
  back: { width: 38, height: 38, alignItems: "center", justifyContent: "center" },
  title: { flex: 1, textAlign: "center", fontSize: 17, fontWeight: "700", color: colors.onSurface },
  card: {
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius?.lg ?? 14, padding: 14, marginBottom: 14,
  },
  h2: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  lbl: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceTertiary, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, minHeight: 40,
    paddingHorizontal: 10, color: colors.onSurface, backgroundColor: colors.surface,
  },
  btn: {
    flexDirection: "row", gap: 8, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.brandPrimary, borderRadius: 10, paddingVertical: 12,
  },
  btnT: { color: "#fff", fontWeight: "800", fontSize: 13.5 },
  msg: { marginTop: 10, fontSize: 12.5, color: colors.brandPrimary, fontWeight: "600" },
  hr: { flexDirection: "row", borderBottomWidth: 1, borderColor: colors.border, paddingBottom: 6 },
  hc: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary, textTransform: "uppercase" },
  tr: { flexDirection: "row", alignItems: "center", paddingVertical: 5 },
  trAlt: { backgroundColor: colors.surface },
  cell: { fontSize: 12.5, color: colors.onSurface, paddingHorizontal: 2 },
  cellIn: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 6, marginRight: 3,
    paddingVertical: 5, paddingHorizontal: 6, fontSize: 12.5, color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  chip: { borderRadius: 14, paddingVertical: 5, paddingHorizontal: 10 },
  chipT: { fontSize: 11.5, fontWeight: "800" },
  vBadge: {
    fontSize: 10, fontWeight: "800", borderRadius: 6, overflow: "hidden",
    paddingVertical: 3, paddingHorizontal: 6, textAlign: "center",
  },
  miniBtn: { borderRadius: 7, paddingVertical: 7, paddingHorizontal: 9 },
  miniBtnT: { color: "#fff", fontWeight: "800", fontSize: 10.5 },
  resT: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  reqRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderTopWidth: 1, borderColor: colors.border, paddingVertical: 9,
  },
});
