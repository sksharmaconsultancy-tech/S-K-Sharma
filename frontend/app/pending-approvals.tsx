/**
 * Iter 587 — Pending Approvals (RBAC Phase 3 Maker-Checker).
 * Critical changes (salary change, bank change, employee deletion) raised
 * by non-super admins land here as PENDING requests with OLD vs NEW values.
 * An authorized checker (never the maker) approves or rejects. Nothing is
 * applied until approved. Super Admin can toggle which actions require
 * approval.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator, Alert, Platform, Pressable, RefreshControl,
  ScrollView, StyleSheet, Switch, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const STATUSES = ["PENDING", "APPROVED", "REJECTED"];
const ACTION_ICON: Record<string, any> = {
  salary_change: "cash-outline",
  bank_change: "card-outline",
  employee_delete: "trash-outline",
};

const notify = (title: string, msg: string) => {
  if (Platform.OS === "web") (globalThis as any).alert?.(`${title}\n${msg}`);
  else Alert.alert(title, msg);
};

export default function PendingApprovalsScreen() {
  const router = useRouter();
  const [status, setStatus] = useState("PENDING");
  const [rows, setRows] = useState<any[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [settings, setSettings] = useState<any>(null);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const [isSuper, setIsSuper] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (s: string) => {
    setLoading(true); setError(null);
    try {
      const r = await api<{ approvals: any[]; pending_count: number }>(
        `/admin/approvals?status=${s}`);
      setRows(r.approvals || []);
      setPendingCount(r.pending_count || 0);
    } catch (e: any) { setError(e.message || "Failed to load approvals"); }
    finally { setLoading(false); }
  }, []);

  const loadSettings = useCallback(async () => {
    try {
      const r = await api<any>(`/admin/maker-checker/settings`);
      setSettings(r.settings); setLabels(r.labels || {});
    } catch { /* non-super roles can still read; ignore */ }
    try {
      const me = await api<any>(`/auth/me`);
      setIsSuper((me?.user?.role || me?.role) === "super_admin");
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { void load(status); }, [status, load]);
  useEffect(() => { void loadSettings(); }, [loadSettings]);

  const toggle = async (key: string, value: boolean) => {
    const next = { ...settings, actions: { ...settings.actions, [key]: value } };
    setSettings(next);
    try {
      await api(`/admin/maker-checker/settings`, {
        method: "PUT", body: { actions: { [key]: value } },
      });
    } catch (e: any) {
      notify("Failed", e.message || "Could not update settings");
      void loadSettings();
    }
  };

  const decide = async (id: string, decision: "approve" | "reject") => {
    setBusy(true);
    try {
      await api(`/admin/approvals/${id}/decide`, {
        method: "POST", body: { decision, reason: reason.trim() || undefined },
      });
      notify(decision === "approve" ? "Approved" : "Rejected",
        decision === "approve"
          ? "The change has been applied."
          : "Nothing was changed — original data stays the same.");
      setOpen(null); setReason("");
      void load(status);
    } catch (e: any) {
      notify("Failed", e.message || "Decision failed");
    } finally { setBusy(false); }
  };

  const fmtVal = (v: any) => {
    if (v === null || v === undefined || v === "") return "—";
    if (Array.isArray(v)) {
      return v.map((r: any) =>
        r && typeof r === "object" ? `${r.head}: ${r.amount}` : String(r)).join(", ") || "—";
    }
    if (typeof v === "object") return JSON.stringify(v);
    return String(v);
  };

  const fmtAt = (iso?: string) => {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return `${d.toLocaleDateString("en-IN")} ${d.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
    } catch { return iso; }
  };

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 6 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.h1}>Pending Approvals</Text>
          <Text style={st.sub}>Maker-Checker · 4-eyes on critical changes</Text>
        </View>
        {pendingCount > 0 ? (
          <View style={st.countBadge}>
            <Text style={st.countTxt}>{pendingCount}</Text>
          </View>
        ) : null}
      </View>

      <View style={st.tabs}>
        {STATUSES.map((s) => (
          <Pressable key={s} onPress={() => { setStatus(s); setOpen(null); }}
            style={[st.tab, status === s && st.tabOn]} testID={`pa-tab-${s}`}>
            <Text style={[st.tabTxt, status === s && st.tabTxtOn]}>{s}</Text>
          </Pressable>
        ))}
      </View>

      <ScrollView
        contentContainerStyle={{ padding: spacing.lg, gap: 10, paddingBottom: 60 }}
        refreshControl={<RefreshControl refreshing={false} onRefresh={() => void load(status)} />}
      >
        {isSuper && settings ? (
          <View style={st.block}>
            <Text style={st.blockTitle}>Approval Required For (Super Admin)</Text>
            {Object.keys(settings.actions || {}).map((k) => (
              <View key={k} style={st.setRow}>
                <Text style={st.line}>{labels[k] || k}</Text>
                <Switch value={!!settings.actions[k]}
                  onValueChange={(v) => void toggle(k, v)}
                  testID={`pa-toggle-${k}`} />
              </View>
            ))}
          </View>
        ) : null}

        {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
        {error ? <Text style={{ color: "#DC2626" }}>{error}</Text> : null}
        {!loading && rows.length === 0 ? (
          <Text style={st.empty}>No {status.toLowerCase()} requests.</Text>
        ) : null}

        {rows.map((a) => {
          const expanded = open === a.approval_id;
          const keys = Array.from(new Set([
            ...Object.keys(a.old_values || {}), ...Object.keys(a.new_values || {}),
          ]));
          return (
            <View key={a.approval_id} style={st.card}>
              <Pressable style={st.cardHead}
                onPress={() => { setOpen(expanded ? null : a.approval_id); setReason(""); }}
                testID={`pa-card-${a.approval_id}`}>
                <Ionicons name={ACTION_ICON[a.action_type] || "document-outline"}
                  size={18} color={colors.brandPrimary} />
                <View style={{ flex: 1 }}>
                  <Text style={st.name}>
                    {a.action_label} — {a.target_name || a.target_user_id}
                    {a.target_code ? ` (${a.target_code})` : ""}
                  </Text>
                  <Text style={st.subTxt}>
                    By {a.maker_name} ({a.maker_role}) · {fmtAt(a.created_at)} · {a.approval_id}
                  </Text>
                </View>
                <View style={[st.badge, {
                  backgroundColor: a.status === "PENDING" ? "#FEF3C7"
                    : a.status === "APPROVED" ? "#DCFCE7" : "#FEE2E2",
                }]}>
                  <Text style={[st.badgeTxt, {
                    color: a.status === "PENDING" ? "#92400E"
                      : a.status === "APPROVED" ? "#166534" : "#B91C1C",
                  }]}>{a.status}</Text>
                </View>
              </Pressable>

              {expanded ? (
                <View style={{ gap: 8, marginTop: 8 }}>
                  <View style={st.diffHead}>
                    <Text style={[st.diffCellHead, { flex: 1.2 }]}>Field</Text>
                    <Text style={st.diffCellHead}>Old Value</Text>
                    <Text style={st.diffCellHead}>New Value</Text>
                  </View>
                  {keys.map((k) => (
                    <View key={k} style={st.diffRow}>
                      <Text style={[st.diffCell, { flex: 1.2, fontWeight: "700" }]}>{k}</Text>
                      <Text style={[st.diffCell, { color: "#B91C1C" }]}>
                        {fmtVal((a.old_values || {})[k])}
                      </Text>
                      <Text style={[st.diffCell, { color: "#166534" }]}>
                        {fmtVal((a.new_values || {})[k])}
                      </Text>
                    </View>
                  ))}
                  {a.notes ? <Text style={st.line}>Maker note: {a.notes}</Text> : null}
                  {a.status === "PENDING" ? (
                    <>
                      <TextInput style={st.input} value={reason} onChangeText={setReason}
                        placeholder="Reason / remark (optional)"
                        placeholderTextColor={colors.onSurfaceTertiary}
                        testID="pa-reason-input" />
                      <View style={{ flexDirection: "row", gap: 8 }}>
                        <Pressable
                          style={[st.btn, { flex: 1, backgroundColor: "#16A34A" }]}
                          disabled={busy}
                          onPress={() => void decide(a.approval_id, "approve")}
                          testID="pa-approve-btn">
                          <Ionicons name="checkmark" size={16} color="#fff" />
                          <Text style={st.btnTxt}>Approve & Apply</Text>
                        </Pressable>
                        <Pressable
                          style={[st.btn, { flex: 1, backgroundColor: "#DC2626" }]}
                          disabled={busy}
                          onPress={() => void decide(a.approval_id, "reject")}
                          testID="pa-reject-btn">
                          <Ionicons name="close" size={16} color="#fff" />
                          <Text style={st.btnTxt}>Reject</Text>
                        </Pressable>
                      </View>
                      <Text style={st.hint}>
                        The maker cannot approve their own request. Rejecting keeps the
                        original data completely unchanged.
                      </Text>
                    </>
                  ) : (
                    <Text style={st.line}>
                      {a.status} by {a.checker_name} ({a.checker_role}) · {fmtAt(a.decided_at)}
                      {a.decision_reason ? ` · Reason: ${a.decision_reason}` : ""}
                    </Text>
                  )}
                </View>
              ) : null}
            </View>
          );
        })}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 8,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderBottomColor: colors.border,
  },
  h1: { fontSize: 18, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary },
  countBadge: {
    backgroundColor: "#DC2626", borderRadius: 99, minWidth: 26, height: 26,
    alignItems: "center", justifyContent: "center", paddingHorizontal: 6,
  },
  countTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  tabs: {
    flexDirection: "row", gap: 8, paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  tab: {
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  tabOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  tabTxtOn: { color: "#fff" },
  empty: { color: colors.onSurfaceTertiary, fontSize: 13, textAlign: "center", marginTop: 30 },
  block: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, gap: 6, backgroundColor: colors.surfaceSecondary,
  },
  blockTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  setRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    minHeight: 36,
  },
  card: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, backgroundColor: colors.surfaceSecondary,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  name: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  subTxt: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  badge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 99 },
  badgeTxt: { fontSize: 10, fontWeight: "800" },
  line: { fontSize: 12, color: colors.onSurfaceSecondary },
  hint: { fontSize: 11, color: colors.onSurfaceTertiary, fontStyle: "italic" },
  diffHead: {
    flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border,
    paddingBottom: 4,
  },
  diffRow: {
    flexDirection: "row", borderBottomWidth: 1, borderBottomColor: colors.border,
    paddingVertical: 4,
  },
  diffCellHead: { flex: 1, fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceTertiary },
  diffCell: { flex: 1, fontSize: 11.5, color: colors.onSurface },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, color: colors.onSurface,
    backgroundColor: colors.surface, fontSize: 13,
  },
  btn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderRadius: radius.md, paddingHorizontal: 14, justifyContent: "center", minHeight: 44,
  },
  btnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
});
