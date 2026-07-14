/**
 * Iter 106 — Database Viewer / Editor (Super Admin, web only).
 * Browse every MongoDB collection of the CURRENT server (preview,
 * production or the user's own VPS), inspect documents, edit raw JSON
 * and delete records.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ScrollView, TextInput,
  ActivityIndicator, Platform, Modal,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type Coll = { name: string; count: number };
type Firm = { company_id: string; name: string; company_code?: string };
type Emp = { user_id: string; name: string; employee_code?: string; company_id?: string };

export default function DatabaseViewerScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const [colls, setColls] = useState<Coll[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [docs, setDocs] = useState<any[]>([]);
  const [total, setTotal] = useState(0);
  const [skip, setSkip] = useState(0);
  const [loading, setLoading] = useState(false);
  const [field, setField] = useState("");
  const [value, setValue] = useState("");
  // Firm-wise / Employee-wise filters
  const [firms, setFirms] = useState<Firm[]>([]);
  const [emps, setEmps] = useState<Emp[]>([]);
  const [firmId, setFirmId] = useState("");
  const [empId, setEmpId] = useState("");
  const [editDoc, setEditDoc] = useState<any>(null);
  const [editText, setEditText] = useState("");
  const [busy, setBusy] = useState(false);
  // Data source: this server vs personal VPS Mongo
  const [source, setSource] = useState<"local" | "external">("local");
  const [cfg, setCfg] = useState<any>(null);
  const [cfgOpen, setCfgOpen] = useState(false);
  const [cfgUrl, setCfgUrl] = useState("");
  const [cfgDb, setCfgDb] = useState("");
  const [cfgMsg, setCfgMsg] = useState<string | null>(null);
  const [cfgBusy, setCfgBusy] = useState(false);
  const LIMIT = 20;

  useEffect(() => {
    if (Platform.OS !== "web") router.replace("/(tabs)");
  }, [router]);

  const loadColls = useCallback((src: "local" | "external") => {
    setColls([]); setActive(null); setDocs([]);
    const sp = src === "external" ? "?source=external" : "";
    api<{ collections: Coll[] }>(`/admin/database/collections${sp}`)
      .then((r) => setColls(r.collections || []))
      .catch((e) => { setColls([]); window.alert(e?.message || "Cannot reach database"); });
    api<{ firms: Firm[]; employees: Emp[] }>(`/admin/database/filters${sp}`)
      .then((r) => { setFirms(r.firms || []); setEmps(r.employees || []); })
      .catch(() => { setFirms([]); setEmps([]); });
  }, []);

  useEffect(() => {
    loadColls("local");
    api<any>("/admin/database/config").then(setCfg).catch(() => {});
  }, [loadColls]);

  const loadDocs = useCallback(async (
    coll: string, s: number, f?: string, v?: string, cid?: string, uid?: string,
  ) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ skip: String(s), limit: String(LIMIT) });
      if (f && v) { params.set("field", f); params.set("value", v); }
      if (cid) params.set("company_id", cid);
      if (uid) params.set("user_id", uid);
      if (source === "external") params.set("source", "external");
      const r = await api<{ documents: any[]; total: number }>(
        `/admin/database/${encodeURIComponent(coll)}/documents?${params.toString()}`);
      setDocs(r.documents || []);
      setTotal(r.total || 0);
      setSkip(s);
    } catch (e: any) {
      window.alert(e?.message || "Failed to load documents");
    } finally { setLoading(false); }
  }, [source]);

  const openColl = (c: string) => {
    setActive(c); setField(""); setValue("");
    void loadDocs(c, 0, undefined, undefined, firmId, empId);
  };

  const openEdit = (d: any) => {
    const { __id, ...rest } = d;
    setEditDoc(d);
    setEditText(JSON.stringify(rest, null, 2));
  };

  const saveEdit = async () => {
    if (!active || !editDoc) return;
    let parsed: any;
    try { parsed = JSON.parse(editText); }
    catch { window.alert("Invalid JSON — fix the syntax before saving."); return; }
    setBusy(true);
    try {
      const sp = source === "external" ? "?source=external" : "";
      await api(`/admin/database/${encodeURIComponent(active)}/documents/${editDoc.__id}${sp}`, {
        method: "PUT", body: { document: parsed },
      });
      setEditDoc(null);
      await loadDocs(active, skip, field, value, firmId, empId);
    } catch (e: any) { window.alert(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  const del = async (d: any) => {
    if (!active) return;
    if (!window.confirm(`Delete this document from "${active}" permanently?`)) return;
    try {
      const sp = source === "external" ? "?source=external" : "";
      await api(`/admin/database/${encodeURIComponent(active)}/documents/${d.__id}${sp}`, {
        method: "DELETE",
      });
      await loadDocs(active, skip, field, value, firmId, empId);
    } catch (e: any) { window.alert(e?.message || "Delete failed"); }
  };

  if (user && user.role !== "super_admin") {
    return (
      <View style={styles.center}>
        <Text style={{ color: colors.onSurfaceTertiary }}>Super Admin only.</Text>
      </View>
    );
  }

  const summary = (d: any) => {
    const keys = Object.keys(d).filter((k) => k !== "__id").slice(0, 4);
    return keys.map((k) => `${k}: ${typeof d[k] === "object" ? "…" : String(d[k]).slice(0, 40)}`).join(" · ");
  };

  return (
    <View style={styles.root}>
      <View style={styles.pageHead}>
        <View style={{ flex: 1 }}>
          <Text style={styles.h1}>Database Viewer</Text>
          <Text style={styles.h1sub}>
            Live data · edits are immediate & permanent — be careful
          </Text>
        </View>
        {/* Data source toggle: this server vs personal VPS */}
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <Pressable
            onPress={() => { setSource("local"); loadColls("local"); }}
            style={[styles.srcChip, source === "local" && styles.srcChipOn]}
            testID="dbv-src-local">
            <Ionicons name="server-outline" size={14}
              color={source === "local" ? "#fff" : colors.onSurface} />
            <Text style={[styles.srcTxt, source === "local" && { color: "#fff" }]}>This Server</Text>
          </Pressable>
          <Pressable
            onPress={() => {
              if (!cfg?.configured) { setCfgOpen(true); return; }
              setSource("external"); loadColls("external");
            }}
            style={[styles.srcChip, source === "external" && styles.srcChipOn]}
            testID="dbv-src-external">
            <Ionicons name="cloud-outline" size={14}
              color={source === "external" ? "#fff" : colors.onSurface} />
            <Text style={[styles.srcTxt, source === "external" && { color: "#fff" }]}>
              {cfg?.label || "VPS Server"}
            </Text>
          </Pressable>
          <Pressable onPress={() => {
            setCfgUrl(""); setCfgDb(cfg?.db_name || ""); setCfgMsg(null); setCfgOpen(true);
          }} style={styles.gearBtn} testID="dbv-settings">
            <Ionicons name="settings-outline" size={17} color={colors.onSurface} />
          </Pressable>
        </View>
      </View>

      <View style={{ flexDirection: "row", flex: 1, gap: spacing.md, padding: spacing.md }}>
        {/* Collections list */}
        <ScrollView style={styles.collPane}>
          {colls.map((c) => (
            <Pressable key={c.name} onPress={() => openColl(c.name)}
              style={[styles.collRow, active === c.name && styles.collRowOn]}
              testID={`dbv-coll-${c.name}`}>
              <Text style={[styles.collName, active === c.name && { color: "#fff" }]} numberOfLines={1}>
                {c.name}
              </Text>
              <Text style={[styles.collCount, active === c.name && { color: "rgba(255,255,255,0.8)" }]}>
                {c.count}
              </Text>
            </Pressable>
          ))}
          {colls.length === 0 ? <ActivityIndicator color={colors.brandPrimary} style={{ margin: 20 }} /> : null}
        </ScrollView>

        {/* Documents */}
        <View style={{ flex: 1 }}>
          {!active ? (
            <View style={styles.center}>
              <Ionicons name="server-outline" size={40} color={colors.onSurfaceTertiary} />
              <Text style={{ color: colors.onSurfaceTertiary, marginTop: 8 }}>
                Pick a collection on the left to browse its records.
              </Text>
            </View>
          ) : (
            <>
              {/* Firm-wise / Employee-wise quick filters */}
              <View style={styles.searchRow}>
                <select
                  value={firmId}
                  onChange={(e) => {
                    const cid = (e.target as HTMLSelectElement).value;
                    setFirmId(cid); setEmpId("");
                    void loadDocs(active, 0, field, value, cid, "");
                  }}
                  style={styles.select as any}
                  data-testid="dbv-firm"
                >
                  <option value="">All firms</option>
                  {firms.map((f) => (
                    <option key={f.company_id} value={f.company_id}>
                      {f.name}{f.company_code ? ` · ${f.company_code}` : ""}
                    </option>
                  ))}
                </select>
                <select
                  value={empId}
                  onChange={(e) => {
                    const uid = (e.target as HTMLSelectElement).value;
                    setEmpId(uid);
                    void loadDocs(active, 0, field, value, firmId, uid);
                  }}
                  style={styles.select as any}
                  data-testid="dbv-emp"
                >
                  <option value="">All employees</option>
                  {emps
                    .filter((em) => !firmId || em.company_id === firmId)
                    .map((em) => (
                      <option key={em.user_id} value={em.user_id}>
                        {em.employee_code ? `${em.employee_code} · ` : ""}{em.name}
                      </option>
                    ))}
                </select>
              </View>
              <View style={styles.searchRow}>
                <TextInput style={[styles.input, { width: 180 }]} value={field} onChangeText={setField}
                  placeholder="Field (e.g. name)" testID="dbv-field" />
                <TextInput style={[styles.input, { flex: 1 }]} value={value} onChangeText={setValue}
                  placeholder="Value contains…" testID="dbv-value"
                  onSubmitEditing={() => loadDocs(active, 0, field, value, firmId, empId)} />
                <Pressable style={styles.btn} onPress={() => loadDocs(active, 0, field, value, firmId, empId)} testID="dbv-search">
                  <Ionicons name="search" size={15} color="#fff" />
                  <Text style={styles.btnTxt}>Search</Text>
                </Pressable>
                <Pressable style={[styles.btn, { backgroundColor: colors.onSurfaceTertiary }]}
                  onPress={() => {
                    setField(""); setValue(""); setFirmId(""); setEmpId("");
                    void loadDocs(active, 0);
                  }}>
                  <Text style={styles.btnTxt}>Clear</Text>
                </Pressable>
              </View>

              <Text style={styles.metaTxt}>
                {active} — {total} records · showing {Math.min(skip + 1, total)}–{Math.min(skip + LIMIT, total)}
              </Text>

              {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginTop: 30 }} /> : (
                <ScrollView style={{ flex: 1 }}>
                  {docs.map((d) => (
                    <View key={d.__id} style={styles.docRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.docSummary} numberOfLines={2}>{summary(d)}</Text>
                        <Text style={styles.docId}>_id: {d.__id}</Text>
                      </View>
                      <Pressable style={styles.editBtn} onPress={() => openEdit(d)} testID={`dbv-edit-${d.__id}`}>
                        <Ionicons name="create-outline" size={14} color="#fff" />
                        <Text style={styles.btnTxt}>Edit</Text>
                      </Pressable>
                      <Pressable style={styles.delBtn} onPress={() => del(d)} testID={`dbv-del-${d.__id}`}>
                        <Ionicons name="trash-outline" size={14} color="#DC2626" />
                      </Pressable>
                    </View>
                  ))}
                </ScrollView>
              )}

              <View style={styles.pager}>
                <Pressable disabled={skip === 0}
                  style={[styles.btn, skip === 0 && { opacity: 0.4 }]}
                  onPress={() => loadDocs(active, Math.max(0, skip - LIMIT), field, value, firmId, empId)}>
                  <Text style={styles.btnTxt}>← Prev</Text>
                </Pressable>
                <Pressable disabled={skip + LIMIT >= total}
                  style={[styles.btn, skip + LIMIT >= total && { opacity: 0.4 }]}
                  onPress={() => loadDocs(active, skip + LIMIT, field, value, firmId, empId)}>
                  <Text style={styles.btnTxt}>Next →</Text>
                </Pressable>
              </View>
            </>
          )}
        </View>
      </View>

      {/* Edit modal */}
      <Modal visible={!!editDoc} transparent animationType="fade" onRequestClose={() => setEditDoc(null)}>
        <View style={styles.modalBg}>
          <View style={styles.modalCard}>
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 8 }}>
              <Text style={[styles.h1, { fontSize: 16, flex: 1 }]}>
                Edit document — {active}
              </Text>
              <Pressable onPress={() => setEditDoc(null)}>
                <Ionicons name="close" size={20} color={colors.onSurfaceTertiary} />
              </Pressable>
            </View>
            <Text style={styles.docId}>_id: {editDoc?.__id} (cannot be changed)</Text>
            <TextInput
              multiline
              style={styles.jsonBox}
              value={editText}
              onChangeText={setEditText}
              testID="dbv-json"
            />
            <Pressable onPress={saveEdit} disabled={busy}
              style={[styles.btn, { alignSelf: "flex-end", marginTop: 10 }, busy && { opacity: 0.5 }]}
              testID="dbv-save">
              {busy ? <ActivityIndicator color="#fff" size="small" /> : (
                <><Ionicons name="save-outline" size={15} color="#fff" />
                  <Text style={styles.btnTxt}>Save Changes</Text></>
              )}
            </Pressable>
          </View>
        </View>
      </Modal>
      {/* VPS database settings modal */}
      <Modal visible={cfgOpen} transparent animationType="fade" onRequestClose={() => setCfgOpen(false)}>
        <View style={styles.modalBg}>
          <View style={[styles.modalCard, { maxWidth: 560 }]}>
            <View style={{ flexDirection: "row", alignItems: "center", marginBottom: 6 }}>
              <Text style={[styles.h1, { fontSize: 16, flex: 1 }]}>Personal VPS Database Settings</Text>
              <Pressable onPress={() => setCfgOpen(false)}>
                <Ionicons name="close" size={20} color={colors.onSurfaceTertiary} />
              </Pressable>
            </View>
            {cfg?.configured ? (
              <Text style={styles.metaTxt}>
                Currently saved: {cfg.mongo_url_masked} → {cfg.db_name}
              </Text>
            ) : (
              <Text style={styles.metaTxt}>No VPS database saved yet.</Text>
            )}
            <Text style={[styles.metaTxt, { color: "#B45309" }]}>
              Your VPS MongoDB must be reachable from the internet (bind IP +
              firewall + auth user). Example: mongodb://user:pass@YOUR-VPS-IP:27017
            </Text>
            <TextInput style={[styles.input, { marginTop: 8 }]} value={cfgUrl} onChangeText={setCfgUrl}
              placeholder="mongodb://user:password@vps-ip:27017" testID="dbv-cfg-url" />
            <TextInput style={[styles.input, { marginTop: 8 }]} value={cfgDb} onChangeText={setCfgDb}
              placeholder="Database name (e.g. payroll_production)" testID="dbv-cfg-db" />
            {cfgMsg ? <Text style={[styles.metaTxt, { marginTop: 8, fontWeight: "700" }]}>{cfgMsg}</Text> : null}
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12, justifyContent: "flex-end" }}>
              <Pressable disabled={cfgBusy}
                style={[styles.btn, { backgroundColor: "#B45309" }, cfgBusy && { opacity: 0.5 }]}
                onPress={async () => {
                  setCfgBusy(true); setCfgMsg(null);
                  try {
                    const r = await api<any>("/admin/database/config/test", {
                      method: "POST", body: { mongo_url: cfgUrl, db_name: cfgDb },
                    });
                    setCfgMsg(r.ok
                      ? `✓ Connected — ${r.collections_found} collections found`
                      : `✗ ${r.error}`);
                  } catch (e: any) { setCfgMsg(e?.message || "Test failed"); }
                  finally { setCfgBusy(false); }
                }} testID="dbv-cfg-test">
                <Text style={styles.btnTxt}>Test Connection</Text>
              </Pressable>
              <Pressable disabled={cfgBusy}
                style={[styles.btn, cfgBusy && { opacity: 0.5 }]}
                onPress={async () => {
                  setCfgBusy(true); setCfgMsg(null);
                  try {
                    await api("/admin/database/config", {
                      method: "PUT", body: { mongo_url: cfgUrl, db_name: cfgDb },
                    });
                    const fresh = await api<any>("/admin/database/config");
                    setCfg(fresh);
                    setCfgMsg("✓ Saved");
                    if (fresh.configured) { setSource("external"); loadColls("external"); setCfgOpen(false); }
                  } catch (e: any) { setCfgMsg(e?.message || "Save failed"); }
                  finally { setCfgBusy(false); }
                }} testID="dbv-cfg-save">
                <Text style={styles.btnTxt}>Save & Connect</Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  pageHead: {
    flexDirection: "row", alignItems: "center", gap: 12,
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
    borderBottomWidth: 1, borderColor: colors.divider, backgroundColor: colors.surface,
  },
  srcChip: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.divider, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 8, backgroundColor: colors.surface,
  },
  srcChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  srcTxt: { fontSize: 12, fontWeight: "800", color: colors.onSurface },
  gearBtn: {
    width: 34, height: 34, borderRadius: 8, alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.divider,
  },
  h1: { ...type.h2, color: colors.onSurface, fontWeight: "800" },
  h1sub: { fontSize: 12, color: "#B45309", marginTop: 2, fontWeight: "600" },
  collPane: {
    width: 240, backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.divider, maxHeight: "100%",
  },
  collRow: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 9, borderBottomWidth: 1, borderColor: colors.divider,
  },
  collRowOn: { backgroundColor: colors.brandPrimary },
  collName: { fontSize: 12.5, fontWeight: "700", color: colors.onSurface, flex: 1 },
  collCount: { fontSize: 11, color: colors.onSurfaceTertiary, marginLeft: 6 },
  searchRow: { flexDirection: "row", gap: 8, marginBottom: 8 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  select: {
    padding: 9, borderRadius: 8, borderWidth: 1, borderColor: colors.border,
    fontSize: 13, backgroundColor: colors.surface, color: colors.onSurface,
    flex: 1, minWidth: 200,
  },
  btn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandPrimary, paddingHorizontal: 14, paddingVertical: 9,
    borderRadius: radius.md,
  },
  btnTxt: { color: "#fff", fontWeight: "800", fontSize: 12.5 },
  metaTxt: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginBottom: 6 },
  docRow: {
    flexDirection: "row", alignItems: "center", gap: 10,
    backgroundColor: colors.surface, borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.divider,
    paddingHorizontal: 12, paddingVertical: 9, marginBottom: 6,
  },
  docSummary: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  docId: { fontSize: 10.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  editBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: "#16A34A", paddingHorizontal: 10, paddingVertical: 7, borderRadius: radius.md,
  },
  delBtn: {
    borderWidth: 1, borderColor: "#FCA5A5", padding: 7, borderRadius: radius.md,
  },
  pager: { flexDirection: "row", gap: 10, justifyContent: "center", paddingVertical: 8 },
  modalBg: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.5)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: 14, padding: 16,
    width: "100%", maxWidth: 760, maxHeight: "90%",
  },
  jsonBox: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: 12, fontSize: 12.5, color: colors.onSurface,
    backgroundColor: colors.background, marginTop: 8,
    minHeight: 340, maxHeight: 440,
    fontFamily: Platform.OS === "web" ? "monospace" : undefined,
    textAlignVertical: "top",
  },
});
