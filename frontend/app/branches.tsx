import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  TextInput,
  RefreshControl,
  Alert,
  Platform,
  KeyboardAvoidingView,
  Switch,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useFocusEffect, useRouter } from "expo-router";
import * as Location from "expo-location";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

type Branch = {
  branch_id: string;
  company_id: string;
  name: string;
  address?: string | null;
  office_lat: number;
  office_lng: number;
  geofence_radius_m: number;
  active: boolean;
};

export default function BranchesScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const isAdmin = isSuper || user?.role === "company_admin";

  const [branches, setBranches] = useState<Branch[]>([]);
  const [companies, setCompanies] = useState<any[]>([]);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [editing, setEditing] = useState<Branch | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [faceMatchEnabled, setFaceMatchEnabled] = useState<boolean>(false);
  const [faceMatchBusy, setFaceMatchBusy] = useState(false);

  // Which company's face-match toggle we're editing:
  //  - company_admin → their own company
  //  - super_admin   → currently-selected company (null when "all")
  const targetCompanyId = isSuper
    ? companyFilter === "all"
      ? null
      : (companyFilter as string)
    : (user as any)?.company_id || null;

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Branches", msg);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q =
        isSuper && companyFilter !== "all"
          ? `?company_id=${companyFilter}`
          : "";
      const r = await api<{ branches: Branch[] }>(`/company/branches${q}`);
      setBranches(r.branches || []);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyFilter, isSuper]);

  useEffect(() => {
    if (isSuper && companies.length === 0) {
      api<{ companies: any[] }>("/companies")
        .then((r) => setCompanies(r.companies || []))
        .catch(() => {});
    }
  }, [isSuper, companies.length]);

  useEffect(() => { load(); }, [load]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  // Sync face-match toggle whenever the target company changes.
  useEffect(() => {
    if (!targetCompanyId) {
      setFaceMatchEnabled(false);
      return;
    }
    if (isSuper) {
      const c = companies.find((x: any) => x.company_id === targetCompanyId);
      setFaceMatchEnabled(!!c?.face_match_enabled);
    } else {
      // company_admin — read from own user.company object
      setFaceMatchEnabled(!!(user as any)?.company?.face_match_enabled);
    }
  }, [targetCompanyId, companies, isSuper, user]);

  const toggleFaceMatch = async (next: boolean) => {
    if (!targetCompanyId) return;
    setFaceMatchBusy(true);
    // Optimistic
    setFaceMatchEnabled(next);
    try {
      await api(`/admin/companies/${targetCompanyId}/face-match`, {
        method: "PATCH",
        body: { enabled: next },
      });
      // Refresh the cached companies list for super_admin
      if (isSuper) {
        const r = await api<{ companies: any[] }>("/companies");
        setCompanies(r.companies || []);
      }
    } catch (e: any) {
      setFaceMatchEnabled(!next);
      showMsg(e?.message || "Could not update face-match setting.");
    } finally {
      setFaceMatchBusy(false);
    }
  };

  const del = async (b: Branch) => {
    const confirmed = Platform.OS === "web"
      ? window.confirm(`Delete branch "${b.name}"? This can't be undone.`)
      : await new Promise<boolean>((res) =>
          Alert.alert(
            "Delete branch",
            `Delete "${b.name}"? This can't be undone.`,
            [
              { text: "Cancel", onPress: () => res(false), style: "cancel" },
              { text: "Delete", style: "destructive", onPress: () => res(true) },
            ],
          ),
        );
    if (!confirmed) return;
    try {
      await api(`/company/branches/${b.branch_id}`, { method: "DELETE" });
      setBranches((prev) => prev.filter((x) => x.branch_id !== b.branch_id));
    } catch (e: any) {
      showMsg(e?.message || "Delete failed");
    }
  };

  if (!isAdmin) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()} hitSlop={8}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <Text style={styles.h1}>Branches</Text>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>
        <View style={styles.forb}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbT}>Admins only</Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Branches</Text>
          <Pressable
            onPress={() => { setEditing(null); setShowForm(true); }}
            hitSlop={8}
            testID="branch-add"
          >
            <Ionicons name="add-circle" size={26} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </SafeAreaView>

      {showForm ? (
        <BranchForm
          initial={editing || undefined}
          companies={companies}
          isSuper={isSuper}
          companyFilter={companyFilter}
          onCancel={() => setShowForm(false)}
          onSaved={() => { setShowForm(false); load(); }}
        />
      ) : (
        <KeyboardAwareScrollView bottomOffset={62}
          contentContainerStyle={styles.scroll}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => { setRefreshing(true); load(); }}
              tintColor={colors.brandPrimary}
            />
          }
        >
          <View style={styles.introCard}>
            <View style={styles.introIcon}>
              <Ionicons name="git-branch" size={20} color={colors.brandPrimary} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.introTitle}>Multi-branch geofencing</Text>
              <Text style={styles.introSub}>
                Employees can punch-in at ANY of your branches. Each branch
                has its own coordinates + geofence radius.
              </Text>
            </View>
          </View>

          {isSuper && (
            <View style={{ marginBottom: spacing.md }}>
              <CompanyPicker
                testID="branches-company-picker"
                value={companyFilter}
                onChange={setCompanyFilter}
                companies={companies}
                label=""
                compact={false}
              />
            </View>
          )}

          {/* Face-match toggle — per-company */}
          {targetCompanyId ? (
            <View style={styles.fmCard} testID="face-match-card">
              <View style={styles.fmHead}>
                <View style={styles.fmIcon}>
                  <Ionicons
                    name="scan-outline"
                    size={18}
                    color={colors.brandPrimary}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.fmTitle}>Face-match verification</Text>
                  <Text style={styles.fmSub}>
                    Verify each punch selfie against the employee&apos;s enrolled
                    profile photo. Mismatches are flagged for admin review —
                    the punch is never blocked.
                  </Text>
                </View>
                <Switch
                  testID="face-match-switch"
                  value={faceMatchEnabled}
                  onValueChange={toggleFaceMatch}
                  disabled={faceMatchBusy}
                  trackColor={{
                    true: colors.brandPrimary,
                    false: colors.border,
                  }}
                />
              </View>
              <Pressable
                style={styles.fmReview}
                onPress={() => router.push("/attendance-review")}
                testID="face-match-review"
              >
                <Ionicons
                  name="alert-circle-outline"
                  size={14}
                  color={colors.brandPrimary}
                />
                <Text style={styles.fmReviewTxt}>Review flagged punches</Text>
                <Ionicons
                  name="chevron-forward"
                  size={14}
                  color={colors.brandPrimary}
                />
              </Pressable>
            </View>
          ) : null}

          {loading ? (
            <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
          ) : branches.length === 0 ? (
            <View style={styles.empty} testID="branches-empty">
              <Ionicons name="location-outline" size={40} color={colors.onSurfaceTertiary} />
              <Text style={styles.emptyT}>No branches yet</Text>
              <Text style={styles.emptyS}>
                Tap ＋ to add your first branch. The main office is always
                counted as one implicit branch.
              </Text>
            </View>
          ) : (
            branches.map((b) => (
              <View key={b.branch_id} style={styles.card} testID={`branch-${b.branch_id}`}>
                <View style={styles.cardHead}>
                  <View style={styles.pin}>
                    <Ionicons name="business" size={16} color={colors.onCta} />
                  </View>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name}>{b.name}</Text>
                    {!!b.address && <Text style={styles.sub}>{b.address}</Text>}
                    <Text style={styles.metaTxt}>
                      {b.office_lat.toFixed(5)}, {b.office_lng.toFixed(5)}
                      {"  ·  "}
                      {b.geofence_radius_m}m radius
                    </Text>
                  </View>
                  <View style={styles.actions}>
                    <Pressable
                      onPress={() => { setEditing(b); setShowForm(true); }}
                      style={styles.editBtn}
                      testID={`branch-edit-${b.branch_id}`}
                    >
                      <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
                    </Pressable>
                    <Pressable
                      onPress={() => del(b)}
                      style={styles.delBtn}
                      testID={`branch-delete-${b.branch_id}`}
                    >
                      <Ionicons name="trash-outline" size={16} color="#B91C1C" />
                    </Pressable>
                  </View>
                </View>
              </View>
            ))
          )}
          <View style={{ height: 40 }} />
        </KeyboardAwareScrollView>
      )}
    </View>
  );
}

