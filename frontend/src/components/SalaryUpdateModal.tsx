/**
 * Iter 89 — Salary Update Modal for the Employee Master screen.
 *
 * Opened from a "Salary" button on each employee row. Loads both the
 * ACTUAL structure (what the employee gets) and the COMPLIANCE
 * structure (what appears on statutory registers), lets the admin edit
 * either or both, and saves via PATCH /admin/employees/{user_id}/salary.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Modal, Pressable, TextInput, ScrollView,
  ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";
import MasterSelect from "@/src/components/MasterSelect";


type Row = { head: string; amount: number; rate_type?: string; working_days?: number };
// Editable row — amount kept as a STRING while typing so decimals like
// "1500.00" or ".50" can be entered freely; parsed on save.
type ERow = { head: string; amount: string };
type Payload = {
  user_id: string;
  name: string;
  employee_code: string;
  company_id?: string | null;
  employee_type?: string | null;
  salary_monthly: number;
  salary_structure_actual: Row[];
  salary_structure_compliance: Row[];
  actual_salary_allowances?: Row[];
  actual_salary_deductions?: Row[];
  compliance_basic?: number;
  compliance_gross?: number;
  compliance_salary_allowances?: Row[];
  compliance_salary_mode?: string | null;
  firm_allowance_heads?: string[];
  firm_deduction_heads?: string[];
  salary_updated_at?: string | null;
  salary_updated_by?: string | null;
  history?: any[];
};

const RATE_OPTIONS = ["Monthly", "Daily", "Hourly"] as const;
type RateType = "monthly" | "daily" | "hourly";

// Statutory employer-contribution policy (matches payroll engine):
//   PF  Employer = 12%   × Basic (compliance)
//   ESI Employer = 3.25% × Gross (compliance, only when gross ≤ ₹21,000)
const PF_EMPLOYER_RATE = 0.12;
const ESI_EMPLOYER_RATE = 0.0325;
const ESI_GROSS_CEILING = 21000;

const round2 = (v: number) => Math.round(v * 100) / 100;
// Keep only digits and a single decimal point while typing.
const cleanNum = (v: string) => {
  const s = v.replace(/[^0-9.]/g, "");
  const i = s.indexOf(".");
  return i === -1 ? s : s.slice(0, i + 1) + s.slice(i + 1).replace(/\./g, "");
};


export default function SalaryUpdateModal({
  visible, userId, onClose, onSaved,
}: {
  visible: boolean;
  userId: string | null;
  onClose: () => void;
  onSaved?: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [data, setData] = useState<Payload | null>(null);
  const [monthly, setMonthly] = useState("");
  // Iter 91 — Employee Type / Group editable right inside Update Salary.
  const [empType, setEmpType] = useState("");
  const [origEmpType, setOrigEmpType] = useState("");
  // Actual structure — fixed layout
  const [basicAmount, setBasicAmount] = useState("0");
  const [basicRate, setBasicRate] = useState<RateType>("monthly");
  const [rateMenuOpen, setRateMenuOpen] = useState(false);
  // Iter 94 — SEPARATE rate basis for the Compliance salary (user request:
  // "Salary Rate Basis for Both Salary Options Required Separately").
  const [complRate, setComplRate] = useState<RateType>("monthly");
  const [complRateMenuOpen, setComplRateMenuOpen] = useState(false);
  const [sal, setSal] = useState<{ amount: string; days: string }[]>([
    { amount: "0", days: "0" }, { amount: "0", days: "0" }, { amount: "0", days: "0" },
  ]);
  // Allowances / Deductions — heads linked from Firm Master (amounts only)
  const [allowances, setAllowances] = useState<ERow[]>([]);
  const [deductions, setDeductions] = useState<ERow[]>([]);
  // Iter 137 (user directive) — Compliance salary LINKED to the Employee
  // Master fields: Basic (compliance_basic) + firm-head allowance lines
  // (compliance_salary_allowances). Same heads as the Add/Edit form.
  const [complBasic, setComplBasic] = useState("0");
  const [complAllow, setComplAllow] = useState<ERow[]>([]);
  const [notes, setNotes] = useState("");

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const r = await api<Payload>(`/admin/employees/${userId}/salary`);
      setData(r);
      setMonthly(String(r.salary_monthly || 0));
      setEmpType(r.employee_type || "");
      setOrigEmpType(r.employee_type || "");

      const rows = r.salary_structure_actual || [];
      const basic = rows.find((x) => /basic/i.test(x.head || ""));
      setBasicAmount(String(basic?.amount ?? 0));
      setBasicRate(((basic?.rate_type as RateType) || "monthly"));
      setSal([1, 2, 3].map((i) => {
        const row = rows.find((x) =>
          new RegExp(`^salary\\s*${i}$`, "i").test((x.head || "").trim()),
        );
        return { amount: String(row?.amount ?? 0), days: String(row?.working_days ?? 0) };
      }));

      // Firm-Master-linked heads: show every ENABLED head; carry over any
      // previously saved amount (matched by head, case-insensitive).
      const savedAllow = r.actual_salary_allowances || [];
      setAllowances((r.firm_allowance_heads || []).map((h) => ({
        head: h,
        amount: String(
          savedAllow.find((a) => (a.head || "").toLowerCase() === h.toLowerCase())?.amount || 0,
        ),
      })));
      const savedDed = r.actual_salary_deductions || [];
      setDeductions((r.firm_deduction_heads || []).map((h) => ({
        head: h,
        amount: String(
          savedDed.find((d) => (d.head || "").toLowerCase() === h.toLowerCase())?.amount || 0,
        ),
      })));

      // Iter 137 — Compliance values come from the Employee Master fields;
      // legacy salary_structure_compliance rows are used as a fallback so
      // older records still pre-fill correctly.
      const structRows = r.salary_structure_compliance || [];
      const structBasic = structRows.find((x) => /^basic/i.test((x.head || "").trim()));
      setComplBasic(String(r.compliance_basic || structBasic?.amount || 0));
      const savedCompl = r.compliance_salary_allowances || [];
      setComplAllow((r.firm_allowance_heads || []).map((h) => ({
        head: h,
        amount: String(
          savedCompl.find((a) => (a.head || "").toLowerCase() === h.toLowerCase())?.amount
          ?? structRows.find((a) => (a.head || "").toLowerCase() === h.toLowerCase())?.amount
          ?? 0,
        ),
      })));
      setComplRate(
        ((r.compliance_salary_mode as RateType)
          || (structBasic as any)?.rate_type
          || "monthly") as RateType,
      );
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Failed to load salary");
    } finally { setLoading(false); }
  }, [userId]);

  useEffect(() => { if (visible) load(); }, [visible, load]);

  const monthlyNum = Number(monthly || 0);
  const basicNum = Number(basicAmount || 0);
  const totalActual = basicNum + sal.reduce((s, r) => s + Number(r.amount || 0), 0);
  const totalAllow = allowances.reduce((s, r) => s + Number(r.amount || 0), 0);
  const totalDed = deductions.reduce((s, r) => s + Number(r.amount || 0), 0);

  // ── Compliance (Iter 137 — linked to Employee Master fields) ──
  // Gross = Basic + Σ allowance lines; PF/ESI employer auto per policy.
  const complBasicNum = Number(complBasic || 0);
  const complAllowTotal = complAllow.reduce((s, x) => s + Number(x.amount || 0), 0);
  const complGross = complBasicNum + complAllowTotal;
  const pfEmployerAuto = round2(PF_EMPLOYER_RATE * complBasicNum);
  const esiEmployerAuto =
    complGross > 0 && complGross <= ESI_GROSS_CEILING
      ? round2(ESI_EMPLOYER_RATE * complGross)
      : 0;

  const editRow = (set: any, arr: ERow[], idx: number, patch: Partial<ERow>) => {
    const next = [...arr];
    next[idx] = { ...next[idx], ...patch };
    set(next);
  };
  const editSal = (idx: number, patch: Partial<{ amount: string; days: string }>) => {
    setSal((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], ...patch };
      return next;
    });
  };

  const submit = async () => {
    if (!userId) return;
    setSaving(true);
    try {
      const r = await api<{ warnings: string[] }>(
        `/admin/employees/${userId}/salary`,
        {
          method: "PATCH",
          body: {
            salary_monthly: monthlyNum,
            salary_structure_actual: [
              { head: "Basic", amount: basicNum, rate_type: basicRate },
              ...sal.map((s, i) => ({
                head: `Salary ${i + 1}`,
                amount: Number(s.amount) || 0,
                working_days: Number(s.days) || 0,
              })),
            ],
            actual_salary_allowances: allowances.map(({ head, amount }) => ({
              head, amount: Number(amount) || 0,
            })),
            actual_salary_deductions: deductions.map(({ head, amount }) => ({
              head, amount: Number(amount) || 0,
            })),
            // Iter 137 — Compliance saved via the LINKED Employee-Master
            // fields; the backend rebuilds salary_structure_compliance +
            // Compliance Gross (= Basic + allowances) from these.
            compliance_basic: complBasicNum,
            compliance_salary_allowances: complAllow.map(({ head, amount }) => ({
              head, amount: Number(amount) || 0,
            })),
            compliance_salary_mode: complRate,
            notes: notes.trim() || undefined,
          },
        },
      );
      let msg = "Salary updated ✓";
      if (r.warnings?.length) msg += `\n\nWarnings:\n${r.warnings.join("\n")}`;
      // Iter 91 — persist Employee Type / Group change alongside salary.
      if (empType.trim() !== origEmpType.trim()) {
        try {
          await api("/admin/user-role", {
            method: "PATCH",
            body: { user_id: userId, employee_type: empType.trim() || null },
          });
          msg += "\nEmployee Type / Group updated ✓";
        } catch (e: any) {
          msg += `\nEmployee Type update failed: ${e?.message || "error"}`;
        }
      }
      if (Platform.OS === "web") window.alert(msg);
      onSaved?.();
      onClose();
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Save failed");
    } finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.head}>
            <View style={{ flex: 1 }}>
              <Text style={styles.title}>Update Employee Salary</Text>
              {data ? (
                <Text style={styles.subtitle}>
                  {data.name || "—"} · {data.employee_code || "—"}
                </Text>
              ) : null}
            </View>
            <Pressable onPress={onClose} hitSlop={10}>
              <Ionicons name="close" size={22} color={colors.onSurface} />
            </Pressable>
          </View>

          {loading || !data ? (
            <ActivityIndicator style={{ margin: 40 }} color={colors.brandPrimary} />
          ) : (
            <ScrollView contentContainerStyle={{ padding: spacing.md, gap: spacing.md }}>
              {/* ================= PART A — EMPLOYEE ACTUAL SALARY ======= */}
              <View style={styles.partHead}>
                <Ionicons name="cash" size={15} color={colors.brandPrimary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.partHeadTxt}>EMPLOYEE ACTUAL SALARY</Text>
                  <Text style={styles.partHeadSub}>What the employee actually receives</Text>
                </View>
              </View>

              {/* Monthly gross */}
              <View style={styles.row}>
                <Text style={styles.lbl}>Monthly Gross Salary (₹)</Text>
                <TextInput
                  value={monthly}
                  onChangeText={setMonthly}
                  keyboardType="numeric"
                  style={styles.input}
                  placeholder="e.g. 25000"
                />
              </View>

              {/* Iter 91 — Employee Type / Group editable here too */}
              <MasterSelect
                label="Employee Type / Group"
                masterType="group"
                companyId={data.company_id}
                value={empType}
                onChange={setEmpType}
                placeholder="Select employee type / group…"
                testID="sum-emp-type"
              />

              {/* Actual structure — fixed layout */}
              <View style={[styles.structBlock, { zIndex: 30 }]}>
                <View style={styles.structHead}>
                  <Ionicons name="cash-outline" size={16} color={colors.brandPrimary} />
                  <Text style={styles.structTitle}>Actual Salary Structure</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={[styles.totalTxt,
                    Math.abs(totalActual - monthlyNum) < 1 && monthlyNum > 0
                      ? { color: colors.success } : { color: colors.warning }]}>
                    Total ₹{totalActual.toLocaleString()}
                  </Text>
                </View>

                {/* Basic Salary + rate-type dropdown */}
                <View style={[styles.rowInline, { zIndex: 40 }]}>
                  <Text style={[styles.fixedHead, { flex: 1.4 }]}>Basic Salary</Text>
                  <TextInput
                    value={basicAmount}
                    onChangeText={(v) => setBasicAmount(cleanNum(v))}
                    keyboardType="numeric"
                    placeholder="0"
                    style={[styles.input, { flex: 1 }]}
                    testID="salary-basic-amount"
                  />
                  <View style={{ position: "relative", zIndex: 50 }}>
                    <Pressable
                      style={styles.dropBtn}
                      onPress={() => setRateMenuOpen((o) => !o)}
                      testID="salary-basic-rate"
                    >
                      <Text style={styles.dropBtnTxt}>
                        {basicRate.charAt(0).toUpperCase() + basicRate.slice(1)}
                      </Text>
                      <Ionicons
                        name={rateMenuOpen ? "chevron-up" : "chevron-down"}
                        size={13}
                        color={colors.onSurfaceSecondary}
                      />
                    </Pressable>
                    {rateMenuOpen ? (
                      <View style={styles.dropMenu}>
                        {RATE_OPTIONS.map((opt) => {
                          const val = opt.toLowerCase() as RateType;
                          return (
                            <Pressable
                              key={opt}
                              style={styles.dropItem}
                              onPress={() => { setBasicRate(val); setRateMenuOpen(false); }}
                              testID={`salary-rate-${val}`}
                            >
                              <Text style={[
                                styles.dropItemTxt,
                                basicRate === val && { color: colors.brandPrimary, fontWeight: "800" },
                              ]}>
                                {opt}
                              </Text>
                            </Pressable>
                          );
                        })}
                      </View>
                    ) : null}
                  </View>
                </View>

                {/* Salary 1 / 2 / 3 with working days */}
                <View style={styles.rowInline}>
                  <View style={{ flex: 1.4 }} />
                  <Text style={[styles.colLbl, { flex: 1 }]}>Amount (₹)</Text>
                  <Text style={[styles.colLbl, { width: 96 }]}>Working Days</Text>
                </View>
                {sal.map((s, i) => (
                  <View key={i} style={styles.rowInline}>
                    <Text style={[styles.fixedHead, { flex: 1.4 }]}>Salary {i + 1}</Text>
                    <TextInput
                      value={s.amount}
                      onChangeText={(v) => editSal(i, { amount: cleanNum(v) })}
                      keyboardType="numeric"
                      placeholder="0"
                      style={[styles.input, { flex: 1 }]}
                      testID={`salary-${i + 1}-amount`}
                    />
                    <TextInput
                      value={s.days}
                      onChangeText={(v) => editSal(i, { days: v })}
                      keyboardType="numeric"
                      placeholder="0"
                      style={[styles.input, { width: 96 }]}
                      testID={`salary-${i + 1}-days`}
                    />
                  </View>
                ))}
              </View>

              {/* Allowances — heads linked from Firm Master */}
              <View style={styles.structBlock}>
                <View style={styles.structHead}>
                  <Ionicons name="add-circle-outline" size={16} color={colors.success} />
                  <Text style={styles.structTitle}>Allowances</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={[styles.totalTxt, { color: colors.success }]}>
                    + ₹{totalAllow.toLocaleString()}
                  </Text>
                </View>
                {allowances.length === 0 ? (
                  <Text style={styles.emptyHint}>
                    No allowances enabled for this firm — enable heads in Firm Master → Allowances.
                  </Text>
                ) : allowances.map((r, idx) => (
                  <View key={r.head} style={styles.rowInline}>
                    <Text style={[styles.fixedHead, { flex: 1.4 }]}>{r.head}</Text>
                    <TextInput
                      value={r.amount}
                      onChangeText={(v) => editRow(setAllowances, allowances, idx, { amount: cleanNum(v) })}
                      keyboardType="numeric"
                      placeholder="0.00"
                      style={[styles.input, { flex: 1 }]}
                      testID={`allowance-${idx}`}
                    />
                  </View>
                ))}
              </View>

              {/* Deductions — heads linked from Firm Master */}
              <View style={styles.structBlock}>
                <View style={styles.structHead}>
                  <Ionicons name="remove-circle-outline" size={16} color={colors.error} />
                  <Text style={styles.structTitle}>Deductions</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={[styles.totalTxt, { color: colors.error }]}>
                    − ₹{totalDed.toLocaleString()}
                  </Text>
                </View>
                {deductions.length === 0 ? (
                  <Text style={styles.emptyHint}>
                    No deductions enabled for this firm — enable heads in Firm Master → Deductions.
                  </Text>
                ) : deductions.map((r, idx) => (
                  <View key={r.head} style={styles.rowInline}>
                    <Text style={[styles.fixedHead, { flex: 1.4 }]}>{r.head}</Text>
                    <TextInput
                      value={r.amount}
                      onChangeText={(v) => editRow(setDeductions, deductions, idx, { amount: cleanNum(v) })}
                      keyboardType="numeric"
                      placeholder="0.00"
                      style={[styles.input, { flex: 1 }]}
                      testID={`deduction-${idx}`}
                    />
                  </View>
                ))}
              </View>

              {/* ============ PART B — COMPLIANCE SALARY (SEPARATE) ====== */}
              <View style={styles.partDivider} />
              <View style={[styles.partHead, { borderLeftColor: "#B45309" }]}>
                <Ionicons name="shield-checkmark" size={15} color="#B45309" />
                <View style={{ flex: 1 }}>
                  <Text style={[styles.partHeadTxt, { color: "#B45309" }]}>
                    COMPLIANCE SALARY (PF / ESI / TDS)
                  </Text>
                  <Text style={styles.partHeadSub}>
                    Statutory registers only — kept SEPARATE from Actual salary
                  </Text>
                </View>
              </View>

              {/* Compliance structure */}
              <View style={[styles.structBlock, styles.complBlock, { zIndex: 20 }]}>
                <View style={styles.structHead}>
                  <Ionicons name="shield-checkmark-outline" size={16} color={colors.brandPrimary} />
                  <Text style={styles.structTitle}>Compliance Salary — linked to Employee Master</Text>
                  <View style={{ flex: 1 }} />
                  <Text style={[styles.totalTxt, { color: colors.brandPrimary }]}>
                    Gross ₹{complGross.toLocaleString()}
                  </Text>
                </View>

                {/* Iter 94 — SEPARATE rate basis for compliance salary */}
                <View style={[styles.rowInline, { zIndex: 60 }]}>
                  <Text style={[styles.fixedHead, { flex: 1.4 }]}>Rate Basis (Compliance)</Text>
                  <View style={{ position: "relative", zIndex: 70, flex: 1 }}>
                    <Pressable
                      style={styles.dropBtn}
                      onPress={() => setComplRateMenuOpen((o) => !o)}
                      testID="compliance-basic-rate"
                    >
                      <Text style={styles.dropBtnTxt}>
                        {complRate.charAt(0).toUpperCase() + complRate.slice(1)}
                      </Text>
                      <Ionicons
                        name={complRateMenuOpen ? "chevron-up" : "chevron-down"}
                        size={13}
                        color={colors.onSurfaceSecondary}
                      />
                    </Pressable>
                    {complRateMenuOpen ? (
                      <View style={styles.dropMenu}>
                        {RATE_OPTIONS.map((opt) => {
                          const val = opt.toLowerCase() as RateType;
                          return (
                            <Pressable
                              key={opt}
                              style={styles.dropItem}
                              onPress={() => { setComplRate(val); setComplRateMenuOpen(false); }}
                              testID={`compliance-rate-${val}`}
                            >
                              <Text style={[
                                styles.dropItemTxt,
                                complRate === val && { color: colors.brandPrimary, fontWeight: "800" },
                              ]}>
                                {opt}
                              </Text>
                            </Pressable>
                          );
                        })}
                      </View>
                    ) : null}
                  </View>
                  <View style={{ width: 16 }} />
                </View>
                {/* Iter 137 — Employee Basic (Compliance) — same field as
                    the Employee Master form (compliance_basic). */}
                <View style={styles.rowInline}>
                  <Text style={[styles.fixedHead, { flex: 1.4 }]}>Employee Basic (Compliance)</Text>
                  <TextInput
                    value={complBasic}
                    onChangeText={(v) => setComplBasic(cleanNum(v))}
                    keyboardType="numeric"
                    placeholder="0"
                    style={[styles.input, { flex: 1 }]}
                    testID="compliance-basic-amount"
                  />
                  <View style={{ width: 16 }} />
                </View>

                {/* Allowance heads — SAME heads as Firm Master / Employee
                    Master (HRA, CONV., etc.). */}
                {complAllow.length === 0 ? (
                  <Text style={styles.emptyHint}>
                    No allowances enabled for this firm — enable heads in Firm Master → Allowances.
                  </Text>
                ) : complAllow.map((r, idx) => (
                  <View key={r.head} style={styles.rowInline}>
                    <Text style={[styles.fixedHead, { flex: 1.4 }]}>{r.head}</Text>
                    <TextInput
                      value={r.amount}
                      onChangeText={(v) => editRow(setComplAllow, complAllow, idx, { amount: cleanNum(v) })}
                      keyboardType="numeric"
                      placeholder="0"
                      style={[styles.input, { flex: 1 }]}
                      testID={`compliance-allowance-${idx}`}
                    />
                    <View style={{ width: 16 }} />
                  </View>
                ))}

                {/* Totals + auto employer contributions */}
                <View style={styles.rowInline}>
                  <Text style={[styles.fixedHead, { flex: 1.4 }]}>Total Allowances</Text>
                  <View style={[styles.input, styles.autoAmount, { flex: 1 }]}>
                    <Text style={styles.autoAmountTxt}>{complAllowTotal.toLocaleString()}</Text>
                    <View style={styles.autoBadge}><Text style={styles.autoBadgeTxt}>AUTO</Text></View>
                  </View>
                  <View style={{ width: 16 }} />
                </View>
                <View style={styles.rowInline}>
                  <Text style={[styles.fixedHead, { flex: 1.4 }]}>Compliance Gross (Basic + Allowances)</Text>
                  <View style={[styles.input, styles.autoAmount, { flex: 1 }]}>
                    <Text style={styles.autoAmountTxt}>{complGross.toLocaleString()}</Text>
                    <View style={styles.autoBadge}><Text style={styles.autoBadgeTxt}>AUTO</Text></View>
                  </View>
                  <View style={{ width: 16 }} />
                </View>
                <View style={styles.rowInline}>
                  <Text style={[styles.fixedHead, { flex: 1.4 }]}>PF Employer (12% × Basic)</Text>
                  <View style={[styles.input, styles.autoAmount, { flex: 1 }]}>
                    <Text style={styles.autoAmountTxt}>{pfEmployerAuto.toFixed(2)}</Text>
                    <View style={styles.autoBadge}><Text style={styles.autoBadgeTxt}>AUTO</Text></View>
                  </View>
                  <View style={{ width: 16 }} />
                </View>
                <View style={styles.rowInline}>
                  <Text style={[styles.fixedHead, { flex: 1.4 }]}>ESI Employer (3.25% × Gross)</Text>
                  <View style={[styles.input, styles.autoAmount, { flex: 1 }]}>
                    <Text style={styles.autoAmountTxt}>{esiEmployerAuto.toFixed(2)}</Text>
                    <View style={styles.autoBadge}><Text style={styles.autoBadgeTxt}>AUTO</Text></View>
                  </View>
                  <View style={{ width: 16 }} />
                </View>
                <Text style={styles.autoHint}>
                  Heads are linked from Firm Master → Allowances and saved on the Employee Master —
                  the Add/Edit form, this modal and Bulk Correction all edit the SAME values.
                  ESI Employer applies only when gross ≤ ₹21,000.
                </Text>
              </View>

              {/* Audit notes */}
              <View style={styles.row}>
                <Text style={styles.lbl}>Notes (optional — for audit trail)</Text>
                <TextInput
                  value={notes}
                  onChangeText={setNotes}
                  placeholder="e.g. Increment effective 1-Jul, or PF cap adjustment"
                  style={[styles.input, { minHeight: 48 }]}
                  multiline
                />
              </View>

              {/* Recent history */}
              {data.history && data.history.length > 0 ? (
                <View style={styles.historyBlock}>
                  <Text style={styles.historyTitle}>Recent Changes</Text>
                  {data.history.slice(0, 5).map((h, idx) => (
                    <View key={idx} style={styles.historyRow}>
                      <Text style={styles.historyTxt}>
                        {new Date(h.changed_at).toLocaleString()} — ₹{h.prev?.salary_monthly || 0} → ₹{h.next?.salary_monthly || 0}
                        {h.notes ? ` · ${h.notes}` : ""}
                      </Text>
                    </View>
                  ))}
                </View>
              ) : null}
            </ScrollView>
          )}

          <View style={styles.footer}>
            <Pressable onPress={onClose} style={styles.cancelBtn}>
              <Text style={styles.cancelBtnTxt}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={submit}
              disabled={saving || loading}
              style={({ pressed }) => [
                styles.saveBtn,
                (saving || loading) && { opacity: 0.5 },
                pressed && { opacity: 0.85 },
              ]}
              testID="salary-modal-save"
            >
              {saving ? <ActivityIndicator size="small" color="#FFF" /> : <Ionicons name="save-outline" size={16} color="#FFF" />}
              <Text style={styles.saveBtnTxt}>{saving ? "Saving..." : "Save Salary"}</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}


