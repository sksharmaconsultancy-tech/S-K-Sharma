/**
 * Attendance Email Config — Iter 60.
 *
 * Super Admin / Sub-Admin configures the automated month-end attendance
 * sheet email for each firm:
 *   • Recipient list (comma-separated)
 *   • Enabled toggle
 *   • "Send now" for a specific month (super admin only)
 *   • Delivery log (last 50)
 *
 * The cron itself runs on the 1st of every month at 09:00 IST and sends
 * the previous month's attendance sheet as a base64 XLSX attachment via
 * Resend.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  TextInput,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import MonthPicker from "@/src/components/MonthPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Company = { company_id: string; name: string };
type LogItem = {
  log_id: string;
  company_id: string;
  month: string;
  recipients: string[];
  delivered: boolean;
  email_id?: string;
  error?: string;
  sent_at: string;
};

function currentMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function showMsg(msg: string, title = "Attendance Email") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function AttendanceEmailConfigScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const isAdminish = isSuper || user?.role === "sub_admin";

  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState<string>("");
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  useEffect(() => {
    if (globalCid) setCompanyId(globalCid);
  }, [globalCid]);
  const [recipientsText, setRecipientsText] = useState<string>("");
  const [enabled, setEnabled] = useState<boolean>(true);
  const [saving, setSaving] = useState(false);
  const [triggering, setTriggering] = useState(false);
  const [monthToSend, setMonthToSend] = useState<string>(currentMonth());
  const [logs, setLogs] = useState<LogItem[]>([]);

  useEffect(() => {
    if (!isAdminish) return;
    (async () => {
      try {
        const r = await api<{ companies: Company[] }>("/companies");
        setCompanies(r.companies || []);
        if (r.companies?.length && !companyId) setCompanyId(r.companies[0].company_id);
      } catch (e: any) {
        showMsg(e?.message || "Could not load companies");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdminish]);

  const loadConfig = useCallback(async () => {
    if (!companyId) return;
    try {
      const cfg = await api<{ recipients: string[]; enabled: boolean }>(
        `/admin/companies/${companyId}/attendance-email-config`,
      );
      setRecipientsText((cfg.recipients || []).join(", "));
      setEnabled(cfg.enabled !== false);
      const l = await api<{ items: LogItem[] }>(
        `/admin/attendance-email/log?company_id=${encodeURIComponent(companyId)}&limit=20`,
      );
      setLogs(l.items || []);
    } catch (e: any) {
      showMsg(e?.message || "Load failed");
    }
  }, [companyId]);

  useEffect(() => {
    void loadConfig();
  }, [loadConfig]);

  const save = async () => {
    if (!companyId) return;
    setSaving(true);
    try {
      const recipients = recipientsText
        .split(/[,;\n]+/)
        .map((s) => s.trim().toLowerCase())
        .filter((s) => s && s.includes("@"));
      await api(`/admin/companies/${companyId}/attendance-email-config`, {
        method: "PUT",
        body: { recipients, enabled },
      });
      setRecipientsText(recipients.join(", "));
      showMsg("Saved.");
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const triggerNow = async (dryRun: boolean) => {
    if (!isSuper) return showMsg("Only super admin can trigger sends.");
    if (!companyId) return;
    setTriggering(true);
    try {
      const r = await api<{ results: any[] }>(
        `/admin/attendance-email/trigger-now?dry_run=${dryRun}&company_id=${encodeURIComponent(companyId)}&month=${encodeURIComponent(monthToSend)}`,
        { method: "POST" },
      );
      showMsg(
        `${dryRun ? "Dry-run" : "Sent"} — ${JSON.stringify(r.results?.[0] || {})}`,
      );
      await loadConfig();
    } catch (e: any) {
      showMsg(e?.message || "Trigger failed");
    } finally {
      setTriggering(false);
    }
  };

  if (!isAdminish) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Only Super/Sub-admins can access this.</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.h1}>Attendance Sheet Email — Auto</Text>
            <Text style={styles.hsub}>
              Cron: 1st of each month, 09:00 IST · Resend delivery · XLSX attached
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.card}>
          <Text style={styles.label}>Company (Firm)</Text>
          {Platform.OS === "web" ? (
            <select
              data-testid="aec-company"
              value={companyId}
              onChange={(e) => setCompanyId((e.target as HTMLSelectElement).value)}
              style={styles.selectStyle as any}
            >
              <option value="">— select —</option>
              {companies.map((c) => (
                <option key={c.company_id} value={c.company_id}>
                  {c.name}
                </option>
              ))}
            </select>
          ) : (
            <Text style={styles.smallHint}>Best used on desktop web.</Text>
          )}
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>Recipients (comma separated)</Text>
          <TextInput
            testID="aec-recipients"
            value={recipientsText}
            onChangeText={setRecipientsText}
            placeholder="hr@firm.com, payroll@firm.com"
            placeholderTextColor={colors.onSurfaceTertiary}
            multiline
            style={[styles.input, { minHeight: 60, textAlignVertical: "top" }]}
          />
          <Text style={styles.smallHint}>
            Leave blank to fallback to the company_admin&apos;s registered email.
          </Text>

          <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
            <Pressable
              onPress={() => setEnabled(!enabled)}
              style={[styles.chip, enabled && styles.chipActive]}
              testID="aec-enabled-toggle"
            >
              <Ionicons
                name={enabled ? "checkmark-circle" : "pause-circle-outline"}
                size={14}
                color={enabled ? "#fff" : colors.onSurfaceSecondary}
              />
              <Text style={[styles.chipTxt, { color: enabled ? "#fff" : colors.onSurfaceSecondary }]}>
                {enabled ? "Cron enabled" : "Cron paused"}
              </Text>
            </Pressable>
          </View>

          <Pressable
            onPress={save}
            disabled={saving || !companyId}
            style={[styles.primaryBtn, (saving || !companyId) && { opacity: 0.5 }]}
            testID="aec-save"
          >
            {saving ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.primaryBtnTxt}>Save configuration</Text>
            )}
          </Pressable>
        </View>

        {isSuper ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>Send now (bypass cron)</Text>
            <View style={styles.gridRow}>
              <View style={styles.gridCol}>
                <Text style={styles.label}>Month</Text>
                <MonthPicker
                  value={monthToSend}
                  onChange={setMonthToSend}
                  allowEmpty
                  emptyLabel="Auto (previous month)"
                  testID="aec-month-picker"
                />
              </View>
            </View>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 10 }}>
              <Pressable
                onPress={() => triggerNow(true)}
                disabled={triggering}
                style={[styles.secondaryBtn, { flex: 1 }, triggering && { opacity: 0.5 }]}
                testID="aec-dryrun"
              >
                <Ionicons name="eye-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.secondaryBtnTxt}>Dry-run</Text>
              </Pressable>
              <Pressable
                onPress={() => triggerNow(false)}
                disabled={triggering}
                style={[styles.primaryBtn, { flex: 1 }, triggering && { opacity: 0.5 }]}
                testID="aec-send"
              >
                {triggering ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="paper-plane-outline" size={14} color="#fff" />
                    <Text style={styles.primaryBtnTxt}>Send now</Text>
                  </>
                )}
              </Pressable>
            </View>
          </View>
        ) : null}

        {logs.length > 0 ? (
          <View style={styles.card}>
            <Text style={styles.stepTitle}>Recent deliveries</Text>
            {logs.map((l) => (
              <View key={l.log_id} style={styles.logRow}>
                <Ionicons
                  name={l.delivered ? "checkmark-circle" : "close-circle"}
                  size={16}
                  color={l.delivered ? "#1F7A3A" : "#B02A2A"}
                />
                <View style={{ flex: 1 }}>
                  <Text style={styles.rowName}>
                    {l.month} — {l.recipients.slice(0, 2).join(", ")}
                    {l.recipients.length > 2 ? ` +${l.recipients.length - 2}` : ""}
                  </Text>
                  <Text style={styles.smallHint}>
                    {l.sent_at?.slice(0, 19)}
                    {l.error ? ` · err: ${l.error.slice(0, 60)}` : ""}
                  </Text>
                </View>
              </View>
            ))}
          </View>
        ) : null}

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  h1: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  hsub: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },
  scroll: { padding: spacing.lg, maxWidth: 960, alignSelf: "center", width: "100%" },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: { marginTop: 8, color: colors.onSurfaceSecondary, textAlign: "center" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 6,
    textTransform: "uppercase",
  },
  input: {
    borderWidth: 1,
    borderColor: colors.borderStrong,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  smallHint: { color: colors.onSurfaceSecondary, fontSize: 11, marginTop: 4 },
  stepTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800", marginBottom: 8 },
  gridRow: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  gridCol: { flex: 1, minWidth: 200 },
  chip: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.divider,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { fontSize: 12, fontWeight: "700" },
  selectStyle: {
    padding: 10,
    borderRadius: 8,
    borderColor: colors.borderStrong,
    borderWidth: 1,
    fontSize: 14,
    width: "100%",
  },
  primaryBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    marginTop: 10,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  primaryBtnTxt: { color: "#fff", fontWeight: "800" },
  secondaryBtn: {
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.brandTertiary,
  },
  secondaryBtnTxt: { color: colors.brandPrimary, fontWeight: "800" },
  logRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  rowName: { color: colors.onSurface, fontSize: 13, fontWeight: "600" },
});
