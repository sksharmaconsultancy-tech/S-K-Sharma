/**
 * Iter 736 — Branches inside Firm Master.
 * User request: "can we set into the existing Firm master who already
 * added in Firms?" — branch add/edit/delete + state assignment now lives
 * as a Firm Master section, scoped to the selected firm.
 * Uses the same APIs as the standalone /branches screen.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput,
  ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as Location from "expo-location";

import { api } from "@/src/api/client";
import { confirmYesNo } from "@/src/utils/confirm";
import { colors, radius, spacing, type } from "@/src/theme";

type Branch = {
  branch_id: string;
  company_id: string;
  name: string;
  address?: string | null;
  office_lat: number;
  office_lng: number;
  geofence_radius_m: number;
  active: boolean;
  state?: string | null;
};

export default function BranchesSection({ companyId }: { companyId: string }) {
  const router = useRouter();
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Branch | null>(null);
  const [stateNames, setStateNames] = useState<string[]>([]);
  const [stateOpen, setStateOpen] = useState<string | null>(null);

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
  };

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const r = await api<{ branches: Branch[] }>(`/company/branches?company_id=${companyId}`);
      setBranches(r.branches || []);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => { load(); setShowForm(false); setEditing(null); }, [load]);

  useEffect(() => {
    api<{ states: any[] }>("/admin/branch-extras/states")
      .then((r) => setStateNames((r.states || []).map((s) => s.state)))
      .catch(() => {});
  }, []);

  const setBranchState = async (b: Branch, s: string) => {
    try {
      await api("/admin/branch-extras/branch-state", {
        method: "POST", body: { branch_id: b.branch_id, state: s },
      });
      setBranches((prev) => prev.map((x) => x.branch_id === b.branch_id ? { ...x, state: s } : x));
      setStateOpen(null);
    } catch (e: any) { showMsg(e?.message || "State save failed"); }
  };

  const remove = async (b: Branch) => {
    const ok = await confirmYesNo(
      `Delete branch "${b.name}"? This can't be undone.`, "Delete branch");
    if (!ok) return;
    try {
      await api(`/company/branches/${b.branch_id}`, { method: "DELETE" });
      setBranches((prev) => prev.filter((x) => x.branch_id !== b.branch_id));
    } catch (e: any) { showMsg(e?.message || "Delete failed"); }
  };

  return (
    <View style={styles.card} testID="fm-branches-section">
      <View style={styles.headRow}>
        <View style={styles.headLeft}>
          <Ionicons name="git-branch-outline" size={16} color={colors.brandPrimary} />
          <Text style={styles.headTitle}>Branches / Locations</Text>
          <View style={styles.countPill}>
            <Text style={styles.countPillTxt}>{branches.length}</Text>
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: 8 }}>
          <Pressable
            onPress={() => router.push("/branches" as any)}
            style={styles.linkBtn}
            testID="fm-branches-open-full"
          >
            <Ionicons name="open-outline" size={13} color={colors.brandPrimary} />
            <Text style={styles.linkBtnTxt}>Full screen</Text>
          </Pressable>
          <Pressable
            onPress={() => { setEditing(null); setShowForm(true); }}
            style={styles.addBtn}
            testID="fm-branches-add"
          >
            <Ionicons name="add" size={15} color="#FFF" />
            <Text style={styles.addBtnTxt}>Add Branch</Text>
          </Pressable>
        </View>
      </View>

      <Text style={styles.hint}>
        Employees can punch-in at any branch of this firm (geofenced). Set
        each branch&apos;s State so PT / LWF / Minimum-Wage compliance applies
        correctly.
      </Text>

      {showForm ? (
        <BranchForm
          companyId={companyId}
          initial={editing}
          onCancel={() => { setShowForm(false); setEditing(null); }}
          onSaved={() => { setShowForm(false); setEditing(null); load(); }}
        />
      ) : null}

      {loading ? (
        <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 16 }} />
      ) : branches.length === 0 && !showForm ? (
        <View style={styles.empty} testID="fm-branches-empty">
          <Ionicons name="git-branch" size={22} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyT}>No branches yet for this firm</Text>
          <Text style={styles.emptyS}>
            Tap &quot;Add Branch&quot; to register the first location. The main office
            is always counted as one implicit branch.
          </Text>
        </View>
      ) : (
        branches.map((b) => (
          <View key={b.branch_id} style={styles.bCard} testID={`fm-branch-${b.branch_id}`}>
            <View style={{ flex: 1, minWidth: 200 }}>
              <Text style={styles.bName}>{b.name}</Text>
              {b.address ? <Text style={styles.bMeta}>{b.address}</Text> : null}
              <Text style={styles.bMeta}>
                {b.office_lat?.toFixed(5)}, {b.office_lng?.toFixed(5)} · radius {b.geofence_radius_m} m
              </Text>
              {/* State chip / picker */}
              {stateOpen === b.branch_id ? (
                <View style={styles.stateWrap}>
                  {stateNames.map((s) => (
                    <Pressable
                      key={s}
                      onPress={() => setBranchState(b, s)}
                      style={[styles.stateChip, b.state === s && styles.stateChipOn]}
                      testID={`fm-branch-state-${b.branch_id}-${s}`}
                    >
                      <Text style={[styles.stateChipTxt, b.state === s && { color: "#FFF" }]}>{s}</Text>
                    </Pressable>
                  ))}
                  <Pressable onPress={() => setStateOpen(null)} style={styles.stateChip}>
                    <Text style={styles.stateChipTxt}>✕ close</Text>
                  </Pressable>
                </View>
              ) : (
                <Pressable
                  onPress={() => setStateOpen(b.branch_id)}
                  style={[styles.statePill, !b.state && styles.statePillEmpty]}
                  testID={`fm-branch-state-open-${b.branch_id}`}
                >
                  <Ionicons name="map-outline" size={11}
                            color={b.state ? colors.brandPrimary : "#B45309"} />
                  <Text style={[styles.statePillTxt, !b.state && { color: "#B45309" }]}>
                    {b.state || "Set state (compliance)"}
                  </Text>
                </Pressable>
              )}
            </View>
            <View style={{ flexDirection: "row", gap: 6 }}>
              <Pressable
                onPress={() => { setEditing(b); setShowForm(true); }}
                style={styles.iconBtn}
                testID={`fm-branch-edit-${b.branch_id}`}
              >
                <Ionicons name="create-outline" size={16} color={colors.brandPrimary} />
              </Pressable>
              <Pressable
                onPress={() => remove(b)}
                style={styles.iconBtn}
                testID={`fm-branch-delete-${b.branch_id}`}
              >
                <Ionicons name="trash-outline" size={16} color={colors.error} />
              </Pressable>
            </View>
          </View>
        ))
      )}
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  Inline add / edit form                                            */
/* ------------------------------------------------------------------ */

