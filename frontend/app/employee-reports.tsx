/**
 * Iter 292 (user request) — Employee Reports hub.
 *
 * One place for all per-employee report options:
 *   Pay Slip · Salary Certificate · Salary Register · Annual Salary
 *   Statement · Appointment Letter · Experience Letter · Relieving Letter
 *
 * Pay Slip and Annual Statement download inline (pick employee + period);
 * letters open the HR Letters generator pre-set to the right type; Salary
 * Register opens the Compliance Salary Run screen.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  ScrollView,
  Platform,
  Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import MonthPicker from "@/src/components/MonthPicker";
import { colors } from "@/src/theme";

type Card = {
  key: string; title: string; desc: string; icon: string;
  kind: "payslip" | "annual" | "route" | "letter";
  route?: string; letter?: string;
};

const CARDS: Card[] = [
  { key: "payslip", title: "Pay Slip", desc: "Monthly payslip PDF for one employee", icon: "receipt-outline", kind: "payslip" },
  { key: "salary_certificate", title: "Salary Certificate", desc: "Certificate of current salary (bank/visa)", icon: "cash-outline", kind: "letter", letter: "salary_certificate" },
  { key: "register", title: "Salary Register", desc: "Firm-wide monthly salary register", icon: "book-outline", kind: "route", route: "/compliance-salary-run" },
  { key: "annual", title: "Annual Salary Statement", desc: "Month-by-month FY statement (Excel)", icon: "bar-chart-outline", kind: "annual" },
  { key: "appointment", title: "Appointment Letter", desc: "Formal appointment on letterhead", icon: "document-text-outline", kind: "letter", letter: "appointment" },
  { key: "experience", title: "Experience Letter", desc: "Service & conduct certificate", icon: "ribbon-outline", kind: "letter", letter: "experience" },
  { key: "relieving", title: "Relieving Letter", desc: "Resignation acceptance & relieving", icon: "exit-outline", kind: "letter", letter: "relieving" },
];

const currentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const currentFy = () => {
  const d = new Date();
  return d.getMonth() + 1 >= 4 ? d.getFullYear() : d.getFullYear() - 1;
};

export default function EmployeeReportsHub() {
  const router = useRouter();
  const { user } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [cid, setCid] = useState("");
  const [modal, setModal] = useState<"payslip" | "annual" | null>(null);
  const [emps, setEmps] = useState<any[]>([]);
  const [empQ, setEmpQ] = useState("");
  const [selEmp, setSelEmp] = useState<any | null>(null);
  const [month, setMonth] = useState(currentMonth());
  const [fy, setFy] = useState(currentFy());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (user?.role === "company_admin") setCid(user.company_id || "");
    else if (selectedCompanyId && selectedCompanyId !== "all") setCid(selectedCompanyId);
  }, [user, selectedCompanyId]);

  const loadEmps = useCallback(async () => {
    if (!cid) return;
    try {
      const r = await api<{ employees: any[] }>(
        `/admin/company-staff/eligible-employees?company_id=${cid}`);
      setEmps(r.employees || []);
    } catch { setEmps([]); }
  }, [cid]);
  useEffect(() => { loadEmps(); }, [loadEmps]);

  const openCard = (c: Card) => {
    setErr("");
    if (c.kind === "route") { router.push(c.route as any); return; }
    if (c.kind === "letter") { router.push(`/hr-letters?type=${c.letter}` as any); return; }
    if (!cid) { setErr("Select a firm first."); return; }
    setSelEmp(null);
    setEmpQ("");
    setModal(c.kind);
  };

  const download = async () => {
    if (!selEmp) { setErr("Pick an employee."); return; }
    setBusy(true);
    setErr("");
    try {
      const path = modal === "payslip"
        ? `/admin/employee-payslip.pdf?company_id=${cid}&user_id=${selEmp.user_id}&month=${month}`
        : `/admin/annual-salary-statement.xlsx?company_id=${cid}&user_id=${selEmp.user_id}&fy=${fy}`;
      const r = await apiBinary(path);
      if (Platform.OS === "web" && r.webBlobUrl) {
        if (modal === "payslip") window.open(r.webBlobUrl, "_blank");
        else {
          const a = document.createElement("a");
          a.href = r.webBlobUrl;
          a.download = `annual-salary-${selEmp.employee_code}-FY${fy}.xlsx`;
          a.click();
        }
      }
      setModal(null);
    } catch (e: any) {
      setErr(e?.message || "Download failed");
    } finally { setBusy(false); }
  };

  const filteredEmps = useMemo(() => {
    const t = empQ.trim().toLowerCase();
    if (!t) return emps.slice(0, 50);
    return emps.filter((e) =>
      [e.name, e.employee_code, e.email].some((v) => String(v || "").toLowerCase().includes(t)),
    ).slice(0, 50);
  }, [emps, empQ]);

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.head}>
        <Pressable onPress={() => router.back()} hitSlop={10}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={s.title}>Employee Reports</Text>
        <View style={{ flex: 1 }} />
        {user?.role !== "company_admin" ? (
          <View style={{ minWidth: 220 }}>
            <CompanyPicker value={cid} onChange={(v: any) => setCid(!v || v === "all" ? "" : v)} />
          </View>
        ) : null}
      </View>
      <ScrollView contentContainerStyle={{ padding: 14, paddingBottom: 60 }}>
        {err ? <Text style={s.err}>{err}</Text> : null}
        <View style={s.grid}>
          {CARDS.map((c) => (
            <Pressable key={c.key} style={s.card} onPress={() => openCard(c)} testID={`emp-report-${c.key}`}>
              <View style={s.cardIcon}>
                <Ionicons name={c.icon as any} size={22} color={colors.brandPrimary} />
              </View>
              <Text style={s.cardTitle}>{c.title}</Text>
              <Text style={s.cardDesc}>{c.desc}</Text>
              <View style={s.cardGo}>
                <Ionicons name="chevron-forward" size={15} color={colors.onSurfaceTertiary} />
              </View>
            </Pressable>
          ))}
        </View>
      </ScrollView>

      {/* Employee + period picker for Pay Slip / Annual Statement */}
      <Modal visible={!!modal} transparent animationType="fade" onRequestClose={() => setModal(null)}>
        <View style={s.modalWrap}>
          <View style={s.modalCard}>
            <View style={s.modalHead}>
              <Text style={s.modalTitle}>
                {modal === "payslip" ? "Pay Slip" : "Annual Salary Statement"}
              </Text>
              <Pressable onPress={() => setModal(null)} hitSlop={10}>
                <Ionicons name="close" size={22} color={colors.onSurfaceSecondary} />
              </Pressable>
            </View>
            {modal === "payslip" ? (
              <MonthPicker value={month} onChange={setMonth} />
            ) : (
              <View style={s.fyRow}>
                {[fy - 1, fy, fy + 1].filter((y) => y <= currentFy()).map((y) => (
                  <Pressable key={y} style={[s.fyChip, fy === y && s.fyChipOn]} onPress={() => setFy(y)}>
                    <Text style={[s.fyTxt, fy === y && s.fyTxtOn]}>FY {y}-{String((y + 1) % 100).padStart(2, "0")}</Text>
                  </Pressable>
                ))}
              </View>
            )}
            <TextInput style={s.search} value={empQ} onChangeText={setEmpQ}
              placeholder="Search employee / code…" placeholderTextColor="#94A3B8" />
            {selEmp ? (
              <View style={s.pickedRow}>
                <Ionicons name="person-circle-outline" size={18} color={colors.brandPrimary} />
                <Text style={s.pickedTxt}>{selEmp.name} · #{selEmp.employee_code}</Text>
                <Pressable onPress={() => setSelEmp(null)} hitSlop={8}>
                  <Ionicons name="close-circle" size={18} color={colors.onSurfaceTertiary} />
                </Pressable>
              </View>
            ) : (
              <ScrollView style={s.empList} nestedScrollEnabled>
                {filteredEmps.map((e) => (
                  <Pressable key={e.user_id} style={s.empRow} onPress={() => setSelEmp(e)}>
                    <Text style={s.empName}>{e.name} · #{e.employee_code}</Text>
                  </Pressable>
                ))}
              </ScrollView>
            )}
            {err ? <Text style={s.err}>{err}</Text> : null}
            <Pressable style={[s.dlBtn, (!selEmp || busy) && { opacity: 0.5 }]}
              disabled={!selEmp || busy} onPress={download} testID="emp-report-download">
              {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                <>
                  <Ionicons name="download-outline" size={16} color="#fff" />
                  <Text style={s.dlTxt}>{modal === "payslip" ? "Open Pay Slip PDF" : "Download Excel"}</Text>
                </>
              )}
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  head: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 14, paddingVertical: 10,
    borderBottomWidth: 1, borderBottomColor: colors.border, zIndex: 20,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  card: {
    width: 250, backgroundColor: colors.surfaceSecondary, borderRadius: 14,
    borderWidth: 1, borderColor: colors.border, padding: 14,
  },
  cardIcon: {
    width: 40, height: 40, borderRadius: 10, alignItems: "center",
    justifyContent: "center", backgroundColor: "rgba(37,99,235,0.1)",
    marginBottom: 8,
  },
  cardTitle: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  cardDesc: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 3, minHeight: 30 },
  cardGo: { alignItems: "flex-end" },
  err: { color: "#DC2626", fontSize: 12.5, marginVertical: 6 },
  modalWrap: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.5)", alignItems: "center",
    justifyContent: "center", padding: 16,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 16,
    width: "100%", maxWidth: 420, gap: 10,
  },
  modalHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  modalTitle: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  search: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8, height: 40,
    paddingHorizontal: 10, color: colors.onSurface, backgroundColor: colors.surfaceSecondary,
  },
  empList: {
    maxHeight: 180, borderWidth: 1, borderColor: colors.border, borderRadius: 8,
  },
  empRow: {
    paddingHorizontal: 12, paddingVertical: 9,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  empName: { fontSize: 13, color: colors.onSurface, fontWeight: "600" },
  pickedRow: {
    flexDirection: "row", alignItems: "center", gap: 8, borderWidth: 1,
    borderColor: "rgba(37,99,235,0.35)", backgroundColor: "rgba(37,99,235,0.06)",
    borderRadius: 8, paddingHorizontal: 10, height: 42,
  },
  pickedTxt: { flex: 1, fontSize: 13, fontWeight: "700", color: colors.onSurface },
  fyRow: { flexDirection: "row", gap: 8 },
  fyChip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
  },
  fyChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  fyTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  fyTxtOn: { color: "#fff" },
  dlBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brandPrimary, borderRadius: 10, height: 44,
  },
  dlTxt: { color: "#fff", fontSize: 14, fontWeight: "800" },
});
