/**
 * Approval Workflow Builder — RBAC Phase 3.
 * Per-module multi-level approval chains (levels = Company Admin or any
 * company staff role). Admin-only (staff cannot see this page).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, ActivityIndicator, Platform, Alert, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors } from "@/src/theme";

const toast = (m: string) => (Platform.OS === "web" ? window.alert(m) : Alert.alert("Workflow", m));

export default function ApprovalWorkflows() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const role = user?.role as string;
  const isStaff = !!(user as any)?.is_company_staff;

  const [companyId, setCompanyId] = useState<string>(
    role === "company_admin" ? (user?.company_id || "") : (selectedCompanyId || ""));
  const [loading, setLoading] = useState(true);
  const [modules, setModules] = useState<any[]>([]);
  const [roles, setRoles] = useState<any[]>([]);
  const [wfs, setWfs] = useState<Record<string, any>>({});
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  // Follow the global active-firm picker.
  useEffect(() => {
    if (role !== "company_admin" && selectedCompanyId) setCompanyId(selectedCompanyId);
  }, [selectedCompanyId, role]);
  const load = useCallback(async () => {
    if (!companyId) { setLoading(false); return; }
    setLoading(true);
    try {
      const r = await api(`/admin/approval-workflows?company_id=${companyId}`);
      setModules(r.modules || []); setRoles(r.roles || []); setWfs(r.workflows || {});
    } catch (e: any) { toast(e?.message || "Failed to load"); }
    finally { setLoading(false); }
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  const save = async (moduleKey: string, levels: any[], enabled: boolean) => {
    setSaving(moduleKey);
    try {
      await api("/admin/approval-workflows", {
        method: "POST",
        body: { company_id: companyId, module: moduleKey, enabled, levels },
      });
      await load();
    } catch (e: any) { toast(e?.message || "Save failed"); }
    finally { setSaving(null); setAddingFor(null); }
  };

  if (authLoading) return null;
  if (!user || isStaff || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={s.root} edges={["top"]}>
      <View style={s.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={s.hBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={s.title}>Approval Workflow Builder</Text>
          <Text style={s.subtitle}>Multi-level approval chains per module — no coding needed</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={s.body}>
        {role !== "company_admin" ? (
          <View style={{ marginBottom: 12 }}>
            <CompanyPicker value={companyId} onChange={(v: any) => setCompanyId(v || "")} />
          </View>
        ) : null}
        {!companyId ? <Text style={s.muted}>Select a firm to configure its workflows.</Text> : null}
        {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : null}

        {!loading && companyId ? modules.map((m) => {
          const wf = wfs[m.key] || { enabled: false, levels: [] };
          const levels = wf.levels || [];
          return (
            <View key={m.key} style={s.card} testID={`wf-${m.key}`}>
              <View style={s.cardHead}>
                <View style={s.cardIcon}><Ionicons name="git-branch-outline" size={16} color={colors.brandPrimary} /></View>
                <Text style={s.cardTitle}>{m.label}</Text>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={s.muted}>{wf.enabled ? "Enabled" : "Off"}</Text>
                  <Switch
                    value={!!wf.enabled}
                    onValueChange={(v) => save(m.key, levels.map((l: any) => ({ approver_type: l.approver_type, role_id: l.role_id })), v)}
                    trackColor={{ true: colors.brandPrimary, false: colors.surfaceTertiary }}
                    testID={`wf-toggle-${m.key}`}
                  />
                </View>
              </View>

              {/* Chain visual */}
              <View style={s.chain}>
                <View style={[s.node, { backgroundColor: "rgba(100,116,139,0.12)" }]}>
                  <Text style={[s.nodeTxt, { color: "#475569" }]}>Request</Text>
                </View>
                {levels.map((l: any, i: number) => (
                  <React.Fragment key={i}>
                    <Ionicons name="arrow-forward" size={14} color={colors.onSurfaceTertiary} />
                    <View style={s.node}>
                      <Text style={s.nodeTxt}>L{l.level} · {l.role_name || "Company Admin"}</Text>
                      <Pressable hitSlop={8} onPress={() => save(m.key,
                        levels.filter((_: any, j: number) => j !== i).map((x: any) => ({ approver_type: x.approver_type, role_id: x.role_id })),
                        wf.enabled)} testID={`wf-remove-${m.key}-${i}`}>
                        <Ionicons name="close-circle" size={15} color="#DC2626" />
                      </Pressable>
                    </View>
                  </React.Fragment>
                ))}
                <Ionicons name="arrow-forward" size={14} color={colors.onSurfaceTertiary} />
                <View style={[s.node, { backgroundColor: "rgba(5,150,105,0.12)" }]}>
                  <Text style={[s.nodeTxt, { color: "#059669" }]}>Approved</Text>
                </View>
              </View>

              {/* Add level */}
              {addingFor === m.key ? (
                <View style={s.pickWrap}>
                  <Text style={s.muted}>Add approver level:</Text>
                  <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8, marginTop: 6 }}>
                    <Pressable style={s.chip} testID={`wf-add-admin-${m.key}`}
                      onPress={() => save(m.key, [...levels.map((x: any) => ({ approver_type: x.approver_type, role_id: x.role_id })), { approver_type: "company_admin" }], true)}>
                      <Text style={s.chipTxt}>Company Admin</Text>
                    </Pressable>
                    {roles.map((r) => (
                      <Pressable key={r.role_id} style={s.chip} testID={`wf-add-${m.key}-${r.name.replace(/\s+/g, "-")}`}
                        onPress={() => save(m.key, [...levels.map((x: any) => ({ approver_type: x.approver_type, role_id: x.role_id })), { approver_type: "company_role", role_id: r.role_id }], true)}>
                        <Text style={s.chipTxt}>{r.name}</Text>
                      </Pressable>
                    ))}
                  </View>
                </View>
              ) : (
                <Pressable style={s.addBtn} onPress={() => setAddingFor(m.key)} testID={`wf-add-level-${m.key}`}>
                  {saving === m.key ? <ActivityIndicator size="small" color={colors.brandPrimary} /> : (
                    <><Ionicons name="add" size={14} color={colors.brandPrimary} />
                      <Text style={s.addTxt}>Add Approval Level</Text></>)}
                </Pressable>
              )}
              {m.key !== "advance" ? (
                <Text style={[s.muted, { marginTop: 8 }]}>Currently enforced for Advance issuance; other modules coming next.</Text>
              ) : null}
            </View>
          );
        }) : null}
        <View style={{ height: 40 }} />
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", gap: 10, paddingHorizontal: 16, paddingVertical: 12,
    backgroundColor: colors.surfaceSecondary, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: colors.border,
  },
  hBtn: { width: 38, height: 38, borderRadius: 12, alignItems: "center", justifyContent: "center", backgroundColor: colors.surfaceTertiary },
  title: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 1 },
  body: { padding: 16, width: "100%", maxWidth: 900, alignSelf: "center" },
  muted: { fontSize: 12, color: colors.onSurfaceTertiary },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 16, padding: 14,
    borderWidth: 1, borderColor: colors.border, marginBottom: 12,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  cardIcon: { width: 30, height: 30, borderRadius: 9, backgroundColor: "rgba(37,99,235,0.1)", alignItems: "center", justifyContent: "center" },
  cardTitle: { flex: 1, fontSize: 14.5, fontWeight: "800", color: colors.onSurface },
  chain: { flexDirection: "row", alignItems: "center", gap: 6, flexWrap: "wrap", marginTop: 12 },
  node: {
    flexDirection: "row", alignItems: "center", gap: 5, backgroundColor: "rgba(37,99,235,0.1)",
    borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6,
  },
  nodeTxt: { fontSize: 11.5, fontWeight: "800", color: colors.brandPrimary },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 5, alignSelf: "flex-start",
    borderWidth: 1, borderColor: "rgba(37,99,235,0.35)", borderRadius: 10,
    paddingHorizontal: 12, height: 32, marginTop: 12, backgroundColor: "rgba(37,99,235,0.06)",
  },
  addTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  pickWrap: { marginTop: 12, backgroundColor: colors.surface, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.border },
  chip: {
    paddingHorizontal: 12, height: 32, borderRadius: 16, backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  chipTxt: { fontSize: 12, fontWeight: "600", color: colors.onSurfaceSecondary },
});
