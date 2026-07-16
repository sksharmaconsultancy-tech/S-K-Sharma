/**
 * Iter 149 — Manual CL/PL balance per employee.
 *
 * Admins set a per-employee yearly CL / PL allowance that OVERRIDES the
 * firm-level Leave Policy default. Blank = firm default. Used by the
 * Leave Report, the employee's own balance screen and leave validation.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  Pressable,
  TextInput,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { api } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius } from "@/src/theme";

type Emp = {
  user_id: string;
  name: string;
  employee_code?: string;
  designation?: string;
  cl_allowed_override?: number | null;
  pl_allowed_override?: number | null;
};

export default function LeaveBalanceConfig() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();

  const canPickFirm = user?.role !== "company_admin";
  const [companyId, setCompanyId] = useState<string | "all">(
    user?.role === "company_admin" ? (user.company_id || "all") : (selectedCompanyId || "all"),
  );
  const [data, setData] = useState<any>(null);
  const [emps, setEmps] = useState<Emp[]>([]);
  // Draft text per user_id+field so typing isn't clamped mid-edit.
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState("");
  const [msg, setMsg] = useState("");

  const load = useCallback(async () => {
    if (!companyId || companyId === "all") { setData(null); setEmps([]); return; }
    setLoading(true);
    setMsg("");
    try {
      const r = await api(`/admin/leave-balance-config?company_id=${companyId}`);
      setData(r);
      setEmps(r.employees || []);
      const d: Record<string, string> = {};
      for (const e of r.employees || []) {
        d[`${e.user_id}:cl`] = e.cl_allowed_override != null ? String(e.cl_allowed_override) : "";
        d[`${e.user_id}:pl`] = e.pl_allowed_override != null ? String(e.pl_allowed_override) : "";
      }
      setDraft(d);
      setDirty({});
    } catch (e: any) {
      setMsg(e?.message || "Could not load employees");
      setData(null);
      setEmps([]);
    } finally { setLoading(false); }
  }, [companyId]);

  useEffect(() => { load(); }, [load]);

  const edit = (uid: string, field: "cl" | "pl", v: string) => {
    const clean = v.replace(/[^0-9.]/g, "");
    setDraft((p) => ({ ...p, [`${uid}:${field}`]: clean }));
    setDirty((p) => ({ ...p, [uid]: true }));
  };

  const saveAll = async () => {
    const uids = Object.keys(dirty).filter((k) => dirty[k]);
    if (uids.length === 0) { setMsg("Nothing to save."); return; }
    setSaving(true);
    setMsg("");
    let ok = 0, err = 0;
    for (const uid of uids) {
      const cl = draft[`${uid}:cl`] ?? "";
      const pl = draft[`${uid}:pl`] ?? "";
      try {
        await api("/admin/leave-balance", {
          method: "PATCH",
          body: {
            user_id: uid,
            cl_allowed: cl.trim() === "" ? null : Number(cl),
            pl_allowed: pl.trim() === "" ? null : Number(pl),
          },
        });
        ok += 1;
      } catch { err += 1; }
    }
    setSaving(false);
    setDirty({});
    setMsg(`Saved ${ok} employee${ok === 1 ? "" : "s"}${err ? ` · ${err} failed` : ""} ✓`);
  };

  const filtered = useMemo(() => {
    if (!search.trim()) return emps;
    const s = search.trim().toLowerCase();
    return emps.filter(
      (e) =>
        (e.name || "").toLowerCase().includes(s) ||
        (e.employee_code || "").toLowerCase().includes(s),
    );
  }, [emps, search]);

  const dirtyCount = Object.values(dirty).filter(Boolean).length;

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role as string)) {
    return <Redirect href="/" />;
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} style={styles.backBtn}>
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>CL / PL Balance (Manual)</Text>
        <View style={{ width: 38 }} />
      </View>

      <KeyboardAvoidingView
        style={{ flex: 1 }}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={styles.toolbar}>
          {canPickFirm && (
            <CompanyPicker
              value={companyId}
              onChange={setCompanyId}
              label="Firm"
              allowAll={false}
              compact
              testID="lbc-firm-picker"
            />
          )}
          {data && (
            <Text style={styles.hint}>
              Firm default — CL: {data.cl_default} · PL: {data.pl_default} / year.
              {"\n"}Enter a value to override for that employee; leave BLANK to use the firm default.
            </Text>
          )}
          <TextInput
            value={search}
            onChangeText={setSearch}
            placeholder="Search by name or code…"
            placeholderTextColor={colors.onSurfaceTertiary}
            style={styles.search}
            autoCapitalize="none"
            testID="lbc-search"
          />
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
        ) : !data ? (
          <Text style={[styles.hint, { textAlign: "center", marginTop: 40 }]}>
            {msg || "Select a firm to configure CL/PL balances."}
          </Text>
        ) : (
          <FlatList
            data={filtered}
            keyExtractor={(e) => e.user_id}
            contentContainerStyle={{ paddingHorizontal: 16, paddingBottom: 90 }}
            keyboardShouldPersistTaps="handled"
            ListHeaderComponent={
              <View style={styles.rowHead}>
                <Text style={[styles.hCell, { flex: 1 }]}>Employee</Text>
                <Text style={[styles.hCell, styles.numCol]}>CL / yr</Text>
                <Text style={[styles.hCell, styles.numCol]}>PL / yr</Text>
              </View>
            }
            renderItem={({ item }) => {
              const isOv =
                (draft[`${item.user_id}:cl`] || "") !== "" ||
                (draft[`${item.user_id}:pl`] || "") !== "";
              return (
                <View style={[styles.row, dirty[item.user_id] && styles.rowDirty]}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.empName} numberOfLines={1}>
                      {item.name || "—"}
                      {item.employee_code ? (
                        <Text style={styles.empCode}>  ·  {item.employee_code}</Text>
                      ) : null}
                    </Text>
                    {isOv && <Text style={styles.ovTag}>manual override</Text>}
                  </View>
                  <TextInput
                    value={draft[`${item.user_id}:cl`] ?? ""}
                    onChangeText={(v) => edit(item.user_id, "cl", v)}
                    placeholder={String(data.cl_default)}
                    placeholderTextColor={colors.onSurfaceTertiary}
                    keyboardType="decimal-pad"
                    selectTextOnFocus
                    style={[styles.numInput]}
                    testID={`lbc-cl-${item.user_id}`}
                  />
                  <TextInput
                    value={draft[`${item.user_id}:pl`] ?? ""}
                    onChangeText={(v) => edit(item.user_id, "pl", v)}
                    placeholder={String(data.pl_default)}
                    placeholderTextColor={colors.onSurfaceTertiary}
                    keyboardType="decimal-pad"
                    selectTextOnFocus
                    style={[styles.numInput]}
                    testID={`lbc-pl-${item.user_id}`}
                  />
                </View>
              );
            }}
            ListEmptyComponent={
              <Text style={[styles.hint, { textAlign: "center", marginTop: 30 }]}>
                No employees found.
              </Text>
            }
          />
        )}

        {/* Save bar */}
        {data && (
          <View style={styles.saveBar}>
            {!!msg && <Text style={styles.msg} numberOfLines={1}>{msg}</Text>}
            <Pressable
              onPress={saveAll}
              disabled={saving || dirtyCount === 0}
              style={[styles.saveBtn, (saving || dirtyCount === 0) && { opacity: 0.5 }]}
              testID="lbc-save"
            >
              {saving ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.saveT}>
                  Save{dirtyCount > 0 ? ` (${dirtyCount})` : ""}
                </Text>
              )}
            </Pressable>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: 12, paddingVertical: 10,
  },
  backBtn: { width: 38, height: 38, alignItems: "center", justifyContent: "center" },
  headerTitle: { flex: 1, textAlign: "center", fontSize: 17, fontWeight: "700", color: colors.onSurface },

  toolbar: { paddingHorizontal: 16, gap: 10, marginBottom: 6 },
  hint: { fontSize: 12, color: colors.onSurfaceTertiary, lineHeight: 17 },
  search: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius?.md ?? 10,
    paddingVertical: 9, paddingHorizontal: 12, fontSize: 14,
    color: colors.onSurface, backgroundColor: colors.surfaceSecondary,
  },

  rowHead: { flexDirection: "row", alignItems: "center", paddingVertical: 6, gap: 8 },
  hCell: { fontSize: 11.5, fontWeight: "800", color: colors.onSurfaceTertiary, textTransform: "uppercase" },
  numCol: { width: 72, textAlign: "center" },

  row: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: colors.surfaceSecondary, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius?.md ?? 10, padding: 10, marginBottom: 8,
  },
  rowDirty: { borderColor: colors.brandPrimary },
  empName: { fontSize: 13.5, fontWeight: "700", color: colors.onSurface },
  empCode: { fontSize: 11.5, fontWeight: "600", color: colors.onSurfaceTertiary },
  ovTag: { fontSize: 10.5, color: colors.brandPrimary, fontWeight: "700", marginTop: 1 },
  numInput: {
    width: 72, minHeight: 44, textAlign: "center",
    borderWidth: 1, borderColor: colors.border, borderRadius: 8,
    fontSize: 14, fontWeight: "700", color: colors.onSurface,
    backgroundColor: colors.surface,
  },

  saveBar: {
    flexDirection: "row", alignItems: "center", gap: 10,
    padding: 12, borderTopWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  msg: { flex: 1, fontSize: 12.5, color: colors.onSurfaceSecondary },
  saveBtn: {
    marginLeft: "auto", backgroundColor: colors.brandPrimary,
    borderRadius: 10, paddingVertical: 12, paddingHorizontal: 22, minWidth: 110,
    alignItems: "center",
  },
  saveT: { color: "#fff", fontWeight: "800", fontSize: 14 },
});
