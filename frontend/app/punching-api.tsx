/**
 * Iter 561 (user spec) — API Integration Master: Secure Punching Data
 * Push API (Settings → API Integration → Punching API).
 *
 * Super Admin only. Manage B2B API clients (per-company credentials,
 * IP whitelist, machine codes, batch/rate limits, activate/block,
 * credential rotation), view API request logs, and copy the vendor
 * integration document. Secrets are shown ONCE at generation.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Modal, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type Client = {
  client_id: string;
  name: string;
  company_id: string;
  company_code: string;
  environment?: string;
  api_version?: string;
  allowed_ips?: string[];
  machine_codes?: string[];
  max_batch?: number;
  rate_limit?: number;
  status?: string;
  blocked?: boolean;
  created_at?: string;
  expiry_date?: string | null;
  last_request_at?: string;
  last_success_at?: string;
  last_failed_at?: string;
};

type Log = {
  log_id: string; at: string; client_id: string; company_code: string;
  request_id: string; source_ip: string; received: number; accepted: number;
  duplicate: number; failed: number; http_status: number;
  processing_ms: number; error?: string; security_failure?: string;
};

function showMsg(msg: string, title = "API Integration") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

const fmtAt = (s?: string) => (s ? s.slice(0, 16).replace("T", " ") : "—");

export default function ApiIntegrationScreen() {
  const { user, loading: authLoading } = useAuth();
  const isSuper = user?.role === "super_admin";

  const [tab, setTab] = useState<"clients" | "logs">("clients");
  const [clients, setClients] = useState<Client[]>([]);
  const [logs, setLogs] = useState<Log[]>([]);
  const [companies, setCompanies] = useState<{ company_id: string; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  // create/edit modal
  const [showEditor, setShowEditor] = useState(false);
  const [editing, setEditing] = useState<Client | null>(null);
  const [fName, setFName] = useState("");
  const [fCompanyId, setFCompanyId] = useState("");
  const [fCode, setFCode] = useState("");
  const [fIps, setFIps] = useState("");
  const [fMachines, setFMachines] = useState("");
  const [fBatch, setFBatch] = useState("1000");
  const [fRate, setFRate] = useState("60");
  const [fEnv, setFEnv] = useState("production");
  const [fExpiry, setFExpiry] = useState("");

  // credentials shown ONCE
  const [creds, setCreds] = useState<{ client_id: string; api_key?: string; secret_key?: string } | null>(null);

  // Iter 562 — Test Console
  const [tcClient, setTcClient] = useState<Client | null>(null);
  const [tcKey, setTcKey] = useState("");
  const [tcEmp, setTcEmp] = useState("");
  const [tcOut, setTcOut] = useState<{ curl?: string; python?: string; note?: string; live_status?: number; live_response?: any } | null>(null);
  const [tcBusy, setTcBusy] = useState(false);

  // log filters
  const [lgStatus, setLgStatus] = useState("");
  const [lgClient, setLgClient] = useState("");
  const [lgFrom, setLgFrom] = useState("");
  const [lgTo, setLgTo] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ clients: Client[] }>("/admin/punch-api/clients");
      setClients(r.clients || []);
      const c = await api<{ companies: { company_id: string; name: string }[] }>("/companies?lite=1");
      setCompanies(c.companies || []);
    } catch (e: any) {
      showMsg(e?.message || "Could not load API clients");
    } finally { setLoading(false); }
  }, []);

  const loadLogs = useCallback(async () => {
    setLoading(true);
    try {
      const p = new URLSearchParams();
      if (lgStatus) p.set("status", lgStatus);
      if (lgClient.trim()) p.set("client_id", lgClient.trim());
      if (lgFrom) p.set("from_date", lgFrom);
      if (lgTo) p.set("to_date", lgTo);
      const r = await api<{ logs: Log[] }>(`/admin/punch-api/logs?${p.toString()}`);
      setLogs(r.logs || []);
    } catch (e: any) {
      showMsg(e?.message || "Could not load logs");
    } finally { setLoading(false); }
  }, [lgStatus, lgClient, lgFrom, lgTo]);

  useEffect(() => { if (isSuper) load(); }, [isSuper, load]);
  useEffect(() => { if (isSuper && tab === "logs") loadLogs(); }, [isSuper, tab]); // eslint-disable-line react-hooks/exhaustive-deps

  const openCreate = () => {
    setEditing(null);
    setFName(""); setFCompanyId(companies[0]?.company_id || ""); setFCode("");
    setFIps(""); setFMachines(""); setFBatch("1000"); setFRate("60");
    setFEnv("production"); setFExpiry("");
    setShowEditor(true);
  };
  const openEdit = (c: Client) => {
    setEditing(c);
    setFName(c.name); setFCompanyId(c.company_id); setFCode(c.company_code);
    setFIps((c.allowed_ips || []).join(", "));
    setFMachines((c.machine_codes || []).join(", "));
    setFBatch(String(c.max_batch || 1000)); setFRate(String(c.rate_limit || 60));
    setFEnv(c.environment || "production"); setFExpiry(c.expiry_date || "");
    setShowEditor(true);
  };

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const ips = fIps.split(",").map((s) => s.trim()).filter(Boolean);
      const machines = fMachines.split(",").map((s) => s.trim()).filter(Boolean);
      if (editing) {
        await api(`/admin/punch-api/clients/${editing.client_id}`, {
          method: "PATCH",
          body: {
            name: fName, allowed_ips: ips, machine_codes: machines,
            max_batch: Number(fBatch) || 1000, rate_limit: Number(fRate) || 60,
            environment: fEnv, expiry_date: fExpiry || null,
          },
        });
        setShowEditor(false);
      } else {
        const r = await api<{ credentials: any }>("/admin/punch-api/clients", {
          method: "POST",
          body: {
            name: fName, company_id: fCompanyId, company_code: fCode,
            allowed_ips: ips, machine_codes: machines,
            max_batch: Number(fBatch) || 1000, rate_limit: Number(fRate) || 60,
            environment: fEnv, expiry_date: fExpiry || null,
          },
        });
        setShowEditor(false);
        setCreds(r.credentials);
      }
      await load();
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  const rotate = async (c: Client, what: "key" | "secret" | "both") => {
    const ok = Platform.OS === "web"
      ? globalThis.confirm?.(`Rotate ${what === "both" ? "API Key + Secret" : what === "key" ? "API Key" : "Secret Key"} for ${c.client_id}? The vendor must update their integration immediately.`)
      : true;
    if (!ok) return;
    try {
      const r = await api<{ credentials: any }>(`/admin/punch-api/clients/${c.client_id}/rotate`, {
        method: "POST", body: { what },
      });
      setCreds(r.credentials);
    } catch (e: any) { showMsg(e?.message || "Rotate failed"); }
  };

  const patchFlag = async (c: Client, body: Record<string, any>) => {
    try {
      await api(`/admin/punch-api/clients/${c.client_id}`, { method: "PATCH", body });
      await load();
    } catch (e: any) { showMsg(e?.message || "Update failed"); }
  };

  const deleteOne = async (c: Client) => {
    const ok = Platform.OS === "web"
      ? globalThis.confirm?.(`Delete API client ${c.client_id} (${c.name})? The vendor loses access immediately.`)
      : true;
    if (!ok) return;
    try {
      await api(`/admin/punch-api/clients/${c.client_id}`, { method: "DELETE" });
      setClients((prev) => prev.filter((x) => x.client_id !== c.client_id));
    } catch (e: any) { showMsg(e?.message || "Delete failed"); }
  };

  const copyDocs = async () => {
    try {
      const base = Platform.OS === "web" ? `?base_url=${encodeURIComponent(globalThis.location?.origin || "")}` : "";
      const r = await api<{ markdown: string; endpoint: string }>(`/admin/punch-api/docs${base}`);
      if (Platform.OS === "web" && (navigator as any)?.clipboard) {
        await (navigator as any).clipboard.writeText(r.markdown);
        showMsg("Vendor integration document copied to clipboard — paste it into an email/Word file for the client.");
      }
    } catch (e: any) { showMsg(e?.message || "Could not fetch docs"); }
  };

  const copyTxt = async (t: string) => {
    if (Platform.OS === "web" && (navigator as any)?.clipboard) {
      await (navigator as any).clipboard.writeText(t);
      showMsg("Copied");
    }
  };

  // Iter 562 — generate a signed sample request / fire a live test.
  const runTestConsole = async (sendNow: boolean) => {
    if (!tcClient || tcBusy) return;
    if (!tcKey.trim()) { showMsg("Paste the client's API Key first"); return; }
    setTcBusy(true);
    try {
      const r = await api<any>(`/admin/punch-api/clients/${tcClient.client_id}/test-console`, {
        method: "POST",
        body: {
          api_key: tcKey.trim(),
          employee_code: tcEmp.trim() || undefined,
          base_url: Platform.OS === "web" ? globalThis.location?.origin : undefined,
          send_now: sendNow,
        },
      });
      setTcOut(r);
    } catch (e: any) {
      showMsg(e?.message || "Test console failed");
    } finally { setTcBusy(false); }
  };

  if (authLoading) {
    return <View style={st.root}><View style={st.center}><ActivityIndicator color={colors.brandPrimary} /></View></View>;
  }
  if (!isSuper) {
    return (
      <View style={st.root}><View style={st.center}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
        <Text style={st.dimTxt}>Super Admin only</Text>
      </View></View>
    );
  }

  return (
    <View style={st.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={st.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={st.h1}>API Integration — Punching API</Text>
            <Text style={st.hsub}>Secure B2B punch-push API (POST /api/v1/punching)</Text>
          </View>
          <Pressable onPress={openCreate} style={st.addBtn} testID="api-add-client">
            <Ionicons name="add" size={14} color="#fff" />
            <Text style={st.addTxt}>New Client</Text>
          </Pressable>
        </View>
        <View style={st.tabs}>
          {(["clients", "logs"] as const).map((t) => (
            <Pressable key={t} onPress={() => setTab(t)}
              style={[st.tabBtn, tab === t && st.tabOn]} testID={`api-tab-${t}`}>
              <Text style={[st.tabTxt, tab === t && st.tabTxtOn]}>
                {t === "clients" ? "API Clients" : "API Logs"}
              </Text>
            </Pressable>
          ))}
          <View style={{ flex: 1 }} />
          <Pressable onPress={copyDocs} style={st.docsBtn} testID="api-copy-docs">
            <Ionicons name="document-text-outline" size={13} color={colors.brandPrimary} />
            <Text style={st.docsTxt}>Copy Vendor Docs</Text>
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={st.scroll}>
        {tab === "clients" ? (
          <>
            {/* Iter 564 (user request) — the exact API URL for the vendor */}
            {Platform.OS === "web" ? (
              <View style={st.urlCard}>
                <Ionicons name="link-outline" size={15} color="#15803D" />
                <Text style={st.urlLbl}>API URL for the vendor:</Text>
                <Text style={st.urlVal} selectable numberOfLines={1} testID="api-endpoint-url">
                  {`POST ${globalThis.location?.origin || ""}/api/v1/punching`}
                </Text>
                <Pressable onPress={() => copyTxt(`${globalThis.location?.origin || ""}/api/v1/punching`)} hitSlop={6}>
                  <Ionicons name="copy-outline" size={15} color="#15803D" />
                </Pressable>
              </View>
            ) : null}
            <View style={st.noteCard}>
              <Ionicons name="shield-checkmark-outline" size={16} color={colors.brandPrimary} />
              <Text style={st.noteTxt}>
                Vendors can ONLY push punches (HTTPS + IP whitelist + API key + HMAC signature +
                replay protection + rate limits + duplicate-transaction protection). No read access,
                no salary/PF/PAN/bank data ever. Secret keys are shown ONCE — store them safely.
              </Text>
            </View>
            {loading ? <ActivityIndicator style={{ margin: 30 }} color={colors.brandPrimary} /> :
              clients.length === 0 ? (
                <Text style={st.dimTxt}>No API clients yet — press “New Client” to onboard a company (e.g. Sangam Farms).</Text>
              ) : clients.map((c) => (
                <View key={c.client_id} style={[st.card, (c.status !== "active" || c.blocked) && { opacity: 0.6 }]}>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                    <Text style={st.name}>{c.name}</Text>
                    <View style={st.pill}><Text style={st.pillTxt}>{c.client_id}</Text></View>
                    <View style={[st.pill, { backgroundColor: "#EFF6FF" }]}><Text style={[st.pillTxt, { color: "#1D4ED8" }]}>{c.company_code}</Text></View>
                    <View style={[st.pill, { backgroundColor: c.environment === "uat" ? "#FEF3C7" : "#DCFCE7" }]}>
                      <Text style={[st.pillTxt, { color: c.environment === "uat" ? "#B45309" : "#15803D" }]}>
                        {(c.environment || "production").toUpperCase()}
                      </Text>
                    </View>
                    {c.blocked ? <View style={[st.pill, { backgroundColor: "#FEE2E2" }]}><Text style={[st.pillTxt, { color: "#DC2626" }]}>BLOCKED</Text></View> : null}
                    {c.status !== "active" ? <View style={[st.pill, { backgroundColor: "#F1F5F9" }]}><Text style={st.pillTxt}>INACTIVE</Text></View> : null}
                  </View>
                  <Text style={st.sub}>
                    Firm: {companies.find((x) => x.company_id === c.company_id)?.name || c.company_id}
                    {"   ·   "}Batch {c.max_batch || 1000}/req · {c.rate_limit || 60} req/min
                    {c.expiry_date ? `   ·   Expires ${c.expiry_date}` : ""}
                  </Text>
                  <Text style={st.sub}>
                    IPs: {(c.allowed_ips || []).join(", ") || "any (⚠ add a whitelist!)"}
                    {"   ·   "}Machines: {(c.machine_codes || []).join(", ") || "any"}
                  </Text>
                  <Text style={st.sub}>
                    Last request: {fmtAt(c.last_request_at)} · Last success: {fmtAt(c.last_success_at)} · Last failed: {fmtAt(c.last_failed_at)}
                  </Text>
                  <View style={st.actions}>
                    <Pressable onPress={() => openEdit(c)} style={st.actBtn}>
                      <Ionicons name="create-outline" size={13} color={colors.brandPrimary} />
                      <Text style={st.actTxt}>Edit / IPs</Text>
                    </Pressable>
                    <Pressable onPress={() => rotate(c, "key")} style={st.actBtn}>
                      <Ionicons name="key-outline" size={13} color="#B45309" />
                      <Text style={[st.actTxt, { color: "#B45309" }]}>Rotate Key</Text>
                    </Pressable>
                    <Pressable onPress={() => rotate(c, "secret")} style={st.actBtn}>
                      <Ionicons name="lock-closed-outline" size={13} color="#B45309" />
                      <Text style={[st.actTxt, { color: "#B45309" }]}>Rotate Secret</Text>
                    </Pressable>
                    <Pressable onPress={() => patchFlag(c, { status: c.status === "active" ? "inactive" : "active" })} style={st.actBtn}>
                      <Ionicons name={c.status === "active" ? "pause-outline" : "play-outline"} size={13} color="#0369A1" />
                      <Text style={[st.actTxt, { color: "#0369A1" }]}>{c.status === "active" ? "Deactivate" : "Activate"}</Text>
                    </Pressable>
                    <Pressable onPress={() => patchFlag(c, { blocked: !c.blocked })} style={st.actBtn}>
                      <Ionicons name={c.blocked ? "shield-checkmark-outline" : "ban-outline"} size={13} color="#DC2626" />
                      <Text style={[st.actTxt, { color: "#DC2626" }]}>{c.blocked ? "Unblock" : "Block"}</Text>
                    </Pressable>
                    <Pressable onPress={() => { setTcClient(c); setTcKey(""); setTcEmp(""); setTcOut(null); }} style={st.actBtn} testID={`api-test-${c.client_id}`}>
                      <Ionicons name="flask-outline" size={13} color="#7C3AED" />
                      <Text style={[st.actTxt, { color: "#7C3AED" }]}>Test Console</Text>
                    </Pressable>
                    <Pressable onPress={() => { setTab("logs"); setLgClient(c.client_id); }} style={st.actBtn}>
                      <Ionicons name="list-outline" size={13} color={colors.onSurfaceSecondary} />
                      <Text style={[st.actTxt, { color: colors.onSurfaceSecondary }]}>Logs</Text>
                    </Pressable>
                    <Pressable onPress={() => deleteOne(c)} style={st.actBtn}>
                      <Ionicons name="trash-outline" size={13} color="#DC2626" />
                      <Text style={[st.actTxt, { color: "#DC2626" }]}>Delete</Text>
                    </Pressable>
                  </View>
                </View>
              ))}
          </>
        ) : (
          <>
            <View style={st.filterRow}>
              {Platform.OS === "web" ? (
                <>
                  <select value={lgStatus} onChange={(e) => setLgStatus((e.target as HTMLSelectElement).value)} style={WEB_SEL}>
                    <option value="">All</option>
                    <option value="success">Success</option>
                    <option value="failed">Failed</option>
                  </select>
                  <input type="date" value={lgFrom} onChange={(e) => setLgFrom((e.target as HTMLInputElement).value)} style={WEB_SEL} />
                  <input type="date" value={lgTo} onChange={(e) => setLgTo((e.target as HTMLInputElement).value)} style={WEB_SEL} />
                </>
              ) : null}
              <TextInput style={st.fInput} value={lgClient} onChangeText={setLgClient}
                placeholder="Client ID" placeholderTextColor={colors.onSurfaceTertiary} />
              <Pressable onPress={loadLogs} style={st.addBtn}>
                <Ionicons name="search-outline" size={13} color="#fff" />
                <Text style={st.addTxt}>Filter</Text>
              </Pressable>
            </View>
            {loading ? <ActivityIndicator style={{ margin: 30 }} color={colors.brandPrimary} /> :
              logs.length === 0 ? <Text style={st.dimTxt}>No API requests logged yet.</Text> :
                logs.map((l) => (
                  <View key={l.log_id} style={st.logRow}>
                    <View style={{ flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
                      <View style={[st.pill, { backgroundColor: l.http_status === 200 ? "#DCFCE7" : "#FEE2E2" }]}>
                        <Text style={[st.pillTxt, { color: l.http_status === 200 ? "#15803D" : "#DC2626" }]}>{l.http_status}</Text>
                      </View>
                      <Text style={st.logAt}>{fmtAt(l.at)}</Text>
                      <Text style={st.logMeta}>{l.client_id} · {l.company_code || "—"} · {l.source_ip}</Text>
                    </View>
                    <Text style={st.logMeta}>
                      Req {l.request_id || "—"} · recv {l.received} / ok {l.accepted} / dup {l.duplicate} / fail {l.failed} · {l.processing_ms} ms
                    </Text>
                    {(l.security_failure || l.error) ? (
                      <Text style={st.logErr}>{l.security_failure || l.error}</Text>
                    ) : null}
                  </View>
                ))}
          </>
        )}
        <View style={{ height: 40 }} />
      </ScrollView>

      {/* Create / Edit modal */}
      <Modal visible={showEditor} transparent animationType="fade" onRequestClose={() => setShowEditor(false)}>
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <ScrollView>
              <Text style={st.modalTitle}>{editing ? `Edit — ${editing.client_id}` : "New API Client"}</Text>
              <Text style={st.lbl}>Client / Company display name *</Text>
              <TextInput style={st.input} value={fName} onChangeText={setFName}
                placeholder="e.g. Sangam Farms" placeholderTextColor={colors.onSurfaceTertiary} testID="api-f-name" />
              {!editing ? (
                <>
                  <Text style={st.lbl}>Map to Firm (punches store into this firm) *</Text>
                  {Platform.OS === "web" ? (
                    <select value={fCompanyId} onChange={(e) => setFCompanyId((e.target as HTMLSelectElement).value)} style={WEB_SEL}>
                      <option value="">— select firm —</option>
                      {companies.map((c) => <option key={c.company_id} value={c.company_id}>{c.name}</option>)}
                    </select>
                  ) : null}
                  <Text style={st.lbl}>Company Code (vendor sends this in JSON) *</Text>
                  <TextInput style={st.input} value={fCode} onChangeText={(v) => setFCode(v.toUpperCase())}
                    autoCapitalize="characters" placeholder="e.g. SANGAM001"
                    placeholderTextColor={colors.onSurfaceTertiary} testID="api-f-code" />
                </>
              ) : null}
              <Text style={st.lbl}>Allowed IPs (comma separated — leave blank = any ⚠)</Text>
              <TextInput style={st.input} value={fIps} onChangeText={setFIps}
                placeholder="203.0.113.10, 203.0.113.11" placeholderTextColor={colors.onSurfaceTertiary} />
              <Text style={st.lbl}>Machine Codes allowed (comma separated — blank = any)</Text>
              <TextInput style={st.input} value={fMachines} onChangeText={setFMachines}
                placeholder="BIO001, BIO002" placeholderTextColor={colors.onSurfaceTertiary} />
              <View style={{ flexDirection: "row", gap: 10 }}>
                <View style={{ flex: 1 }}>
                  <Text style={st.lbl}>Max punches / request</Text>
                  <TextInput style={st.input} value={fBatch} onChangeText={setFBatch} keyboardType="numeric" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={st.lbl}>Rate limit (req/min)</Text>
                  <TextInput style={st.input} value={fRate} onChangeText={setFRate} keyboardType="numeric" />
                </View>
              </View>
              <View style={{ flexDirection: "row", gap: 10 }}>
                <View style={{ flex: 1 }}>
                  <Text style={st.lbl}>Environment</Text>
                  {Platform.OS === "web" ? (
                    <select value={fEnv} onChange={(e) => setFEnv((e.target as HTMLSelectElement).value)} style={WEB_SEL}>
                      <option value="production">Production</option>
                      <option value="uat">UAT / Testing</option>
                    </select>
                  ) : null}
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={st.lbl}>Expiry date (optional)</Text>
                  {Platform.OS === "web" ? (
                    <input type="date" value={fExpiry} onChange={(e) => setFExpiry((e.target as HTMLInputElement).value)} style={WEB_SEL} />
                  ) : null}
                </View>
              </View>
              <View style={st.modalActions}>
                <Pressable onPress={() => setShowEditor(false)} style={[st.mBtn, st.mBtnGhost]}>
                  <Text style={st.mBtnGhostTxt}>Cancel</Text>
                </Pressable>
                <Pressable onPress={save} style={[st.mBtn, st.mBtnPrimary]} testID="api-f-save">
                  {busy ? <ActivityIndicator size="small" color="#fff" /> :
                    <Text style={st.mBtnPrimaryTxt}>{editing ? "Save changes" : "Create + Generate Credentials"}</Text>}
                </Pressable>
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Iter 562 — Test Console */}
      <Modal visible={!!tcClient} transparent animationType="fade" onRequestClose={() => setTcClient(null)}>
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <ScrollView>
              <Text style={st.modalTitle}>🧪 Test Console — {tcClient?.client_id}</Text>
              <Text style={st.credWarn}>
                Generates a fully SIGNED sample request with this client&apos;s real credentials
                (the server signs it with the stored Secret). Paste the API Key you saved at
                generation. &quot;Send Test Now&quot; fires a real request — it inserts a real punch
                if the employee code exists.
              </Text>
              <Text style={st.lbl}>API Key *</Text>
              <TextInput style={st.input} value={tcKey} onChangeText={setTcKey}
                autoCapitalize="none" placeholder="pk_…" placeholderTextColor={colors.onSurfaceTertiary}
                testID="api-tc-key" />
              <Text style={st.lbl}>Employee Code for the sample punch (optional)</Text>
              <TextInput style={st.input} value={tcEmp} onChangeText={setTcEmp}
                placeholder="e.g. 123" placeholderTextColor={colors.onSurfaceTertiary} />
              <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
                <Pressable onPress={() => runTestConsole(false)} style={[st.mBtn, st.mBtnGhost, { flex: 1 }]} testID="api-tc-generate">
                  {tcBusy ? <ActivityIndicator size="small" color={colors.brandPrimary} /> :
                    <Text style={st.mBtnGhostTxt}>Generate curl + Python</Text>}
                </Pressable>
                <Pressable onPress={() => runTestConsole(true)} style={[st.mBtn, st.mBtnPrimary, { flex: 1 }]} testID="api-tc-send">
                  {tcBusy ? <ActivityIndicator size="small" color="#fff" /> :
                    <Text style={st.mBtnPrimaryTxt}>Send Test Now</Text>}
                </Pressable>
              </View>
              {tcOut?.live_status !== undefined ? (
                <View style={[st.credRow, { marginTop: 10 }]}>
                  <Text style={st.lbl}>Live response — HTTP {tcOut.live_status}</Text>
                  <Text style={[st.credVal, { color: tcOut.live_status === 200 ? "#15803D" : "#DC2626" }]} selectable>
                    {JSON.stringify(tcOut.live_response, null, 2)}
                  </Text>
                </View>
              ) : null}
              {tcOut?.curl ? (
                <View style={st.credRow}>
                  <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                    <Text style={st.lbl}>curl (valid ±5 min)</Text>
                    <Pressable onPress={() => copyTxt(tcOut.curl!)} hitSlop={6}>
                      <Ionicons name="copy-outline" size={15} color={colors.brandPrimary} />
                    </Pressable>
                  </View>
                  <Text style={st.credVal} selectable>{tcOut.curl}</Text>
                </View>
              ) : null}
              {tcOut?.python ? (
                <View style={st.credRow}>
                  <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                    <Text style={st.lbl}>Python (signs fresh requests)</Text>
                    <Pressable onPress={() => copyTxt(tcOut.python!)} hitSlop={6}>
                      <Ionicons name="copy-outline" size={15} color={colors.brandPrimary} />
                    </Pressable>
                  </View>
                  <Text style={st.credVal} selectable>{tcOut.python}</Text>
                </View>
              ) : null}
              <View style={st.modalActions}>
                <Pressable onPress={() => setTcClient(null)} style={[st.mBtn, st.mBtnGhost]}>
                  <Text style={st.mBtnGhostTxt}>Close</Text>
                </Pressable>
              </View>
            </ScrollView>
          </View>
        </View>
      </Modal>

      {/* Credentials — shown ONCE */}
      <Modal visible={!!creds} transparent animationType="fade" onRequestClose={() => setCreds(null)}>
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <Text style={st.modalTitle}>🔐 Credentials — shown ONCE, save now</Text>
            <Text style={st.credWarn}>
              These will NEVER be displayed again. Share them with the vendor over a secure channel.
            </Text>
            {[["Client ID", creds?.client_id], ["API Key", creds?.api_key], ["Secret Key", creds?.secret_key]]
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <View key={k as string} style={st.credRow}>
                  <Text style={st.lbl}>{k}</Text>
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Text style={st.credVal} selectable numberOfLines={2}>{v}</Text>
                    <Pressable onPress={() => copyTxt(String(v))} hitSlop={6}>
                      <Ionicons name="copy-outline" size={16} color={colors.brandPrimary} />
                    </Pressable>
                  </View>
                </View>
              ))}
            <View style={st.modalActions}>
              <Pressable onPress={() => setCreds(null)} style={[st.mBtn, st.mBtnPrimary]}>
                <Text style={st.mBtnPrimaryTxt}>I have saved them</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const WEB_SEL: any = {
  border: `1px solid ${colors.border}`, borderRadius: 8, padding: "9px 10px",
  fontSize: 13, color: colors.onSurface, background: colors.background, width: "100%",
};

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  h1: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  hsub: { fontSize: 11, color: colors.onSurfaceTertiary },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
  },
  addTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  tabs: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.md, paddingVertical: 8,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  tabBtn: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: radius.pill, borderWidth: 1, borderColor: colors.border },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  docsBtn: { flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 10, paddingVertical: 7, borderRadius: radius.md, borderWidth: 1, borderColor: colors.brandPrimary },
  docsTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  scroll: { padding: spacing.md, ...(Platform.OS === "web" ? { maxWidth: 980, width: "100%", alignSelf: "center" } : {}) },
  noteCard: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    backgroundColor: "#EFF6FF", borderRadius: radius.lg,
    borderWidth: 1, borderColor: "#BFDBFE", padding: 12, marginBottom: 12,
  },
  noteTxt: { flex: 1, fontSize: 12, color: "#1E40AF", lineHeight: 17 },
  urlCard: {
    flexDirection: "row", gap: 8, alignItems: "center",
    backgroundColor: "#F0FDF4", borderRadius: radius.lg,
    borderWidth: 1, borderColor: "#BBF7D0", padding: 12, marginBottom: 10,
  },
  urlLbl: { fontSize: 12, fontWeight: "800", color: "#15803D" },
  urlVal: {
    flex: 1, fontSize: 12, fontWeight: "700", color: "#166534",
    fontFamily: Platform.OS === "web" ? "monospace" : undefined,
  },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 12, marginBottom: 10,
  },
  name: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 3 },
  pill: { backgroundColor: "#F1F5F9", paddingHorizontal: 7, paddingVertical: 2, borderRadius: radius.pill },
  pillTxt: { fontSize: 10, fontWeight: "800", color: colors.onSurfaceSecondary },
  actions: {
    flexDirection: "row", gap: 6, marginTop: 10, flexWrap: "wrap",
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.divider, paddingTop: 8,
  },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 9, paddingVertical: 6,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
  },
  actTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  filterRow: { flexDirection: "row", gap: 8, alignItems: "center", marginBottom: 12, flexWrap: "wrap" },
  fInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13, minWidth: 130,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  logRow: {
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, padding: 10, marginBottom: 8,
  },
  logAt: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  logMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 2 },
  logErr: { fontSize: 11, color: "#DC2626", marginTop: 3, fontWeight: "600" },
  modalWrap: { flex: 1, backgroundColor: "rgba(15,23,42,0.45)", alignItems: "center", justifyContent: "center", padding: 20 },
  modalCard: { backgroundColor: colors.surface, borderRadius: radius.lg, padding: 18, width: "100%", maxWidth: 540, maxHeight: "90%" },
  modalTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  lbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: Platform.OS === "web" ? 10 : 8,
    fontSize: 13, color: colors.onSurface, backgroundColor: colors.background,
  },
  modalActions: { flexDirection: "row", justifyContent: "flex-end", gap: 8, marginTop: 16 },
  mBtn: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md, alignItems: "center", justifyContent: "center", minWidth: 90 },
  mBtnGhost: { borderWidth: 1, borderColor: colors.border },
  mBtnGhostTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  mBtnPrimary: { backgroundColor: colors.brandPrimary },
  mBtnPrimaryTxt: { fontSize: 13, fontWeight: "800", color: "#fff" },
  credWarn: { fontSize: 12, color: "#B45309", backgroundColor: "#FFFBEB", padding: 8, borderRadius: radius.md, marginBottom: 4 },
  credRow: { marginBottom: 4 },
  credVal: { flex: 1, fontSize: 12, fontFamily: Platform.OS === "web" ? "monospace" : undefined, color: colors.onSurface, backgroundColor: colors.background, padding: 8, borderRadius: radius.md, borderWidth: 1, borderColor: colors.border },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8, padding: 40 },
  dimTxt: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 20 },
});