const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center", justifyContent: "center",
    padding: spacing.md,
  },
  sheet: {
    width: "100%", maxWidth: 720, maxHeight: "92%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    overflow: "hidden",
  },
  head: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  title: { ...type.h4, color: colors.onSurface },
  subtitle: { ...type.caption, color: colors.onSurfaceSecondary, marginTop: 2 },
  row: { gap: 4 },
  rowInline: { flexDirection: "row", gap: 8, alignItems: "center" },
  lbl: { ...type.label, color: colors.onSurfaceSecondary },
  input: {
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 8,
    backgroundColor: colors.surface, color: colors.onSurface,
    fontSize: 13, minHeight: 36,
  },
  structBlock: {
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.sm, gap: 6,
    backgroundColor: colors.surfaceSecondary,
  },
  // Iter 94 — compliance block visually separated from Actual salary
  complBlock: {
    borderColor: "#F0C987",
    backgroundColor: "#FFFBF3",
  },
  partHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    paddingHorizontal: 10,
    borderLeftWidth: 3,
    borderLeftColor: colors.brandPrimary,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.sm,
  },
  partHeadTxt: {
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 0.6,
    color: colors.brandPrimary,
  },
  partHeadSub: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 1 },
  partDivider: {
    height: 2,
    backgroundColor: colors.border,
    borderRadius: 2,
    marginVertical: 2,
  },
  structHead: { flexDirection: "row", alignItems: "center", gap: 6 },
  structTitle: { ...type.h6, color: colors.onSurface },
  totalTxt: { ...type.label, fontWeight: "800" },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingVertical: 4, paddingHorizontal: 8,
    alignSelf: "flex-start",
  },
  addBtnTxt: { ...type.label, color: colors.brandPrimary },
  fixedHead: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  colLbl: {
    fontSize: 10, color: colors.onSurfaceTertiary,
    fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.3,
  },
  emptyHint: {
    ...type.caption, color: colors.onSurfaceTertiary,
    paddingVertical: 6, fontStyle: "italic",
  },
  dropBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 8,
    minHeight: 36, minWidth: 96,
    backgroundColor: colors.surface,
    justifyContent: "space-between",
  },
  dropBtnTxt: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
  dropMenu: {
    position: "absolute", top: 38, left: 0, right: 0,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm,
    zIndex: 100, elevation: 8,
    shadowColor: "#000", shadowOpacity: 0.15,
    shadowRadius: 8, shadowOffset: { width: 0, height: 4 },
  },
  dropItem: { paddingHorizontal: 12, paddingVertical: 9 },
  dropItemTxt: { color: colors.onSurface, fontSize: 13 },
  autoAmount: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between",
    backgroundColor: colors.surfaceTertiary,
  },
  autoAmountTxt: { color: colors.onSurface, fontSize: 13, fontWeight: "700" },
  autoBadge: {
    backgroundColor: colors.brandTertiary,
    borderRadius: 4, paddingHorizontal: 5, paddingVertical: 1,
  },
  autoBadgeTxt: {
    fontSize: 8, fontWeight: "900",
    color: colors.brandPrimary, letterSpacing: 0.5,
  },
  autoHint: {
    ...type.caption, color: colors.onSurfaceTertiary,
    fontStyle: "italic", paddingTop: 2,
  },
  historyBlock: {
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm, padding: 8,
    backgroundColor: colors.surfaceTertiary,
  },
  historyTitle: { ...type.label, color: colors.onSurface, fontWeight: "700", marginBottom: 4 },
  historyRow: { paddingVertical: 2 },
  historyTxt: { ...type.caption, color: colors.onSurfaceSecondary },
  footer: {
    flexDirection: "row", gap: 8, justifyContent: "flex-end",
    padding: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.divider,
  },
  cancelBtn: {
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.pill,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  cancelBtnTxt: { color: colors.onSurface, fontWeight: "600", fontSize: 13 },
  saveBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.pill,
    backgroundColor: colors.brandPrimary,
  },
  saveBtnTxt: { color: colors.onBrandPrimary, fontWeight: "700", fontSize: 13 },
});
