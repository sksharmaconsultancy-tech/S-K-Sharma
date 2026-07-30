/**
 * Iter 395 — WhatsApp Configuration (per-firm Cloud API settings).
 * Credentials, queue behaviour, automation event toggles, webhook info,
 * connection test. Access: super_admin / company_admin / sub_admin.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Switch, Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const WA_GREEN = "#128C7E";
const WA_LIGHT = "#25D366";

const CRED_FIELDS: { key: string; label: string; hint?: string; secure?: boolean }[] = [
  { key: "business_number", label: "WhatsApp Business Number", hint: "e.g. 919876543210" },
  { key: "display_name", label: "Display Name" },
  { key: "phone_number_id", label: "Phone Number ID", hint: "From Meta → WhatsApp → API Setup" },
  { key: "waba_id", label: "Business Account ID (WABA)" },
  { key: "access_token", label: "Permanent Access Token", secure: true },
  { key: "webhook_verify_token", label: "Webhook Verify Token", hint: "Any secret string; also enter it in Meta webhook config" },
  { key: "webhook_secret", label: "Webhook Secret (App Secret)", secure: true, hint: "Meta App → Settings → Basic" },
  { key: "api_version", label: "API Version", hint: "e.g. v22.0" },
  { key: "default_country_code", label: "Default Country Code", hint: "91 for India" },
];

const QUEUE_NUM_FIELDS: { key: string; label: string }[] = [
  { key: "max_retries", label: "Maximum Retry Count" },
  { key: "daily_limit", label: "Daily Message Limit" },
  { key: "attachment_limit_mb", label: "Attachment Size Limit (MB)" },
  { key: "auto_delete_days", label: "Auto Delete Logs Older Than (days)" },
];

export default function WhatsAppConfigScreen() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [companies, setCompanies] = useState<{ company_id: string; name: string }[]>([]);
  const [cid, setCid] = useState<string>("");
  const [form, setForm] = useState<Record<string, any>>({});
  const [events, setEvents] = useState<{ key: string; label: string; group: string }[]>([]);
  const [configured, setConfigured] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [ddOpen, setDdOpen] = useState(false);

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

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true); setBanner(null);
    try {
      const r = await api<any>(`/admin/whatsapp/settings?company_id=${cid}`);
      setForm(r.settings || {});
      setEvents(r.automation_events || []);
      setConfigured(!!r.configured);
    } catch (e: any) {
      setBanner({ kind: "err", msg: e?.message || "Failed to load" });
    } finally { setLoading(false); }
  }, [cid]);
  useEffect(() => { load(); }, [load]);

  const save = async () => {
    setSaving(true); setBanner(null);
    try {
      const r = await api<any>(`/admin/whatsapp/settings?company_id=${cid}`,
        { method: "PUT", body: form });
      setForm(r.settings || {});
      setConfigured(!!r.configured);
      setBanner({ kind: "ok", msg: "Settings saved." });
    } catch (e: any) {
      setBanner({ kind: "err", msg: e?.message || "Save failed" });
    } finally { setSaving(false); }
  };

  const testConn = async () => {
    setTesting(true); setBanner(null);
    try {
      const r = await api<any>(`/admin/whatsapp/test-connection?company_id=${cid}`,
        { method: "POST", body: {} });
      if (r.ok) setBanner({ kind: "ok", msg: `Connected ✅ ${r.verified_name || ""} ${r.phone || ""} (quality: ${r.quality_rating || "—"})` });
      else setBanner({ kind: "err", msg: r.error || "Connection failed" });
    } catch (e: any) {
      setBanner({ kind: "err", msg: e?.message || "Connection failed" });
    } finally { setTesting(false); }
  };

  const groups = useMemo(() => {
    const g: Record<string, typeof events> = {};
    events.forEach((e) => { (g[e.group] = g[e.group] || []).push(e); });
    return g;
  }, [events]);

  const auto = form.automation || {};
  const firmName = companies.find((c) => c.company_id === cid)?.name || cid;

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={st.backBtn} testID="wa-cfg-back">
          <Ionicons name="arrow-back" size={22} color={colors.text} />
        </Pressable>
        <Ionicons name="logo-whatsapp" size={22} color={WA_LIGHT} />
        <Text style={st.title}>WhatsApp Configuration</Text>
        <View style={{ flex: 1 }} />
        <View style={[st.pill, { backgroundColor: configured ? "#DCFCE7" : "#FEF3C7" }]}>
          <Text style={{ color: configured ? "#166534" : "#92400E", fontSize: 12, fontWeight: "700" }}>
            {configured ? "CONFIGURED" : "PENDING CONFIG"}
          </Text>
        </View>
      </View>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={WA_GREEN} />
      ) : (
        <ScrollView contentContainerStyle={st.body}>
          {banner && (
            <View style={[st.banner, banner.kind === "ok" ? st.bannerOk : st.bannerErr]}>
              <Text style={{ color: banner.kind === "ok" ? "#166534" : "#991B1B" }}>{banner.msg}</Text>
            </View>
          )}

          {/* Firm selector */}
          {isSuper && (
            <View style={st.card}>
              <Text style={st.cardTitle}>Company / Firm</Text>
              <Pressable style={st.dd} onPress={() => setDdOpen(!ddOpen)} testID="wa-cfg-firm-dd">
                <Text style={st.ddText}>{firmName || "Select firm"}</Text>
                <Ionicons name={ddOpen ? "chevron-up" : "chevron-down"} size={16} color={colors.muted} />
              </Pressable>
              {ddOpen && (
                <View style={st.ddList}>
                  {companies.map((c) => (
                    <Pressable key={c.company_id} style={st.ddItem}
                      onPress={() => { setCid(c.company_id); setDdOpen(false); }}>
                      <Text style={{ color: c.company_id === cid ? WA_GREEN : colors.text }}>{c.name}</Text>
                    </Pressable>
                  ))}
                </View>
              )}
            </View>
          )}

          {/* Enable + credentials */}
          <View style={st.card}>
            <View style={st.rowBetween}>
              <Text style={st.cardTitle}>Enable WhatsApp</Text>
              <Switch value={!!form.enabled} testID="wa-cfg-enable"
                onValueChange={(v) => setForm({ ...form, enabled: v })}
                trackColor={{ true: WA_LIGHT }} />
            </View>
            <Text style={st.hint}>
              Enter your Meta WhatsApp Business Cloud API credentials below. Until configured,
              messages will queue and can be retried after setup.
            </Text>
            {CRED_FIELDS.map((f) => (
              <View key={f.key} style={st.field}>
                <Text style={st.label}>{f.label}</Text>
                <TextInput
                  style={st.input}
                  value={String(form[f.key] ?? "")}
                  secureTextEntry={false}
                  autoCapitalize="none"
                  placeholder={f.hint || ""}
                  placeholderTextColor={colors.muted}
                  onChangeText={(v) => setForm({ ...form, [f.key]: v })}
                  testID={`wa-cfg-${f.key}`}
                />
                {f.hint ? <Text style={st.hintSmall}>{f.hint}</Text> : null}
              </View>
            ))}
            <Pressable style={[st.btn, { backgroundColor: "#0EA5E9" }]} onPress={testConn}
              disabled={testing} testID="wa-cfg-test">
              {testing ? <ActivityIndicator color="#fff" size="small" /> : (
                <><Ionicons name="flash-outline" size={16} color="#fff" />
                  <Text style={st.btnText}>Test Connection</Text></>
              )}
            </Pressable>
          </View>

          {/* Webhook info */}
          <View style={st.card}>
            <Text style={st.cardTitle}>Webhook (Chatbot & Delivery Status)</Text>
            <Text style={st.hint}>
              In Meta App Dashboard → WhatsApp → Configuration, set the Callback URL to your
              portal domain + /api/whatsapp/webhook and use the Verify Token entered above.
              Subscribe to the &quot;messages&quot; webhook field.
            </Text>
            <View style={st.codeBox}>
              <Text style={st.codeText}>https://YOUR-DOMAIN/api/whatsapp/webhook</Text>
            </View>
            <Text style={st.hintSmall}>
              Chatbot keywords employees can send: SALARY, ATTENDANCE, LEAVE, PF, ESIC, HOLIDAY, PROFILE, BANK, HELP
            </Text>
          </View>

          {/* Queue settings */}
          <View style={st.card}>
            <Text style={st.cardTitle}>Message Queue</Text>
            <View style={st.rowBetween}>
              <Text style={st.label}>Queue Enabled</Text>
              <Switch value={form.queue_enabled !== false}
                onValueChange={(v) => setForm({ ...form, queue_enabled: v })}
                trackColor={{ true: WA_LIGHT }} />
            </View>
            <View style={st.rowBetween}>
              <Text style={st.label}>Retry Failed Messages</Text>
              <Switch value={form.retry_failed !== false}
                onValueChange={(v) => setForm({ ...form, retry_failed: v })}
                trackColor={{ true: WA_LIGHT }} />
            </View>
            {QUEUE_NUM_FIELDS.map((f) => (
              <View key={f.key} style={st.rowBetween}>
                <Text style={st.label}>{f.label}</Text>
                <TextInput style={[st.input, st.numInput]}
                  keyboardType="numeric"
                  value={String(form[f.key] ?? "")}
                  onChangeText={(v) => setForm({ ...form, [f.key]: Number(v.replace(/\D/g, "")) || 0 })} />
              </View>
            ))}
          </View>

          {/* Automation toggles */}
          <View style={st.card}>
            <Text style={st.cardTitle}>Automatic Notifications</Text>
            <Text style={st.hint}>
              Turn on the events that should automatically send WhatsApp messages for this firm.
            </Text>
            {Object.entries(groups).map(([g, evs]) => (
              <View key={g} style={{ marginTop: spacing.sm }}>
                <Text style={st.groupTitle}>{g}</Text>
                {evs.map((e) => (
                  <View key={e.key} style={st.rowBetween}>
                    <Text style={[st.label, { flex: 1 }]}>{e.label}</Text>
                    <Switch value={!!auto[e.key]} testID={`wa-auto-${e.key}`}
                      onValueChange={(v) =>
                        setForm({ ...form, automation: { ...auto, [e.key]: v } })}
                      trackColor={{ true: WA_LIGHT }} />
                  </View>
                ))}
              </View>
            ))}
          </View>

          <Pressable style={[st.btn, { backgroundColor: WA_GREEN, marginBottom: 40 }]}
            onPress={save} disabled={saving} testID="wa-cfg-save">
            {saving ? <ActivityIndicator color="#fff" size="small" /> : (
              <><Ionicons name="save-outline" size={16} color="#fff" />
                <Text style={st.btnText}>Save Configuration</Text></>
            )}
          </Pressable>
        </ScrollView>
      )}
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.border,
    backgroundColor: colors.card,
  },
  backBtn: { padding: 6 },
  title: { fontSize: 17, fontWeight: "700", color: colors.text },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  body: { padding: spacing.md, gap: spacing.md, maxWidth: 860, width: "100%", alignSelf: "center" },
  card: {
    backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, gap: spacing.xs,
  },
  cardTitle: { fontSize: 15, fontWeight: "700", color: colors.text },
  groupTitle: { fontSize: 13, fontWeight: "700", color: "#128C7E", marginBottom: 4, textTransform: "uppercase" },
  hint: { fontSize: 12.5, color: colors.muted, lineHeight: 18 },
  hintSmall: { fontSize: 11.5, color: colors.muted, marginTop: 2 },
  field: { marginTop: spacing.xs },
  label: { fontSize: 13, color: colors.text, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 8 : 6,
    color: colors.text, backgroundColor: colors.background, fontSize: 13.5,
  },
  numInput: { width: 110, textAlign: "right" },
  rowBetween: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingVertical: 6, gap: spacing.sm,
  },
  btn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    borderRadius: radius.md, paddingVertical: 12, marginTop: spacing.sm, minHeight: 44,
  },
  btnText: { color: "#fff", fontWeight: "700", fontSize: 14 },
  banner: { borderRadius: radius.md, padding: spacing.sm },
  bannerOk: { backgroundColor: "#DCFCE7" },
  bannerErr: { backgroundColor: "#FEE2E2" },
  dd: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 10,
  },
  ddText: { color: colors.text, fontSize: 13.5 },
  ddList: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, marginTop: 4, maxHeight: 260, overflow: "hidden" },
  ddItem: { paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border },
  codeBox: { backgroundColor: "#0F172A", borderRadius: radius.md, padding: spacing.sm, marginTop: 4 },
  codeText: { color: "#4ADE80", fontFamily: Platform.OS === "web" ? "monospace" : "Courier", fontSize: 12 },
});