function BranchForm({
  companyId, initial, onCancel, onSaved,
}: {
  companyId: string;
  initial: Branch | null;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [address, setAddress] = useState(initial?.address || "");
  const [lat, setLat] = useState(initial ? String(initial.office_lat) : "");
  const [lng, setLng] = useState(initial ? String(initial.office_lng) : "");
  const [radiusM, setRadiusM] = useState(initial ? String(initial.geofence_radius_m) : "200");
  const [busy, setBusy] = useState(false);

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
  };

  const useCurrentLocation = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") { showMsg("Location permission required."); return; }
      const l = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setLat(String(l.coords.latitude));
      setLng(String(l.coords.longitude));
    } catch (e: any) { showMsg(e?.message || "Could not get location."); }
  };

  const save = async () => {
    if (!name.trim()) { showMsg("Branch name is required"); return; }
    const latN = parseFloat(lat);
    const lngN = parseFloat(lng);
    if (!Number.isFinite(latN) || !Number.isFinite(lngN)) {
      showMsg("Latitude and longitude must be numbers");
      return;
    }
    const radN = parseInt(radiusM, 10) || 200;
    setBusy(true);
    try {
      const body = {
        name: name.trim(),
        address: address.trim() || null,
        office_lat: latN,
        office_lng: lngN,
        geofence_radius_m: radN,
      };
      if (initial) {
        await api(`/company/branches/${initial.branch_id}`, { method: "PATCH", body });
      } else {
        await api("/company/branches", {
          method: "POST", body: { ...body, company_id: companyId },
        });
      }
      onSaved();
    } catch (e: any) {
      showMsg(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.form} testID="fm-branch-form">
      <Text style={styles.formTitle}>{initial ? "Edit branch" : "Add branch"}</Text>
      <View style={styles.formRow}>
        <FF label="Branch name *" value={name} onChangeText={setName}
            placeholder="Andheri office" testID="fm-branch-name" />
        <FF label="Address" value={address} onChangeText={setAddress}
            placeholder="Optional street address" />
      </View>
      <View style={styles.formRow}>
        <FF label="Latitude *" value={lat} onChangeText={setLat}
            placeholder="19.0760" keyboardType="decimal-pad" testID="fm-branch-lat" />
        <FF label="Longitude *" value={lng} onChangeText={setLng}
            placeholder="72.8777" keyboardType="decimal-pad" testID="fm-branch-lng" />
        <FF label="Geofence radius (m)" value={radiusM} onChangeText={setRadiusM}
            placeholder="200" keyboardType="number-pad" testID="fm-branch-radius" />
      </View>
      <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
        <Pressable onPress={useCurrentLocation} style={styles.gpsBtn} testID="fm-branch-use-gps">
          <Ionicons name="locate" size={14} color={colors.brandPrimary} />
          <Text style={styles.gpsTxt}>Use my current GPS location</Text>
        </Pressable>
        <View style={{ flex: 1 }} />
        <Pressable onPress={onCancel} style={[styles.formBtn, styles.formBtnGhost]}>
          <Text style={[styles.formBtnTxt, { color: colors.onSurfaceSecondary }]}>Cancel</Text>
        </Pressable>
        <Pressable onPress={save} disabled={busy}
                   style={[styles.formBtn, busy && { opacity: 0.7 }]}
                   testID="fm-branch-save">
          {busy ? <ActivityIndicator color="#FFF" size="small" /> : (
            <Text style={styles.formBtnTxt}>{initial ? "Save changes" : "Add branch"}</Text>
          )}
        </Pressable>
      </View>
    </View>
  );
}

