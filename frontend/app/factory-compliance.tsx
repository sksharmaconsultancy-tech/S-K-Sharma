/**
 * Factory & Boilers Compliance (Phase D).
 * Tabs: Compliance Dashboard · Registers (computed + data-entry) ·
 * Add Record (dynamic form per register kind).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Platform,
  StyleSheet,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import RegisterTable, {
  ExportButtons,
  shared,
} from "@/src/components/RegisterTable";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors } from "@/src/theme";

export default function FactoryComplianceScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const { selectedCompanyId } = useSelectedCompany();
  const [tab, setTab] = useState<"dashboard" | "registers" | "entry">(
    "dashboard",
  );
  const [kinds, setKinds] = useState<any>({ masters: [], computed: [] });
  const [kind, setKind] = useState("daily-attendance");
  const [entryKind, setEntryKind] = useState("license");
  const [form, setForm] = useState<Record<string, string>>({});
  const [records, setRecords] = useState<any[]>([]);
  const [data, setData] = useState<any>(null);
  const [dash, setDash] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  const companyId =
    user?.role === "company_admin" ? user.company_id : selectedCompanyId;

  useEffect(() => {
    api<any>("/admin/factory/kinds")
      .then(setKinds)
      .catch(() => {});
  }, []);

  const loadDash = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      setDash(await api<any>(`/admin/factory/dashboard?company_id=${companyId}`));
    } catch {
      setDash(null);
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  const loadRegister = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      setData(
        await api<any>(
          `/admin/factory/register/${kind}?company_id=${companyId}`,
        ),
      );
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [companyId, kind]);

  const loadRecords = useCallback(async () => {
    if (!companyId) return;
    try {
      const r = await api<any>(
        `/admin/factory/records?kind=${entryKind}&company_id=${companyId}`,
      );
      setRecords(r.records || []);
    } catch {
      setRecords([]);
    }
  }, [companyId, entryKind]);

  useEffect(() => {
    if (tab === "dashboard") void loadDash();
    if (tab === "registers") void loadRegister();
    if (tab === "entry") void loadRecords();
  }, [tab, loadDash, loadRegister, loadRecords]);

  const save = async () => {
    if (!companyId) return;
    setSaving(true);
    setMsg("");
    try {
      await api("/admin/factory/records", {
        method: "POST",
        body: { company_id: companyId, kind: entryKind, data: form },
      });
      setForm({});
      setMsg("✓ Record saved");
      void loadRecords();
    } catch (e: any) {
      setMsg(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const del = async (rid: string) => {
    try {
      await api(`/admin/factory/records/${rid}`, { method: "DELETE" });
      void loadRecords();
    } catch {}
  };

  if (authLoading) return null;
  if (!user || !["company_admin", "super_admin", "sub_admin"].includes(user.role))
    return <Redirect href="/" />;

  const allRegs = [...(kinds.computed || []), ...(kinds.masters || [])];
  const entryMeta = (kinds.masters || []).find((m: any) => m.kind === entryKind);

  return (
    <SafeAreaView style={shared.safe} edges={["top"]}>
      <View style={shared.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="fc-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={shared.headerTitle}>Factory & Boilers Compliance</Text>
        {tab === "registers" && companyId ? (
          <ExportButtons
            basePath={`/admin/factory/register/${kind}?company_id=${companyId}`}
            fileBase={kind}
          />
        ) : (
          <View style={{ width: 40 }} />
        )}
      </View>
      <ScrollView contentContainerStyle={{ padding: 12 }}>
        <View style={shared.tabs}>
          {(
            [
              ["dashboard", "Compliance Dashboard"],
              ["registers", "Registers"],
              ["entry", "Data Entry"],
            ] as const
          ).map(([kk, lbl]) => (
            <Pressable
              key={kk}
              onPress={() => setTab(kk)}
              style={[shared.tab, tab === kk && shared.tabActive]}
              testID={`fc-tab-${kk}`}
            >
              <Text style={[shared.tabTxt, tab === kk && shared.tabTxtActive]}>
                {lbl}
              </Text>
            </Pressable>
          ))}
        </View>

        {loading && <ActivityIndicator style={{ marginVertical: 24 }} />}

        {!loading && tab === "dashboard" && dash && (
          <>
            <View style={st.scoreRow}>
              <View style={st.scoreCard}>
                <Text style={[st.scoreVal, { color: "#15803D" }]}>
                  {dash.compliance_pct}%
                </Text>
                <Text style={st.scoreLbl}>Compliance Score</Text>
              </View>
              <View style={st.scoreCard}>
                <Text style={[st.scoreVal, { color: "#B91C1C" }]}>
                  {dash.risk_pct}%
                </Text>
                <Text style={st.scoreLbl}>Risk Score</Text>
              </View>
              <View style={st.scoreCard}>
                <Text style={st.scoreVal}>{dash.accidents_this_month}</Text>
                <Text style={st.scoreLbl}>Accidents This Month</Text>
              </View>
              <View style={st.scoreCard}>
                <Text style={st.scoreVal}>{dash.near_miss_this_month}</Text>
                <Text style={st.scoreLbl}>Near Miss This Month</Text>
              </View>
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>
                ⏰ Due / Expiry Alerts (next 45 days)
              </Text>
              {(dash.alerts || []).length === 0 && (
                <Text style={shared.meta}>
                  No upcoming renewals or inspections. Add licenses, boilers,
                  medicals etc. in the Data Entry tab to track due dates.
                </Text>
              )}
              {(dash.alerts || []).map((a: any, i: number) => (
                <View key={i} style={st.alertRow}>
                  <Text
                    style={[
                      st.alertStatus,
                      a.status === "OVERDUE" && { color: "#B91C1C" },
                    ]}
                  >
                    {a.status}
                  </Text>
                  <Text style={st.alertTxt}>
                    {a.what} — {a.ref} · due {a.due}
                  </Text>
                </View>
              ))}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>Records on File</Text>
              {Object.entries<number>(dash.record_counts || {}).map(
                ([kk, n]) => (
                  <Text key={kk} style={shared.meta}>
                    • {kk}: {n}
                  </Text>
                ),
              )}
              {Object.keys(dash.record_counts || {}).length === 0 && (
                <Text style={shared.meta}>No records yet.</Text>
              )}
            </View>
          </>
        )}

        {tab === "registers" && (
          <>
            <View style={shared.row}>
              {Platform.OS === "web" && (
                <select
                  data-testid="fc-register"
                  value={kind}
                  onChange={(e) =>
                    setKind((e.target as HTMLSelectElement).value)
                  }
                  style={{
                    padding: 8,
                    borderRadius: 8,
                    borderColor: "#CBD5E1",
                    borderWidth: 1,
                    fontSize: 13,
                    maxWidth: 340,
                  } as any}
                >
                  {allRegs.map((r: any) => (
                    <option key={r.kind} value={r.kind}>
                      {r.title}
                    </option>
                  ))}
                </select>
              )}
            </View>
            {!loading && data && (
              <View style={[shared.card, { marginTop: 10 }]}>
                <Text style={shared.cardTitle}>{data.title}</Text>
                <RegisterTable
                  columns={data.columns}
                  rows={data.rows}
                  totals={data.totals}
                />
              </View>
            )}
          </>
        )}

        {tab === "entry" && (
          <>
            <View style={shared.row}>
              {Platform.OS === "web" && (
                <select
                  data-testid="fc-entry-kind"
                  value={entryKind}
                  onChange={(e) => {
                    setForm({});
                    setEntryKind((e.target as HTMLSelectElement).value);
                  }}
                  style={{
                    padding: 8,
                    borderRadius: 8,
                    borderColor: "#CBD5E1",
                    borderWidth: 1,
                    fontSize: 13,
                    maxWidth: 340,
                  } as any}
                >
                  {(kinds.masters || []).map((m: any) => (
                    <option key={m.kind} value={m.kind}>
                      {m.title}
                    </option>
                  ))}
                </select>
              )}
            </View>
            <View style={[shared.card, { marginTop: 10 }]}>
              <Text style={shared.cardTitle}>
                Add — {entryMeta?.title || entryKind}
              </Text>
              <View style={st.formWrap}>
                {(entryMeta?.fields || []).map((f: any) => (
                  <View key={f.key} style={st.formField}>
                    <Text style={st.formLbl}>{f.label}</Text>
                    <TextInput
                      style={shared.input}
                      value={form[f.key] || ""}
                      onChangeText={(t) =>
                        setForm((p) => ({ ...p, [f.key]: t }))
                      }
                      placeholder={
                        /date|due|validity|inspection/i.test(f.key)
                          ? "YYYY-MM-DD"
                          : f.label
                      }
                      testID={`fc-f-${f.key}`}
                    />
                  </View>
                ))}
              </View>
              <Pressable
                onPress={save}
                disabled={saving}
                style={st.saveBtn}
                testID="fc-save"
              >
                {saving ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={st.saveTxt}>Save Record</Text>
                )}
              </Pressable>
              {!!msg && <Text style={shared.meta}>{msg}</Text>}
            </View>
            <View style={shared.card}>
              <Text style={shared.cardTitle}>
                Existing Records ({records.length})
              </Text>
              {records.map((r) => (
                <View key={r.record_id} style={st.recRow}>
                  <Text style={st.recTxt} numberOfLines={2}>
                    {Object.values(r.data || {})
                      .filter(Boolean)
                      .slice(0, 5)
                      .join(" · ")}
                  </Text>
                  <Pressable
                    onPress={() => del(r.record_id)}
                    hitSlop={8}
                    testID={`fc-del-${r.record_id}`}
                  >
                    <Ionicons name="trash-outline" size={17} color="#B91C1C" />
                  </Pressable>
                </View>
              ))}
              {records.length === 0 && (
                <Text style={shared.meta}>No records yet.</Text>
              )}
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  scoreRow: { flexDirection: "row", gap: 8, marginBottom: 12, flexWrap: "wrap" },
  scoreCard: {
    flexGrow: 1,
    minWidth: 140,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 12,
    padding: 12,
    alignItems: "center",
  },
  scoreVal: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  scoreLbl: { fontSize: 11, color: colors.onSurfaceSecondary, marginTop: 3 },
  alertRow: { flexDirection: "row", alignItems: "center", marginBottom: 6 },
  alertStatus: {
    fontSize: 10.5,
    fontWeight: "800",
    color: "#B45309",
    width: 76,
  },
  alertTxt: { fontSize: 12, color: colors.onSurface, flex: 1 },
  formWrap: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  formField: { minWidth: 200, flexGrow: 1, maxWidth: 320 },
  formLbl: {
    fontSize: 11.5,
    color: colors.onSurfaceSecondary,
    marginBottom: 3,
  },
  saveBtn: {
    marginTop: 12,
    backgroundColor: colors.brandPrimary,
    borderRadius: 8,
    paddingVertical: 10,
    alignItems: "center",
    maxWidth: 220,
  },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 13 },
  recRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 7,
    borderBottomWidth: 0.5,
    borderBottomColor: colors.border,
    gap: 8,
  },
  recTxt: { fontSize: 12, color: colors.onSurface, flex: 1 },
});
