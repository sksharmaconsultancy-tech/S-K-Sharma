/**
 * Iter 300 — Legacy Import Wizard.
 *
 * 1) Map old firms → portal firms (tick which to import)
 * 2) Head-wise selection (employee field groups + online/offline salary)
 * 3) Preview counts → Start Import → live progress → summary
 */
import React, { useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Stack } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const FIELD_GROUPS: { key: string; label: string }[] = [
  { key: "personal", label: "Personal (Name, F/H Name, DOB, DOJ, Type, Desig.)" },
  { key: "contact", label: "Contact (Mobile, Email, Address)" },
  { key: "ids", label: "IDs (PAN, Aadhaar, UAN, PF No, ESIC No)" },
  { key: "bank", label: "Bank (A/c, IFSC, Bank name)" },
  { key: "salary", label: "Salary heads (Basic, PF Basic, Gross, Allowances)" },
  { key: "status", label: "Status (Resign / Left date)" },
];

// Iter 300e (user) — every portal field an old head can be re-pointed to.
const PORTAL_FIELDS: { key: string; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "father_name", label: "Father / Husband Name" },
  { key: "gender", label: "Gender" },
  { key: "dob", label: "Date of Birth" },
  { key: "doj", label: "Date of Joining" },
  { key: "marital_status", label: "Marital Status" },
  { key: "designation", label: "Designation" },
  { key: "department", label: "Department" },
  { key: "employee_type", label: "Employee Type / Group" },
  { key: "salary_mode", label: "Salary Mode (Daily/Monthly)" },
  { key: "phone", label: "Mobile Number" },
  { key: "email", label: "Email" },
  { key: "present_address", label: "Present Address" },
  { key: "permanent_address", label: "Permanent Address" },
  { key: "pincode", label: "Pincode" },
  { key: "pan_no", label: "PAN Number" },
  { key: "aadhaar_no", label: "Aadhaar Number" },
  { key: "uan_no", label: "UAN Number" },
  { key: "pf_no", label: "PF Number" },
  { key: "esi_ip_no", label: "ESIC IP Number" },
  { key: "bank_name", label: "Bank Name" },
  { key: "bank_account", label: "Bank Account No" },
  { key: "bank_ifsc", label: "IFSC Code" },
  { key: "account_holder", label: "Account Holder Name" },
  { key: "basic_salary", label: "Basic Salary (Online)" },
  { key: "compliance_basic", label: "Compliance Basic" },
  { key: "pf_basic", label: "PF Basic" },
  { key: "compliance_gross", label: "Compliance Gross" },
  { key: "salary_monthly", label: "Actual / Offline Salary" },
  { key: "resign_date", label: "Resign Date" },
  { key: "exit_date", label: "Exit Date" },
];
const fldLabel = (k: string) =>
  k === "skip" ? "⛔ SKIP — do not import" : (PORTAL_FIELDS.find((f) => f.key === k)?.label || k);

// Old head → default portal field (editable per row before import).
const HEAD_MAP: { legacy: string; field: string; group: string }[] = [
  { legacy: "EmpName", field: "name", group: "personal" },
  { legacy: "EmpFatherName", field: "father_name", group: "personal" },
  { legacy: "Gender", field: "gender", group: "personal" },
  { legacy: "DOB", field: "dob", group: "personal" },
  { legacy: "DOJ / NewDOJ", field: "doj", group: "personal" },
  { legacy: "MaritalStatus", field: "marital_status", group: "personal" },
  { legacy: "Designation", field: "designation", group: "personal" },
  { legacy: "Department", field: "department", group: "personal" },
  { legacy: "EmpType", field: "employee_type", group: "personal" },
  { legacy: "PayBasis (Daily/Monthly)", field: "salary_mode", group: "personal" },
  { legacy: "PersMobileNo / PermMobileNo", field: "phone", group: "contact" },
  { legacy: "Email", field: "email", group: "contact" },
  { legacy: "PresentAdd", field: "present_address", group: "contact" },
  { legacy: "PermanentAdd", field: "permanent_address", group: "contact" },
  { legacy: "PinCode", field: "pincode", group: "contact" },
  { legacy: "PANNo", field: "pan_no", group: "ids" },
  { legacy: "AadharCardNo", field: "aadhaar_no", group: "ids" },
  { legacy: "UANNo", field: "uan_no", group: "ids" },
  { legacy: "PFNumber", field: "pf_no", group: "ids" },
  { legacy: "ESINo", field: "esi_ip_no", group: "ids" },
  { legacy: "BankName", field: "bank_name", group: "bank" },
  { legacy: "AccountNo", field: "bank_account", group: "bank" },
  { legacy: "IFSCCode", field: "bank_ifsc", group: "bank" },
  { legacy: "NameOnBankAc", field: "account_holder", group: "bank" },
  { legacy: "BasicSalary", field: "basic_salary", group: "salary" },
  { legacy: "PFBasicSalary", field: "pf_basic", group: "salary" },
  { legacy: "GrossPay", field: "compliance_gross", group: "salary" },
  { legacy: "Salary (rate)", field: "salary_monthly", group: "salary" },
  { legacy: "IsResign + ResignDate", field: "resign_date", group: "status" },
];

