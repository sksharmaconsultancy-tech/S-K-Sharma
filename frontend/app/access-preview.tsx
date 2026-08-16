/**
 * Iter 585 — Access Preview (RBAC Phase 1).
 * Super Admin selects any user → sees their exact EFFECTIVE access
 * (firm scope, branch/department scope, module/action matrix, counts) —
 * computed by the same shared/authz.py engine that protects the APIs.
 * Read-only: nothing here changes permissions.
 */
import React, { useState } from "react";
import {
  ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

const ACTIONS = ["view", "add", "edit", "delete", "export", "approve"];

export default function AccessPreviewScreen() {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const search = async () => {
    setLoading(true); setError(null); setData(null);
    try {
      const r = await api<{ users: any[] }>(
        `/admin/access-preview/users?q=${encodeURIComponent(q.trim())}`);
      setUsers(r.users || []);
    } catch (e: any) { setError(e.message || "Search failed"); }
    finally { setLoading(false); }
  };
  const open = async (uid: string) => {
    setLoading(true); setError(null);
    try { setData(await api<any>(`/admin/access-preview/${uid}`)); }
    catch (e: any) { setError(e.message || "Failed to load access"); }
    finally { setLoading(false); }
  };

  const tick = (v: boolean) => (
    <Text style={{ color: v ? "#16A34A" : "#DC2626", fontWeight: "800", fontSize: 13 }}>
      {v ? "✓" : "✗"}
    </Text>
  );

  return (
    <SafeAreaView style={st.root} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 6 }}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={st.h1}>Access Preview</Text>
          <Text style={st.sub}>Effective access — same engine as the live APIs</Text>
        </View>
      </View>
      <ScrollView contentContainerStyle={{ padding: spacing.lg, gap: 10, paddingBottom: 60 }}>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <TextInput style={st.input} value={q} onChangeText={setQ}
            placeholder="Search user by name / email / mobile"
            placeholderTextColor={colors.onSurfaceTertiary} testID="ap-search-input" />
          <Pressable style={st.btn} onPress={() => void search()} testID="ap-search-btn">
            <Ionicons name="search" size={16} color="#fff" />
            <Text style={st.btnTxt}>Search</Text>
          </Pressable>
        </View>
        {loading ? <ActivityIndicator color={colors.brandPrimary} /> : null}
        {error ? <Text style={{ color: "#DC2626" }}>{error}</Text> : null}
        {!data && users.map((u) => (
          <Pressable key={u.user_id} style={st.card} onPress={() => void open(u.user_id)}
            testID={`ap-user-${u.user_id}`}>
            <View style={{ flex: 1 }}>
              <Text style={st.name}>{u.name || u.email}</Text>
              <Text style={st.subTxt}>{u.role} · {u.email || "—"}</Text>
            </View>
            <Ionicons name="chevron-forward" size={16} color={colors.onSurfaceTertiary} />
          </Pressable>
        ))}
        {data ? (
          <View style={{ gap: 10 }}>
            <Pressable onPress={() => setData(null)} style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <Ionicons name="arrow-back" size={14} color={colors.brandPrimary} />
              <Text style={{ color: colors.brandPrimary, fontWeight: "700", fontSize: 12 }}>Back to results</Text>
            </Pressable>
            <View style={st.card}>
              <View style={{ flex: 1 }}>
                <Text style={st.name}>{data.user.name}</Text>
                <Text style={st.subTxt}>
                  Role: {data.user.role} · 2FA: {data.user.twofa_enabled ? "Enabled" : "Off"}
                  {data.user.last_login_at ? ` · Last login: ${String(data.user.last_login_at).slice(0, 16)}` : ""}
                </Text>
              </View>
            </View>
            <View style={st.block} testID="ap-firm-scope">
              <Text style={st.blockTitle}>Firm Scope — {data.firm_scope.mode}</Text>
              {(data.firm_scope.firms || []).slice(0, 30).map((f: any) => (
                <Text key={f.company_id} style={st.line}>✓ {f.name}</Text>
              ))}
            </View>
            <View style={st.block}>
              <Text style={st.blockTitle}>Branch Scope — {data.branch_scope.mode}</Text>
              {(data.branch_scope.items || []).map((b: any) => (
                <Text key={b.branch_id} style={st.line}>✓ {b.name}</Text>
              ))}
            </View>
            <View style={st.block}>
              <Text style={st.blockTitle}>Department Scope — {data.department_scope.mode}</Text>
              {(data.department_scope.items || []).map((d: any) => (
                <Text key={d.department_id} style={st.line}>✓ {d.name}</Text>
              ))}
            </View>
            <View style={st.block}>
              <Text style={st.blockTitle}>Effective Data Access</Text>
              <Text style={st.line}>Firms: {data.counts.firms} · Employees accessible: {data.counts.employees}</Text>
            </View>
            <View style={st.block} testID="ap-matrix">
              <Text style={st.blockTitle}>Module / Action Matrix (effective)</Text>
              <View style={st.mRow}>
                <Text style={[st.mCellHead, { flex: 2 }]}>Module</Text>
                {ACTIONS.map((a) => (
                  <Text key={a} style={st.mCellHead}>{a.slice(0, 4).toUpperCase()}</Text>
                ))}
              </View>
              {Object.entries(data.matrix || {}).map(([mod, acts]: any) => (
                <View key={mod} style={st.mRow}>
                  <Text style={[st.mCell, { flex: 2, textAlign: "left" }]}>{mod}</Text>
                  {ACTIONS.map((a) => (
                    <View key={a} style={[st.mCell, { alignItems: "center" }]}>{tick(!!acts[a])}</View>
                  ))}
                </View>
              ))}
            </View>
          </View>
        ) : null}
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
  input: {
    flex: 1, borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary, fontSize: 13,
  },
  btn: {
    flexDirection: "row", alignItems: "center", gap: 6, backgroundColor: colors.brandPrimary,
    borderRadius: radius.md, paddingHorizontal: 14, justifyContent: "center", minHeight: 44,
  },
  btnTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  card: {
    flexDirection: "row", alignItems: "center", gap: 8, padding: 12,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    backgroundColor: colors.surfaceSecondary,
  },
  name: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  subTxt: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  block: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, gap: 4, backgroundColor: colors.surfaceSecondary,
  },
  blockTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface, marginBottom: 4 },
  line: { fontSize: 12, color: colors.onSurfaceSecondary },
  mRow: { flexDirection: "row", alignItems: "center", paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: colors.border },
  mCellHead: { flex: 1, fontSize: 10, fontWeight: "800", color: colors.onSurfaceTertiary, textAlign: "center" },
  mCell: { flex: 1, fontSize: 11.5, color: colors.onSurface, textAlign: "center" },
});
