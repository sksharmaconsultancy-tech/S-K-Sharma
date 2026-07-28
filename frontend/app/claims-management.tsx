/**
 * PF & ESIC Claims Management System (Iter 359).
 * Tabs: Dashboard · Claims Register · New/Edit Claim · Reminders · Reports.
 * Supports claims for existing companies AND external (outside) companies.
 * Smart AI: eligibility flags, document completeness score, expected
 * settlement date, duplicate detection (computed server-side on save).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Platform,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import RegisterTable, {
  ExportButtons,
  shared,
} from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

const STATUS_COLORS: Record<string, string> = {
  Pending: "#B45309",
  Submitted: "#1D4ED8",
  Verified: "#0E7490",
  "Under Process": "#7C3AED",
  Approved: "#15803D",
  Rejected: "#B91C1C",
  Settled: "#166534",
};
const REPORTS = [
  ["pf-register", "PF Claims Register"],
  ["esic-register", "ESIC Claims Register"],
  ["pending", "Pending Claims"],
  ["approved", "Approved Claims"],
  ["rejected", "Rejected Claims"],
  ["settlement", "Settlement Register"],
] as const;
const FIELDS: [string, string][] = [
  ["employee_code", "Employee Code"],
  ["employee_name", "Employee Name"],
  ["department", "Department"],
  ["designation", "Designation"],
  ["doj", "Date of Joining (YYYY-MM-DD)"],
  ["dol", "Date of Leaving (YYYY-MM-DD)"],
  ["application_date", "Application Date (YYYY-MM-DD)"],
  ["claim_amount", "Claim Amount (₹)"],
  ["follow_up_date", "Follow-up Date (YYYY-MM-DD)"],
  ["executive", "Handled By (Executive)"],
  ["acknowledgement_no", "Acknowledgement / Ref No."],
  ["payment_reference", "Payment Reference (NEFT/UTR)"],
  ["settlement_date", "Settlement Date (YYYY-MM-DD)"],
  ["remarks", "Remarks"],
];

function WebSelect({
  value,
  onChange,
  options,
  testID,
  width,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  testID: string;
  width?: number;
}) {
  if (Platform.OS !== "web") return null;
  return (
    <select
      data-testid={testID}
      value={value}
      onChange={(e) => onChange((e.target as HTMLSelectElement).value)}
      style={
        {
          padding: 8,
          borderRadius: 8,
          borderColor: "#CBD5E1",
          borderWidth: 1,
          fontSize: 13,
          maxWidth: width || 260,
        } as any
      }
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export default function ClaimsManagementScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { companies } = useSelectedCompany();
  const [tab, setTab] = useState<
    "dashboard" | "register" | "form" | "reminders" | "reports"
  >("dashboard");
  const [meta, setMeta] = useState<any>(null);
  const [dash, setDash] = useState<any>(null);
  const [claims, setClaims] = useState<any[]>([]);
  const [reminders, setReminders] = useState<any[]>([]);
  const [reportKind, setReportKind] = useState("pf-register");
  const [reportData, setReportData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string>("");

  // filters (register tab)
  const [fKind, setFKind] = useState<"pf" | "esic">("pf");
  const [fStatus, setFStatus] = useState("");
  const [fType, setFType] = useState("");
  const [fCompany, setFCompany] = useState("");
  const [fQ, setFQ] = useState("");

  // form state
  const [claimId, setClaimId] = useState("");
  const [cKind, setCKind] = useState<"pf" | "esic">("pf");
  const [cCompany, setCCompany] = useState("");
  const [cStatus, setCStatus] = useState("Pending");
  const [cType, setCType] = useState("");
  const [form, setForm] = useState<Record<string, string>>({});
  const [docs, setDocs] = useState<Record<string, boolean>>({});
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");
  const [aiResult, setAiResult] = useState<any>(null);

  const isCompanyAdmin = user?.role === "company_admin";

  useEffect(() => {
    api<any>("/admin/claims/meta")
      .then(setMeta)
      .catch(() => {});
  }, []);

  const loadDash = useCallback(async () => {
    setLoading(true);
    try {
      const qp = fCompany ? `?company_id=${fCompany}` : "";
      setDash(await api<any>(`/admin/claims/dashboard${qp}`));
    } catch {
      setDash(null);
    } finally {
      setLoading(false);
    }
  }, [fCompany]);

  const loadClaims = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ claim_kind: fKind });
      if (fStatus) p.set("status", fStatus);
      if (fType) p.set("claim_type", fType);
      if (fCompany) p.set("company_id", fCompany);
      if (fQ) p.set("q", fQ);
      const r = await api<any>(`/admin/claims?${p.toString()}`);
      setClaims(r.claims || []);
    } catch {
      setClaims([]);
    } finally {
      setLoading(false);
    }
  }, [fKind, fStatus, fType, fCompany, fQ]);

  const loadReminders = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<any>("/admin/claims/reminders");
      setReminders(r.due || []);
    } catch {
      setReminders([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadReport = useCallback(async () => {
    setLoading(true);
    try {
      const qp = fCompany ? `?company_id=${fCompany}` : "";
      setReportData(await api<any>(`/admin/claims/report/${reportKind}${qp}`));
    } catch {
      setReportData(null);
    } finally {
      setLoading(false);
    }
  }, [reportKind, fCompany]);

  useEffect(() => {
    if (tab === "dashboard") void loadDash();
    if (tab === "register") void loadClaims();
    if (tab === "reminders") void loadReminders();
    if (tab === "reports") void loadReport();
  }, [tab, loadDash, loadClaims, loadReminders, loadReport]);

  const resetForm = (kind: "pf" | "esic" = "pf") => {
    setClaimId("");
    setCKind(kind);
    setCCompany(isCompanyAdmin ? user?.company_id || "" : "");
    setCStatus("Pending");
    setCType("");
    setForm({});
    setDocs({});
    setAiResult(null);
    setMsg("");
  };

  const editClaim = (c: any) => {
    setClaimId(c.claim_id);
    setCKind(c.claim_kind);
    setCCompany(c.company_id || "");
    setCStatus(c.status);
    setCType(c.data?.claim_type || "");
    const f: Record<string, string> = {};
    FIELDS.forEach(([k]) => {
      if (c.data?.[k] != null) f[k] = String(c.data[k]);
    });
    ["uan", "insurance_no", "company_name"].forEach((k) => {
      if (c.data?.[k] != null) f[k] = String(c.data[k]);
    });
    setForm(f);
    setDocs(c.documents || {});
    setAiResult({
      ai_flags: c.ai_flags || [],
      doc_score: c.doc_score,
      expected_settlement: c.expected_settlement,
    });
    setMsg("");
    setTab("form");
  };

  const save = async () => {
    if (!cType) {
      setMsg("Please select a Claim Type");
      return;
    }
    if (cCompany === "external" && !form.company_name) {
      setMsg("Please enter the external company name");
      return;
    }
    if (!cCompany) {
      setMsg("Please select a company (or External / Other Company)");
      return;
    }
    setSaving(true);
    setMsg("");
    try {
      const r = await api<any>("/admin/claims", {
        method: "POST",
        body: {
          claim_id: claimId || undefined,
          claim_kind: cKind,
          company_id: cCompany === "external" ? undefined : cCompany,
          status: cStatus,
          documents: docs,
          data: { ...form, claim_type: cType },
        },
      });
      setClaimId(r.claim_id);
      setAiResult(r);
      setMsg(`✓ Saved ${r.claim_no}`);
    } catch (e: any) {
      setMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const del = async (cid: string) => {
    try {
      await api(`/admin/claims/${cid}`, { method: "DELETE" });
      void loadClaims();
    } catch {}
  };

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const statuses: string[] =
    (cKind === "pf" ? meta?.pf_statuses : meta?.esic_statuses) || [];
  const fStatuses: string[] =
    (fKind === "pf" ? meta?.pf_statuses : meta?.esic_statuses) || [];
  const types: string[] =
    (cKind === "pf" ? meta?.pf_types : meta?.esic_types) || [];
  const fTypes: string[] =
    (fKind === "pf" ? meta?.pf_types : meta?.esic_types) || [];
  const checklist: string[] = meta?.doc_checklist?.[cKind] || [];
  const companyOpts = [
    { value: "", label: "— Select Company —" },
    ...(companies || []).map((c: any) => ({
      value: c.company_id,
      label: c.name,
    })),
    { value: "external", label: "🌐 External / Other Company" },
  ];

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="cl-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>PF & ESIC Claims Management</Text>
        {tab === "reports" ? (
          <ExportButtons
            basePath={`/admin/claims/report/${reportKind}${
              fCompany ? `?company_id=${fCompany}` : ""
            }`}
            fileBase={`claims_${reportKind}`}
          />
        ) : (
          <View style={{ width: 40 }} />
        )}
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        <View style={shared.tabs}>
          {(
            [
              ["dashboard", "Dashboard"],
              ["register", "Claims Register"],
              ["form", claimId ? "Edit Claim" : "New Claim"],
              ["reminders", "Follow-up Reminders"],
              ["reports", "Reports"],
            ] as const
          ).map(([kk, lbl]) => (
            <Pressable
              key={kk}
              onPress={() => {
                if (kk === "form" && tab !== "form" && !claimId) resetForm();
                setTab(kk);
              }}
              style={[shared.tab, tab === kk && shared.tabActive]}
              testID={`cl-tab-${kk}`}
            >
              <Text style={[shared.tabTxt, tab === kk && shared.tabTxtActive]}>
                {lbl}
              </Text>
            </Pressable>
          ))}
        </View>

        {!isCompanyAdmin && tab !== "form" && (
          <View style={[shared.row, { marginBottom: 8 }]}>
            <WebSelect
              testID="cl-company-filter"
              value={fCompany}
              onChange={setFCompany}
              width={280}
              options={[
                { value: "", label: "All Companies" },
                ...(companies || []).map((c: any) => ({
                  value: c.company_id,
                  label: c.name,
                })),
                { value: "external", label: "🌐 External Companies" },
              ]}
            />
          </View>
        )}

        {loading && <ActivityIndicator style={{ marginVertical: 24 }} />}

        {/* ------------------------- DASHBOARD ------------------------- */}
        {!loading && tab === "dashboard" && dash && (
          <>
            <View style={st.scoreRow}>
              {(
                [
                  ["PF Claims", dash.total_pf, colors.brandPrimary],
                  ["ESIC Claims", dash.total_esic, "#0E7490"],
                  ["Pending", dash.pending, "#B45309"],
                  ["Approved", dash.approved, "#15803D"],
                  ["Rejected", dash.rejected, "#B91C1C"],
                  ["Settled", dash.settled, "#166534"],
                ] as const
              ).map(([lbl, val, col]) => (
                <View key={lbl} style={st.scoreCard}>
                  <Text style={[st.scoreVal, { color: col }]}>{val}</Text>
                  <Text style={st.scoreLbl}>{lbl}</Text>
                </View>
              ))}
            </View>
            <View style={st.scoreRow}>
              <View style={st.scoreCard}>
                <Text style={st.scoreVal}>
                  ₹{Number(dash.claim_amount || 0).toLocaleString("en-IN")}
                </Text>
                <Text style={st.scoreLbl}>Total Claim Amount</Text>
              </View>
              <View style={st.scoreCard}>
                <Text style={[st.scoreVal, { color: "#166534" }]}>
                  ₹{Number(dash.settlement_amount || 0).toLocaleString("en-IN")}
                </Text>
                <Text style={st.scoreLbl}>Settled Amount</Text>
              </View>
              <View style={st.scoreCard}>
                <Text style={st.scoreVal}>{dash.avg_processing_days}</Text>
                <Text style={st.scoreLbl}>Avg Processing Days</Text>
              </View>
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>⏰ Follow-ups Due</Text>
              <Text style={shared.meta}>
                Due today/overdue: {dash.due_today} · Next 7 days:{" "}
                {dash.due_week} · Next 30 days: {dash.due_month}
              </Text>
              <Pressable
                onPress={() => setTab("reminders")}
                style={st.linkBtn}
                testID="cl-goto-reminders"
              >
                <Text style={st.linkTxt}>Open Follow-up Reminders →</Text>
              </Pressable>
            </View>
          </>
        )}

        {/* --------------------- CLAIMS REGISTER ---------------------- */}
        {tab === "register" && (
          <>
            <View style={[shared.row, { flexWrap: "wrap", gap: 8 }]}>
              <View style={st.kindToggle}>
                {(["pf", "esic"] as const).map((k) => (
                  <Pressable
                    key={k}
                    onPress={() => {
                      setFKind(k);
                      setFStatus("");
                      setFType("");
                    }}
                    style={[st.kindBtn, fKind === k && st.kindBtnActive]}
                    testID={`cl-kind-${k}`}
                  >
                    <Text
                      style={[st.kindTxt, fKind === k && st.kindTxtActive]}
                    >
                      {k.toUpperCase()}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <WebSelect
                testID="cl-f-status"
                value={fStatus}
                onChange={setFStatus}
                width={160}
                options={[
                  { value: "", label: "All Statuses" },
                  ...fStatuses.map((s) => ({ value: s, label: s })),
                ]}
              />
              <WebSelect
                testID="cl-f-type"
                value={fType}
                onChange={setFType}
                width={230}
                options={[
                  { value: "", label: "All Claim Types" },
                  ...fTypes.map((t) => ({ value: t, label: t })),
                ]}
              />
              <TextInput
                style={[shared.input, { maxWidth: 220, minWidth: 160 }]}
                value={fQ}
                onChangeText={setFQ}
                placeholder="Search name / code / claim no."
                onSubmitEditing={() => void loadClaims()}
                testID="cl-f-q"
              />
              <Pressable
                onPress={() => void loadClaims()}
                style={st.searchBtn}
                testID="cl-f-go"
              >
                <Ionicons name="search" size={16} color="#fff" />
              </Pressable>
            </View>

            {!loading && claims.length === 0 && (
              <Text style={[shared.meta, { marginTop: 16 }]}>
                No {fKind.toUpperCase()} claims found. Use the New Claim tab
                to file one.
              </Text>
            )}
            {!loading &&
              claims.map((c) => {
                const d = c.data || {};
                const open = expanded === c.claim_id;
                const compName =
                  c.company_id === "external"
                    ? `🌐 ${d.company_name || "External"}`
                    : (companies || []).find(
                        (x: any) => x.company_id === c.company_id,
                      )?.name || c.company_id;
                return (
                  <View key={c.claim_id} style={st.claimCard}>
                    <Pressable
                      onPress={() => setExpanded(open ? "" : c.claim_id)}
                      testID={`cl-row-${c.claim_no}`}
                    >
                      <View style={st.claimTop}>
                        <Text style={st.claimNo}>{c.claim_no}</Text>
                        <View
                          style={[
                            st.badge,
                            {
                              backgroundColor:
                                (STATUS_COLORS[c.status] || "#64748B") + "22",
                            },
                          ]}
                        >
                          <Text
                            style={[
                              st.badgeTxt,
                              { color: STATUS_COLORS[c.status] || "#64748B" },
                            ]}
                          >
                            {c.status}
                          </Text>
                        </View>
                      </View>
                      <Text style={st.claimName}>
                        {d.employee_name || "—"}{" "}
                        {d.employee_code ? `(${d.employee_code})` : ""}
                      </Text>
                      <Text style={shared.meta}>
                        {d.claim_type} · {compName} · ₹
                        {Number(d.claim_amount || 0).toLocaleString("en-IN")}
                      </Text>
                      <View style={st.claimMetaRow}>
                        <Text style={st.docScore}>
                          📄 Docs {c.doc_score ?? 0}%
                        </Text>
                        {!!c.expected_settlement &&
                          c.status !== "Settled" &&
                          c.status !== "Rejected" && (
                            <Text style={st.expSettle}>
                              🤖 Expected settlement: {c.expected_settlement}
                            </Text>
                          )}
                        {(c.ai_flags || []).length > 0 && (
                          <Text style={st.aiCount}>
                            ⚠ {(c.ai_flags || []).length} AI alert(s)
                          </Text>
                        )}
                      </View>
                    </Pressable>
                    {open && (
                      <View style={st.detail}>
                        {(c.ai_flags || []).length > 0 && (
                          <View style={st.aiBox}>
                            {(c.ai_flags || []).map((f: string, i: number) => (
                              <Text key={i} style={st.aiFlag}>
                                ⚠ {f}
                              </Text>
                            ))}
                          </View>
                        )}
                        <Text style={st.detailH}>Timeline</Text>
                        {(c.timeline || []).map((t: any, i: number) => (
                          <Text key={i} style={st.tlLine}>
                            • {String(t.at).slice(0, 16).replace("T", " ")} —{" "}
                            <Text style={{ fontWeight: "700" }}>
                              {t.status}
                            </Text>{" "}
                            by {t.by}
                            {t.note ? ` · ${t.note}` : ""}
                          </Text>
                        ))}
                        <Text style={st.detailH}>Documents</Text>
                        <Text style={shared.meta}>
                          {Object.entries(c.documents || {})
                            .filter(([, v]) => v)
                            .map(([k]) => `✓ ${k}`)
                            .join(" · ") || "None marked received"}
                        </Text>
                        <View style={st.actRow}>
                          <Pressable
                            onPress={() => editClaim(c)}
                            style={st.editBtn}
                            testID={`cl-edit-${c.claim_no}`}
                          >
                            <Ionicons
                              name="create-outline"
                              size={15}
                              color="#fff"
                            />
                            <Text style={st.editTxt}>Edit / Update Status</Text>
                          </Pressable>
                          <Pressable
                            onPress={() => del(c.claim_id)}
                            style={st.delBtn}
                            testID={`cl-del-${c.claim_no}`}
                          >
                            <Ionicons
                              name="trash-outline"
                              size={15}
                              color="#B91C1C"
                            />
                          </Pressable>
                        </View>
                      </View>
                    )}
                  </View>
                );
              })}
          </>
        )}

        {/* ------------------------ CLAIM FORM ------------------------- */}
        {tab === "form" && (
          <View style={shared.card}>
            <View style={st.claimTop}>
              <Text style={shared.cardTitle}>
                {claimId ? "Edit Claim" : "File New Claim"}
              </Text>
              {!!claimId && (
                <Pressable onPress={() => resetForm(cKind)} testID="cl-new">
                  <Text style={st.linkTxt}>+ New Claim</Text>
                </Pressable>
              )}
            </View>
            <View style={[st.kindToggle, { marginBottom: 10 }]}>
              {(["pf", "esic"] as const).map((k) => (
                <Pressable
                  key={k}
                  onPress={() => {
                    if (!claimId) {
                      setCKind(k);
                      setCType("");
                      setDocs({});
                    }
                  }}
                  style={[st.kindBtn, cKind === k && st.kindBtnActive]}
                  testID={`cl-form-kind-${k}`}
                >
                  <Text style={[st.kindTxt, cKind === k && st.kindTxtActive]}>
                    {k === "pf" ? "PF Claim" : "ESIC Claim"}
                  </Text>
                </Pressable>
              ))}
            </View>

            <View style={st.formWrap}>
              {!isCompanyAdmin && (
                <View style={st.formField}>
                  <Text style={st.formLbl}>Company</Text>
                  <WebSelect
                    testID="cl-form-company"
                    value={cCompany}
                    onChange={setCCompany}
                    width={320}
                    options={companyOpts}
                  />
                </View>
              )}
              {cCompany === "external" && (
                <View style={st.formField}>
                  <Text style={st.formLbl}>External Company Name *</Text>
                  <TextInput
                    style={shared.input}
                    value={form.company_name || ""}
                    onChangeText={(t) =>
                      setForm((p) => ({ ...p, company_name: t }))
                    }
                    placeholder="e.g. XYZ Industries Pvt Ltd"
                    testID="cl-f-company_name"
                  />
                </View>
              )}
              <View style={st.formField}>
                <Text style={st.formLbl}>Claim Type *</Text>
                <WebSelect
                  testID="cl-form-type"
                  value={cType}
                  onChange={setCType}
                  width={320}
                  options={[
                    { value: "", label: "— Select Claim Type —" },
                    ...types.map((t) => ({ value: t, label: t })),
                  ]}
                />
              </View>
              <View style={st.formField}>
                <Text style={st.formLbl}>Status</Text>
                <WebSelect
                  testID="cl-form-status"
                  value={cStatus}
                  onChange={setCStatus}
                  width={200}
                  options={statuses.map((s) => ({ value: s, label: s }))}
                />
              </View>
              <View style={st.formField}>
                <Text style={st.formLbl}>
                  {cKind === "pf" ? "UAN Number" : "ESIC IP Number"}
                </Text>
                <TextInput
                  style={shared.input}
                  value={form[cKind === "pf" ? "uan" : "insurance_no"] || ""}
                  onChangeText={(t) =>
                    setForm((p) => ({
                      ...p,
                      [cKind === "pf" ? "uan" : "insurance_no"]: t,
                    }))
                  }
                  placeholder={cKind === "pf" ? "12-digit UAN" : "IP Number"}
                  testID="cl-f-idno"
                />
              </View>
              {FIELDS.map(([k, lbl]) => (
                <View key={k} style={st.formField}>
                  <Text style={st.formLbl}>{lbl}</Text>
                  <TextInput
                    style={shared.input}
                    value={form[k] || ""}
                    onChangeText={(t) => setForm((p) => ({ ...p, [k]: t }))}
                    placeholder={
                      /date|doj|dol/.test(k) ? "YYYY-MM-DD" : lbl
                    }
                    testID={`cl-f-${k}`}
                  />
                </View>
              ))}
            </View>

            <Text style={[st.detailH, { marginTop: 12 }]}>
              📄 Document Checklist ({cKind.toUpperCase()})
            </Text>
            <View style={st.docWrap}>
              {checklist.map((d) => (
                <Pressable
                  key={d}
                  onPress={() => setDocs((p) => ({ ...p, [d]: !p[d] }))}
                  style={[st.docChip, docs[d] && st.docChipOn]}
                  testID={`cl-doc-${d}`}
                >
                  <Ionicons
                    name={docs[d] ? "checkbox" : "square-outline"}
                    size={15}
                    color={docs[d] ? "#15803D" : "#94A3B8"}
                  />
                  <Text style={[st.docTxt, docs[d] && { color: "#15803D" }]}>
                    {d}
                  </Text>
                </Pressable>
              ))}
            </View>

            <Pressable
              onPress={save}
              disabled={saving}
              style={st.saveBtn}
              testID="cl-save"
            >
              {saving ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <Text style={st.saveTxt}>
                  {claimId ? "Update Claim" : "Save Claim"}
                </Text>
              )}
            </Pressable>
            {!!msg && (
              <Text
                style={[
                  shared.meta,
                  { marginTop: 8 },
                  msg.startsWith("✓") && { color: "#15803D" },
                ]}
                testID="cl-msg"
              >
                {msg}
              </Text>
            )}

            {aiResult && (
              <View style={st.aiPanel}>
                <Text style={st.detailH}>🤖 Smart AI Analysis</Text>
                <Text style={shared.meta}>
                  Document Completeness Score:{" "}
                  <Text
                    style={{
                      fontWeight: "800",
                      color:
                        (aiResult.doc_score || 0) >= 80
                          ? "#15803D"
                          : "#B45309",
                    }}
                  >
                    {aiResult.doc_score ?? 0}%
                  </Text>
                </Text>
                {!!aiResult.expected_settlement && (
                  <Text style={shared.meta}>
                    Expected Settlement Date:{" "}
                    <Text style={{ fontWeight: "800" }}>
                      {aiResult.expected_settlement}
                    </Text>
                  </Text>
                )}
                {(aiResult.ai_flags || []).length === 0 ? (
                  <Text style={[shared.meta, { color: "#15803D" }]}>
                    ✓ No eligibility or duplicate issues detected
                  </Text>
                ) : (
                  (aiResult.ai_flags || []).map((f: string, i: number) => (
                    <Text key={i} style={st.aiFlag}>
                      ⚠ {f}
                    </Text>
                  ))
                )}
              </View>
            )}
          </View>
        )}

        {/* ------------------------- REMINDERS ------------------------- */}
        {!loading && tab === "reminders" && (
          <View style={shared.card}>
            <Text style={shared.cardTitle}>
              ⏰ Follow-ups Due ({reminders.length})
            </Text>
            {reminders.length === 0 && (
              <Text style={shared.meta}>
                No follow-ups due today. Open claims get an automatic +7 day
                follow-up date.
              </Text>
            )}
            {reminders.map((r, i) => (
              <View key={i} style={st.remRow}>
                <View style={{ flex: 1 }}>
                  <Text style={st.claimName}>
                    {r.claim_no} — {r.employee_name || "—"}
                  </Text>
                  <Text style={shared.meta}>
                    {r.claim_type} · {r.status} · due {r.follow_up_date}
                    {r.executive ? ` · ${r.executive}` : ""}
                  </Text>
                </View>
                <Text style={st.docScore}>📄 {r.doc_score ?? 0}%</Text>
              </View>
            ))}
          </View>
        )}

        {/* -------------------------- REPORTS -------------------------- */}
        {tab === "reports" && (
          <>
            <View style={shared.row}>
              <WebSelect
                testID="cl-report-kind"
                value={reportKind}
                onChange={setReportKind}
                width={260}
                options={REPORTS.map(([v, l]) => ({ value: v, label: l }))}
              />
            </View>
            {!loading && reportData && (
              <View style={[shared.card, { marginTop: 10 }]}>
                <Text style={shared.cardTitle}>{reportData.title}</Text>
                <RegisterTable
                  columns={reportData.columns}
                  rows={reportData.rows}
                  totals={reportData.totals}
                />
              </View>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  scoreRow: { flexDirection: "row", gap: 8, marginBottom: 10, flexWrap: "wrap" },
  scoreCard: {
    flexGrow: 1,
    minWidth: 110,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    alignItems: "center",
  },
  scoreVal: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  scoreLbl: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 3 },
  linkBtn: { marginTop: 8 },
  linkTxt: { color: colors.brandPrimary, fontWeight: "700", fontSize: 12.5 },
  kindToggle: {
    flexDirection: "row",
    backgroundColor: "#F1F5F9",
    borderRadius: 8,
    padding: 3,
  },
  kindBtn: { paddingHorizontal: 16, paddingVertical: 7, borderRadius: 6 },
  kindBtnActive: { backgroundColor: colors.brandPrimary },
  kindTxt: { fontSize: 12.5, fontWeight: "700", color: "#64748B" },
  kindTxtActive: { color: "#fff" },
  searchBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: 8,
    padding: 9,
    justifyContent: "center",
  },
  claimCard: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    marginTop: 10,
  },
  claimTop: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  claimNo: { fontSize: 12, fontWeight: "800", color: colors.brandPrimary },
  badge: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3 },
  badgeTxt: { fontSize: 10.5, fontWeight: "800" },
  claimName: {
    fontSize: 13.5,
    fontWeight: "700",
    color: colors.onSurface,
    marginTop: 3,
  },
  claimMetaRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
    marginTop: 5,
  },
  docScore: { fontSize: 11, fontWeight: "700", color: "#0E7490" },
  expSettle: { fontSize: 11, color: "#7C3AED", fontWeight: "600" },
  aiCount: { fontSize: 11, color: "#B45309", fontWeight: "700" },
  detail: {
    marginTop: 10,
    borderTopWidth: 0.5,
    borderTopColor: colors.border,
    paddingTop: 8,
  },
  detailH: {
    fontSize: 12,
    fontWeight: "800",
    color: colors.onSurface,
    marginTop: 6,
    marginBottom: 3,
  },
  tlLine: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginBottom: 2 },
  aiBox: {
    backgroundColor: "#FFFBEB",
    borderRadius: 8,
    padding: 8,
    borderWidth: 1,
    borderColor: "#FDE68A",
  },
  aiFlag: { fontSize: 11.5, color: "#B45309", marginBottom: 3 },
  actRow: { flexDirection: "row", gap: 10, marginTop: 10, alignItems: "center" },
  editBtn: {
    flexDirection: "row",
    gap: 5,
    alignItems: "center",
    backgroundColor: colors.brandPrimary,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  editTxt: { color: "#fff", fontWeight: "700", fontSize: 12 },
  delBtn: {
    borderWidth: 1,
    borderColor: "#FECACA",
    borderRadius: 8,
    padding: 7,
  },
  formWrap: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  formField: { minWidth: 200, flexGrow: 1, maxWidth: 320 },
  formLbl: { fontSize: 11.5, color: colors.onSurfaceSecondary, marginBottom: 3 },
  docWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 4 },
  docChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 9,
    paddingVertical: 6,
  },
  docChipOn: { borderColor: "#86EFAC", backgroundColor: "#F0FDF4" },
  docTxt: { fontSize: 11.5, color: "#64748B" },
  saveBtn: {
    marginTop: 14,
    backgroundColor: colors.brandPrimary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    maxWidth: 220,
  },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  aiPanel: {
    marginTop: 12,
    backgroundColor: "#F8FAFC",
    borderRadius: 10,
    padding: 10,
    borderWidth: 1,
    borderColor: colors.border,
  },
  remRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border,
  },
});
