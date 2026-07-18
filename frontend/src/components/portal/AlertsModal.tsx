// Phase 2 — Notification/Alert center modal for the portal dashboard.
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal, ActivityIndicator, ScrollView,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

export type PortalAlert = {
  severity: "critical" | "warning" | "info";
  icon: string; title: string; route?: string | null; tab?: string | null;
};
type Notif = { title: string; body?: string; created_at?: string };

const SEV_UI: Record<string, { fg: string; bg: string }> = {
  critical: { fg: "#B91C1C", bg: "#FEF2F2" },
  warning: { fg: "#B45309", bg: "#FFFBEB" },
  info: { fg: "#0369A1", bg: "#F0F9FF" },
};

export default function AlertsModal({
  visible, onClose, onGoTab,
}: { visible: boolean; onClose: () => void; onGoTab: (tab: string) => void }) {
  const router = useRouter();
  const [alerts, setAlerts] = useState<PortalAlert[]>([]);
  const [recent, setRecent] = useState<Notif[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ alerts: PortalAlert[]; recent_notifications: Notif[] }>(
        "/admin/portal-dashboard/alerts");
      setAlerts(r.alerts); setRecent(r.recent_notifications);
    } catch { /* noop */ }
    setLoading(false);
  }, []);

  useEffect(() => { if (visible) load(); }, [visible, load]);

  const openAlert = (a: PortalAlert) => {
    onClose();
    if (a.route) router.push(a.route as any);
    else if (a.tab) onGoTab(a.tab);
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={st.overlay} onPress={onClose}>
        <Pressable style={st.panel} onPress={() => { /* trap */ }}>
          <View style={st.head}>
            <Text style={st.headTitle}>🔔 Notification Center</Text>
            <Pressable onPress={onClose} hitSlop={10} testID="pd-alerts-close">
              <Ionicons name="close" size={18} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>
          {loading ? (
            <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 30 }} />
          ) : (
            <ScrollView style={{ maxHeight: 480 }}>
              <Text style={st.section}>Action required</Text>
              {alerts.length === 0 ? (
                <Text style={st.dim}>✅ All clear — nothing needs your attention.</Text>
              ) : (
                alerts.map((a, i) => {
                  const ui = SEV_UI[a.severity] || SEV_UI.info;
                  return (
                    <Pressable key={i} onPress={() => openAlert(a)} style={st.alertRow}
                      testID={`pd-alert-${i}`}>
                      <View style={[st.alertIcon, { backgroundColor: ui.bg }]}>
                        <Ionicons name={a.icon as any} size={15} color={ui.fg} />
                      </View>
                      <Text style={st.alertTitle} numberOfLines={2}>{a.title}</Text>
                      <Ionicons name="chevron-forward" size={14} color={colors.onSurfaceTertiary} />
                    </Pressable>
                  );
                })
              )}
              <Text style={[st.section, { marginTop: 14 }]}>Recent broadcasts</Text>
              {recent.length === 0 ? (
                <Text style={st.dim}>No recent notifications.</Text>
              ) : (
                recent.map((n, i) => (
                  <View key={i} style={st.notifRow}>
                    <Text style={st.notifTitle} numberOfLines={1}>{n.title}</Text>
                    {n.body ? <Text style={st.notifBody} numberOfLines={2}>{n.body}</Text> : null}
                    {n.created_at ? (
                      <Text style={st.notifTime}>{String(n.created_at).slice(0, 16).replace("T", " ")}</Text>
                    ) : null}
                  </View>
                ))
              )}
            </ScrollView>
          )}
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const st = StyleSheet.create({
  overlay: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
    alignItems: "flex-end", justifyContent: "flex-start", padding: spacing.md,
  },
  panel: {
    width: "100%", maxWidth: 400, backgroundColor: colors.surface,
    borderRadius: radius.lg, padding: 14, marginTop: 52,
  },
  head: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", marginBottom: 8 },
  headTitle: { fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  section: {
    fontSize: 10, fontWeight: "800", color: colors.onSurfaceTertiary,
    textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 6, marginTop: 4,
  },
  dim: { fontSize: 12, color: colors.onSurfaceSecondary, paddingVertical: 8 },
  alertRow: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.divider,
  },
  alertIcon: { width: 30, height: 30, borderRadius: 8, alignItems: "center", justifyContent: "center" },
  alertTitle: { flex: 1, fontSize: 12, fontWeight: "600", color: colors.onSurface },
  notifRow: {
    paddingVertical: 7, borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  notifTitle: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  notifBody: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 1 },
  notifTime: { fontSize: 9.5, color: colors.onSurfaceTertiary, marginTop: 2 },
});
