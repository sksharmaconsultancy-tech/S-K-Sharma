/**
 * Iter 607 — Secure Punch Phase 4: admin screen for
 *  · Verification Audit Log (every device/liveness/anti-spoof/face-match
 *    attempt with result + reason) — spec section 18.
 *  · Registered Devices (WebAuthn passkeys): list, revoke, approve/reject
 *    pending device-change requests — spec sections 2 & 7.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator,
  RefreshControl,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter, useLocalSearchParams } from "expo-router";

import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";
import { confirmYesNo } from "@/src/utils/confirm";

const fmtAt = (iso: string) => (iso || "").replace("T", " ").slice(0, 16);
const Pass = ({ ok, label }: { ok: boolean | undefined | null; label: string }) => (
  <View style={s.checkPill}>
    <Ionicons name={ok ? "checkmark-circle" : "close-circle"} size={13}
      color={ok ? "#059669" : "#DC2626"} />
    <Text style={[s.checkTxt, { color: ok ? "#059669" : "#DC2626" }]}>{label}</Text>
  </View>
);

export default function PunchVerificationAudit() {
  const router = useRouter();
  const params = useLocalSearchParams<{ tab?: string; user_id?: string }>();
  const { selectedCompanyId } = useSelectedCompany();
  const [tab, setTab] = useState<"audit" | "devices">(
    params.tab === "devices" ? "devices" : "audit");
  const [logs, setLogs] = useState<any[]>([]);
  const [devices, setDevices] = useState<any[]>([]);
  const [pending, setPending] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState("");
  const userFilter = (params.user_id as string) || "";

  const cidQ = selectedCompanyId ? `company_id=${selectedCompanyId}` : "";

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [a, d] = await Promise.all([
        api(`/admin/attendance/punch-verification-audit?${cidQ}`),
        api(`/admin/attendance/devices?${cidQ}${userFilter ? `&user_id=${userFilter}` : ""}`),
      ]);
      setLogs((a.logs || []).filter(
        (l: any) => !userFilter || l.user_id === userFilter));
      setDevices(d.devices || []);
      setPending(d.pending_requests || []);
    } catch (e: any) { setMsg(String(e?.message || e)); }
    finally { setLoading(false); }
  }, [cidQ, userFilter]);
  useEffect(() => { load(); }, [load]);

  const revoke = async (dev: any) => {
    const yes = await confirmYesNo(
      `Revoke ${dev.employee_name || dev.user_id}'s registered device${dev.device_label ? ` (${dev.device_label})` : ""}?\n\nIt will no longer authenticate attendance punches.`,
      "Revoke device");
    if (!yes) return;
    try {
      await api("/admin/attendance/devices/revoke", {
        method: "POST", body: { credential_ref: dev.credential_ref, reason: "admin_revoke" },
      });
      setMsg("Device revoked ✓"); await load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
  };

  const decide = async (req: any, approve: boolean) => {
    try {
      await api("/admin/attendance/devices/approve-change", {
        method: "POST", body: { request_id: req.request_id, approve },
      });
      setMsg(approve
        ? "Approved — the employee can now register the new phone ✓"
        : "Request rejected");
      await load();
    } catch (e: any) { setMsg(String(e?.message || e)); }
  };

  const activeDevices = devices.filter((d) => d.status === "active");
  const oldDevices = devices.filter((d) => d.status !== "active");

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={{ padding: 4 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Secure Punch Audit &amp; Devices</Text>
          <Text style={s.subtitle}>
            {userFilter ? "Filtered to one employee · " : ""}
            Verification attempts · registered passkey devices
          </Text>
        </View>
      </View>

      <View style={s.tabs}>
        <Pressable style={[s.tab, tab === "audit" && s.tabOn]} onPress={() => setTab("audit")}
          testID="pva-tab-audit">
          <Ionicons name="shield-checkmark-outline" size={15}
            color={tab === "audit" ? "#fff" : colors.onSurfaceSecondary} />
          <Text style={[s.tabTxt, tab === "audit" && { color: "#fff" }]}>
            Verification Audit ({logs.length})
          </Text>
        </Pressable>
        <Pressable style={[s.tab, tab === "devices" && s.tabOn]} onPress={() => setTab("devices")}
          testID="pva-tab-devices">
          <Ionicons name="phone-portrait-outline" size={15}
            color={tab === "devices" ? "#fff" : colors.onSurfaceSecondary} />
          <Text style={[s.tabTxt, tab === "devices" && { color: "#fff" }]}>
            Devices ({activeDevices.length}{pending.length ? ` · ${pending.length} pending` : ""})
          </Text>
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={s.body}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={load} tintColor={colors.brandPrimary} />}>
        {msg ? <Text style={s.msg}>{msg}</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}

        {/* ─── AUDIT LOG ─── */}
        {tab === "audit" && !loading ? (
          logs.length === 0 ? (
            <View style={s.empty}>
              <Ionicons name="shield-checkmark-outline" size={38} color={colors.onSurfaceTertiary} />
              <Text style={s.muted}>No verification attempts recorded yet.</Text>
            </View>
          ) : logs.map((l, i) => {
            const okRow = String(l.result || "").toUpperCase() === "SUCCESS";
            return (
              <View key={l.audit_id || i} style={s.card} testID={`pva-log-${i}`}>
                <View style={s.cardTop}>
                  <Text style={s.emp}>
                    {l.name || l.user_id}{l.employee_code ? ` (${l.employee_code})` : ""}
                  </Text>
                  <Text style={s.at}>{fmtAt(l.at)}</Text>
                  <View style={[s.pill, { backgroundColor: okRow ? "#05966918" : "#DC262618" }]}>
                    <Text style={[s.pillTxt, { color: okRow ? "#059669" : "#DC2626" }]}>
                      {String(l.result || "").toUpperCase()}
                    </Text>
                  </View>
                </View>
                <Text style={s.stage}>Stage: {l.stage || "—"}</Text>
                {okRow ? (
                  <View style={s.checkRow}>
                    <Pass ok label="Liveness" />
                    <Pass ok label="Anti-Spoof" />
                    <Pass ok label="Face Match" />
                  </View>
                ) : null}
                {l.face_match_score != null ? (
                  <Text style={s.meta}>Face match: {Number(l.face_match_score).toFixed(1)}%</Text>
                ) : null}
                {l.anti_spoof_score != null ? (
                  <Text style={s.meta}>Anti-spoof score: {Number(l.anti_spoof_score).toFixed(2)}</Text>
                ) : null}
                {l.reason ? <Text style={[s.meta, { color: "#DC2626" }]}>Reason: {String(l.reason).replace(/_/g, " ")}</Text> : null}
              </View>
            );
          })
        ) : null}

        {/* ─── DEVICES ─── */}
        {tab === "devices" && !loading ? (
          <>
            {pending.length > 0 ? (
              <>
                <Text style={s.secTitle}>Pending device-change requests</Text>
                {pending.map((r) => (
                  <View key={r.request_id} style={[s.card, { borderColor: "#FCD34D" }]}
                    testID={`pva-req-${r.request_id}`}>
                    <View style={s.cardTop}>
                      <Text style={s.emp}>
                        {r.employee_name || r.user_id}{r.employee_code ? ` (${r.employee_code})` : ""}
                      </Text>
                      <Text style={s.at}>{fmtAt(r.requested_at || r.created_at)}</Text>
                    </View>
                    {r.reason ? <Text style={s.meta}>Reason: {r.reason}</Text> : null}
                    <View style={s.btnRow}>
                      <Pressable style={[s.aBtn, { backgroundColor: "#059669" }]}
                        onPress={() => decide(r, true)} testID={`pva-approve-${r.request_id}`}>
                        <Text style={s.aBtnTxt}>Approve New Device</Text>
                      </Pressable>
                      <Pressable style={[s.aBtn, s.aBtnDanger]} onPress={() => decide(r, false)}>
                        <Text style={[s.aBtnTxt, { color: "#DC2626" }]}>Reject</Text>
                      </Pressable>
                    </View>
                  </View>
                ))}
              </>
            ) : null}

            <Text style={s.secTitle}>Active registered devices</Text>
            {activeDevices.length === 0 ? (
              <Text style={s.muted}>No active devices registered.</Text>
            ) : activeDevices.map((d) => (
              <View key={d.credential_ref} style={s.card} testID={`pva-dev-${d.credential_ref}`}>
                <View style={s.cardTop}>
                  <Text style={s.emp}>
                    {d.employee_name || d.user_id}{d.employee_code ? ` (${d.employee_code})` : ""}
                  </Text>
                  <View style={[s.pill, { backgroundColor: "#05966918" }]}>
                    <Text style={[s.pillTxt, { color: "#059669" }]}>REGISTERED ✓</Text>
                  </View>
                </View>
                <Text style={s.meta}>
                  Authentication: Passkey / WebAuthn
                  {d.device_label ? ` · ${d.device_label}` : ""}
                </Text>
                <Text style={s.meta}>
                  Registered: {fmtAt(d.registered_at)}
                  {d.last_used_at ? ` · Last auth: ${fmtAt(d.last_used_at)}` : " · Never used yet"}
                </Text>
                <View style={s.btnRow}>
                  <Pressable style={[s.aBtn, s.aBtnDanger]} onPress={() => revoke(d)}
                    testID={`pva-revoke-${d.credential_ref}`}>
                    <Ionicons name="ban-outline" size={14} color="#DC2626" />
                    <Text style={[s.aBtnTxt, { color: "#DC2626" }]}>Revoke Device</Text>
                  </Pressable>
                </View>
              </View>
            ))}

            {oldDevices.length > 0 ? (
              <>
                <Text style={s.secTitle}>Revoked / replaced devices</Text>
                {oldDevices.map((d) => (
                  <View key={d.credential_ref} style={[s.card, { opacity: 0.65 }]}>
                    <View style={s.cardTop}>
                      <Text style={s.emp}>
                        {d.employee_name || d.user_id}{d.employee_code ? ` (${d.employee_code})` : ""}
                      </Text>
                      <View style={[s.pill, { backgroundColor: "#94A3B818" }]}>
                        <Text style={[s.pillTxt, { color: "#64748B" }]}>
                          {String(d.status || "").toUpperCase()}
                        </Text>
                      </View>
                    </View>
                    <Text style={s.meta}>
                      {d.device_label || "Device"} · registered {fmtAt(d.registered_at)}
                      {d.revoked_at ? ` · revoked ${fmtAt(d.revoked_at)}` : ""}
                      {d.revoked_reason ? ` (${d.revoked_reason})` : ""}
                    </Text>
                  </View>
                ))}
              </>
            ) : null}
          </>
        ) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10,
    paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12, color: colors.onSurfaceTertiary },
  tabs: {
    flexDirection: "row", gap: 6, paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: colors.surface, borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderRadius: 999, paddingHorizontal: 13, paddingVertical: 8, minHeight: 38,
    backgroundColor: colors.background, borderWidth: 1, borderColor: colors.border,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "800", color: colors.onSurfaceSecondary },
  body: { padding: 16 },
  msg: { fontSize: 12.5, color: "#059669", fontWeight: "700", marginBottom: 8 },
  empty: { alignItems: "center", paddingVertical: 40 },
  muted: { color: colors.onSurfaceTertiary, marginTop: 8, fontSize: 13 },
  secTitle: {
    fontSize: 12, fontWeight: "800", color: colors.onSurfaceTertiary,
    textTransform: "uppercase", marginTop: 14, marginBottom: 8,
  },
  card: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 10,
  },
  cardTop: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  emp: { flex: 1, fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  at: { fontSize: 11.5, color: colors.onSurfaceTertiary },
  pill: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 3 },
  pillTxt: { fontSize: 10, fontWeight: "800" },
  stage: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4, fontWeight: "700" },
  checkRow: { flexDirection: "row", gap: 8, marginTop: 6, flexWrap: "wrap" },
  checkPill: { flexDirection: "row", alignItems: "center", gap: 3 },
  checkTxt: { fontSize: 11.5, fontWeight: "700" },
  meta: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 4 },
  btnRow: { flexDirection: "row", gap: 8, marginTop: 10, flexWrap: "wrap" },
  aBtn: {
    flexDirection: "row", gap: 5, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 9,
    minHeight: 40, alignItems: "center", justifyContent: "center",
  },
  aBtnDanger: { backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA" },
  aBtnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
});