export default function LegacyImportScreen() {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [firms, setFirms] = useState<any[]>([]);
  const [portalFirms, setPortalFirms] = useState<any[]>([]);
  const [sel, setSel] = useState<Record<number, string>>({});   // firm_no -> company_id
  const [pickFor, setPickFor] = useState<number | null>(null);  // modal
  const [groups, setGroups] = useState<string[]>(FIELD_GROUPS.map((g) => g.key));
  const [impEmp, setImpEmp] = useState(true);
  const [impOn, setImpOn] = useState(true);
  const [impOff, setImpOff] = useState(true);
  const [preview, setPreview] = useState<any[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [job, setJob] = useState<any>(null);
  const [showMap, setShowMap] = useState(false); // mapping chart
  // Iter 300e (user) — manual head overrides + 2-step confirmation.
  const [overrides, setOverrides] = useState<Record<string, string>>({}); // src field -> dst field | 'skip'
  const [editHead, setEditHead] = useState<string | null>(null);          // field being remapped
  const [confirmStep, setConfirmStep] = useState(0);                      // 0 hidden, 1, 2

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/admin/legacy-import/firms");
        setFirms(r.firms || []);
        setPortalFirms(r.portal_firms || []);
      } catch (e: any) {
        setErr(e?.message || "Legacy server not reachable — run the setup first.");
      } finally { setLoading(false); }
    })();
  }, []);

  const body = () => ({
    mappings: Object.entries(sel).map(([fn, cid]) => ({ firm_no: Number(fn), company_id: cid })),
    import_employees: impEmp,
    employee_fields: groups,
    salary_online: impOn,
    salary_offline: impOff,
    field_overrides: overrides,
  });

  const runPreview = async () => {
    setBusy(true); setErr(""); setPreview(null);
    try {
      const r = await api<any>("/admin/legacy-import/preview", { method: "POST", body: JSON.stringify(body()) });
      setPreview(r.firms || []);
    } catch (e: any) { setErr(e?.message || "Preview failed"); }
    finally { setBusy(false); }
  };

  const startImport = async () => {
    setBusy(true); setErr("");
    try {
      const r = await api<any>("/admin/legacy-import/run", { method: "POST", body: JSON.stringify(body()) });
      pollJob(r.job_id);
    } catch (e: any) { setErr(e?.message || "Import failed to start"); setBusy(false); }
  };

  const pollJob = async (id: string) => {
    try {
      const j = await api<any>(`/admin/legacy-import/jobs/${id}`);
      setJob(j);
      if (j.status === "done" || j.status === "failed") { setBusy(false); return; }
    } catch { /* keep polling */ }
    setTimeout(() => pollJob(id), 2500);
  };

  const mappedCount = Object.keys(sel).length;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <Stack.Screen options={{ title: "Legacy Import Wizard" }} />
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 80 }}>
        <Text style={st.h1}>Legacy Import Wizard</Text>
        <Text style={st.sub}>
          Choose the firms, tick the heads you want, preview, then import.
          Nothing is written until you press Start Import.
        </Text>
        {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} /> : (
          <>
            {/* STEP 1 — firm mapping */}
            <View style={st.card}>
              <Text style={st.cardTitle}>1️⃣  Select old firms &amp; map to portal firms ({mappedCount} selected)</Text>
              {firms.map((f) => {
                const cid = sel[f.firm_no];
                const pname = portalFirms.find((p) => p.company_id === cid)?.name;
                if (f.already_imported) {
                  return (
                    <View key={f.firm_no} style={[st.firmRow, { opacity: 0.75 }]}>
                      <Ionicons name="checkmark-circle" size={20} color="#16a34a" />
                      <View style={{ flex: 1, minWidth: 0 }}>
                        <Text style={st.firmName} numberOfLines={1}>{f.firm_name}</Text>
                        <Text style={[st.firmMeta, { color: "#16a34a", fontWeight: "700" }]} numberOfLines={1}>
                          ✓ ALREADY IMPORTED{f.imported_into ? ` → ${f.imported_into}` : ""}
                          {f.imported_at ? ` · ${String(f.imported_at).slice(0, 10)}` : ""}
                        </Text>
                      </View>
                    </View>
                  );
                }
                return (
                  <View key={f.firm_no} style={st.firmRow}>
                    <Pressable
                      onPress={() => {
                        const c = { ...sel };
                        if (cid) delete c[f.firm_no];
                        else c[f.firm_no] = f.suggested_company_id || "";
                        if (c[f.firm_no] === "") { setPickFor(f.firm_no); }
                        setSel(c);
                      }}
                      hitSlop={8}
                    >
                      <Ionicons
                        name={cid !== undefined ? "checkbox" : "square-outline"}
                        size={20}
                        color={cid !== undefined ? colors.brandPrimary : colors.onSurfaceTertiary}
                      />
                    </Pressable>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text style={st.firmName} numberOfLines={1}>{f.firm_name}</Text>
                      <Text style={st.firmMeta} numberOfLines={1}>
                        {f.employees} emp · online {f.online_months} mo · offline {f.offline_months} mo
                      </Text>
                    </View>
                    {cid !== undefined ? (
                      <Pressable style={st.mapBtn} onPress={() => setPickFor(f.firm_no)}>
                        <Text style={st.mapBtnTxt} numberOfLines={1}>
                          {pname || "→ choose portal firm"}
                        </Text>
                        <Ionicons name="chevron-down" size={12} color={colors.brandPrimary} />
                      </Pressable>
                    ) : null}
                  </View>
                );
              })}
            </View>

            {/* STEP 2 — head-wise selection */}
            <View style={st.card}>
              <Text style={st.cardTitle}>2️⃣  What to import (tick the heads)</Text>
              <Pressable style={st.tickRow} onPress={() => setImpEmp(!impEmp)}>
                <Ionicons name={impEmp ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Employee Master</Text>
              </Pressable>
              {impEmp ? FIELD_GROUPS.map((g) => (
                <Pressable
                  key={g.key}
                  style={[st.tickRow, { paddingLeft: 28 }]}
                  onPress={() => setGroups(groups.includes(g.key)
                    ? groups.filter((x) => x !== g.key) : [...groups, g.key])}
                >
                  <Ionicons
                    name={groups.includes(g.key) ? "checkbox" : "square-outline"}
                    size={17} color={groups.includes(g.key) ? colors.brandPrimary : colors.onSurfaceTertiary}
                  />
                  <Text style={st.tickTxt}>{g.label}</Text>
                </Pressable>
              )) : null}
              <Pressable style={st.tickRow} onPress={() => setImpOn(!impOn)}>
                <Ionicons name={impOn ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Salary History — ONLINE (PF/ESIC salary, head-wise)</Text>
              </Pressable>
              <Pressable style={st.tickRow} onPress={() => setImpOff(!impOff)}>
                <Ionicons name={impOff ? "checkbox" : "square-outline"} size={19} color={colors.brandPrimary} />
                <Text style={st.tickMain}>Salary History — OFFLINE (actual salary)</Text>
              </Pressable>

              {/* Iter 300e (user) — editable head mapping + override */}
              <Pressable style={[st.tickRow, { marginTop: 6 }]} onPress={() => setShowMap(!showMap)}>
                <Ionicons name={showMap ? "chevron-down" : "chevron-forward"} size={16} color={colors.brandPrimary} />
                <Text style={[st.tickMain, { color: colors.brandPrimary }]}>
                  📖 Head Mapping — verify &amp; change where each old head settles
                </Text>
              </Pressable>
              {showMap ? (
                <View style={st.mapBox}>
                  <Text style={st.mapHint}>
                    Tap any row to change its target head, or set SKIP to not import it.
                  </Text>
                  {["personal", "contact", "ids", "bank", "salary", "status"]
                    .filter((g) => groups.includes(g))
                    .map((g) => (
                      <View key={g}>
                        <Text style={st.mapHead}>
                          {FIELD_GROUPS.find((x) => x.key === g)?.label || g}
                        </Text>
                        {HEAD_MAP.filter((h) => h.group === g).map((h) => {
                          const target = overrides[h.field] ?? h.field;
                          const changed = overrides[h.field] !== undefined && overrides[h.field] !== h.field;
                          return (
                            <Pressable key={h.field} style={st.mapRow} onPress={() => setEditHead(h.field)}>
                              <Text style={st.mapOld} numberOfLines={2}>{h.legacy}</Text>
                              <Ionicons name="arrow-forward" size={11} color={colors.onSurfaceTertiary} />
                              <View style={{ flex: 1.2, flexDirection: "row", alignItems: "center", gap: 4 }}>
                                <Text
                                  style={[
                                    st.mapNew,
                                    changed && (target === "skip" ? { color: "#DC2626" } : { color: "#B45309" }),
                                  ]}
                                  numberOfLines={2}
                                >
                                  {fldLabel(target)}
                                </Text>
                                {changed ? (
                                  <View style={[st.chgBadge, target === "skip" && { backgroundColor: "#FEE2E2" }]}>
                                    <Text style={[st.chgBadgeTxt, target === "skip" && { color: "#DC2626" }]}>
                                      {target === "skip" ? "SKIPPED" : "CHANGED"}
                                    </Text>
                                  </View>
                                ) : null}
                                <Ionicons name="create-outline" size={13} color={colors.brandPrimary} />
                              </View>
                            </Pressable>
                          );
                        })}
                      </View>
                    ))}
                  <Text style={st.mapHead}>SALARY HISTORY → &apos;Legacy Salary Records&apos; screen (archive — live payroll untouched)</Text>
                  <View style={st.mapRow}>
                    <Text style={st.mapOld}>SalaryTrans (Online)</Text>
                    <Ionicons name="arrow-forward" size={11} color={colors.onSurfaceTertiary} />
                    <Text style={st.mapNew}>Online tab: Days, Basic, every Earn/Deduct head with its old name, EPF, ESI, Net</Text>
                  </View>
                  <View style={st.mapRow}>
                    <Text style={st.mapOld}>SalaryTransoff (Offline)</Text>
                    <Ionicons name="arrow-forward" size={11} color={colors.onSurfaceTertiary} />
                    <Text style={st.mapNew}>Offline tab: Days, Rate, W.Basic, Others, TDS, Less EPF/ESI/Adv, Net</Text>
                  </View>
                  {Object.keys(overrides).length ? (
                    <Pressable style={st.resetBtn} onPress={() => setOverrides({})}>
                      <Ionicons name="refresh" size={13} color="#DC2626" />
                      <Text style={{ color: "#DC2626", fontSize: 11.5, fontWeight: "700" }}>
                        Reset all {Object.keys(overrides).length} change(s) to default
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
              ) : null}
            </View>

            {/* STEP 3 — preview & run */}
            <View style={st.card}>
              <Text style={st.cardTitle}>3️⃣  Preview &amp; Import</Text>
              <Pressable
                style={[st.actBtn, { backgroundColor: colors.brandPrimary, opacity: mappedCount && !busy ? 1 : 0.5 }]}
                disabled={!mappedCount || busy}
                onPress={runPreview}
              >
                <Ionicons name="eye-outline" size={16} color="#fff" />
                <Text style={st.actTxt}>Preview (nothing is saved)</Text>
              </Pressable>
              {preview ? preview.map((p) => (
                <View key={p.firm_no} style={st.prevRow}>
                  <Text style={st.firmName}>→ {p.company_name}</Text>
                  <Text style={st.firmMeta}>
                    {impEmp ? `Employees: ${p.employees_new ?? 0} new + ${p.employees_existing ?? 0} update · ` : ""}
                    {impOn ? `Online: ${p.online_rows ?? 0} rows / ${p.online_months ?? 0} months · ` : ""}
                    {impOff ? `Offline: ${p.offline_rows ?? 0} rows / ${p.offline_months ?? 0} months` : ""}
                  </Text>
                </View>
              )) : null}
              {preview ? (
                <Pressable
                  style={[st.actBtn, { backgroundColor: "#B45309", opacity: busy ? 0.5 : 1 }]}
                  disabled={busy}
                  onPress={() => setConfirmStep(1)}
                >
                  <Ionicons name="download-outline" size={16} color="#fff" />
                  <Text style={st.actTxt}>Start Import</Text>
                </Pressable>
              ) : null}
              {job ? (
                <View style={st.prevRow}>
                  <Text style={st.firmName}>
                    {job.status === "done" ? "✅ Import complete" :
                      job.status === "failed" ? "❌ Import failed" : "⏳ Importing…"}
                  </Text>
                  <Text style={st.firmMeta}>
                    Employees: {job.totals?.employees_created || 0} created, {job.totals?.employees_updated || 0} updated ·
                    Online rows: {job.totals?.online_rows || 0} · Offline rows: {job.totals?.offline_rows || 0}
                  </Text>
                  {(job.errors || []).slice(0, 5).map((e: string, i: number) => (
                    <Text key={i} style={st.errTxt}>{e}</Text>
                  ))}
                  {job.status === "done" ? (
                    <Text style={st.firmMeta}>
                      View imported salary: Import / Export → Legacy Salary Records
                    </Text>
                  ) : null}
                </View>
              ) : null}
            </View>
          </>
        )}
        {err ? <Text style={st.errTxt}>{err}</Text> : null}
      </ScrollView>

      {/* portal firm picker */}
      <Modal transparent visible={pickFor !== null} animationType="fade" onRequestClose={() => setPickFor(null)}>
        <Pressable style={st.backdrop} onPress={() => setPickFor(null)} />
        <View style={st.pickSheet}>
          <Text style={st.cardTitle}>Import into which portal firm?</Text>
          <ScrollView style={{ maxHeight: 400 }}>
            {portalFirms.map((p) => (
              <Pressable
                key={p.company_id}
                style={st.pickRow}
                onPress={() => {
                  if (pickFor !== null) setSel({ ...sel, [pickFor]: p.company_id });
                  setPickFor(null);
                }}
              >
                <Ionicons name="business-outline" size={15} color={colors.brandPrimary} />
                <Text style={st.tickTxt}>{p.name}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>
      {/* Iter 300e (user) — head remap picker */}
      <Modal transparent visible={editHead !== null} animationType="fade" onRequestClose={() => setEditHead(null)}>
        <Pressable style={st.backdrop} onPress={() => setEditHead(null)} />
        <View style={st.pickSheet}>
          <Text style={st.cardTitle}>
            Where should &quot;{HEAD_MAP.find((h) => h.field === editHead)?.legacy || editHead}&quot; go?
          </Text>
          <ScrollView style={{ maxHeight: 420 }}>
            <Pressable
              style={st.pickRow}
              onPress={() => {
                if (editHead) {
                  const c = { ...overrides };
                  delete c[editHead];
                  setOverrides(c);
                }
                setEditHead(null);
              }}
            >
              <Ionicons name="refresh-outline" size={15} color={colors.brandPrimary} />
              <Text style={[st.tickTxt, { fontWeight: "700" }]}>
                Default — {fldLabel(editHead || "")}
              </Text>
            </Pressable>
            <Pressable
              style={st.pickRow}
              onPress={() => {
                if (editHead) setOverrides({ ...overrides, [editHead]: "skip" });
                setEditHead(null);
              }}
            >
              <Ionicons name="close-circle-outline" size={15} color="#DC2626" />
              <Text style={[st.tickTxt, { color: "#DC2626", fontWeight: "700" }]}>
                SKIP — do not import this head
              </Text>
            </Pressable>
            {PORTAL_FIELDS.filter((p) => p.key !== editHead).map((p) => (
              <Pressable
                key={p.key}
                style={st.pickRow}
                onPress={() => {
                  if (editHead) setOverrides({ ...overrides, [editHead]: p.key });
                  setEditHead(null);
                }}
              >
                <Ionicons
                  name={overrides[editHead || ""] === p.key ? "radio-button-on" : "radio-button-off"}
                  size={15}
                  color={overrides[editHead || ""] === p.key ? colors.brandPrimary : colors.onSurfaceTertiary}
                />
                <Text style={st.tickTxt}>{p.label}</Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>
      </Modal>

      {/* Iter 300e (user) — 2-step confirmation before writing anything */}
      <Modal transparent visible={confirmStep > 0} animationType="fade" onRequestClose={() => setConfirmStep(0)}>
        <Pressable style={st.backdrop} onPress={() => setConfirmStep(0)} />
        <View style={st.pickSheet}>
          {confirmStep === 1 ? (
            <>
              <Text style={st.confTitle}>⚠️ Confirmation 1 of 2 — Verify Head Mapping</Text>
              <Text style={st.confTxt}>
                {mappedCount} firm(s) selected.
                {impEmp ? ` Employee Master (${groups.length} head groups).` : ""}
                {impOn ? " Online salary history." : ""}
                {impOff ? " Offline salary history." : ""}
              </Text>
              {Object.keys(overrides).length ? (
                <View style={st.confBox}>
                  <Text style={[st.confTxt, { fontWeight: "800", color: "#B45309" }]}>
                    You changed {Object.keys(overrides).length} head(s):
                  </Text>
                  {Object.entries(overrides).map(([src, dst]) => (
                    <Text key={src} style={st.confTxt}>
                      • {HEAD_MAP.find((h) => h.field === src)?.legacy || src} → {fldLabel(dst)}
                    </Text>
                  ))}
                </View>
              ) : (
                <Text style={[st.confTxt, { color: "#16a34a", fontWeight: "700" }]}>
                  All heads are on the DEFAULT mapping (see Head Mapping chart above).
                </Text>
              )}
              <Text style={st.confTxt}>
                If any head would settle in the wrong place, press Cancel and change it in the
                Head Mapping chart first.
              </Text>
              <Pressable style={[st.actBtn, { backgroundColor: colors.brandPrimary }]} onPress={() => setConfirmStep(2)}>
                <Ionicons name="checkmark" size={16} color="#fff" />
                <Text style={st.actTxt}>Mapping is correct — Continue (1/2)</Text>
              </Pressable>
              <Pressable style={st.cancelBtn} onPress={() => setConfirmStep(0)}>
                <Text style={st.cancelTxt}>Cancel — let me check the mapping</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Text style={st.confTitle}>🔴 Final Confirmation 2 of 2</Text>
              <Text style={st.confTxt}>
                Data will now be WRITTEN into the live portal database for {mappedCount} firm(s).
                Imported firms are locked and cannot be imported again.
              </Text>
              <Text style={[st.confTxt, { fontWeight: "800" }]}>Are you sure you want to start the import?</Text>
              <Pressable
                style={[st.actBtn, { backgroundColor: "#B45309" }]}
                onPress={() => { setConfirmStep(0); startImport(); }}
              >
                <Ionicons name="download-outline" size={16} color="#fff" />
                <Text style={st.actTxt}>YES — Start Import Now (2/2)</Text>
              </Pressable>
              <Pressable style={st.cancelBtn} onPress={() => setConfirmStep(1)}>
                <Text style={st.cancelTxt}>← Back</Text>
              </Pressable>
            </>
          )}
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    marginTop: spacing.md, borderWidth: 1, borderColor: colors.border,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface, marginBottom: 6 },
  firmRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  firmName: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  firmMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  mapBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, maxWidth: 220,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 5,
  },
  mapBtnTxt: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  tickRow: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 7 },
  tickMain: { fontSize: 13, fontWeight: "700", color: colors.onSurface },
  tickTxt: { fontSize: 12.5, color: colors.onSurface, flex: 1 },
  actBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    borderRadius: radius.md, paddingVertical: 12, marginTop: 10,
  },
  actTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  prevRow: { paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  errTxt: { color: "#DC2626", fontSize: 12, marginTop: 8 },
  mapBox: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 10, marginTop: 4, backgroundColor: colors.surfaceSecondary,
  },
  mapHead: { fontSize: 11.5, fontWeight: "800", color: colors.brandPrimary, marginTop: 8, marginBottom: 2 },
  mapHint: { fontSize: 11, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  chgBadge: {
    backgroundColor: "#FEF3C7", borderRadius: 4, paddingHorizontal: 4, paddingVertical: 1,
  },
  chgBadgeTxt: { fontSize: 8.5, fontWeight: "800", color: "#B45309" },
  resetBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, marginTop: 10,
    alignSelf: "flex-start", paddingVertical: 4,
  },
  confTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  confTxt: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 4, lineHeight: 18 },
  confBox: {
    borderWidth: 1, borderColor: "#FCD34D", backgroundColor: "#FFFBEB",
    borderRadius: radius.md, padding: 10, marginTop: 8,
  },
  cancelBtn: { alignItems: "center", paddingVertical: 12, marginTop: 4 },
  cancelTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  mapRow: { flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 3 },
  mapOld: { flex: 1, fontSize: 11, color: colors.onSurfaceSecondary },
  mapNew: { flex: 1.2, fontSize: 11, fontWeight: "700", color: colors.onSurface },
  backdrop: { position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.45)" },
  pickSheet: {
    position: "absolute", left: 20, right: 20, top: "15%",
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
  },
  pickRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
});