function FF({
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
    <View style={{ flex: 1, minWidth: 160, marginBottom: spacing.xs }}>
      <Text style={styles.fLabel}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        keyboardType={keyboardType || "default"}
        style={styles.fInput}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  headRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: 8,
  },
  headLeft: { flexDirection: "row", alignItems: "center", gap: 8 },
  headTitle: { ...type.h3, color: colors.onSurface },
  countPill: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 10,
    paddingHorizontal: 8,
    paddingVertical: 2,
  },
  countPillTxt: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary },
  hint: { fontSize: 12, color: colors.onSurfaceTertiary, marginTop: 6, marginBottom: spacing.sm },
  linkBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 7,
  },
  linkBtnTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  addBtn: {
    flexDirection: "row", alignItems: "center", gap: 4,
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  addBtnTxt: { fontSize: 12, fontWeight: "800", color: "#FFF" },
  empty: { alignItems: "center", paddingVertical: 24, gap: 6 },
  emptyT: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  emptyS: { fontSize: 12, color: colors.onSurfaceTertiary, textAlign: "center", maxWidth: 340 },
  bCard: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.sm,
    marginBottom: 8,
    backgroundColor: colors.surfaceSecondary,
  },
  bName: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  bMeta: { fontSize: 11.5, color: colors.onSurfaceTertiary, marginTop: 2 },
  iconBtn: {
    width: 32, height: 32, borderRadius: 8, alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  statePill: {
    flexDirection: "row", alignItems: "center", gap: 4, alignSelf: "flex-start",
    marginTop: 6, borderWidth: 1, borderColor: colors.brandPrimary,
    borderRadius: 12, paddingHorizontal: 8, paddingVertical: 3,
  },
  statePillEmpty: { borderColor: "#F59E0B", backgroundColor: "#FFFBEB" },
  statePillTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  stateWrap: { flexDirection: "row", flexWrap: "wrap", gap: 5, marginTop: 6 },
  stateChip: {
    borderWidth: 1, borderColor: colors.border, borderRadius: 12,
    paddingHorizontal: 8, paddingVertical: 3, backgroundColor: colors.surface,
  },
  stateChipOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  stateChipTxt: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  form: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: spacing.sm, backgroundColor: colors.surface,
  },
  formTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
  formRow: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  fLabel: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  fInput: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, fontSize: 13,
    color: colors.onSurface, backgroundColor: colors.surface,
  },
  gpsBtn: {
    flexDirection: "row", alignItems: "center", gap: 5,
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 7,
  },
  gpsTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  formBtn: {
    backgroundColor: colors.brandPrimary, borderRadius: radius.md,
    paddingHorizontal: 16, paddingVertical: 8, alignItems: "center", justifyContent: "center",
  },
  formBtnGhost: { backgroundColor: colors.surfaceSecondary },
  formBtnTxt: { fontSize: 12.5, fontWeight: "800", color: "#FFF" },
});