function BranchForm({
  initial, companies, isSuper, companyFilter, onCancel, onSaved,
}: {
  initial?: Branch;
  companies: any[];
  isSuper: boolean;
  companyFilter: string | "all";
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [address, setAddress] = useState(initial?.address || "");
  const [lat, setLat] = useState(initial ? String(initial.office_lat) : "");
  const [lng, setLng] = useState(initial ? String(initial.office_lng) : "");
  const [radius, setRadius] = useState(String(initial?.geofence_radius_m || 200));
  const [companyId, setCompanyId] = useState<string>(
    initial?.company_id ||
    (isSuper && companyFilter !== "all" ? companyFilter : ""),
  );
  const [busy, setBusy] = useState(false);

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Branch", msg);
  };

  const useCurrentLocation = async () => {
    try {
      const perm = await Location.requestForegroundPermissionsAsync();
      if (perm.status !== "granted") {
        showMsg("Location permission required.");
        return;
      }
      const l = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High,
      });
      setLat(String(l.coords.latitude));
      setLng(String(l.coords.longitude));
    } catch (e: any) {
      showMsg(e?.message || "Could not get location.");
    }
  };

  const save = async () => {
    if (!name.trim()) { showMsg("Branch name is required"); return; }
    const latN = parseFloat(lat);
    const lngN = parseFloat(lng);
    if (!Number.isFinite(latN) || !Number.isFinite(lngN)) {
      showMsg("Latitude and longitude must be numbers");
      return;
    }
    const radN = parseInt(radius, 10) || 200;
    setBusy(true);
    try {
      if (initial) {
        await api(`/company/branches/${initial.branch_id}`, {
          method: "PATCH",
          body: {
            name: name.trim(),
            address: address.trim() || null,
            office_lat: latN,
            office_lng: lngN,
            geofence_radius_m: radN,
          },
        });
      } else {
        const body: any = {
          name: name.trim(),
          address: address.trim() || null,
          office_lat: latN,
          office_lng: lngN,
          geofence_radius_m: radN,
        };
        if (isSuper && companyId) body.company_id = companyId;
        await api("/company/branches", { method: "POST", body });
      }
      onSaved();
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.formTitle}>
          {initial ? "Edit branch" : "Add branch"}
        </Text>

        {isSuper && !initial && (
          <View style={{ marginBottom: spacing.sm }}>
            <Text style={styles.label}>Company</Text>
            <View style={styles.chipsRow}>
              {companies.map((c) => (
                <Pressable
                  key={c.company_id}
                  onPress={() => setCompanyId(c.company_id)}
                  style={[styles.chip, companyId === c.company_id && styles.chipActive]}
                >
                  <Text
                    style={[
                      styles.chipTxt,
                      companyId === c.company_id && styles.chipTxtActive,
                    ]}
                  >
                    {c.name}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
        )}

        <Field
          label="Branch name *"
          value={name}
          onChangeText={setName}
          placeholder="Andheri office"
          testID="branch-name"
        />
        <Field
          label="Address"
          value={address}
          onChangeText={setAddress}
          placeholder="Optional street address"
        />
        <View style={{ flexDirection: "row", gap: 10 }}>
          <View style={{ flex: 1 }}>
            <Field
              label="Latitude *"
              value={lat}
              onChangeText={setLat}
              placeholder="19.0760"
              keyboardType="decimal-pad"
              testID="branch-lat"
            />
          </View>
          <View style={{ flex: 1 }}>
            <Field
              label="Longitude *"
              value={lng}
              onChangeText={setLng}
              placeholder="72.8777"
              keyboardType="decimal-pad"
              testID="branch-lng"
            />
          </View>
        </View>
        <Pressable
          onPress={useCurrentLocation}
          style={styles.gpsBtn}
          testID="branch-use-gps"
        >
          <Ionicons name="locate" size={16} color={colors.brandPrimary} />
          <Text style={styles.gpsTxt}>Use my current GPS location</Text>
        </Pressable>
        <Field
          label="Geofence radius (m)"
          value={radius}
          onChangeText={setRadius}
          keyboardType="number-pad"
          placeholder="200"
          testID="branch-radius"
        />

        <View style={{ flexDirection: "row", gap: 10, marginTop: spacing.md }}>
          <Pressable
            onPress={onCancel}
            style={[styles.saveBtn, { backgroundColor: colors.surfaceSecondary, flex: 1 }]}
          >
            <Text style={[styles.saveTxt, { color: colors.onSurfaceSecondary }]}>Cancel</Text>
          </Pressable>
          <Pressable
            onPress={save}
            disabled={busy}
            style={[styles.saveBtn, busy && { opacity: 0.7 }, { flex: 1 }]}
            testID="branch-save"
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={styles.saveTxt}>{initial ? "Save changes" : "Add branch"}</Text>
            )}
          </Pressable>
        </View>
        <View style={{ height: 40 }} />
      </KeyboardAwareScrollView>
    </KeyboardAvoidingView>
  );
}

