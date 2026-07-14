/**
 * Portal Credentials — Iter 58.
 *
 * A web-portal page where an employer (company admin) or the super admin
 * stores the login credentials the firm uses for the government labour
 * portals: EPFO, ESIC and SSO Shram Suvidha. Once entered, credentials
 * are encrypted at rest and can be used later to drive Chrome automation
 * for uploading ECR / ESIC challans on the client's behalf.
 *
 * Passwords are NEVER surfaced back once saved — the UI only shows a
 * "Password set — [ Change ] [ Clear ]" state.
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
import { useLocalSearchParams, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type PortalKey = "epfo" | "esic" | "shram_suvidha";

type PortalInfo = {
  label: string;
  username: string;
  notes: string;
  has_password: boolean;
  updated_at?: string;
};

type Response = {
  company_id: string;
  company_name?: string;
  portals: Record<PortalKey, PortalInfo>;
  known_portals: PortalKey[];
  portal_labels: Record<PortalKey, string>;
};

const PORTAL_ORDER: PortalKey[] = ["epfo", "esic", "shram_suvidha"];

const PORTAL_HINTS: Record<PortalKey, string> = {
  epfo:
    "unifiedportal-emp.epfindia.gov.in — used to submit ECR and pay EPF contributions each month.",
  esic:
    "esic.in — used to submit monthly ESIC contributions and generate challans.",
  shram_suvidha:
    "shramsuvidha.gov.in — unified portal for EPFO/ESIC labour-law compliance.",
};

function showMsg(msg: string, title = "Portal credentials") {
  if (Platform.OS === "web") globalThis.alert(msg);
  else Alert.alert(title, msg);
}

export default function PortalCredentialsScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ company_id?: string }>();
  const { user } = useAuth();

  const isCompanyAdmin = user?.role === "company_admin";
  const effectiveCompanyId = isCompanyAdmin
    ? user?.company_id
    : (params.company_id as string | undefined);

  const [state, setState] = useState<Response | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] = useState<PortalKey | null>(null);

  const load = useCallback(async () => {
    if (!effectiveCompanyId) return;
    setLoading(true);
    try {
      const r = await api<Response>(
        `/admin/companies/${effectiveCompanyId}/portal-credentials`,
      );
      setState(r);
    } catch (e: any) {
      showMsg(e?.message || "Could not load credentials");
    } finally {
      setLoading(false);
    }
  }, [effectiveCompanyId]);

  useEffect(() => {
    load();
  }, [load]);

  const savePortal = async (key: PortalKey, body: any) => {
    if (!effectiveCompanyId) return;
    setSavingKey(key);
    try {
      const r = await api<Response>(
        `/admin/companies/${effectiveCompanyId}/portal-credentials`,
        { method: "PATCH", body: { portal: key, ...body } },
      );
      setState(r);
      showMsg("Saved ✓");
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setSavingKey(null);
    }
  };

  if (!effectiveCompanyId) {
    return (
      <SafeAreaView style={styles.root} edges={["top"]}>
        <View style={styles.forb}>
          <Ionicons name="alert-circle-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>
            Choose a company first — open this page from the Companies list.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} testID="pc-back">
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.h1}>Portal credentials</Text>
            <Text style={styles.hsub} numberOfLines={1}>
              {state?.company_name || "—"} · used for ECR / ESIC uploads
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.infoCard}>
          <Ionicons name="lock-closed-outline" size={16} color={colors.brandPrimary} />
          <Text style={styles.infoTxt}>
            Passwords are encrypted at rest with AES/Fernet. They are only ever
            used to log into the respective government portal on your behalf.
            Once saved they cannot be viewed back — only replaced or cleared.
          </Text>
        </View>

        {loading || !state ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : (
          PORTAL_ORDER.map((k) => (
            <PortalCard
              key={k}
              portalKey={k}
              info={state.portals[k]}
              hint={PORTAL_HINTS[k]}
              saving={savingKey === k}
              onSave={(body) => savePortal(k, body)}
            />
          ))
        )}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

function PortalCard({
  portalKey,
  info,
  hint,
  saving,
  onSave,
}: {
  portalKey: PortalKey;
  info: PortalInfo;
  hint: string;
  saving: boolean;
  onSave: (body: {
    username?: string;
    password?: string;
    notes?: string;
    clear_password?: boolean;
  }) => void;
}) {
  const [username, setUsername] = useState(info?.username || "");
  const [notes, setNotes] = useState(info?.notes || "");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);

  useEffect(() => {
    setUsername(info?.username || "");
    setNotes(info?.notes || "");
    setPassword("");
  }, [info]);

  const submit = () => {
    const body: any = {};
    if (username !== info?.username) body.username = username;
    if (notes !== info?.notes) body.notes = notes;
    if (password.trim() !== "") body.password = password;
    if (Object.keys(body).length === 0) {
      showMsg("Nothing to save yet.");
      return;
    }
    onSave(body);
    setPassword("");
  };

  const clearPassword = () => {
    if (!globalThis.confirm?.("Clear the stored password? You'll need to re-enter it to auto-upload.")) return;
    onSave({ clear_password: true });
    setPassword("");
  };

  return (
    <View style={styles.card}>
      <View style={styles.cardHead}>
        <View style={styles.cardIcon}>
          <Ionicons name="key-outline" size={18} color={colors.brandPrimary} />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.cardTitle}>{info?.label || portalKey}</Text>
          <Text style={styles.cardSub}>{hint}</Text>
        </View>
        <View
          style={[
            styles.statusPill,
            info?.has_password ? styles.statusPillOk : styles.statusPillOff,
          ]}
        >
          <Ionicons
            name={info?.has_password ? "checkmark-circle" : "help-circle-outline"}
            size={12}
            color={info?.has_password ? "#0F5B22" : "#7A1B00"}
          />
          <Text
            style={[
              styles.statusPillTxt,
              { color: info?.has_password ? "#0F5B22" : "#7A1B00" },
            ]}
          >
            {info?.has_password ? "Password set" : "Not set"}
          </Text>
        </View>
      </View>

      <View style={styles.gridRow}>
        <View style={styles.gridCol}>
          <Text style={styles.label}>Username / User ID</Text>
          <TextInput
            testID={`pc-${portalKey}-username`}
            value={username}
            onChangeText={setUsername}
            style={styles.input}
            placeholder="e.g. 24DEL1234567"
            placeholderTextColor={colors.onSurfaceTertiary}
            autoCapitalize="none"
          />
        </View>
        <View style={styles.gridCol}>
          <Text style={styles.label}>
            Password {info?.has_password ? "(leave blank to keep unchanged)" : ""}
          </Text>
          <View style={styles.pwWrap}>
            <TextInput
              testID={`pc-${portalKey}-password`}
              value={password}
              onChangeText={setPassword}
              style={[styles.input, { flex: 1 }]}
              placeholder={info?.has_password ? "••••••••" : "Enter password"}
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="none"
              secureTextEntry={!showPw}
            />
            <Pressable
              onPress={() => setShowPw((v) => !v)}
              style={styles.eyeBtn}
              hitSlop={8}
            >
              <Ionicons
                name={showPw ? "eye-off-outline" : "eye-outline"}
                size={16}
                color={colors.onSurfaceSecondary}
              />
            </Pressable>
          </View>
        </View>
      </View>

      <Text style={styles.label}>Notes (optional)</Text>
      <TextInput
        value={notes}
        onChangeText={setNotes}
        style={styles.input}
        placeholder="e.g. TAN / Establishment ID / Rep name"
        placeholderTextColor={colors.onSurfaceTertiary}
      />

      {info?.updated_at ? (
        <Text style={styles.updatedTxt}>
          Last updated{" "}
          {new Date(info.updated_at).toLocaleString([], {
            day: "2-digit",
            month: "short",
            year: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          })}
        </Text>
      ) : null}

      <View style={styles.actionsRow}>
        {info?.has_password ? (
          <Pressable
            onPress={clearPassword}
            style={styles.dangerBtn}
            testID={`pc-${portalKey}-clear`}
          >
            <Ionicons name="trash-outline" size={14} color="#8A1F1F" />
            <Text style={styles.dangerBtnTxt}>Clear password</Text>
          </Pressable>
        ) : null}
        <Pressable
          onPress={submit}
          disabled={saving}
          style={[styles.saveBtn, saving && { opacity: 0.6 }, { flex: 1 }]}
          testID={`pc-${portalKey}-save`}
        >
          {saving ? (
            <ActivityIndicator color="#fff" />
          ) : (
            <>
              <Ionicons name="save-outline" size={14} color="#fff" />
              <Text style={styles.saveBtnTxt}>Save</Text>
            </>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  forb: { flex: 1, alignItems: "center", justifyContent: "center", padding: 40 },
  forbT: {
    marginTop: 8,
    color: colors.onSurfaceSecondary,
    fontSize: type.body,
    textAlign: "center",
  },
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

  scroll: { padding: spacing.lg },
  infoCard: {
    flexDirection: "row",
    gap: 10,
    padding: spacing.md,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    marginBottom: spacing.md,
  },
  infoTxt: {
    flex: 1,
    color: colors.onBrandTertiary,
    fontSize: type.sm,
    lineHeight: 20,
  },

  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
    borderWidth: 1,
    borderColor: colors.divider,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10, marginBottom: 6 },
  cardIcon: {
    width: 32,
    height: 32,
    borderRadius: 16,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  cardTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  cardSub: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },

  statusPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 12,
  },
  statusPillOk: { backgroundColor: "#E7F5EA" },
  statusPillOff: { backgroundColor: "#FDECE2" },
  statusPillTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.3 },

  gridRow: { flexDirection: "row", gap: 10, flexWrap: "wrap", marginTop: 8 },
  gridCol: { flex: 1, minWidth: 240 },
  label: {
    fontSize: 10,
    color: colors.onSurfaceSecondary,
    fontWeight: "800",
    marginBottom: 4,
    marginTop: 8,
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
  pwWrap: { flexDirection: "row", alignItems: "center", gap: 6 },
  eyeBtn: { padding: 8, borderRadius: 6, backgroundColor: colors.surfaceSecondary },
  updatedTxt: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 6 },

  actionsRow: { flexDirection: "row", gap: 8, marginTop: 12 },
  saveBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 6,
  },
  saveBtnTxt: { color: "#fff", fontWeight: "800" },
  dangerBtn: {
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: "#8A1F1F",
    backgroundColor: "#FDECE2",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  dangerBtnTxt: { color: "#8A1F1F", fontWeight: "800", fontSize: type.sm },
});
