/**
 * Employee Add/Master form model — extracted from app/employee-add.tsx
 * during modularization. Pure types, constants and date helpers only
 * (no UI) so both the Add screen and future editors can share them.
 */
export type SalaryLine = { head: string; amount: string };

export type EmpForm = {
  employee_code: string;
  bio_code: string;
  name: string;
  phone: string;
  email: string;
  father_name: string;
  gender: string;
  dob: string;
  doj: string;
  blood_group: string;
  marital_status: string;
  spouse_name: string;
  designation: string;
  department: string;
  employee_type: string;
  employee_group: string;
  is_onroll: boolean;
  shift_id: string;
  ot_applicable: boolean;
  salary_mode: string;
  salary_monthly: string;
  compliance_gross: string;
  // Iter 126g — Compliance Basic + PF Basic (EPF ceiling rule).
  compliance_basic: string;
  pf_basic: string;
  // Iter 126i — VPF (Voluntary PF) — extra employee-side PF deduction.
  vpf_enabled: boolean;
  vpf_amount: string;
  // Iter 94 — SEPARATE rate basis for the Compliance salary part.
  compliance_salary_mode: string;
  // Iter 91 — fixed structure (same as Employee Master Salary Update):
  // Basic + rate basis and Salary 1/2/3 tiers with working days.
  basic_salary: string;
  sal1_amount: string; sal1_days: string;
  sal2_amount: string; sal2_days: string;
  sal3_amount: string; sal3_days: string;
  // Iter 71 — per-employee allowance / deduction line-items, one set
  // for Actual payroll and one for Compliance/Statutory payroll.
  actual_allowances: SalaryLine[];
  actual_deductions: SalaryLine[];
  compliance_allowances: SalaryLine[];
  compliance_deductions: SalaryLine[];
  permanent_address: string;
  pincode: string;
  district: string;
  state: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  family_members: { name: string; relation: string; dob: string }[];
  uan_no: string;
  pf_no: string;
  esi_ip_no: string;
  pan_no: string;
  pan_name: string;
  aadhaar_no: string;
  bank_name: string;
  pay_mode: string;
  bank_account: string;
  bank_ifsc: string;
  upi_id: string;
  address: string;
};

// Iter 189 — enterprise desktop shell section tabs (anchor navigation).
export const SECTION_TABS = [
  { id: "sec-identity", label: "Personal", icon: "person-circle-outline" },
  { id: "sec-employment", label: "Employment", icon: "briefcase-outline" },
  { id: "sec-actual-salary", label: "Salary", icon: "cash-outline" },
  { id: "sec-compliance", label: "Compliance", icon: "shield-half-outline" },
  { id: "sec-statutory", label: "Statutory & Bank", icon: "shield-checkmark-outline" },
  { id: "sec-family", label: "Family", icon: "people-outline" },
];

export const EMPTY_FORM: EmpForm = {
  employee_code: "",
  bio_code: "",
  name: "",
  phone: "",
  email: "",
  father_name: "",
  gender: "",
  dob: "",
  doj: "",
  blood_group: "",
  marital_status: "",
  spouse_name: "",
  designation: "",
  department: "",
  employee_type: "",
  employee_group: "",
  is_onroll: true,
  shift_id: "",
  ot_applicable: true,
  salary_mode: "monthly",
  salary_monthly: "",
  compliance_gross: "",
  compliance_basic: "",
  pf_basic: "",
  vpf_enabled: false,
  vpf_amount: "",
  compliance_salary_mode: "monthly",
  basic_salary: "",
  sal1_amount: "", sal1_days: "",
  sal2_amount: "", sal2_days: "",
  sal3_amount: "", sal3_days: "",
  actual_allowances: [],
  actual_deductions: [],
  compliance_allowances: [],
  compliance_deductions: [],
  uan_no: "",
  pf_no: "",
  esi_ip_no: "",
  pan_no: "",
  pan_name: "",
  aadhaar_no: "",
  bank_name: "",
  pay_mode: "Bank",
  bank_account: "",
  bank_ifsc: "",
  upi_id: "",
  address: "",
  permanent_address: "",
  pincode: "",
  district: "",
  state: "",
  emergency_contact_name: "",
  emergency_contact_phone: "",
  family_members: [],
};

export function ddmmyyyyDashToISO(v: string | undefined): string | null {
  if (!v) return null;
  const m = v.match(/^(\d{2})-(\d{2})-(\d{4})$/);
  if (!m) return null;
  return `${m[3]}-${m[2]}-${m[1]}`;
}

/** Iter 158 — ISO YYYY-MM-DD (from the calendar picker) -> DD-MM-YYYY. */
export function isoToDDMMDash(iso: string): string {
  const m = (iso || "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? `${m[3]}-${m[2]}-${m[1]}` : "";
}

/** Iter 113 — map any OCR/legacy gender text onto the strict options. */
export function normGender(v: string): string {
  const s = (v || "").trim().toLowerCase();
  if (s.startsWith("m")) return "Male";
  if (s.startsWith("f")) return "Female";
  if (s.startsWith("t") || s.includes("trans") || s.startsWith("o")) return "Transgender";
  return "";
}
