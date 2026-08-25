/**
 * Iter 731 — ASSET MANAGEMENT (admin). Tabs: Dashboard | Assets |
 * Incidents | Repairs | Recoveries | Reports. Actions per asset:
 * Assign / Return / Transfer / Repair / Incident / Retire / QR profile.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, TextInput, Platform } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router, Redirect } from "expo-router";
import { api, apiBinary } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Asset = { asset_id: string; asset_code: string; name: string; category?: string; brand?: string; model?: string; serial_number?: string; status: string; assigned_to_name?: string; branch?: string; purchase_cost?: number; warranty_end?: string };
type Emp = { user_id: string; name: string; employee_code?: string };

const TABS = ["Dashboard", "Assets", "Incidents", "Repairs", "Recoveries", "Reports"] as const;
const ym = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`; };

export default function AssetManagementScreen() {
  const { user, loading: authLoading } = useAuth();
  const [companyId, setCompanyId] = useState<string | null>(null);
  const [tab, setTab] = useState<(typeof TABS)[number]>("Dashboard");
  const [msg, setMsg] = useState<string | null>(null);
  const cid = user?.role === "company_admin" ? user.company_id : companyId;

  if (authLoading) return <View style={st.center}><ActivityIndicator /></View>;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(user.role)) return <Redirect href="/" />;

  return (
    <SafeAreaView style={st.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={{ padding: spacing.md, gap: 12 }}>
        <Text style={st.h1}>💼 Asset Management</Text>
        {user.role !== "company_admin" && <CompanyPicker value={companyId} onChange={setCompanyId} />}
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={st.row}>
            {TABS.map((t) => (
              <Pressable key={t} style={[st.chip, tab === t && st.chipOn]} onPress={() => setTab(t)} testID={`am-tab-${t}`}>
                <Text style={[st.chipTxt, tab === t && st.chipTxtOn]}>{t}</Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>
        {!cid ? <Text style={st.note}>पहले firm चुनें</Text> : (
          <>
            {tab === "Dashboard" && <DashboardTab cid={cid} />}
            {tab === "Assets" && <AssetsTab cid={cid} setMsg={setMsg} />}
            {tab === "Incidents" && <IncidentsTab cid={cid} setMsg={setMsg} />}
            {tab === "Repairs" && <RepairsTab cid={cid} setMsg={setMsg} />}
            {tab === "Recoveries" && <RecoveriesTab cid={cid} setMsg={setMsg} />}
            {tab === "Reports" && <ReportsTab cid={cid} setMsg={setMsg} />}
          </>
        )}
        {msg && <Text style={st.note}>{msg}</Text>}
      </ScrollView>
    </SafeAreaView>
  );
}

function DashboardTab({ cid }: { cid: string }) {
  const [d, setD] = useState<any | null>(null);
  useEffect(() => { (async () => { try { setD(await api<any>(`/admin/assets/dashboard?company_id=${cid}`)); } catch { setD(null); } })(); }, [cid]);
  if (!d) return <ActivityIndicator />;
  const card = (label: string, val: any, color = colors.onSurface) => (
    <View style={st.statCard} key={label}>
      <Text style={[st.statVal, { color }]}>{val}</Text>
      <Text style={st.statLbl}>{label}</Text>
    </View>
  );
  return (
    <View style={{ gap: 10 }}>
      <View style={st.grid}>
        {card("Total Assets", d.total_assets)}
        {card("Available", d.by_status?.Available || 0, "#0a7a4f")}
        {card("Assigned", d.by_status?.Assigned || 0, "#1a73e8")}
        {card("Under Repair", d.by_status?.["Under Repair"] || 0, "#e8710a")}
        {card("Damaged", d.by_status?.Damaged || 0, "#b3261e")}
        {card("Lost", d.by_status?.Lost || 0, "#b3261e")}
        {card("Retired", d.by_status?.Retired || 0)}
        {card("Total Value ₹", d.total_value)}
        {card("Pending Returns", d.pending_returns, "#e8710a")}
        {card("Pending Approvals", d.pending_approvals, "#e8710a")}
        {card("Recovery Pending ₹", d.pending_recovery_amount, "#b3261e")}
        {card("Repair Cost ₹", d.total_repair_cost)}
      </View>
      {Object.keys(d.by_category || {}).length > 0 && (
        <View style={st.card}>
          <Text style={st.h2}>Category-wise</Text>
          {Object.entries(d.by_category).map(([k, v]: any) => (
            <View key={k} style={st.line}><Text style={st.lineLbl}>{k}</Text><Text style={st.lineVal}>{v}</Text></View>
          ))}
        </View>
      )}
      {(d.warranty_expiring || []).length > 0 && (
        <View style={st.card}>
          <Text style={st.h2}>⚠️ Warranty expiring (30 दिन)</Text>
          {d.warranty_expiring.map((w: any) => (
            <Text key={w.asset_code} style={st.note}>{w.asset_code} · {w.name} · {w.date}</Text>
          ))}
        </View>
      )}
      {(d.amc_expiring || []).length > 0 && (
        <View style={st.card}>
          <Text style={st.h2}>⚠️ AMC expiring (30 दिन)</Text>
          {d.amc_expiring.map((w: any) => (
            <Text key={w.asset_code} style={st.note}>{w.asset_code} · {w.name} · {w.date}</Text>
          ))}
        </View>
      )}
    </View>
  );
}

function EmpSearch({ cid, sel, setSel }: { cid: string; sel: Emp | null; setSel: (e: Emp | null) => void }) {
  const [q, setQ] = useState("");
  const [emps, setEmps] = useState<Emp[]>([]);
  useEffect(() => { (async () => { try { const r = await api<{ employees: any[] }>(`/admin/employees?company_id=${cid}`); setEmps((r.employees || []).map((e) => ({ user_id: e.user_id, name: e.name, employee_code: e.employee_code }))); } catch { /* */ } })(); }, [cid]);
  const matches = useMemo(() => { const n = q.trim().toLowerCase(); if (!n) return []; return emps.filter((e) => `${e.name} ${e.employee_code || ""}`.toLowerCase().includes(n)).slice(0, 5); }, [q, emps]);
  return (
    <View style={{ gap: 6 }}>
      <TextInput style={st.input} value={sel ? `${sel.name} (${sel.employee_code || ""})` : q}
        onChangeText={(t) => { setSel(null); setQ(t); }} placeholder="Employee खोजें" placeholderTextColor={colors.onSurfaceTertiary} testID="am-emp-search" />
      {!sel && matches.map((e) => (
        <Pressable key={e.user_id} style={st.opt} onPress={() => { setSel(e); setQ(""); }}>
          <Text style={st.optTxt}>{e.name} · {e.employee_code}</Text>
        </Pressable>
      ))}
    </View>
  );
}

