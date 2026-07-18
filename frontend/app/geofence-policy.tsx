/**
 * Geofence Attendance Policy Master (Phase 1).
 * Configure the company default mode + multi-level assignments
 * (branch / site / contractor / category / employee).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  TextInput,
  Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type Mode = { mode: string; label: string; desc: string; color: string };
type Assignment = {
  assignment_id: string;
  scope: string;
  scope_value: string;
  scope_label?: string;
  mode: string;
  settings?: any;
};
type PolicyResp = {
  default_mode: string;
  assignments: Assignment[];
  modes: Mode[];
};

const SCOPES = ["branch", "site", "contractor", "category", "employee"];

export default function GeofencePolicyScreen() {
  const { user, loading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [data, setData] = useState<PolicyResp | null>(null);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(true);
  const [msg, setMsg] = useState<string | null>(null);

  // new-assignment form
  const [scope, setScope] = useState("category");
  const [scopeValue, setScopeValue] = useState("");
  const [aMode, setAMode] = useState("field");
  const [graceDist, setGraceDist] = useState("");
  const [mandSelfie, setMandSelfie] = useState(false);

  const cid = selectedCompanyId || undefined;

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const r = await api<PolicyResp>(
        `/admin/geo-policy${cid ? `?company_id=${cid}` : ""}`,
      );
      setData(r);
    } catch (e: any) {
      setMsg(e?.message || "Failed to load policy.");
    } finally {
      setBusy(false);
    }
  }, [cid]);

  useEffect(() => {
    void load();
  }, [load]);

  const setDefault = useCallback(
    async (mode: string) => {
      setSaving(true);
      setMsg(null);
      try {
        await api("/admin/geo-policy/default", {
          method: "PUT",
          body: { company_id: cid, mode },
        });
        setData((d) => (d ? { ...d, default_mode: mode } : d));
        setMsg("Default policy saved.");
      } catch (e: any) {
        setMsg(e?.message || "Save failed.");
      } finally {
        setSaving(false);
      }
    },
    [cid],
  );

  const addAssignment = useCallback(async () => {
    if (!scopeValue.trim()) {
      setMsg("Enter a scope value (e.g. Sales, branch id, employee code).");
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      await api("/admin/geo-policy/assignments", {
        method: "POST",
        body: {
          company_id: cid,
          scope,
          scope_value: scopeValue.trim(),
          scope_label: scopeValue.trim(),
          mode: aMode,
          settings: {
            grace_distance_m: Number(graceDist) || 0,
            mandatory_selfie: mandSelfie,
          },
        },
      });
      setScopeValue("");
      setGraceDist("");
      setMandSelfie(false);
      await load();
      setMsg("Assignment added.");
    } catch (e: any) {
      setMsg(e?.message || "Could not add assignment.");
    } finally {
      setSaving(false);
    }
  }, [cid, scope, scopeValue, aMode, graceDist, mandSelfie, load]);

  const removeAssignment = useCallback(
    async (id: string) => {
      setSaving(true);
      try {
        await api(
          `/admin/geo-policy/assignments/${id}${cid ? `?company_id=${cid}` : ""}`,
          { method: "DELETE" },
        );
        await load();
      } catch (e: any) {
        setMsg(e?.message || "Delete failed.");
      } finally {
        setSaving(false);
      }
    },
    [cid, load],
  );

  if (loading) return null;
  const role = user?.role as string;
  if (!user || !["super_admin", "sub_admin", "company_admin"].includes(role)) {
    return <Redirect href="/" />;
  }

  const modes = data?.modes || [];
  const modeMeta = (m: string) => modes.find((x) => x.mode === m);

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={st.wrap}>
        <Text style={st.title}>Geofence Attendance Policy</Text>
        <Text style={st.subtitle}>
          Choose how attendance behaves relative to the geofence. Assignments
          override the default (most specific wins: employee › site › branch ›
          contractor › category › company default).
        </Text>

        {msg ? (
          <View style={st.msgBox}>
            <Ionicons name="information-circle" size={15} color="#2563EB" />
            <Text style={st.msgTxt}>{msg}</Text>
          </View>
        ) : null}

        {busy ? (
          <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 24 }} />
        ) : (
          <>
            <Text style={st.section}>Company default mode</Text>
            <View style={st.modeGrid}>
              {modes.map((m) => {
                const active = data?.default_mode === m.mode;
                return (
                  <Pressable
                    key={m.mode}
                    style={[st.modeCard, active && { borderColor: m.color, borderWidth: 2 }]}
                    onPress={() => setDefault(m.mode)}
                    disabled={saving}
                    testID={`mode-${m.mode}`}
                  >
                    <View style={st.modeHead}>
                      <View style={[st.dot, { backgroundColor: m.color }]} />
                      <Text style={st.modeLabel}>{m.label}</Text>
                      {active ? (
                        <Ionicons name="checkmark-circle" size={16} color={m.color} />
                      ) : null}
                    </View>
                    <Text style={st.modeDesc}>{m.desc}</Text>
                  </Pressable>
                );
              })}
            </View>

            <Text style={st.section}>Add an assignment</Text>
            <View style={st.card}>
              <Text style={st.fieldLbl}>Applies to</Text>
              <View style={st.pillRow}>
                {SCOPES.map((s) => (
                  <Pressable
                    key={s}
                    style={[st.pill, scope === s && st.pillActive]}
                    onPress={() => setScope(s)}
                  >
                    <Text style={[st.pillTxt, scope === s && st.pillTxtActive]}>{s}</Text>
                  </Pressable>
                ))}
              </View>

              <Text style={st.fieldLbl}>
                {scope === "employee" ? "Employee code / ID" :
                 scope === "category" ? "Category / employee type (e.g. Sales)" :
                 scope === "contractor" ? "Contractor name" :
                 scope === "branch" ? "Branch id or name" : "Site / worksite id or name"}
              </Text>
              <TextInput
                style={st.input}
                value={scopeValue}
                onChangeText={setScopeValue}
                placeholder="Enter value"
                placeholderTextColor={colors.textSecondary}
              />

              <Text style={st.fieldLbl}>Mode</Text>
              <View style={st.pillRow}>
                {modes.map((m) => (
                  <Pressable
                    key={m.mode}
                    style={[st.pill, aMode === m.mode && { backgroundColor: m.color }]}
                    onPress={() => setAMode(m.mode)}
                  >
                    <Text style={[st.pillTxt, aMode === m.mode && st.pillTxtActive]}>
                      {m.label}
                    </Text>
                  </Pressable>
                ))}
              </View>

              <View style={st.row}>
                <View style={{ flex: 1 }}>
                  <Text style={st.fieldLbl}>Grace distance (m)</Text>
                  <TextInput
                    style={st.input}
                    value={graceDist}
                    onChangeText={setGraceDist}
                    keyboardType="numeric"
                    placeholder="0"
                    placeholderTextColor={colors.textSecondary}
                  />
                </View>
                <View style={st.switchWrap}>
                  <Text style={st.fieldLbl}>Mandatory selfie</Text>
                  <Switch value={mandSelfie} onValueChange={setMandSelfie} />
                </View>
              </View>

              <Pressable style={st.addBtn} onPress={addAssignment} disabled={saving} testID="add-assignment">
                {saving ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <Ionicons name="add" size={18} color="#fff" />
                )}
                <Text style={st.addBtnTxt}>Add assignment</Text>
              </Pressable>
            </View>

            <Text style={st.section}>Current assignments ({data?.assignments.length || 0})</Text>
            {(data?.assignments || []).length === 0 ? (
              <Text style={st.empty}>No assignments — the company default applies to everyone.</Text>
            ) : (
              (data?.assignments || []).map((a) => {
                const m = modeMeta(a.mode);
                return (
                  <View key={a.assignment_id} style={st.aRow}>
                    <View style={[st.dot, { backgroundColor: m?.color || "#888" }]} />
                    <View style={{ flex: 1 }}>
                      <Text style={st.aTitle}>
                        {a.scope}: {a.scope_label || a.scope_value}
                      </Text>
                      <Text style={st.aSub}>{m?.label || a.mode}</Text>
                    </View>
                    <Pressable onPress={() => removeAssignment(a.assignment_id)} hitSlop={8}>
                      <Ionicons name="trash-outline" size={18} color="#DC2626" />
                    </Pressable>
                  </View>
                );
              })
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  wrap: { padding: 20, gap: 12, maxWidth: 780, width: "100%", alignSelf: "center" },
  title: { fontSize: 22, fontWeight: "800", color: colors.textPrimary },
  subtitle: { fontSize: 13, color: colors.textSecondary, lineHeight: 19 },
  section: { fontSize: 14, fontWeight: "800", color: colors.textPrimary, marginTop: 8 },
  msgBox: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#EFF6FF", borderRadius: 10, padding: 10,
  },
  msgTxt: { color: "#1D4ED8", fontSize: 12.5, flex: 1 },
  modeGrid: { gap: 8 },
  modeCard: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 12,
  },
  modeHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  modeLabel: { fontSize: 14, fontWeight: "800", color: colors.textPrimary, flex: 1 },
  modeDesc: { fontSize: 12, color: colors.textSecondary, marginTop: 4, lineHeight: 16 },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border, padding: 14, gap: 8,
  },
  fieldLbl: { fontSize: 12, fontWeight: "700", color: colors.textSecondary, marginTop: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    paddingHorizontal: 12, paddingVertical: 10, fontSize: 14,
    color: colors.textPrimary, backgroundColor: colors.surface,
  },
  pillRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  pill: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 999,
    paddingVertical: 6, paddingHorizontal: 12, backgroundColor: colors.surface,
  },
  pillActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  pillTxt: { fontSize: 12.5, fontWeight: "700", color: colors.textSecondary },
  pillTxtActive: { color: "#fff" },
  row: { flexDirection: "row", gap: 12, alignItems: "flex-start" },
  switchWrap: { alignItems: "flex-start", gap: 4 },
  addBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    backgroundColor: colors.brandPrimary, borderRadius: 10, paddingVertical: 12,
    marginTop: 6, minHeight: 46,
  },
  addBtnTxt: { color: "#fff", fontSize: 14, fontWeight: "800" },
  empty: { fontSize: 13, color: colors.textSecondary, fontStyle: "italic" },
  aRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surfaceSecondary, borderRadius: 10,
    borderWidth: 1, borderColor: colors.border, padding: 12,
  },
  aTitle: { fontSize: 13.5, fontWeight: "700", color: colors.textPrimary },
  aSub: { fontSize: 12, color: colors.textSecondary, marginTop: 2 },
});
