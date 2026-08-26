/**
 * Iter 737 — BRANCH MASTER list (Firm Master → 18. Branches / Locations).
 * Complete enhancement of the Iter 736 section per the user's 25-section
 * Branch Master spec: search + filters, extended master fields, summary
 * counts row (Name | Code | State | Employees | Present | Absent | Status),
 * delete protection (deactivate instead) and the Branch Detail drill-down.
 *
 * Single source of truth = db.branches (same data as the standalone
 * /branches screen — changes reflect in both instantly).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as Location from "expo-location";

import { api } from "@/src/api/client";
import { confirmYesNo } from "@/src/utils/confirm";
import { colors, radius, spacing, type } from "@/src/theme";
import {
  BmField, BmBtn, BmChip, BmChipRow, StatusPill, bm, showWebMsg,
} from "@/src/components/firmMaster/branchMasterUi";
import BranchDetail from "@/src/components/firmMaster/BranchDetail";

export type Branch = {
  branch_id: string;
  company_id: string;
  name: string;
  code?: string | null;
  branch_type?: string | null;
  active?: boolean;
  state?: string | null;
  city?: string | null;
  address?: string | null;
  address1?: string | null;
  address2?: string | null;
  area?: string | null;
  district?: string | null;
  pin_code?: string | null;
  country?: string | null;
  manager_name?: string | null;
  contact_person?: string | null;
  mobile?: string | null;
  email?: string | null;
  office_lat?: number;
  office_lng?: number;
  geofence_enabled?: boolean;
  geofence_radius_m?: number;
  allow_punch_inside?: boolean;
  gps_accuracy_m?: number | null;
  emp_count?: number;
  active_employees?: number;
  present_today?: number;
  absent_today?: number;
  compliance_config?: any;
  payroll_config?: any;
  attendance_config?: any;
};

export default function BranchesSection({ companyId }: { companyId: string }) {
  const router = useRouter();
  const [branches, setBranches] = useState<Branch[]>([]);
  const [branchTypes, setBranchTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Branch | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  // filters
  const [search, setSearch] = useState("");
  const [fStatus, setFStatus] = useState<"" | "active" | "inactive">("");
  const [fState, setFState] = useState("");
  const [fType, setFType] = useState("");
  const [stateNames, setStateNames] = useState<string[]>([]);
  const [showFilters, setShowFilters] = useState(false);

  const load = useCallback(async () => {
    if (!companyId) return;
    setLoading(true);
    try {
      const qs = new URLSearchParams({ company_id: companyId });
      if (search.trim()) qs.set("search", search.trim());
      if (fStatus) qs.set("status", fStatus);
      if (fState) qs.set("state", fState);
      if (fType) qs.set("branch_type", fType);
      const r = await api<{ branches: Branch[]; branch_types: string[] }>(
        `/admin/branch-master/list?${qs.toString()}`);
      setBranches(r.branches || []);
      setBranchTypes(r.branch_types || []);
    } catch { /* ignore */ } finally {
      setLoading(false);
    }
  }, [companyId, search, fStatus, fState, fType]);

  useEffect(() => {
    setShowForm(false); setEditing(null); setDetailId(null);
  }, [companyId]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    api<{ states: any[] }>("/admin/branch-extras/states")
      .then((r) => setStateNames((r.states || []).map((s) => s.state)))
      .catch(() => {});
  }, []);

  const remove = async (b: Branch) => {
    const ok = await confirmYesNo(
      `Delete branch "${b.name}"? Branches with employees / attendance / transfers cannot be deleted — they will be protected.`,
      "Delete branch");
    if (!ok) return;
    try {
      await api(`/company/branches/${b.branch_id}`, { method: "DELETE" });
      setBranches((prev) => prev.filter((x) => x.branch_id !== b.branch_id));
    } catch (e: any) {
      if (e?.status === 409) {
        const deact = await confirmYesNo(
          `${e.message}\n\nDeactivate "${b.name}" instead?`, "Deactivate branch");
        if (deact) await toggleActive(b, false);
      } else {
        showWebMsg(e?.message || "Delete failed");
      }
    }
  };

  const toggleActive = async (b: Branch, active: boolean) => {
    try {
      await api(`/admin/branch-master/${b.branch_id}`, {
        method: "PATCH", body: { active },
      });
      setBranches((prev) => prev.map((x) =>
        x.branch_id === b.branch_id ? { ...x, active } : x));
    } catch (e: any) { showWebMsg(e?.message || "Update failed"); }
  };

  // ---- Branch Detail drill-down (tabs) --------------------------------
  if (detailId) {
    return (
      <BranchDetail
        branchId={detailId}
        companyId={companyId}
        branches={branches}
        onClose={() => { setDetailId(null); load(); }}
      />
    );
  }

  const hasFilter = !!(fStatus || fState || fType);

  return (
    <View style={styles.card} testID="fm-branches-section">
      {/* Header */}
      <View style={styles.headRow}>
        <View style={styles.headLeft}>
          <Ionicons name="git-branch-outline" size={16} color={colors.brandPrimary} />
          <Text style={styles.headTitle}>Branch Master</Text>
          <View style={styles.countPill}>
            <Text style={styles.countPillTxt}>{branches.length}</Text>
          </View>
        </View>
        <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
          <BmBtn label="Full screen" kind="ghost" icon="open-outline" small
                 onPress={() => router.push("/branches" as any)}
                 testID="fm-branches-open-full" />
          <BmBtn label={showFilters ? "Hide filters" : "Filters"} kind="ghost"
                 icon="funnel-outline" small
                 onPress={() => setShowFilters(!showFilters)}
                 testID="fm-branches-filters" />
          <BmBtn label="Add Branch" icon="add" small
                 onPress={() => { setEditing(null); setShowForm(true); }}
                 testID="fm-branches-add" />
        </View>
      </View>

      {/* Search + filters */}
      <View style={styles.searchRow}>
        <Ionicons name="search" size={14} color={colors.onSurfaceTertiary} />
        <TextInput
          value={search}
          onChangeText={setSearch}
          placeholder="Search branch name / code / city…"
          placeholderTextColor={colors.onSurfaceTertiary}
          style={styles.searchInput}
          testID="fm-branches-search"
        />
        {search ? (
          <Pressable onPress={() => setSearch("")}>
            <Ionicons name="close-circle" size={15} color={colors.onSurfaceTertiary} />
          </Pressable>
        ) : null}
      </View>
      {(showFilters || hasFilter) && (
        <View style={styles.filterBox}>
          <View style={bm.chipsWrap}>
            <Text style={styles.filterLbl}>Status:</Text>
            {(["", "active", "inactive"] as const).map((s) => (
              <BmChip key={s || "all"} label={s === "" ? "All" : s === "active" ? "Active" : "Inactive"}
                      on={fStatus === s} onPress={() => setFStatus(s)}
                      testID={`fm-filter-status-${s || "all"}`} />
            ))}
          </View>
          <View style={[bm.chipsWrap, { marginTop: 6 }]}>
            <Text style={styles.filterLbl}>Type:</Text>
            <BmChip label="All" on={fType === ""} onPress={() => setFType("")} />
            {branchTypes.map((t) => (
              <BmChip key={t} label={t} on={fType === t} onPress={() => setFType(fType === t ? "" : t)} />
            ))}
          </View>
          <View style={[bm.chipsWrap, { marginTop: 6 }]}>
            <Text style={styles.filterLbl}>State:</Text>
            <BmChip label="All" on={fState === ""} onPress={() => setFState("")} />
            {stateNames.map((s) => (
              <BmChip key={s} label={s} on={fState === s} onPress={() => setFState(fState === s ? "" : s)} />
            ))}
          </View>
        </View>
      )}

      {showForm ? (
        <BranchForm
          companyId={companyId}
          initial={editing}
          stateNames={stateNames}
          branchTypes={branchTypes.length ? branchTypes
            : ["Head Office", "Branch", "Factory", "Site", "Warehouse", "Remote Office", "Other"]}
          onCancel={() => { setShowForm(false); setEditing(null); }}
          onSaved={() => { setShowForm(false); setEditing(null); load(); }}
        />
      ) : null}

      {loading ? (
        <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 16 }} />
      ) : branches.length === 0 && !showForm ? (
        <View style={styles.empty} testID="fm-branches-empty">
          <Ionicons name="git-branch" size={22} color={colors.onSurfaceTertiary} />
          <Text style={styles.emptyT}>
            {search || hasFilter ? "No branches match the filters" : "No branches yet for this firm"}
          </Text>
        </View>
      ) : (
        <>
          {/* column header */}
          <View style={styles.listHead}>
            <Text style={[styles.listHeadTxt, { flex: 2.2 }]}>Branch</Text>
            <Text style={[styles.listHeadTxt, { flex: 1 }]}>State</Text>
            <Text style={[styles.listHeadTxt, styles.num]}>Emp</Text>
            <Text style={[styles.listHeadTxt, styles.num]}>Present</Text>
            <Text style={[styles.listHeadTxt, styles.num]}>Absent</Text>
            <Text style={[styles.listHeadTxt, { width: 66 }]}>Status</Text>
            <Text style={[styles.listHeadTxt, { width: 108, textAlign: "right" }]}>Actions</Text>
          </View>
          {branches.map((b) => (
            <Pressable
              key={b.branch_id}
              style={styles.bRow}
              onPress={() => setDetailId(b.branch_id)}
              testID={`fm-branch-${b.branch_id}`}
            >
              <View style={{ flex: 2.2 }}>
                <Text style={styles.bName}>{b.name}</Text>
                <Text style={styles.bMeta}>
                  {b.code || "—"}{b.branch_type ? ` · ${b.branch_type}` : ""}
                  {b.city ? ` · ${b.city}` : ""}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                {b.state ? (
                  <Text style={styles.bState}>{b.state}</Text>
                ) : (
                  <Text style={styles.bStateEmpty}>Set state</Text>
                )}
              </View>
              <Text style={[styles.bNum, styles.num]}>{b.emp_count ?? 0}</Text>
              <Text style={[styles.bNum, styles.num, { color: "#15803D" }]}>{b.present_today ?? 0}</Text>
              <Text style={[styles.bNum, styles.num, { color: "#B91C1C" }]}>{b.absent_today ?? 0}</Text>
              <View style={{ width: 66 }}>
                <StatusPill active={b.active !== false} />
              </View>
              <View style={{ width: 108, flexDirection: "row", gap: 5, justifyContent: "flex-end" }}>
                <Pressable onPress={() => setDetailId(b.branch_id)} style={styles.iconBtn}
                           testID={`fm-branch-view-${b.branch_id}`}>
                  <Ionicons name="eye-outline" size={15} color={colors.onSurfaceSecondary} />
                </Pressable>
                <Pressable onPress={() => { setEditing(b); setShowForm(true); }} style={styles.iconBtn}
                           testID={`fm-branch-edit-${b.branch_id}`}>
                  <Ionicons name="create-outline" size={15} color={colors.brandPrimary} />
                </Pressable>
                <Pressable onPress={() => remove(b)} style={styles.iconBtn}
                           testID={`fm-branch-delete-${b.branch_id}`}>
                  <Ionicons name="trash-outline" size={15} color={colors.error} />
                </Pressable>
              </View>
            </Pressable>
          ))}
          <Text style={styles.hint}>
            Row पर click करें → Branch Detail (Overview · Compliance · Payroll ·
            Attendance · Employees · Documents · History). Present/Absent counts
            आज के punches से (home-branch employees).
          </Text>
        </>
      )}
    </View>
  );
}

