/**
 * Super Admin Rights — manage super_admin accounts (Super Admin only).
 *
 * Lists every super_admin account, lets the primary super admin add a
 * colleague (email OTP login always works; password optional), reset a
 * password, enable/disable, and delete. Backend blocks self-disable /
 * self-delete and protects the last enabled super admin.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, ScrollView, Pressable, TextInput,
  ActivityIndicator, Modal, Platform, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { router } from "expo-router";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing } from "@/src/theme";

type SuperAdmin = {
  user_id: string;
  name: string;
  email?: string | null;
  phone_e164?: string | null;
  disabled?: boolean;
  created_at?: string;
  password_must_change?: boolean;
};

function showMsg(msg: string, title = "Super Admin Rights") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function SuperAdminAccessScreen() {
  const { user, loading: authLoading } = useAuth();
  const isSuper = user?.role === "super_admin";

  const [rows, setRows] = useState<SuperAdmin[]>([]);
  const [meId, setMeId] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [showEditor, setShowEditor] = useState(false);
  const [editing, setEditing] = useState<SuperAdmin | null>(null);
  const [busy, setBusy] = useState(false);

  // editor fields
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ super_admins: SuperAdmin[]; me: string }>("/admin/super-admins");
      setRows(r.super_admins || []);
      setMeId(r.me || "");
    } catch (e: any) {
      showMsg(e?.message || "Could not load super admins");
    } finally { setLoading(false); }
  }, []);

  useEffect(() => { if (isSuper) load(); }, [isSuper, load]);

  const openCreate = () => {
    setEditing(null);
    setName(""); setEmail(""); setPhone(""); setPassword("");
    setShowEditor(true);
  };
  const openEdit = (r: SuperAdmin) => {
    setEditing(r);
    setName(r.name || ""); setEmail(r.email || "");
    setPhone(r.phone_e164 || ""); setPassword("");
    setShowEditor(true);
  };

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (editing) {
        await api(`/admin/super-admins/${editing.user_id}`, {
          method: "PATCH",
          body: { name, email, phone },
        });
        if (password.trim()) {
          await api(`/admin/super-admins/${editing.user_id}/reset-password`, {
            method: "POST", body: { password: password.trim() },
          });
        }
      } else {
        await api("/admin/super-admins", {
          method: "POST",
          body: { name, email, phone: phone || null, password: password.trim() || null },
        });
      }
      setShowEditor(false);
      await load();
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  const toggleDisabled = async (r: SuperAdmin) => {
    try {
      await api(`/admin/super-admins/${r.user_id}`, {
        method: "PATCH", body: { disabled: !r.disabled },
      });
      await load();
    } catch (e: any) { showMsg(e?.message || "Update failed"); }
  };

  const deleteOne = async (r: SuperAdmin) => {
    const ok = Platform.OS === "web"
      ? globalThis.confirm?.(`Delete super admin "${r.name}"? This cannot be undone.`)
      : true;
    if (!ok) return;
    try {
      await api(`/admin/super-admins/${r.user_id}`, { method: "DELETE" });
      setRows((prev) => prev.filter((x) => x.user_id !== r.user_id));
    } catch (e: any) { showMsg(e?.message || "Delete failed"); }
  };

  if (authLoading) {
    return (
      <View style={styles.root}><View style={styles.center}>
        <ActivityIndicator color={colors.brandPrimary} />
      </View></View>
    );
  }

  if (!isSuper) {
    return (
      <View style={styles.root}><View style={styles.center}>
        <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
        <Text style={styles.dimTxt}>Super Admin only</Text>
      </View></View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1, alignItems: "center" }}>
            <Text style={styles.h1}>Super Admin Rights</Text>
            <Text style={styles.hsub}>Root accounts with full portal access</Text>
          </View>
          <Pressable onPress={openCreate} style={styles.addBtn} testID="sa-add">
            <Ionicons name="person-add-outline" size={14} color="#fff" />
            <Text style={styles.addTxt}>Add</Text>
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.noteCard}>
          <Ionicons name="shield-checkmark-outline" size={16} color={colors.brandPrimary} />
          <Text style={styles.noteTxt}>
            Super admins can access EVERYTHING — every firm, every salary run, every setting.
            For limited access use Sub Admins instead. You cannot disable or delete yourself,
            and the last enabled super admin is protected.
          </Text>
        </View>

        {loading ? (
          <ActivityIndicator style={{ margin: 30 }} color={colors.brandPrimary} />
        ) : rows.map((r) => (
          <View key={r.user_id} style={[styles.card, r.disabled && { opacity: 0.55 }]}>
            <View style={styles.cardHead}>
              <View style={styles.avatar}>
                <Text style={styles.avatarTxt}>{(r.name || "?").slice(0, 1).toUpperCase()}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                  <Text style={styles.name}>{r.name}</Text>
                  {r.user_id === meId ? (
                    <View style={styles.meBadge}><Text style={styles.meBadgeTxt}>You</Text></View>
                  ) : null}
                  {r.disabled ? (
                    <View style={styles.offBadge}><Text style={styles.offBadgeTxt}>Disabled</Text></View>
                  ) : null}
                </View>
                <Text style={styles.sub}>{r.email || "—"}{r.phone_e164 ? ` · ${r.phone_e164}` : ""}</Text>
              </View>
            </View>
            <View style={styles.actions}>
              <Pressable onPress={() => openEdit(r)} style={styles.actBtn} testID={`sa-edit-${r.user_id}`}>
                <Ionicons name="create-outline" size={14} color={colors.brandPrimary} />
                <Text style={styles.actTxt}>Edit</Text>
              </Pressable>
              {r.user_id !== meId ? (
                <>
                  <Pressable onPress={() => toggleDisabled(r)} style={styles.actBtn}>
                    <Ionicons name={r.disabled ? "play-outline" : "pause-outline"} size={14} color="#B45309" />
                    <Text style={[styles.actTxt, { color: "#B45309" }]}>
                      {r.disabled ? "Enable" : "Disable"}
                    </Text>
                  </Pressable>
                  <Pressable onPress={() => deleteOne(r)} style={styles.actBtn}>
                    <Ionicons name="trash-outline" size={14} color="#DC2626" />
                    <Text style={[styles.actTxt, { color: "#DC2626" }]}>Delete</Text>
                  </Pressable>
                </>
              ) : null}
            </View>
          </View>
        ))}
        <View style={{ height: 40 }} />
      </ScrollView>

      {/* Editor modal */}
      <Modal visible={showEditor} transparent animationType="fade" onRequestClose={() => setShowEditor(false)}>
        <View style={styles.modalWrap}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>
              {editing ? `Edit — ${editing.name}` : "Add Super Admin"}
            </Text>
            <Text style={styles.lbl}>Full name *</Text>
            <TextInput style={styles.input} value={name} onChangeText={setName}
                       placeholder="e.g. Rakesh Sharma" placeholderTextColor={colors.onSurfaceTertiary}
                       testID="sa-name" />
            <Text style={styles.lbl}>Email (used for OTP login) *</Text>
            <TextInput style={styles.input} value={email} onChangeText={setEmail}
                       autoCapitalize="none" keyboardType="email-address"
                       placeholder="name@example.com" placeholderTextColor={colors.onSurfaceTertiary}
                       testID="sa-email" />
            <Text style={styles.lbl}>Phone (optional, +91…)</Text>
            <TextInput style={styles.input} value={phone} onChangeText={setPhone}
                       keyboardType="phone-pad" placeholder="+919999999999"
                       placeholderTextColor={colors.onSurfaceTertiary} testID="sa-phone" />
            <Text style={styles.lbl}>
              {editing ? "Reset password (leave blank to keep current)" : "Password (optional — OTP login always works)"}
            </Text>
            <TextInput style={styles.input} value={password} onChangeText={setPassword}
                       secureTextEntry placeholder="min 6 characters"
                       placeholderTextColor={colors.onSurfaceTertiary} testID="sa-password" />
            <View style={styles.modalActions}>
              <Pressable onPress={() => setShowEditor(false)} style={[styles.mBtn, styles.mBtnGhost]}>
                <Text style={styles.mBtnGhostTxt}>Cancel</Text>
              </Pressable>
              <Pressable onPress={save} style={[styles.mBtn, styles.mBtnPrimary]} testID="sa-save">
                {busy ? <ActivityIndicator size="small" color="#fff" /> : (
                  <Text style={styles.mBtnPrimaryTxt}>{editing ? "Save changes" : "Create"}</Text>
                )}
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
  header: {
    flexDirection: "row", alignItems: "center",
    paddingHorizontal: spacing.md, paddingVertical: 10,
    backgroundColor: colors.surface,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  h1: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  hsub: { fontSize: 11, color: colors.onSurfaceTertiary },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.md,
  },
  addTxt: { color: "#fff", fontWeight: "800", fontSize: 12 },
  scroll: { padding: spacing.md, ...(Platform.OS === "web" ? { maxWidth: 760, width: "100%", alignSelf: "center" } : {}) },
  noteCard: {
    flexDirection: "row", gap: 8, alignItems: "flex-start",
    backgroundColor: "#EFF6FF", borderRadius: radius.lg,
    borderWidth: 1, borderColor: "#BFDBFE",
    padding: 12, marginBottom: 12,
  },
  noteTxt: { flex: 1, fontSize: 12, color: "#1E40AF", lineHeight: 17 },
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    borderWidth: 1, borderColor: colors.border,
    padding: 12, marginBottom: 10,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  avatar: {
    width: 38, height: 38, borderRadius: 19,
    backgroundColor: "#1E3A8A", alignItems: "center", justifyContent: "center",
  },
  avatarTxt: { color: "#fff", fontWeight: "800", fontSize: 15 },
  name: { fontSize: 14, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 1 },
  meBadge: {
    backgroundColor: "#DCFCE7", paddingHorizontal: 7, paddingVertical: 2,
    borderRadius: radius.pill,
  },
  meBadgeTxt: { fontSize: 10, fontWeight: "800", color: "#15803D" },
  offBadge: {
    backgroundColor: "#FEE2E2", paddingHorizontal: 7, paddingVertical: 2,
    borderRadius: radius.pill,
  },
  offBadgeTxt: { fontSize: 10, fontWeight: "800", color: "#DC2626" },
  actions: {
    flexDirection: "row", gap: 8, marginTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: colors.divider,
    paddingTop: 8,
  },
  actBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    paddingHorizontal: 10, paddingVertical: 7,
    borderRadius: radius.md, borderWidth: 1, borderColor: colors.border,
  },
  actTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  modalWrap: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.45)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  modalCard: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: 18, width: "100%", maxWidth: 460,
  },
  modalTitle: { fontSize: 16, fontWeight: "800", color: colors.onSurface, marginBottom: 10 },
  lbl: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 10, marginBottom: 4 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: Platform.OS === "web" ? 10 : 8,
    fontSize: 13, color: colors.onSurface, backgroundColor: colors.background,
  },
  modalActions: { flexDirection: "row", justifyContent: "flex-end", gap: 8, marginTop: 16 },
  mBtn: {
    paddingHorizontal: 16, paddingVertical: 10, borderRadius: radius.md,
    alignItems: "center", justifyContent: "center", minWidth: 90,
  },
  mBtnGhost: { borderWidth: 1, borderColor: colors.border },
  mBtnGhostTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  mBtnPrimary: { backgroundColor: colors.brandPrimary },
  mBtnPrimaryTxt: { fontSize: 13, fontWeight: "800", color: "#fff" },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8, padding: 40 },
  dimTxt: { color: colors.onSurfaceTertiary, fontSize: 13 },
});
