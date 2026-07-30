/**
 * Iter 395 — WhatsApp Communication Center.
 * Tabs: Dashboard · Send · Salary Slips · History · Scheduler · Reports.
 * Deep-linkable via ?tab= (used by Payroll / Attendance / Compliance menus).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Platform, Modal,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router, useLocalSearchParams } from "expo-router";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const WA_GREEN = "#128C7E";
const WA_LIGHT = "#25D366";

const TABS = [
  { key: "dashboard", label: "Dashboard", icon: "speedometer-outline" },
  { key: "send", label: "Send Message", icon: "send-outline" },
  { key: "slips", label: "Salary Slips", icon: "document-text-outline" },
  { key: "history", label: "History", icon: "time-outline" },
  { key: "schedules", label: "Scheduler", icon: "alarm-outline" },
  { key: "reports", label: "Reports", icon: "bar-chart-outline" },
] as const;

const STATUS_COLORS: Record<string, { bg: string; fg: string }> = {
  queued: { bg: "#FEF3C7", fg: "#92400E" },
  sending: { bg: "#DBEAFE", fg: "#1D4ED8" },
  sent: { bg: "#DCFCE7", fg: "#166534" },
  delivered: { bg: "#D1FAE5", fg: "#065F46" },
  read: { bg: "#CFFAFE", fg: "#155E75" },
  failed: { bg: "#FEE2E2", fg: "#991B1B" },
  cancelled: { bg: "#F3F4F6", fg: "#4B5563" },
};

function dlBinary(path: string, filename: string) {
  apiBinary(path).then(({ webBlobUrl }) => {
    if (Platform.OS === "web" && webBlobUrl) {
      const a = document.createElement("a");
      a.href = webBlobUrl; a.download = filename; a.click();
    }
  }).catch(() => {});
}

export default function WhatsAppCenterScreen() {
  const { user } = useAuth();
  const params = useLocalSearchParams<{ tab?: string }>();
  const isSuper = user?.role === "super_admin";
  const [tab, setTab] = useState<string>(
    TABS.some((t) => t.key === params.tab) ? String(params.tab) : "dashboard");
  const [companies, setCompanies] = useState<{ company_id: string; name: string }[]>([]);
  const [cid, setCid] = useState("");
  const [ddOpen, setDdOpen] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/companies?lite=1");
        const list = (r?.companies || r || []).filter((c: any) => c.is_active !== false);
        setCompanies(list.map((c: any) => ({ company_id: c.company_id, name: c.name })));
        if (!isSuper && user?.company_id) setCid(user.company_id);
        else if (list.length) setCid(list[0].company_id);
      } catch { /* noop */ }
    })();
  }, [isSuper, user?.company_id]);

  const firmName = companies.find((c) => c.company_id === cid)?.name || "Select firm";

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 6 }}>
          <Ionicons name="arrow-back" size={22} color={colors.text} />
        </Pressable>
        <Ionicons name="logo-whatsapp" size={22} color={WA_LIGHT} />
        <Text style={st.title}>WhatsApp Center</Text>
        <View style={{ flex: 1 }} />
        {isSuper && (
          <Pressable style={st.firmDd} onPress={() => setDdOpen(!ddOpen)} testID="wa-center-firm">
            <Text style={st.firmDdText} numberOfLines={1}>{firmName}</Text>
            <Ionicons name="chevron-down" size={14} color={colors.muted} />
          </Pressable>
        )}
        <Pressable style={{ padding: 6 }} onPress={() => router.push("/whatsapp-templates")}>
          <Ionicons name="albums-outline" size={20} color={WA_GREEN} />
        </Pressable>
        <Pressable style={{ padding: 6 }} onPress={() => router.push("/whatsapp-config")}>
          <Ionicons name="settings-outline" size={20} color={WA_GREEN} />
        </Pressable>
      </View>
      {ddOpen && (
        <View style={st.ddList}>
          {companies.map((c) => (
            <Pressable key={c.company_id} style={st.ddItem}
              onPress={() => { setCid(c.company_id); setDdOpen(false); }}>
              <Text style={{ color: c.company_id === cid ? WA_GREEN : colors.text, fontSize: 13 }}>{c.name}</Text>
            </Pressable>
          ))}
        </View>
      )}

      <ScrollView horizontal showsHorizontalScrollIndicator={false}
        style={{ flexGrow: 0 }} contentContainerStyle={st.tabRow}>
        {TABS.map((t) => (
          <Pressable key={t.key} testID={`wa-tab-${t.key}`}
            style={[st.tabBtn, tab === t.key && st.tabBtnActive]}
            onPress={() => setTab(t.key)}>
            <Ionicons name={t.icon as any} size={15}
              color={tab === t.key ? "#fff" : colors.muted} />
            <Text style={[st.tabText, tab === t.key && { color: "#fff" }]}>{t.label}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {banner && (
        <View style={[st.banner, { backgroundColor: banner.kind === "ok" ? "#DCFCE7" : "#FEE2E2" }]}>
          <Text style={{ color: banner.kind === "ok" ? "#166534" : "#991B1B", fontSize: 12.5, flex: 1 }}>
            {banner.msg}
          </Text>
          <Pressable onPress={() => setBanner(null)}>
            <Ionicons name="close" size={16} color={colors.muted} />
          </Pressable>
        </View>
      )}

      {!cid ? <ActivityIndicator style={{ marginTop: 40 }} color={WA_GREEN} /> : (
        <>
          {tab === "dashboard" && <DashboardTab cid={cid} />}
          {tab === "send" && <SendTab cid={cid} setBanner={setBanner} />}
          {tab === "slips" && <SlipsTab cid={cid} setBanner={setBanner} />}
          {tab === "history" && <HistoryTab cid={cid} setBanner={setBanner} />}
          {tab === "schedules" && <SchedulesTab cid={cid} setBanner={setBanner} />}
          {tab === "reports" && <ReportsTab cid={cid} />}
        </>
      )}
    </SafeAreaView>
  );
}

/* ------------------------------------------------------------ Dashboard */
function DashboardTab({ cid }: { cid: string }) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try { setData(await api<any>(`/admin/whatsapp/dashboard?company_id=${cid}`)); }
    catch { /* noop */ } finally { setLoading(false); }
  }, [cid]);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);

  if (loading && !data) return <ActivityIndicator style={{ marginTop: 40 }} color={WA_GREEN} />;
  const k = data?.kpis || {};
  const cards = [
    { label: "Sent Today", value: k.sent_today, icon: "paper-plane-outline", color: "#0EA5E9" },
    { label: "Delivered", value: k.delivered, icon: "checkmark-done-outline", color: "#10B981" },
    { label: "Read", value: k.read, icon: "eye-outline", color: "#06B6D4" },
    { label: "Failed", value: k.failed, icon: "alert-circle-outline", color: "#EF4444" },
    { label: "Pending Queue", value: k.pending, icon: "hourglass-outline", color: "#F59E0B" },
    { label: "Success %", value: `${k.success_pct ?? 0}%`, icon: "trending-up-outline", color: "#22C55E" },
    { label: "Failure %", value: `${k.failure_pct ?? 0}%`, icon: "trending-down-outline", color: "#F97316" },
    { label: "Total Messages", value: k.total, icon: "chatbubbles-outline", color: WA_GREEN },
  ];
  const maxTrend = Math.max(1, ...(data?.trend || []).map((t: any) => t.count));
  return (
    <ScrollView contentContainerStyle={st.body}>
      {!k.configured && (
        <View style={[st.card, { backgroundColor: "#FFFBEB", borderColor: "#FDE68A" }]}>
          <Text style={{ color: "#92400E", fontSize: 13 }}>
            ⚠ WhatsApp is not configured for this firm yet. Open Settings (top-right gear) and
            enter your Meta Cloud API credentials. Queued messages will send after setup.
          </Text>
        </View>
      )}
      <View style={st.kpiGrid}>
        {cards.map((c) => (
          <View key={c.label} style={st.kpiCard} testID={`wa-kpi-${c.label}`}>
            <Ionicons name={c.icon as any} size={18} color={c.color} />
            <Text style={st.kpiValue}>{c.value ?? 0}</Text>
            <Text style={st.kpiLabel}>{c.label}</Text>
          </View>
        ))}
      </View>
      <View style={st.card}>
        <Text style={st.cardTitle}>Last 14 Days</Text>
        <View style={{ flexDirection: "row", alignItems: "flex-end", gap: 4, height: 90, marginTop: 8 }}>
          {(data?.trend || []).map((t: any) => (
            <View key={t.date} style={{ flex: 1, alignItems: "center" }}>
              <View style={{
                width: "70%", borderRadius: 3,
                height: Math.max(4, (t.count / maxTrend) * 76),
                backgroundColor: t.failed > 0 ? "#F59E0B" : WA_LIGHT,
              }} />
              <Text style={{ fontSize: 8, color: colors.muted }}>{t.date.slice(8)}</Text>
            </View>
          ))}
          {!(data?.trend || []).length && (
            <Text style={{ color: colors.muted, fontSize: 12 }}>No messages yet.</Text>
          )}
        </View>
      </View>
      <View style={st.card}>
        <Text style={st.cardTitle}>Top Templates</Text>
        {(data?.top_templates || []).map((t: any) => (
          <View key={t.category} style={st.rowBetween}>
            <Text style={{ color: colors.text, fontSize: 13 }}>{t.category}</Text>
            <Text style={{ color: WA_GREEN, fontWeight: "700" }}>{t.count}</Text>
          </View>
        ))}
        {!(data?.top_templates || []).length && (
          <Text style={{ color: colors.muted, fontSize: 12 }}>No data yet.</Text>
        )}
      </View>
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

/* ----------------------------------------------------------------- Send */
function SendTab({ cid, setBanner }: { cid: string; setBanner: any }) {
  const [templates, setTemplates] = useState<any[]>([]);
  const [tplId, setTplId] = useState<string>("");
  const [body, setBody] = useState("");
  const [mode, setMode] = useState<"company" | "department" | "employees">("employees");
  const [department, setDepartment] = useState("");
  const [employees, setEmployees] = useState<any[]>([]);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [q, setQ] = useState("");
  const [sending, setSending] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [scheduleAt, setScheduleAt] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>(`/admin/whatsapp/templates?company_id=${cid}`);
        setTemplates((r.templates || []).filter((t: any) => t.active !== false));
        const e = await api<any>(`/admin/employees?company_id=${cid}`);
        setEmployees(e.employees || e || []);
      } catch { /* noop */ }
    })();
  }, [cid]);

  const filteredEmp = useMemo(() => {
    const s = q.trim().toLowerCase();
    const list = Array.isArray(employees) ? employees : [];
    if (!s) return list.slice(0, 200);
    return list.filter((e: any) =>
      (e.name || "").toLowerCase().includes(s) ||
      (e.employee_code || "").toLowerCase().includes(s)).slice(0, 200);
  }, [employees, q]);

  const doPreview = async () => {
    const uid = sel.size ? Array.from(sel)[0] : undefined;
    try {
      const r = await api<any>(`/admin/whatsapp/preview?company_id=${cid}`, {
        method: "POST",
        body: { body: body || undefined, template_id: !body ? tplId : undefined, user_id: uid },
      });
      setPreview(r.rendered || "");
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || "Preview failed" }); }
  };

  const send = async () => {
    setSending(true);
    try {
      const target = mode === "employees"
        ? { mode: "employees", user_ids: Array.from(sel) }
        : mode === "department" ? { mode: "department", department }
          : { mode: "company" };
      const r = await api<any>(`/admin/whatsapp/send?company_id=${cid}`, {
        method: "POST",
        body: {
          target, template_id: tplId || undefined, body: body || undefined,
          scheduled_at: scheduleAt || undefined,
        },
      });
      setBanner({
        kind: "ok",
        msg: `${r.queued} message(s) queued${r.configured ? "" : " (will send after WhatsApp is configured)"}.`,
      });
      setSel(new Set());
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || "Send failed" }); }
    finally { setSending(false); }
  };

  return (
    <ScrollView contentContainerStyle={st.body}>
      <View style={st.card}>
        <Text style={st.cardTitle}>1 · Message</Text>
        <Text style={st.label}>Template</Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false}>
          <View style={{ flexDirection: "row", gap: 6 }}>
            <Pressable style={[st.chip, !tplId && st.chipActive]} onPress={() => setTplId("")}>
              <Text style={[st.chipText, !tplId && { color: "#fff" }]}>Custom text</Text>
            </Pressable>
            {templates.map((t) => (
              <Pressable key={t.template_id}
                style={[st.chip, tplId === t.template_id && st.chipActive]}
                onPress={() => { setTplId(t.template_id); setBody(""); }}>
                <Text style={[st.chipText, tplId === t.template_id && { color: "#fff" }]}>{t.name}</Text>
              </Pressable>
            ))}
          </View>
        </ScrollView>
        {!tplId && (
          <>
            <Text style={st.label}>Message text</Text>
            <TextInput style={[st.input, { minHeight: 90, textAlignVertical: "top" }]}
              multiline value={body} onChangeText={setBody}
              placeholder="Type your message… variables like {{EmployeeName}} work here too"
              placeholderTextColor={colors.muted} testID="wa-send-body" />
          </>
        )}
      </View>

      <View style={st.card}>
        <Text style={st.cardTitle}>2 · Recipients</Text>
        <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
          {([["employees", "Selected Employees"], ["department", "Department"], ["company", "Entire Firm"]] as const)
            .map(([m, lbl]) => (
              <Pressable key={m} style={[st.chip, mode === m && st.chipActive]} onPress={() => setMode(m)}>
                <Text style={[st.chipText, mode === m && { color: "#fff" }]}>{lbl}</Text>
              </Pressable>
            ))}
        </View>
        {mode === "department" && (
          <TextInput style={[st.input, { marginTop: 8 }]} value={department}
            onChangeText={setDepartment} placeholder="Department name"
            placeholderTextColor={colors.muted} />
        )}
        {mode === "employees" && (
          <>
            <TextInput style={[st.input, { marginTop: 8 }]} value={q} onChangeText={setQ}
              placeholder="Search employee…" placeholderTextColor={colors.muted} />
            <Text style={st.hintSmall}>{sel.size} selected</Text>
            <ScrollView style={{ maxHeight: 260 }}>
              {filteredEmp.map((e: any) => {
                const on = sel.has(e.user_id);
                return (
                  <Pressable key={e.user_id} style={st.empRow}
                    onPress={() => {
                      const n = new Set(sel);
                      if (on) n.delete(e.user_id); else n.add(e.user_id);
                      setSel(n);
                    }}>
                    <Ionicons name={on ? "checkbox" : "square-outline"} size={18}
                      color={on ? WA_GREEN : colors.muted} />
                    <Text style={{ color: colors.text, fontSize: 13, flex: 1 }}>
                      {e.name} <Text style={{ color: colors.muted }}>({e.employee_code || "—"})</Text>
                    </Text>
                    <Text style={{ color: e.whatsapp_number || e.phone ? WA_GREEN : "#EF4444", fontSize: 11 }}>
                      {e.whatsapp_number || e.phone || "no number"}
                    </Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          </>
        )}
      </View>

      <View style={st.card}>
        <Text style={st.cardTitle}>3 · Schedule (optional)</Text>
        <TextInput style={st.input} value={scheduleAt} onChangeText={setScheduleAt}
          placeholder="Leave blank = send now · or ISO e.g. 2026-06-25T09:00:00+05:30"
          placeholderTextColor={colors.muted} autoCapitalize="none" />
      </View>

      <View style={{ flexDirection: "row", gap: 8 }}>
        <Pressable style={[st.btn, { flex: 1, backgroundColor: "#0EA5E9" }]} onPress={doPreview}>
          <Ionicons name="eye-outline" size={16} color="#fff" />
          <Text style={st.btnText}>Preview</Text>
        </Pressable>
        <Pressable style={[st.btn, { flex: 2, backgroundColor: WA_GREEN }]}
          onPress={send} disabled={sending} testID="wa-send-go">
          {sending ? <ActivityIndicator size="small" color="#fff" /> : (
            <><Ionicons name="send" size={16} color="#fff" />
              <Text style={st.btnText}>{scheduleAt ? "Schedule" : "Send Now"}</Text></>
          )}
        </Pressable>
      </View>

      <Modal visible={preview !== null} transparent animationType="fade"
        onRequestClose={() => setPreview(null)}>
        <View style={st.modalWrap}>
          <View style={[st.modalCard, { backgroundColor: "#ECE5DD" }]}>
            <Text style={[st.cardTitle, { color: "#111" }]}>Preview</Text>
            <View style={st.waBubble}>
              <Text style={{ color: "#111", fontSize: 13.5, lineHeight: 19 }}>{preview}</Text>
            </View>
            <Pressable style={[st.btn, { backgroundColor: WA_GREEN, marginTop: 12 }]}
              onPress={() => setPreview(null)}>
              <Text style={st.btnText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

/* ------------------------------------------------------------ Salary Slips */
function SlipsTab({ cid, setBanner }: { cid: string; setBanner: any }) {
  const now = new Date();
  const prev = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const [month, setMonth] = useState(
    `${prev.getFullYear()}-${String(prev.getMonth() + 1).padStart(2, "0")}`);
  const [sending, setSending] = useState(false);
  const send = async () => {
    setSending(true);
    try {
      const r = await api<any>(`/admin/whatsapp/send-salary-slips?company_id=${cid}`,
        { method: "POST", body: { month } });
      setBanner({ kind: "ok", msg: `${r.queued} payslip(s) queued for WhatsApp delivery (skipped ${r.skipped}).` });
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || "Failed" }); }
    finally { setSending(false); }
  };
  return (
    <ScrollView contentContainerStyle={st.body}>
      <View style={st.card}>
        <Text style={st.cardTitle}>Send Salary Slips via WhatsApp</Text>
        <Text style={st.hintSmall}>
          Every employee with a processed salary for the selected month receives their payslip
          PDF on WhatsApp using the &quot;Salary Slip&quot; template.
        </Text>
        <Text style={st.label}>Month (YYYY-MM)</Text>
        <TextInput style={st.input} value={month} onChangeText={setMonth}
          placeholder="2026-05" placeholderTextColor={colors.muted}
          autoCapitalize="none" testID="wa-slips-month" />
        <Pressable style={[st.btn, { backgroundColor: WA_GREEN }]}
          onPress={send} disabled={sending} testID="wa-slips-send">
          {sending ? <ActivityIndicator size="small" color="#fff" /> : (
            <><Ionicons name="logo-whatsapp" size={16} color="#fff" />
              <Text style={st.btnText}>Queue Payslips for {month}</Text></>
          )}
        </Pressable>
      </View>
    </ScrollView>
  );
}

/* -------------------------------------------------------------- History */
function HistoryTab({ cid, setBanner }: { cid: string; setBanner: any }) {
  const [rows, setRows] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [detail, setDetail] = useState<any>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams({ company_id: cid, limit: "100" });
      if (status) qs.set("status", status);
      if (q) qs.set("q", q);
      const r = await api<any>(`/admin/whatsapp/messages?${qs.toString()}`);
      setRows(r.messages || []); setTotal(r.total || 0);
    } catch { /* noop */ } finally { setLoading(false); }
  }, [cid, status, q]);
  useEffect(() => { load(); }, [load]);

  const act = async (msgId: string, action: "retry" | "cancel" | "delete") => {
    try {
      if (action === "delete") {
        await api<any>(`/admin/whatsapp/messages/${msgId}`, { method: "DELETE" });
      } else {
        await api<any>(`/admin/whatsapp/messages/${msgId}/${action}`, { method: "POST", body: {} });
      }
      setBanner({ kind: "ok", msg: `Message ${action} done.` });
      load();
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || `${action} failed` }); }
  };

  return (
    <View style={{ flex: 1 }}>
      <View style={[st.body, { paddingBottom: 0 }]}>
        <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
          {["", "queued", "sent", "delivered", "read", "failed", "cancelled"].map((s) => (
            <Pressable key={s || "all"} style={[st.chip, status === s && st.chipActive]}
              onPress={() => setStatus(s)}>
              <Text style={[st.chipText, status === s && { color: "#fff" }]}>{s || "All"} </Text>
            </Pressable>
          ))}
        </View>
        <TextInput style={[st.input, { marginTop: 8 }]} value={q} onChangeText={setQ}
          placeholder="Search name / code / number…" placeholderTextColor={colors.muted} />
        <Text style={st.hintSmall}>{total} message(s)</Text>
      </View>
      {loading ? <ActivityIndicator style={{ marginTop: 30 }} color={WA_GREEN} /> : (
        <ScrollView contentContainerStyle={[st.body, { paddingTop: spacing.xs }]}>
          {rows.map((m) => {
            const sc = STATUS_COLORS[m.status] || STATUS_COLORS.queued;
            return (
              <Pressable key={m.msg_id} style={st.msgRow} onPress={() => setDetail(m)}>
                <View style={{ flex: 1 }}>
                  <Text style={{ color: colors.text, fontSize: 13.5, fontWeight: "600" }}>
                    {m.employee_name || m.to || "—"}
                    <Text style={{ color: colors.muted, fontWeight: "400" }}>
                      {"  "}· {m.category} · {m.source}
                    </Text>
                  </Text>
                  <Text style={{ color: colors.muted, fontSize: 11.5 }} numberOfLines={1}>
                    {m.body}
                  </Text>
                  <Text style={{ color: colors.muted, fontSize: 10.5 }}>
                    {(m.created_at || "").replace("T", " ").slice(0, 16)}
                    {m.retry_count ? `  · retries: ${m.retry_count}` : ""}
                    {m.error ? `  · ${m.error}` : ""}
                  </Text>
                </View>
                <View style={[st.statusPill, { backgroundColor: sc.bg }]}>
                  <Text style={{ color: sc.fg, fontSize: 10.5, fontWeight: "700" }}>{m.status}</Text>
                </View>
                {m.status === "failed" && (
                  <Pressable style={{ padding: 6 }} onPress={() => act(m.msg_id, "retry")}>
                    <Ionicons name="refresh" size={16} color="#0EA5E9" />
                  </Pressable>
                )}
                {m.status === "queued" && (
                  <Pressable style={{ padding: 6 }} onPress={() => act(m.msg_id, "cancel")}>
                    <Ionicons name="close-circle-outline" size={16} color="#F59E0B" />
                  </Pressable>
                )}
                <Pressable style={{ padding: 6 }} onPress={() => act(m.msg_id, "delete")}>
                  <Ionicons name="trash-outline" size={16} color="#DC2626" />
                </Pressable>
              </Pressable>
            );
          })}
          {!rows.length && (
            <Text style={{ color: colors.muted, textAlign: "center", marginTop: 30 }}>No messages.</Text>
          )}
          <View style={{ height: 40 }} />
        </ScrollView>
      )}
      <Modal visible={!!detail} transparent animationType="fade" onRequestClose={() => setDetail(null)}>
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <Text style={st.cardTitle}>Message Detail</Text>
            {detail && (
              <ScrollView style={{ maxHeight: 380 }}>
                {[["To", detail.to], ["Employee", detail.employee_name],
                  ["Category", detail.category], ["Source", detail.source],
                  ["Status", detail.status], ["Error", detail.error],
                  ["Created", detail.created_at], ["Sent", detail.sent_at],
                  ["Delivered", detail.delivered_at], ["Read", detail.read_at],
                  ["Retries", detail.retry_count], ["WA ID", detail.wa_message_id],
                ].map(([k, v]) => v != null && v !== "" ? (
                  <View key={String(k)} style={st.rowBetween}>
                    <Text style={{ color: colors.muted, fontSize: 12 }}>{k}</Text>
                    <Text style={{ color: colors.text, fontSize: 12, flexShrink: 1 }}>{String(v)}</Text>
                  </View>
                ) : null)}
                <Text style={[st.label, { marginTop: 8 }]}>Body</Text>
                <View style={st.waBubble}>
                  <Text style={{ color: "#111", fontSize: 13 }}>{detail.body}</Text>
                </View>
              </ScrollView>
            )}
            <Pressable style={[st.btn, { backgroundColor: WA_GREEN, marginTop: 12 }]}
              onPress={() => setDetail(null)}>
              <Text style={st.btnText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </View>
  );
}