/* ------------------------------------------------------------------ */
/*  Add / Edit form — Basic + Address + GPS sections                  */
/* ------------------------------------------------------------------ */

function BranchForm({
  companyId, initial, stateNames, branchTypes, onCancel, onSaved,
}: {
  companyId: string;
  initial: Branch | null;
  stateNames: string[];
  branchTypes: string[];
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(initial?.name || "");
  const [code, setCode] = useState(initial?.code || "");
  const [branchType, setBranchType] = useState(initial?.branch_type || "Branch");
  const [manager, setManager] = useState(initial?.manager_name || "");
  const [contact, setContact] = useState(initial?.contact_person || "");
  const [mobile, setMobile] = useState(initial?.mobile || "");
  const [email, setEmail] = useState(initial?.email || "");
  // address
  const [addr1, setAddr1] = useState(initial?.address1 || initial?.address || "");
  const [addr2, setAddr2] = useState(initial?.address2 || "");
  const [area, setArea] = useState(initial?.area || "");
  const [city, setCity] = useState(initial?.city || "");
  const [district, setDistrict] = useState(initial?.district || "");
  const [stateName, setStateName] = useState(initial?.state || "");
  const [pin, setPin] = useState(initial?.pin_code || "");
  const [country, setCountry] = useState(initial?.country || "India");
  // gps
  const [lat, setLat] = useState(initial?.office_lat != null ? String(initial.office_lat) : "");
  const [lng, setLng] = useState(initial?.office_lng != null ? String(initial.office_lng) : "");
  const [radiusM, setRadiusM] = useState(String(initial?.geofence_radius_m ?? 200));
  const [geoEnabled, setGeoEnabled] = useState(initial?.geofence_enabled !== false);
  const [busy, setBusy] = useState(false);

  const useCurrentLocation = async () => {
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") { showWebMsg("Location permission required."); return; }
      const l = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setLat(String(l.coords.latitude));
      setLng(String(l.coords.longitude));
      showWebMsg(`Location captured ✓\nLat ${l.coords.latitude.toFixed(6)}, Lng ${l.coords.longitude.toFixed(6)}`);
    } catch (e: any) { showWebMsg(e?.message || "Could not get location."); }
  };

  const save = async () => {
    if (!name.trim()) { showWebMsg("Branch name is required"); return; }
    const latN = parseFloat(lat);
    const lngN = parseFloat(lng);
    if (!Number.isFinite(latN) || !Number.isFinite(lngN)) {
      showWebMsg("Latitude and longitude must be numbers (use the GPS button or Google Maps)");
      return;
    }
    if (pin.trim() && !/^\d{6}$/.test(pin.trim())) {
      showWebMsg("PIN Code must be exactly 6 digits");
      return;
    }
    setBusy(true);
    try {
      const body: any = {
        name: name.trim(),
        code: code.trim() || null,
        branch_type: branchType,
        manager_name: manager.trim() || null,
        contact_person: contact.trim() || null,
        mobile: mobile.trim() || null,
        email: email.trim() || null,
        address1: addr1.trim() || null,
        address2: addr2.trim() || null,
        area: area.trim() || null,
        city: city.trim() || null,
        district: district.trim() || null,
        state: stateName || null,
        pin_code: pin.trim() || null,
        country: country.trim() || null,
        office_lat: latN,
        office_lng: lngN,
        geofence_radius_m: parseInt(radiusM, 10) || 200,
        geofence_enabled: geoEnabled,
      };
      if (initial) {
        await api(`/admin/branch-master/${initial.branch_id}`, { method: "PATCH", body });
      } else {
        await api("/admin/branch-master/create", {
          method: "POST", body: { ...body, company_id: companyId },
        });
      }
      onSaved();
    } catch (e: any) {
      showWebMsg(e?.message || "Save failed");
    } finally { setBusy(false); }
  };

  return (
    <View style={styles.form} testID="fm-branch-form">
      <Text style={styles.formTitle}>{initial ? "Edit branch" : "Add branch"}</Text>

      <Text style={bm.secTitle}>Basic Information</Text>
      <View style={bm.row}>
        <BmField label="Branch name *" value={name} onChangeText={setName}
                 placeholder="Jodhpur Office" testID="fm-branch-name" />
        <BmField label="Branch / Location Code" value={code}
                 onChangeText={(t) => setCode(t.toUpperCase())}
                 placeholder="JDP001" testID="fm-branch-code" width={150} />
      </View>
      <BmChipRow label="Branch Type" options={branchTypes} value={branchType}
                 onChange={setBranchType} testID="fm-branch-type" />
      <View style={bm.row}>
        <BmField label="Branch Manager" value={manager} onChangeText={setManager}
                 placeholder="Manager name" />
        <BmField label="Contact Person" value={contact} onChangeText={setContact}
                 placeholder="Contact person" />
        <BmField label="Branch Mobile" value={mobile} onChangeText={setMobile}
                 placeholder="98xxxxxxxx" keyboardType="phone-pad" width={150} />
        <BmField label="Branch Email" value={email} onChangeText={setEmail}
                 placeholder="branch@firm.com" keyboardType="email-address" />
      </View>

      <Text style={bm.secTitle}>Address</Text>
      <View style={bm.row}>
        <BmField label="Address Line 1" value={addr1} onChangeText={setAddr1} />
        <BmField label="Address Line 2" value={addr2} onChangeText={setAddr2} />
      </View>
      <View style={bm.row}>
        <BmField label="Area / Locality" value={area} onChangeText={setArea} />
        <BmField label="City" value={city} onChangeText={setCity} testID="fm-branch-city" />
        <BmField label="District" value={district} onChangeText={setDistrict} />
        <BmField label="PIN Code" value={pin} onChangeText={setPin}
                 keyboardType="number-pad" width={110} testID="fm-branch-pin" />
        <BmField label="Country" value={country} onChangeText={setCountry} width={120} />
      </View>
      <BmChipRow label="State (PT / LWF / Min-Wage compliance)" options={stateNames}
                 value={stateName} onChange={setStateName} testID="fm-branch-state-chip" />

      <Text style={bm.secTitle}>GPS &amp; Geofence</Text>
      <View style={bm.row}>
        <BmField label="Latitude *" value={lat} onChangeText={setLat}
                 placeholder="26.2389" keyboardType="decimal-pad" testID="fm-branch-lat" width={150} />
        <BmField label="Longitude *" value={lng} onChangeText={setLng}
                 placeholder="73.0243" keyboardType="decimal-pad" testID="fm-branch-lng" width={150} />
        <BmField label="Geofence radius (m)" value={radiusM} onChangeText={setRadiusM}
                 keyboardType="number-pad" width={140} testID="fm-branch-radius" />
      </View>
      <View style={{ flexDirection: "row", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
        <BmBtn label="Use my current GPS location" kind="ghost" icon="locate" small
               onPress={useCurrentLocation} testID="fm-branch-use-gps" />
        <BmChip label={geoEnabled ? "Geofence: ON" : "Geofence: OFF"} on={geoEnabled}
                onPress={() => setGeoEnabled(!geoEnabled)} testID="fm-branch-geofence-toggle" />
        {Platform.OS === "web" && lat && lng ? (
          <Pressable onPress={() => window.open(`https://maps.google.com/?q=${lat},${lng}`, "_blank")}>
            <Text style={styles.mapLink}>📍 View on map</Text>
          </Pressable>
        ) : null}
      </View>

      <View style={{ flexDirection: "row", gap: 8, marginTop: spacing.sm, justifyContent: "flex-end" }}>
        <BmBtn label="Cancel" kind="ghost" onPress={onCancel} />
        <BmBtn label={initial ? "Save changes" : "Add branch"} onPress={save}
               busy={busy} testID="fm-branch-save" />
      </View>
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
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between", flexWrap: "wrap", gap: 8,
  },
  headLeft: { flexDirection: "row", alignItems: "center", gap: 8 },
  headTitle: { ...type.h3, color: colors.onSurface },
  countPill: {
    backgroundColor: colors.surfaceSecondary, borderRadius: 10,
    paddingHorizontal: 8, paddingVertical: 2,
  },
  countPillTxt: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 7, marginTop: spacing.sm,
    backgroundColor: colors.surfaceSecondary,
  },
  searchInput: { flex: 1, fontSize: 13, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" } as any : {}) },
  filterBox: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.sm, marginTop: 8, backgroundColor: colors.surfaceSecondary,
  },
  filterLbl: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary, marginRight: 4, alignSelf: "center" },
  empty: { alignItems: "center", paddingVertical: 24, gap: 6 },
  emptyT: { fontSize: 13, fontWeight: "700", color: colors.onSurfaceSecondary },
  listHead: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 10, paddingVertical: 6, marginTop: spacing.sm,
  },
  listHeadTxt: { fontSize: 10.5, fontWeight: "800", color: colors.onSurfaceTertiary, textTransform: "uppercase" },
  num: { width: 52, textAlign: "center" },
  bRow: {
    flexDirection: "row", alignItems: "center", gap: 6,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 9, marginBottom: 6,
    backgroundColor: colors.surfaceSecondary,
  },
  bName: { fontSize: 13, fontWeight: "800", color: colors.onSurface },
  bMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  bState: { fontSize: 11.5, fontWeight: "700", color: colors.brandPrimary },
  bStateEmpty: { fontSize: 11, fontWeight: "700", color: "#B45309" },
  bNum: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  iconBtn: {
    width: 28, height: 28, borderRadius: 7, alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  hint: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 6 },
  form: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    padding: spacing.sm, marginTop: spacing.sm, marginBottom: spacing.sm,
    backgroundColor: colors.surface,
  },
  formTitle: { fontSize: 13.5, fontWeight: "800", color: colors.onSurface },
  mapLink: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
});