function AssetsTab({ cid, setMsg }: { cid: string; setMsg: (s: string) => void }) {
  const [items, setItems] = useState<Asset[]>([]);
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState<any>({});
  const [action, setAction] = useState<{ type: string; asset: Asset } | null>(null);
  const [aForm, setAForm] = useState<any>({});
  const [selEmp, setSelEmp] = useState<Emp | null>(null);
  const [cats, setCats] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [r, c] = await Promise.all([
        api<{ assets: Asset[] }>(`/admin/assets?company_id=${cid}${q ? `&q=${encodeURIComponent(q)}` : ""}`),
        api<{ categories: string[] }>(`/admin/assets/categories?company_id=${cid}`),
      ]);
      setItems(r.assets || []); setCats(c.categories || []);
    } catch (e: any) { setMsg(e?.message || "Load failed"); }
    finally { setLoading(false); }
  }, [cid, q, setMsg]);
  useEffect(() => { load(); }, [load]);

  const F = (k: string, ph: string, w?: number) => (
    <TextInput key={k} style={[st.input, w ? { width: w } : { flex: 1, minWidth: 140 }]} value={form[k] ?? ""}
      onChangeText={(t) => setForm((f: any) => ({ ...f, [k]: t }))} placeholder={ph} placeholderTextColor={colors.onSurfaceTertiary} />
  );

  const saveAsset = async () => {
    setBusy(true);
    try {
      await api("/admin/assets", { method: "POST", body: { ...form, company_id: cid } });
      setForm({}); setShowAdd(false); setMsg("Asset added ✓"); await load();
    } catch (e: any) { setMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const runAction = async () => {
    if (!action) return;
    const { type, asset } = action;
    setBusy(true);
    try {
      if (type === "Assign") {
        if (!selEmp) { setMsg("Employee चुनें"); setBusy(false); return; }
        await api(`/admin/assets/${asset.asset_id}/assign`, { method: "POST", body: { user_id: selEmp.user_id, ...aForm } });
      } else if (type === "Return") {
        await api(`/admin/assets/${asset.asset_id}/return`, { method: "POST", body: aForm });
      } else if (type === "Transfer") {
        await api(`/admin/assets/${asset.asset_id}/transfer`, { method: "POST", body: { ...(selEmp ? { user_id: selEmp.user_id } : {}), ...aForm } });
      } else if (type === "Repair") {
        await api(`/admin/assets/${asset.asset_id}/repair`, { method: "POST", body: aForm });
      } else if (type === "Incident") {
        await api(`/admin/assets/${asset.asset_id}/incident`, { method: "POST", body: aForm });
      } else if (type === "Retire") {
        await api(`/admin/assets/${asset.asset_id}`, { method: "PATCH", body: { status: "Retired" } });
      }
      setMsg(`${type} ✓`); setAction(null); setAForm({}); setSelEmp(null); await load();
    } catch (e: any) { setMsg(e?.message || `${type} failed`); }
    finally { setBusy(false); }
  };

  const AF = (k: string, ph: string) => (
    <TextInput key={k} style={[st.input, { flex: 1, minWidth: 130 }]} value={aForm[k] ?? ""}
      onChangeText={(t) => setAForm((f: any) => ({ ...f, [k]: t }))} placeholder={ph} placeholderTextColor={colors.onSurfaceTertiary} />
  );

  return (
    <View style={{ gap: 10 }}>
      <View style={st.row}>
        <TextInput style={[st.input, { flex: 1 }]} value={q} onChangeText={setQ} placeholder="Search code/name/serial…" placeholderTextColor={colors.onSurfaceTertiary} />
        <Pressable style={st.btn} onPress={() => setShowAdd(!showAdd)} testID="am-add-toggle"><Text style={st.btnTxt}>{showAdd ? "✕" : "+ Asset"}</Text></Pressable>
      </View>
      {showAdd && (
        <View style={st.card}>
          <Text style={st.h2}>नया Asset</Text>
          <View style={st.rowWrap}>{F("name", "Asset Name *")}{F("brand", "Brand")}{F("model", "Model")}</View>
          <ScrollView horizontal showsHorizontalScrollIndicator={false}>
            <View style={st.row}>
              {cats.map((c) => (
                <Pressable key={c} style={[st.chip, form.category === c && st.chipOn]} onPress={() => setForm((f: any) => ({ ...f, category: c }))}>
                  <Text style={[st.chipTxt, form.category === c && st.chipTxtOn]}>{c}</Text>
                </Pressable>
              ))}
            </View>
          </ScrollView>
          <View style={st.rowWrap}>{F("serial_number", "Serial No")}{F("imei", "IMEI")}{F("reg_number", "Reg No")}</View>
          <View style={st.rowWrap}>{F("purchase_date", "Purchase YYYY-MM-DD")}{F("purchase_cost", "Cost ₹")}{F("vendor", "Vendor")}</View>
          <View style={st.rowWrap}>{F("warranty_end", "Warranty End YYYY-MM-DD")}{F("amc_end", "AMC End YYYY-MM-DD")}</View>
          <View style={st.rowWrap}>{F("branch", "Branch")}{F("location", "Location")}{F("remarks", "Remarks")}</View>
          <Pressable style={[st.btn, busy && { opacity: 0.6 }]} onPress={saveAsset} disabled={busy} testID="am-asset-save">
            {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>Save Asset</Text>}
          </Pressable>
        </View>
      )}
      {action && (
        <View style={st.card}>
          <Text style={st.h2}>{action.type}: {action.asset.name} ({action.asset.asset_code})</Text>
          {action.type === "Assign" && (<>
            <EmpSearch cid={cid} sel={selEmp} setSel={setSelEmp} />
            <View style={st.rowWrap}>{AF("condition_at_issue", "Condition (Good)")}{AF("accessories", "Accessories")}{AF("expected_return_date", "Expected return YYYY-MM-DD")}</View>
          </>)}
          {action.type === "Return" && (<>
            <View style={st.rowWrap}>{AF("condition_at_return", "Condition")}{AF("missing_accessories", "Missing accessories")}{AF("damage_details", "Damage details")}</View>
            <View style={st.row}>
              {["available", "damaged", "repair"].map((o) => (
                <Pressable key={o} style={[st.chip, aForm.outcome === o && st.chipOn]} onPress={() => setAForm((f: any) => ({ ...f, outcome: o }))}>
                  <Text style={[st.chipTxt, aForm.outcome === o && st.chipTxtOn]}>{o}</Text>
                </Pressable>
              ))}
            </View>
          </>)}
          {action.type === "Transfer" && (<>
            <EmpSearch cid={cid} sel={selEmp} setSel={setSelEmp} />
            <View style={st.rowWrap}>{AF("branch", "New Branch")}{AF("location", "New Location")}{AF("department", "New Department")}</View>
          </>)}
          {action.type === "Repair" && (
            <View style={st.rowWrap}>{AF("complaint_details", "Complaint details")}{AF("service_vendor", "Vendor")}{AF("repair_cost", "Est cost ₹")}</View>
          )}
          {action.type === "Incident" && (<>
            <View style={st.row}>
              {["Damage", "Lost", "Missing Accessories", "Theft", "Misuse"].map((o) => (
                <Pressable key={o} style={[st.chip, aForm.incident_type === o && st.chipOn]} onPress={() => setAForm((f: any) => ({ ...f, incident_type: o }))}>
                  <Text style={[st.chipTxt, aForm.incident_type === o && st.chipTxtOn]}>{o}</Text>
                </Pressable>
              ))}
            </View>
            <View style={st.rowWrap}>{AF("description", "Description")}{AF("estimated_amount", "Estimated ₹")}</View>
          </>)}
          {action.type === "Retire" && <Text style={st.note}>Asset को Retired/Scrapped mark किया जाएगा।</Text>}
          <View style={st.row}>
            <Pressable style={[st.btn, busy && { opacity: 0.6 }]} onPress={runAction} disabled={busy} testID="am-action-go">
              {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>Confirm {action.type}</Text>}
            </Pressable>
            <Pressable style={[st.btn, { backgroundColor: colors.surfaceSecondary }]} onPress={() => { setAction(null); setAForm({}); setSelEmp(null); }}>
              <Text style={[st.btnTxt, { color: colors.onSurface }]}>Cancel</Text>
            </Pressable>
          </View>
        </View>
      )}
      {loading ? <ActivityIndicator /> : items.map((a) => (
        <View key={a.asset_id} style={st.item}>
          <Pressable style={{ flex: 1 }} onPress={() => router.push(`/asset-profile?id=${a.asset_id}`)}>
            <Text style={st.itemName}>{a.asset_code} · {a.name}</Text>
            <Text style={st.itemSub}>{a.category}{a.brand ? ` · ${a.brand}` : ""}{a.serial_number ? ` · SN ${a.serial_number}` : ""}{a.assigned_to_name ? ` · 👤 ${a.assigned_to_name}` : ""}</Text>
            <View style={st.row}>
              <Text style={[st.badge, { color: a.status === "Available" ? "#0a7a4f" : a.status === "Assigned" ? "#1a73e8" : "#b3261e" }]}>{a.status}</Text>
              {(["Available", "Returned"].includes(a.status) ? ["Assign"] : a.status === "Assigned" ? ["Return", "Transfer"] : [])
                .concat(["Repair", "Incident", "Retire"]).map((t) => (
                  <Pressable key={t} style={st.miniBtn} onPress={() => { setAction({ type: t, asset: a }); setAForm({}); setSelEmp(null); }}>
                    <Text style={st.miniTxt}>{t}</Text>
                  </Pressable>
                ))}
            </View>
          </Pressable>
        </View>
      ))}
      {!loading && items.length === 0 && <Text style={st.note}>कोई asset नहीं — + Asset से जोड़ें</Text>}
    </View>
  );
}

function IncidentsTab({ cid, setMsg }: { cid: string; setMsg: (s: string) => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [appr, setAppr] = useState<{ id: string; amt: string; monthly: string } | null>(null);
  const load = useCallback(async () => { try { const r = await api<{ incidents: any[] }>(`/admin/assets/incidents?company_id=${cid}`); setItems(r.incidents || []); } catch { /* */ } }, [cid]);
  useEffect(() => { load(); }, [load]);
  const approve = async (decision: string) => {
    if (!appr) return;
    try {
      await api(`/admin/assets/incidents/${appr.id}/approve`, { method: "POST", body: { decision, approved_amount: Number(appr.amt) || 0, monthly_recovery: Number(appr.monthly) || 0 } });
      setMsg("Incident " + decision + " ✓"); setAppr(null); await load();
    } catch (e: any) { setMsg(e?.message || "failed"); }
  };
  return (
    <View style={{ gap: 8 }}>
      {items.map((i) => (
        <View key={i.incident_id} style={st.item}>
          <View style={{ flex: 1 }}>
            <Text style={st.itemName}>{i.asset_code} · {i.incident_type} · {i.incident_date}</Text>
            <Text style={st.itemSub}>{i.employee_name || "-"} · Est ₹{i.estimated_amount} · {i.approval_status}{i.approved_amount ? ` · Approved ₹${i.approved_amount}` : ""}</Text>
            {i.approval_status === "pending" && (
              appr?.id === i.incident_id ? (
                <View style={st.row}>
                  <TextInput style={[st.input, { width: 90 }]} value={appr.amt} onChangeText={(t) => setAppr({ ...appr, amt: t })} placeholder="₹ Approve" keyboardType="numeric" placeholderTextColor={colors.onSurfaceTertiary} />
                  <TextInput style={[st.input, { width: 90 }]} value={appr.monthly} onChangeText={(t) => setAppr({ ...appr, monthly: t })} placeholder="₹/month" keyboardType="numeric" placeholderTextColor={colors.onSurfaceTertiary} />
                  <Pressable style={st.miniBtn} onPress={() => approve("approved")}><Text style={st.miniTxt}>✓ Approve</Text></Pressable>
                  <Pressable style={st.miniBtn} onPress={() => approve("rejected")}><Text style={st.miniTxt}>✕ Reject</Text></Pressable>
                </View>
              ) : (
                <Pressable style={st.miniBtn} onPress={() => setAppr({ id: i.incident_id, amt: String(i.estimated_amount || ""), monthly: "" })}>
                  <Text style={st.miniTxt}>Review / Approve</Text>
                </Pressable>
              )
            )}
          </View>
        </View>
      ))}
      {items.length === 0 && <Text style={st.note}>कोई incident नहीं</Text>}
    </View>
  );
}

function RepairsTab({ cid, setMsg }: { cid: string; setMsg: (s: string) => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [cost, setCost] = useState<{ id: string; amt: string } | null>(null);
  const load = useCallback(async () => { try { const r = await api<{ repairs: any[] }>(`/admin/assets/repairs?company_id=${cid}`); setItems(r.repairs || []); } catch { /* */ } }, [cid]);
  useEffect(() => { load(); }, [load]);
  const complete = async () => {
    if (!cost) return;
    try { await api(`/admin/assets/repairs/${cost.id}/complete`, { method: "POST", body: { repair_cost: Number(cost.amt) || 0 } }); setMsg("Repair complete ✓"); setCost(null); await load(); }
    catch (e: any) { setMsg(e?.message || "failed"); }
  };
  return (
    <View style={{ gap: 8 }}>
      {items.map((r) => (
        <View key={r.repair_id} style={st.item}>
          <View style={{ flex: 1 }}>
            <Text style={st.itemName}>{r.asset_code} · {r.asset_name} · {r.status}</Text>
            <Text style={st.itemSub}>{r.complaint_date} · {r.complaint_details} · {r.service_vendor || "-"} · ₹{r.repair_cost || 0}</Text>
            {r.status === "open" && (
              cost?.id === r.repair_id ? (
                <View style={st.row}>
                  <TextInput style={[st.input, { width: 100 }]} value={cost.amt} onChangeText={(t) => setCost({ ...cost, amt: t })} placeholder="Final ₹" keyboardType="numeric" placeholderTextColor={colors.onSurfaceTertiary} />
                  <Pressable style={st.miniBtn} onPress={complete}><Text style={st.miniTxt}>✓ Mark Complete</Text></Pressable>
                </View>
              ) : (
                <Pressable style={st.miniBtn} onPress={() => setCost({ id: r.repair_id, amt: String(r.repair_cost || "") })}>
                  <Text style={st.miniTxt}>Complete Repair</Text>
                </Pressable>
              )
            )}
          </View>
        </View>
      ))}
      {items.length === 0 && <Text style={st.note}>कोई repair record नहीं</Text>}
    </View>
  );
}

function RecoveriesTab({ cid, setMsg }: { cid: string; setMsg: (s: string) => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [month, setMonth] = useState(ym());
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { try { const r = await api<{ recoveries: any[] }>(`/admin/assets/recoveries?company_id=${cid}`); setItems(r.recoveries || []); } catch { /* */ } }, [cid]);
  useEffect(() => { load(); }, [load]);
  const apply = async () => {
    setBusy(true);
    try { const r = await api<any>("/admin/assets/recoveries/apply", { method: "POST", body: { company_id: cid, month } }); setMsg(`✓ ${r.applied} employees पर लगा। ${r.note || r.detail || ""}`); await load(); }
    catch (e: any) { setMsg(e?.message || "Apply failed"); }
    finally { setBusy(false); }
  };
  return (
    <View style={{ gap: 8 }}>
      <View style={st.row}>
        <TextInput style={[st.input, { width: 100 }]} value={month} onChangeText={setMonth} placeholder="YYYY-MM" placeholderTextColor={colors.onSurfaceTertiary} />
        <Pressable style={[st.btn, busy && { opacity: 0.6 }]} onPress={apply} disabled={busy} testID="am-recovery-apply">
          {busy ? <ActivityIndicator color="#fff" size="small" /> : <Text style={st.btnTxt}>Salary में Apply करें</Text>}
        </Pressable>
      </View>
      <Text style={st.note}>Apply के बाद Compliance run को Reprocess (With EXISTING Data) करें।</Text>
      {items.map((r) => (
        <View key={r.recovery_id} style={st.item}>
          <View style={{ flex: 1 }}>
            <Text style={st.itemName}>{r.employee_name} · {r.asset_code} · {r.status}</Text>
            <Text style={st.itemSub}>Total ₹{r.total_recovery} · ₹{r.monthly_recovery}/माह · Recovered ₹{r.recovered_amount} · Pending ₹{r.pending_amount} · {r.start_month} → {r.end_month}</Text>
          </View>
        </View>
      ))}
      {items.length === 0 && <Text style={st.note}>कोई recovery नहीं</Text>}
    </View>
  );
}

function ReportsTab({ cid, setMsg }: { cid: string; setMsg: (s: string) => void }) {
  const kinds = [["register", "Asset Register"], ["assignments", "Assignment History"], ["incidents", "Damage/Loss Report"], ["repairs", "Repair Report"], ["recoveries", "Recovery Report"]];
  const dl = async (kind: string, fmt: string) => {
    try {
      const res = await apiBinary(`/admin/assets/report/${kind}?company_id=${cid}&fmt=${fmt}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl; a.download = `Asset_${kind}.${fmt === "pdf" ? "pdf" : "xlsx"}`; a.click();
      }
    } catch (e: any) { setMsg(e?.message || "Export failed"); }
  };
  return (
    <View style={{ gap: 8 }}>
      {kinds.map(([k, label]) => (
        <View key={k} style={st.item}>
          <Text style={[st.itemName, { flex: 1 }]}>{label}</Text>
          <Pressable style={st.miniBtn} onPress={() => dl(k, "xlsx")}><Text style={st.miniTxt}>Excel</Text></Pressable>
          <Pressable style={st.miniBtn} onPress={() => dl(k, "pdf")}><Text style={st.miniTxt}>PDF</Text></Pressable>
        </View>
      ))}
    </View>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  h1: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  h2: { fontSize: 15, fontWeight: "700", color: colors.onSurface },
  row: { flexDirection: "row", gap: 8, alignItems: "center", flexWrap: "wrap" },
  rowWrap: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md, gap: 10 },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8, color: colors.onSurface, backgroundColor: colors.surface },
  opt: { paddingVertical: 8, paddingHorizontal: 10, backgroundColor: colors.surfaceSecondary, borderRadius: radius.md },
  optTxt: { color: colors.onSurface, fontSize: 13 },
  chip: { paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: colors.border },
  chipOn: { backgroundColor: colors.cta, borderColor: colors.cta },
  chipTxt: { fontSize: 12, color: colors.onSurface },
  chipTxtOn: { color: "#fff", fontWeight: "700" },
  btn: { backgroundColor: colors.cta, borderRadius: radius.md, paddingVertical: 10, paddingHorizontal: 14, alignItems: "center", minHeight: 44, justifyContent: "center" },
  btnTxt: { color: "#fff", fontWeight: "700" },
  note: { fontSize: 12, color: colors.onSurfaceSecondary },
  item: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: colors.surface, borderRadius: radius.md, padding: 12 },
  itemName: { fontWeight: "700", color: colors.onSurface, fontSize: 13 },
  itemSub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 2 },
  badge: { fontSize: 11, fontWeight: "800", marginRight: 4 },
  miniBtn: { paddingHorizontal: 9, paddingVertical: 5, borderRadius: radius.sm, borderWidth: 1, borderColor: colors.border, marginTop: 4 },
  miniTxt: { fontSize: 11, color: colors.onSurface, fontWeight: "600" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  statCard: { backgroundColor: colors.surface, borderRadius: radius.md, padding: 12, minWidth: 105, flexGrow: 1, alignItems: "center" },
  statVal: { fontSize: 18, fontWeight: "900" },
  statLbl: { fontSize: 10, color: colors.onSurfaceSecondary, marginTop: 2, textAlign: "center" },
  line: { flexDirection: "row", justifyContent: "space-between", paddingVertical: 4 },
  lineLbl: { color: colors.onSurfaceSecondary, fontSize: 13 },
  lineVal: { color: colors.onSurface, fontSize: 13, fontWeight: "700" },
});
