/**
 * Iter 395 — WhatsApp Message Templates (CRUD + variables + preview).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Modal, Platform, Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { router } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

const WA_GREEN = "#128C7E";

type Tpl = {
  template_id: string; company_id: string; category: string; name: string;
  body: string; language: string; meta_template_name?: string;
  active: boolean; is_default?: boolean;
};

export default function WhatsAppTemplatesScreen() {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [, setCompanies] = useState<{ company_id: string; name: string }[]>([]);
  const [cid, setCid] = useState("");
  const [templates, setTemplates] = useState<Tpl[]>([]);
  const [variables, setVariables] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Partial<Tpl> | null>(null);
  const [saving, setSaving] = useState(false);
  const [previewText, setPreviewText] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<any>("/companies?lite=1");
        const list = (r?.companies || r || []).filter((c: any) => c.is_active !== false);
        setCompanies(list.map((c: any) => ({ company_id: c.company_id, name: c.name })));
        if (!isSuper && user?.company_id) setCid(user.company_id);
        else if (list.length) setCid(list[0].company_id);
      } catch { /* noop */ }
    })();
  }, [isSuper, user?.company_id]);

  const load = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    try {
      const r = await api<any>(`/admin/whatsapp/templates?company_id=${cid}`);
      setTemplates(r.templates || []);
      setVariables(r.variables || []);
    } catch (e: any) {
      setBanner({ kind: "err", msg: e?.message || "Failed to load" });
    } finally { setLoading(false); }
  }, [cid]);
  useEffect(() => { load(); }, [load]);

  const seed = async () => {
    try {
      const r = await api<any>(`/admin/whatsapp/templates/seed-defaults?company_id=${cid}`,
        { method: "POST", body: {} });
      setBanner({ kind: "ok", msg: `${r.created} default templates created.` });
      load();
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || "Seed failed" }); }
  };

  const saveTpl = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      if (editing.template_id) {
        await api<any>(`/admin/whatsapp/templates/${editing.template_id}`,
          { method: "PUT", body: editing });
      } else {
        await api<any>(`/admin/whatsapp/templates?company_id=${cid}`,
          { method: "POST", body: editing });
      }
      setEditing(null);
      setBanner({ kind: "ok", msg: "Template saved." });
      load();
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || "Save failed" }); }
    finally { setSaving(false); }
  };

  const delTpl = async (id: string) => {
    try {
      await api<any>(`/admin/whatsapp/templates/${id}`, { method: "DELETE" });
      load();
    } catch (e: any) { setBanner({ kind: "err", msg: e?.message || "Delete failed" }); }
  };

  const preview = async (t: Partial<Tpl>) => {
    try {
      const r = await api<any>(`/admin/whatsapp/preview?company_id=${cid}`,
        { method: "POST", body: { body: t.body } });
      setPreviewText(r.rendered || "");
    } catch { setPreviewText(t.body || ""); }
  };

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return templates;
    return templates.filter((t) =>
      t.name.toLowerCase().includes(q) || t.category.toLowerCase().includes(q) ||
      (t.body || "").toLowerCase().includes(q));
  }, [templates, query]);

  return (
    <SafeAreaView style={st.safe} edges={["top"]}>
      <View style={st.header}>
        <Pressable onPress={() => router.back()} style={{ padding: 6 }}>
          <Ionicons name="arrow-back" size={22} color={colors.text} />
        </Pressable>
        <Ionicons name="logo-whatsapp" size={22} color="#25D366" />
        <Text style={st.title}>WhatsApp Templates</Text>
        <View style={{ flex: 1 }} />
        <Pressable style={st.smallBtn} onPress={seed} testID="wa-tpl-seed">
          <Ionicons name="download-outline" size={14} color="#fff" />
          <Text style={st.smallBtnText}>Seed Defaults</Text>
        </Pressable>
        <Pressable style={[st.smallBtn, { backgroundColor: "#0EA5E9" }]}
          onPress={() => setEditing({ category: "custom", name: "", body: "", language: "en", active: true })}
          testID="wa-tpl-new">
          <Ionicons name="add" size={14} color="#fff" />
          <Text style={st.smallBtnText}>New Template</Text>
        </Pressable>
      </View>

      {banner && (
        <View style={[st.banner, banner.kind === "ok" ? { backgroundColor: "#DCFCE7" } : { backgroundColor: "#FEE2E2" }]}>
          <Text style={{ color: banner.kind === "ok" ? "#166534" : "#991B1B", fontSize: 12.5 }}>{banner.msg}</Text>
        </View>
      )}

      <View style={st.searchRow}>
        <Ionicons name="search" size={16} color={colors.muted} />
        <TextInput style={st.searchInput} value={query} onChangeText={setQuery}
          placeholder="Search templates…" placeholderTextColor={colors.muted} />
      </View>

      {loading ? <ActivityIndicator style={{ marginTop: 40 }} color={WA_GREEN} /> : (
        <ScrollView contentContainerStyle={st.body}>
          {filtered.map((t) => (
            <View key={t.template_id} style={st.card}>
              <View style={st.rowBetween}>
                <View style={{ flex: 1 }}>
                  <Text style={st.tplName}>{t.name}</Text>
                  <View style={{ flexDirection: "row", gap: 6, marginTop: 2, flexWrap: "wrap" }}>
                    <View style={st.catPill}><Text style={st.catText}>{t.category}</Text></View>
                    {t.company_id === "__global__" && (
                      <View style={[st.catPill, { backgroundColor: "#E0F2FE" }]}>
                        <Text style={[st.catText, { color: "#0369A1" }]}>global</Text>
                      </View>
                    )}
                    {!t.active && (
                      <View style={[st.catPill, { backgroundColor: "#FEE2E2" }]}>
                        <Text style={[st.catText, { color: "#991B1B" }]}>inactive</Text>
                      </View>
                    )}
                  </View>
                </View>
                <View style={{ flexDirection: "row", gap: 4 }}>
                  <Pressable style={st.iconBtn} onPress={() => preview(t)}>
                    <Ionicons name="eye-outline" size={17} color="#0EA5E9" />
                  </Pressable>
                  <Pressable style={st.iconBtn} onPress={() => setEditing({ ...t })}>
                    <Ionicons name="create-outline" size={17} color={WA_GREEN} />
                  </Pressable>
                  <Pressable style={st.iconBtn} onPress={() => delTpl(t.template_id)}>
                    <Ionicons name="trash-outline" size={17} color="#DC2626" />
                  </Pressable>
                </View>
              </View>
              <Text style={st.tplBody} numberOfLines={3}>{t.body}</Text>
            </View>
          ))}
          {!filtered.length && (
            <Text style={{ color: colors.muted, textAlign: "center", marginTop: 30 }}>
              No templates yet — tap &quot;Seed Defaults&quot; to load 30 ready-made templates.
            </Text>
          )}
          <View style={{ height: 40 }} />
        </ScrollView>
      )}

      {/* Edit modal */}
      <Modal visible={!!editing} transparent animationType="fade" onRequestClose={() => setEditing(null)}>
        <View style={st.modalWrap}>
          <View style={st.modalCard}>
            <Text style={st.modalTitle}>{editing?.template_id ? "Edit Template" : "New Template"}</Text>
            <ScrollView style={{ maxHeight: 460 }}>
              <Text style={st.label}>Name</Text>
              <TextInput style={st.input} value={editing?.name || ""}
                onChangeText={(v) => setEditing({ ...editing!, name: v })} />
              <Text style={st.label}>Category (event key)</Text>
              <TextInput style={st.input} value={editing?.category || ""}
                autoCapitalize="none"
                onChangeText={(v) => setEditing({ ...editing!, category: v })} />
              <Text style={st.label}>Message Body</Text>
              <TextInput style={[st.input, { minHeight: 120, textAlignVertical: "top" }]}
                multiline value={editing?.body || ""}
                onChangeText={(v) => setEditing({ ...editing!, body: v })}
                testID="wa-tpl-body" />
              <Text style={st.label}>Insert variable:</Text>
              <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 6 }}>
                {variables.map((v) => (
                  <Pressable key={v} style={st.varChip}
                    onPress={() => setEditing({ ...editing!, body: `${editing?.body || ""}{{${v}}}` })}>
                    <Text style={st.varChipText}>{`{{${v}}}`}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={st.label}>Meta Approved Template Name (optional)</Text>
              <TextInput style={st.input} value={editing?.meta_template_name || ""}
                autoCapitalize="none" placeholder="leave blank to send as text"
                placeholderTextColor={colors.muted}
                onChangeText={(v) => setEditing({ ...editing!, meta_template_name: v })} />
              <View style={[st.rowBetween, { marginTop: 8 }]}>
                <Text style={st.label}>Active</Text>
                <Switch value={editing?.active !== false}
                  onValueChange={(v) => setEditing({ ...editing!, active: v })}
                  trackColor={{ true: "#25D366" }} />
              </View>
            </ScrollView>
            <View style={{ flexDirection: "row", gap: 8, marginTop: 12 }}>
              <Pressable style={[st.btn, { flex: 1, backgroundColor: colors.border }]}
                onPress={() => setEditing(null)}>
                <Text style={[st.btnText, { color: colors.text }]}>Cancel</Text>
              </Pressable>
              <Pressable style={[st.btn, { flex: 1, backgroundColor: WA_GREEN }]}
                onPress={saveTpl} disabled={saving} testID="wa-tpl-save">
                {saving ? <ActivityIndicator size="small" color="#fff" /> :
                  <Text style={st.btnText}>Save</Text>}
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>

      {/* Preview modal */}
      <Modal visible={previewText !== null} transparent animationType="fade"
        onRequestClose={() => setPreviewText(null)}>
        <View style={st.modalWrap}>
          <View style={[st.modalCard, { backgroundColor: "#ECE5DD" }]}>
            <Text style={[st.modalTitle, { color: "#111" }]}>Preview</Text>
            <View style={st.waBubble}>
              <Text style={{ color: "#111", fontSize: 13.5, lineHeight: 19 }}>{previewText}</Text>
            </View>
            <Pressable style={[st.btn, { backgroundColor: WA_GREEN, marginTop: 12 }]}
              onPress={() => setPreviewText(null)}>
              <Text style={st.btnText}>Close</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  );
}

const st = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row", alignItems: "center", gap: spacing.sm,
    paddingHorizontal: spacing.md, paddingVertical: spacing.sm,
    borderBottomWidth: 1, borderBottomColor: colors.border, backgroundColor: colors.card,
  },
  title: { fontSize: 17, fontWeight: "700", color: colors.text },
  smallBtn: {
    flexDirection: "row", alignItems: "center", gap: 4, backgroundColor: WA_GREEN,
    borderRadius: radius.md, paddingHorizontal: 10, paddingVertical: 8,
  },
  smallBtnText: { color: "#fff", fontSize: 12, fontWeight: "700" },
  banner: { margin: spacing.sm, borderRadius: radius.md, padding: spacing.sm },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 6, margin: spacing.sm,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, backgroundColor: colors.card,
  },
  searchInput: { flex: 1, paddingVertical: 8, color: colors.text, fontSize: 13.5 },
  body: { padding: spacing.md, gap: spacing.sm, maxWidth: 860, width: "100%", alignSelf: "center" },
  card: {
    backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border,
  },
  rowBetween: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  tplName: { fontSize: 14.5, fontWeight: "700", color: colors.text },
  tplBody: { fontSize: 12.5, color: colors.muted, marginTop: 6, lineHeight: 18 },
  catPill: { backgroundColor: "#DCFCE7", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 2 },
  catText: { fontSize: 11, color: "#166534", fontWeight: "600" },
  iconBtn: { padding: 8 },
  modalWrap: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)", alignItems: "center",
    justifyContent: "center", padding: spacing.md,
  },
  modalCard: {
    backgroundColor: colors.card, borderRadius: radius.lg, padding: spacing.md,
    width: "100%", maxWidth: 560,
  },
  modalTitle: { fontSize: 16, fontWeight: "700", color: colors.text, marginBottom: 8 },
  label: { fontSize: 12.5, color: colors.muted, marginTop: 10, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: Platform.OS === "web" ? 8 : 6,
    color: colors.text, backgroundColor: colors.background, fontSize: 13.5,
  },
  varChip: { backgroundColor: "#F0FDF4", borderWidth: 1, borderColor: "#BBF7D0", borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4 },
  varChipText: { fontSize: 11.5, color: "#166534" },
  btn: { alignItems: "center", justifyContent: "center", borderRadius: radius.md, paddingVertical: 12, minHeight: 44 },
  btnText: { color: "#fff", fontWeight: "700" },
  waBubble: {
    backgroundColor: "#fff", borderRadius: 10, padding: 12,
    borderTopLeftRadius: 2, maxWidth: "92%",
    ...(Platform.OS === "web" ? { boxShadow: "0 1px 2px rgba(0,0,0,0.15)" } as any : {}),
  },
});