function Field({
  label, value, onChangeText, placeholder, keyboardType, testID,
}: {
  label: string;
  value: string;
  onChangeText: (t: string) => void;
  placeholder?: string;
  keyboardType?: "default" | "decimal-pad" | "number-pad";
  testID?: string;
}) {
  return (
    <View style={{ marginBottom: spacing.sm }}>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        keyboardType={keyboardType || "default"}
        style={styles.input}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl },

  introCard: {
    flexDirection: "row", gap: 10,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md, padding: spacing.md,
    marginBottom: spacing.md,
  },
  introIcon: {
    width: 36, height: 36, borderRadius: 18,
    backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center",
  },
  introTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  introSub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 4, lineHeight: 17 },

  fmCard: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  fmHead: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
  },
  fmIcon: {
    width: 34,
    height: 34,
    borderRadius: 8,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  fmTitle: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "800",
  },
  fmSub: {
    color: colors.onSurfaceSecondary,
    fontSize: 12,
    marginTop: 4,
    lineHeight: 17,
  },
  fmReview: {
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  fmReviewTxt: {
    flex: 1,
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },

  empty: { alignItems: "center", gap: 8, paddingVertical: 40 },
  emptyT: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  emptyS: { color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center" },

  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    borderWidth: 1, borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  pin: {
    width: 34, height: 34, borderRadius: 17,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center",
  },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  sub: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },
  metaTxt: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 4 },
  actions: { flexDirection: "row", gap: 6 },
  editBtn: {
    padding: 8, borderRadius: 8,
    backgroundColor: colors.brandTertiary,
  },
  delBtn: {
    padding: 8, borderRadius: 8,
    backgroundColor: "#FDECEC",
  },

  forb: { flex: 1, alignItems: "center", justifyContent: "center", gap: 8 },
  forbT: { color: colors.onSurface, fontSize: type.lg, fontWeight: "600" },

  formTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700", marginBottom: spacing.md },
  label: { color: colors.onSurfaceSecondary, fontSize: 12, marginBottom: 4, fontWeight: "600" },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 12,
    color: colors.onSurface, fontSize: 14,
  },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    paddingVertical: 6, paddingHorizontal: 12,
    borderRadius: 999,
    borderWidth: 1, borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
  },
  chipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  chipTxt: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "600" },
  chipTxtActive: { color: "#fff" },

  gpsBtn: {
    flexDirection: "row", alignItems: "center", gap: 6,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    paddingVertical: 10, paddingHorizontal: 12,
    alignSelf: "flex-start",
    marginBottom: spacing.sm,
  },
  gpsTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "700" },

  saveBtn: {
    backgroundColor: colors.cta,
    borderRadius: radius.md,
    paddingVertical: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  saveTxt: { color: "#fff", fontSize: type.base, fontWeight: "700" },
});