/* ------------------------------------------------------------- Schedules */
function SchedulesTab({ cid, setBanner }: { cid: string; setBanner: any }) {
  const [rows, setRows] = useState<any[]>([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<any>({ type: "once", time: "09:00", category: "custom" });
  const load = useCallback(async () => {
    try {
      const r = await api<any>(`/admin/whatsapp/schedules?company_id=${cid}`);
      setRows(r.schedules || []);
    } catch { /* noop */ }
  }, [cid]);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    try {
      await api<any>(`/admin/whatsapp/schedules?company_id=${cid}`,
        { method: "POST", body: { ...form, target: { mode: "company" } } });
      setBanner({ kind: "ok", msg: "Schedule created." });
      setCreating(false); load();
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || "Failed" }); }
  };
  const del = async (id: string) => {
    try { await api<any>(`/admin/whatsapp/schedules/${id}`, { method: "DELETE" }); load(); }
    catch { /* noop */ }
  };

  return (
    <ScrollView contentContainerStyle={st.body}>
      <Pressable style={[st.btn, { backgroundColor: WA_GREEN }]}
        onPress={() => setCreating(true)} testID="wa-sched-new">
        <Ionicons name="add" size={16} color="#fff" />
        <Text style={st.btnText}>New Schedule</Text>
      </Pressable>
      <Text style={st.hintSmall}>
        Birthday / anniversary / festival greetings are automatic — enable them in
        WhatsApp Configuration → Automatic Notifications. Use schedules for recurring custom messages.
      </Text>
      {rows.map((s) => (
        <View key={s.schedule_id} style={st.card}>
          <View style={st.rowBetween}>
            <View style={{ flex: 1 }}>
              <Text style={{ color: colors.text, fontWeight: "700", fontSize: 14 }}>{s.title}</Text>
              <Text style={{ color: colors.muted, fontSize: 12 }}>
                {s.type} · {s.time} · {s.category}
                {s.active === false ? " · inactive" : ""}
              </Text>
              <Text style={{ color: colors.muted, fontSize: 11 }}>
                next: {(s.next_run_at || "—").replace("T", " ").slice(0, 16)}
              </Text>
            </View>
            <Pressable style={{ padding: 8 }} onPress={() => del(s.schedule_id)}>
              <Ionicons name="trash-outline" size={17} color="#DC2626" />
            </Pressable>
          </View>
        </View>
      ))}
      {!rows.length && <Text style={{ color: colors.muted, textAlign: "center" }}>No schedules.</Text>}

      <Modal visible={creating} transparent animationType="fade" onRequestClose={() => setCreating(false)}>
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <Text style={st.cardTitle}>New Schedule</Text>
            <Text style={st.label}>Title</Text>
            <TextInput style={st.input} value={form.title || ""}
              onChangeText={(v) => setForm({ ...form, title: v })} />
            <Text style={st.label}>Repeat</Text>
            <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
              {["once", "daily", "weekly", "monthly"].map((t) => (
                <Pressable key={t} style={[st.chip, form.type === t && st.chipActive]}
                  onPress={() => setForm({ ...form, type: t })}>
                  <Text style={[st.chipText, form.type === t && { color: "#fff" }]}>{t}</Text>
                </Pressable>
              ))}
            </View>
            {form.type === "once" && (
              <>
                <Text style={st.label}>Date (YYYY-MM-DD)</Text>
                <TextInput style={st.input} value={form.date || ""} autoCapitalize="none"
                  onChangeText={(v) => setForm({ ...form, date: v })} />
              </>
            )}
            <Text style={st.label}>Time (HH:MM, IST)</Text>
            <TextInput style={st.input} value={form.time || ""} autoCapitalize="none"
              onChangeText={(v) => setForm({ ...form, time: v })} />
            <Text style={st.label}>Message</Text>
            <TextInput style={[st.input, { minHeight: 80, textAlignVertical: "top" }]}
              multiline value={form.custom_body || ""}
              onChangeText={(v) => setForm({ ...form, custom_body: v })} />
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <Pressable style={[st.btn, { flex: 1, backgroundColor: colors.border }]}
                onPress={() => setCreating(false)}>
                <Text style={[st.btnText, { color: colors.text }]}>Cancel</Text>
              </Pressable>
              <Pressable style={[st.btn, { flex: 1, backgroundColor: WA_GREEN }]} onPress={create}>
                <Text style={st.btnText}>Create</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

/* --------------------------------------------------------------- Reports */
function ReportsTab({ cid }: { cid: string }) {
  const [groupBy, setGroupBy] = useState("date");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [rows, setRows] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const qs = () => {
    const p = new URLSearchParams({ company_id: cid, group_by: groupBy });
    if (from) p.set("date_from", from);
    if (to) p.set("date_to", to);
    return p.toString();
  };
  const load = async () => {
    setLoading(true);
    try {
      const r = await api<any>(`/admin/whatsapp/report?${qs()}&fmt=json`);
      setRows(r.rows || []);
    } catch { /* noop */ } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, [cid, groupBy]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <ScrollView contentContainerStyle={st.body}>
      <View style={st.card}>
        <Text style={st.cardTitle}>Delivery Reports</Text>
        <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
          {[["date", "Daily"], ["category", "Template-wise"]].map(([k, l]) => (
            <Pressable key={k} style={[st.chip, groupBy === k && st.chipActive]}
              onPress={() => setGroupBy(k)}>
              <Text style={[st.chipText, groupBy === k && { color: "#fff" }]}>{l}</Text>
            </Pressable>
          ))}
        </View>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <TextInput style={[st.input, { flex: 1 }]} value={from} onChangeText={setFrom}
            placeholder="From YYYY-MM-DD" placeholderTextColor={colors.muted} autoCapitalize="none" />
          <TextInput style={[st.input, { flex: 1 }]} value={to} onChangeText={setTo}
            placeholder="To YYYY-MM-DD" placeholderTextColor={colors.muted} autoCapitalize="none" />
          <Pressable style={[st.btn, { backgroundColor: "#0EA5E9", paddingHorizontal: 14, marginTop: 0 }]}
            onPress={load}>
            <Text style={st.btnText}>Go</Text>
          </Pressable>
        </View>
        <View style={{ flexDirection: "row", gap: 8, marginTop: 8 }}>
          <Pressable style={[st.btn, { flex: 1, backgroundColor: "#16A34A" }]}
            onPress={() => dlBinary(`/admin/whatsapp/report?${qs()}&fmt=xlsx`, "whatsapp_report.xlsx")}
            testID="wa-report-xlsx">
            <Ionicons name="download-outline" size={15} color="#fff" />
            <Text style={st.btnText}>Excel</Text>
          </Pressable>
          <Pressable style={[st.btn, { flex: 1, backgroundColor: "#DC2626" }]}
            onPress={() => dlBinary(`/admin/whatsapp/report?${qs()}&fmt=pdf`, "whatsapp_report.pdf")}
            testID="wa-report-pdf">
            <Ionicons name="document-outline" size={15} color="#fff" />
            <Text style={st.btnText}>PDF</Text>
          </Pressable>
        </View>
      </View>
      <View style={st.card}>
        {loading ? <ActivityIndicator color={WA_GREEN} /> : (
          <>
            <View style={[st.tableRow, { borderBottomWidth: 1, borderBottomColor: colors.border }]}>
              {[groupBy === "date" ? "Date" : "Template", "Total", "Sent", "Dlvd", "Read", "Fail", "Pend"].map((h, i) => (
                <Text key={h} style={[st.th, i === 0 && { flex: 2, textAlign: "left" }]}>{h}</Text>
              ))}
            </View>
            {rows.map((r) => (
              <View key={String(r.group)} style={st.tableRow}>
                <Text style={[st.td, { flex: 2, textAlign: "left" }]}>{String(r.group)}</Text>
                <Text style={st.td}>{r.total}</Text>
                <Text style={st.td}>{r.sent}</Text>
                <Text style={st.td}>{r.delivered}</Text>
                <Text style={st.td}>{r.read}</Text>
                <Text style={[st.td, { color: r.failed ? "#DC2626" : colors.muted }]}>{r.failed}</Text>
                <Text style={st.td}>{r.pending}</Text>
              </View>
            ))}
            {!rows.length && <Text style={{ color: colors.muted, fontSize: 12 }}>No data.</Text>}
          </>
        )}
      </View>
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.xs,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.card,
  },
  title: { fontSize: 17, fontWeight: "700", color: colors.text },
  firmDd: {
    flexDirection: "row", alignItems: "center", gap: 4, maxWidth: 190,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 8, paddingVertical: 6,
  },
  firmDdText: { color: colors.text, fontSize: 12.5, flexShrink: 1 },
  ddList: { backgroundColor: colors.card, borderBottomWidth: 1, borderColor: colors.border, maxHeight: 240 },
  ddItem: { paddingHorizontal: 16, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  tabRow: { paddingHorizontal: spacing.sm, paddingVertical: spacing.xs, gap: 6 },
  tabBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: 999,
    backgroundColor: colors.card, borderWidth: 1, borderColor: colors.border,
  },
  tabBtnActive: { backgroundColor: WA_GREEN, borderColor: WA_GREEN },
  tabText: { fontSize: 12.5, color: colors.muted, fontWeight: "600" },
  banner: {
    flexDirection: "row", alignItems: "center", gap: 8,
    marginHorizontal: spacing.md, marginTop: spacing.xs,
    borderRadius: radius.md, padding: spacing.sm,
  },
  body: { padding: spacing.md, gap: spacing.md, maxWidth: 900, width: "100%", alignSelf: "center" },
  card: {
    backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, gap: 4,
  },
  cardTitle: { fontSize: 14.5, fontWeight: "700", color: colors.text },
  label: { fontSize: 12.5, color: colors.muted, marginTop: 8, marginBottom: 4 },
  hintSmall: { fontSize: 11.5, color: colors.muted, marginTop: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 8 : 6,
    color: colors.text, backgroundColor: colors.background, fontSize: 13.5,
  },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderRadius: radius.md, paddingVertical: 12, minHeight: 44,
  },
  btnText: { color: "#fff", fontWeight: "700", fontSize: 13.5 },
  chip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingHorizontal: 10, paddingVertical: 6, backgroundColor: colors.card,
  },
  chipActive: { backgroundColor: WA_GREEN, borderColor: WA_GREEN },
  chipText: { fontSize: 12, color: colors.text },
  kpiGrid: { flexDirection: "row", flexWrap: "wrap", gap: spacing.sm },
  kpiCard: {
    flexGrow: 1, flexBasis: 150, backgroundColor: colors.card,
    borderRadius: radius.lg, borderWidth: 1, borderColor: colors.border,
    padding: spacing.md, gap: 2,
  },
  kpiValue: { fontSize: 22, fontWeight: "800", color: colors.text },
  kpiLabel: { fontSize: 11.5, color: colors.muted },
  rowBetween: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 5, gap: spacing.sm,
  },
  empRow: {
    flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  msgRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.card, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: spacing.sm,
  },
  statusPill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  modalWrap: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)", alignItems: "center",
    justifyContent: "center", padding: spacing.md,
  },
  modalCard: {
    backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md,
    width: "100%", maxWidth: 540,
  },
  waBubble: {
    backgroundColor: "#fff", borderRadius: 10, padding: 12, borderTopLeftRadius: 2,
    marginTop: 6,
  },
  tableRow: { flexDirection: "row", alignItems: "center", paddingVertical: 6 },
  th: { flex: 1, fontSize: 11, fontWeight: "700", color: colors.muted, textAlign: "right" },
  td: { flex: 1, fontSize: 12, color: colors.text, textAlign: "right" },
});
