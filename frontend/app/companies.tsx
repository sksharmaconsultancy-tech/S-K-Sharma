import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator,
  Modal, TextInput, KeyboardAvoidingView, Platform, Alert, Share,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import {
  requestLocation,
  reverseGeocodeDetailed,
} from "@/src/utils/location";
import { colors, radius, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import BusinessCategoryPicker, {
  BusinessCategoryValue,
  buildLabel,
  fetchBusinessCategories,
} from "@/src/components/BusinessCategoryPicker";

type Company = {
  company_id: string;
  name: string;
  address?: string;
  office_lat: number;
  office_lng: number;
  geofence_radius_m: number;
  business_category?: string | null;
  business_subcategory?: string | null;
  enabled?: boolean;
  created_at: string;
  stats?: { employees: number; present_today: number; pending_leaves: number };
};

export default function CompaniesScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Company | null>(null);
  const [name, setName] = useState("");
  const [companyCode, setCompanyCode] = useState("");
  const [address, setAddress] = useState("");
  const [lat, setLat] = useState("");
  const [lng, setLng] = useState("");
  const [radiusM, setRadiusM] = useState("200");
  const [complianceEnabled, setComplianceEnabled] = useState(true);
  const [adminName, setAdminName] = useState("");
  const [adminPhone, setAdminPhone] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [createdCredentials, setCreatedCredentials] = useState<{
    company_name: string;
    identifier?: string | null;
    temp_pin?: string | null;
    temp_password?: string | null;
  } | null>(null);
  const [businessCat, setBusinessCat] = useState<BusinessCategoryValue>({
    category: null,
    subcategory: null,
    label: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [searching, setSearching] = useState(false);
  const [gpsBusy, setGpsBusy] = useState(false);
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [autoLookedUp, setAutoLookedUp] = useState(false);
  const [gpsFilled, setGpsFilled] = useState(false);
  const debounceRef = React.useRef<any>(null);
  const skipAutoRef = React.useRef(false);

  const useMyLocation = async () => {
    setError(null);
    setGpsBusy(true);
    try {
      const loc = await requestLocation();
      if (!loc) {
        setError("Location permission denied. Please enable it in Settings.");
        return;
      }
      // Skip debounced auto-lookup which would otherwise re-geocode from text.
      skipAutoRef.current = true;
      setLat(loc.latitude.toFixed(6));
      setLng(loc.longitude.toFixed(6));
      const info = await reverseGeocodeDetailed(loc.latitude, loc.longitude);
      if (info) {
        skipAutoRef.current = true;
        setAddress(info.display_name || info.address || address);
      }
      setGpsFilled(true);
      setAutoLookedUp(false);
      setSearchResults([]);
    } catch (e: any) {
      setError(e?.message || "Could not read your current location");
    } finally {
      setGpsBusy(false);
    }
  };

  const searchAddress = async (auto = false) => {
    setError(null);
    setSearchResults([]);
    const q = address.trim();
    if (!q) {
      if (!auto) setError("Enter an address first");
      return;
    }
    setSearching(true);
    try {
      const url =
        "https://nominatim.openstreetmap.org/search?format=json&limit=5&q=" +
        encodeURIComponent(q);
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(`Search failed (${res.status})`);
      const data = await res.json();
      if (!Array.isArray(data) || data.length === 0) {
        if (!auto) setError("No matching location found. Try a more specific address.");
        setAutoLookedUp(false);
        return;
      }
      setSearchResults(data);
      pickResult(data[0], true);
      setAutoLookedUp(auto);
    } catch (e: any) {
      if (!auto) setError(e.message || "Address search failed");
      setAutoLookedUp(false);
    } finally {
      setSearching(false);
    }
  };

  const pickResult = (r: any, silent = false) => {
    // Setting lat/lng here shouldn't retrigger auto-lookup
    skipAutoRef.current = true;
    setLat(String(parseFloat(r.lat).toFixed(6)));
    setLng(String(parseFloat(r.lon).toFixed(6)));
    if (!silent && r.display_name && !address.trim().includes(r.display_name.slice(0, 20))) {
      // preserve user's typed address
    }
  };

  // Debounced auto-lookup while the user types the address.
  React.useEffect(() => {
    if (skipAutoRef.current) {
      skipAutoRef.current = false;
      return;
    }
    if (!open) return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const q = address.trim();
    if (q.length < 6) {
      setAutoLookedUp(false);
      return;
    }
    debounceRef.current = setTimeout(() => {
      searchAddress(true).catch(() => {});
    }, 900);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [address, open]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ companies: Company[] }>("/companies");
      setCompanies(r.companies || []);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useOnRefresh(load);

  const openCreate = () => {
    setEditing(null);
    setName(""); setCompanyCode(""); setAddress(""); setLat(""); setLng(""); setRadiusM("200");
    setComplianceEnabled(true);
    setBusinessCat({ category: null, subcategory: null, label: "" });
    setAdminName(""); setAdminPhone(""); setAdminEmail("");
    setSearchResults([]);
    setGpsFilled(false);
    setAutoLookedUp(false);
    setError(null);
    setOpen(true);
  };

  const openEdit = async (c: Company) => {
    setEditing(c);
    setName(c.name);
    setCompanyCode((c as any).company_code || "");
    setAddress(c.address || "");
    setLat(String(c.office_lat));
    setLng(String(c.office_lng));
    setRadiusM(String(c.geofence_radius_m));
    setComplianceEnabled(c.compliance_enabled !== false);
    setSearchResults([]);
    setGpsFilled(false);
    setAutoLookedUp(false);
    setError(null);
    // Pre-populate business type dropdown from stored values
    if (c.business_category) {
      try {
        const cats = await fetchBusinessCategories();
        const match = cats.find((cat) => cat.key === c.business_category);
        setBusinessCat({
          category: c.business_category,
          subcategory: c.business_subcategory || null,
          label: buildLabel(match, c.business_subcategory || null),
        });
      } catch {
        setBusinessCat({
          category: c.business_category,
          subcategory: c.business_subcategory || null,
          label: c.business_subcategory
            ? `${c.business_category} — ${c.business_subcategory}`
            : String(c.business_category),
        });
      }
    } else {
      setBusinessCat({ category: null, subcategory: null, label: "" });
    }
    setOpen(true);
  };

  // User directive — LIVE validation: while ANY error is showing on the
  // form, Save is disabled. Only when every error is cleared does the
  // Create/Save button actually create the company.
  const liveErrors: string[] = [];
  if (open) {
    if (!name.trim()) liveErrors.push("Company name is required");
    if (!lat.trim() || !lng.trim() || !radiusM.trim()) {
      liveErrors.push("Location (latitude, longitude) and geofence radius are required");
    } else {
      const la = parseFloat(lat);
      const ln = parseFloat(lng);
      const rr = parseInt(radiusM, 10);
      if (Number.isNaN(la) || la < -90 || la > 90) liveErrors.push("Latitude must be a number between -90 and 90");
      if (Number.isNaN(ln) || ln < -180 || ln > 180) liveErrors.push("Longitude must be a number between -180 and 180");
      if (Number.isNaN(rr) || rr <= 0) liveErrors.push("Geofence radius must be a positive number (metres)");
    }
    const cc = companyCode.trim().toUpperCase();
    if (cc && !/^[A-Z0-9]{2,8}$/.test(cc)) liveErrors.push("Company Code must be 2–8 letters/digits (e.g. SKS, ACME)");
    if (!editing) {
      const em = adminEmail.trim();
      if (em && !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(em)) liveErrors.push("Employer/Admin email is not a valid email address");
      const ph = adminPhone.replace(/[^\d]/g, "");
      if (adminPhone.trim() && (ph.length < 10 || ph.length > 13)) liveErrors.push("Employer/Admin phone must have 10–13 digits");
    }
  }

  const submit = async () => {
    setError(null);
    if (liveErrors.length) {
      setError("Please clear the errors shown above before saving.");
      return;
    }
    if (!name || !lat || !lng || !radiusM) {
      setError("Fill all required fields");
      return;
    }
    const latN = parseFloat(lat);
    const lngN = parseFloat(lng);
    const rN = parseInt(radiusM, 10);
    if (Number.isNaN(latN) || Number.isNaN(lngN) || Number.isNaN(rN)) {
      setError("Latitude, Longitude and Radius must be numbers");
      return;
    }
    setSubmitting(true);
    try {
      const body: any = {
        name,
        address: address || null,
        office_lat: latN,
        office_lng: lngN,
        geofence_radius_m: rN,
        compliance_enabled: complianceEnabled,
        business_category: businessCat.category,
        business_subcategory: businessCat.subcategory,
      };
      const cc = companyCode.trim().toUpperCase();
      if (cc) {
        if (!/^[A-Z0-9]{2,8}$/.test(cc)) {
          setError("Company Code must be 2–8 letters/digits (e.g. SKS, ACME)");
          setSubmitting(false);
          return;
        }
        body.company_code = cc;
      }
      if (editing) {
        await api(`/companies/${editing.company_id}`, {
          method: "PATCH",
          body,
        });
      } else {
        // On CREATE, add optional admin credentials block. If provided,
        // backend provisions a company_admin with a temp PIN + temp password
        // (returned once in `admin`) so we can surface them to the super admin.
        if (adminPhone.trim() || adminEmail.trim()) {
          body.admin_phone = adminPhone.trim() || null;
          body.admin_email = adminEmail.trim() || null;
          body.admin_name = adminName.trim() || null;
        }
        const r = await api<any>("/companies", { method: "POST", body });
        // Reveal the one-time temp credentials so the super admin can share
        // them with the employer.
        if (r && r.admin && (r.admin.temp_pin || r.admin.temp_password)) {
          setCreatedCredentials({
            company_name: r.name || name,
            identifier: r.admin.email || r.admin.phone,
            temp_pin: r.admin.temp_pin || null,
            temp_password: r.admin.temp_password || null,
          });
        }
      }
      setOpen(false);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const doDelete = (c: Company) => {
    const proceed = async (force = false) => {
      try {
        const qs = force ? "?force=true" : "";
        const r = await api<any>(`/companies/${c.company_id}${qs}`, { method: "DELETE" });
        // User directive — sub-admin force delete needs Super Admin approval.
        if (r?.approval_required) {
          const m = r.message || "Deletion sent to the Super Admin for approval.";
          if (Platform.OS === "web") window.alert(m);
          else Alert.alert("Approval required", m);
          return;
        }
        await load();
      } catch (e: any) {
        // 409 means employees are linked — offer force cascade
        const msg = e?.message || "Delete failed";
        if (msg.includes("still linked") || msg.includes("employee(s)")) {
          const confirmMsg = `${msg}\n\nProceed with FORCE DELETE? This will permanently remove ALL employees, attendance, leaves, tickets and payslips for "${c.name}".`;
          if (Platform.OS === "web") {
            if (typeof window !== "undefined" && window.confirm(confirmMsg)) {
              proceed(true);
            }
          } else {
            Alert.alert(
              "Force delete company",
              confirmMsg,
              [
                { text: "Cancel", style: "cancel" },
                { text: "Force delete", style: "destructive", onPress: () => proceed(true) },
              ],
            );
          }
          return;
        }
        setError(msg);
      }
    };
    if (Platform.OS === "web") {
      if (typeof window !== "undefined" && window.confirm(`Delete "${c.name}"?`)) proceed(false);
    } else {
      Alert.alert("Delete company", `Delete "${c.name}"? This cannot be undone.`, [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: () => proceed(false) },
      ]);
    }
  };

  if (user?.role !== "super_admin" && user?.role !== "sub_admin") {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
          <View style={styles.header}>
            <Pressable onPress={() => router.back()}>
              <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
            </Pressable>
            <Text style={styles.h1}>Companies</Text>
            <View style={{ width: 26 }} />
          </View>
        </SafeAreaView>
        <View style={styles.forbidden}>
          <Ionicons name="lock-closed-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.forbTitle}>Super admin only</Text>
          <Text style={styles.forbBody}>
            Only super admins can manage the companies under this consultancy.
          </Text>
        </View>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Companies</Text>
          <View style={{ width: 26 }} />
        </View>
        <Text style={styles.sub}>
          All client companies managed under S.K. Sharma & Co.
        </Text>
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : companies.length === 0 ? (
          <View style={styles.empty}>
            <View style={styles.emptyIcon}>
              <Ionicons name="business-outline" size={30} color={colors.onBrandTertiary} />
            </View>
            <Text style={styles.emptyTitle}>No companies yet</Text>
            <Text style={styles.emptyBody}>
              Add your first client company to start managing their attendance,
              payroll and compliance under one panel.
            </Text>
          </View>
        ) : (
          companies.map((c) => (
            <Pressable
              key={c.company_id}
              style={styles.card}
              testID={`company-${c.company_id}`}
              onPress={() => router.push({ pathname: "/company-details", params: { company_id: c.company_id } })}
            >
              <View style={styles.cardHead}>
                <View style={styles.avatar}>
                  <Ionicons name="business" size={20} color={colors.onBrandTertiary} />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.cardName}>{c.name}</Text>
                  {c.address ? (
                    <Text style={styles.cardAddr} numberOfLines={1}>{c.address}</Text>
                  ) : null}
                </View>
                <Pressable
                  testID={`edit-company-${c.company_id}`}
                  onPress={(e) => { e.stopPropagation(); openEdit(c); }}
                  hitSlop={8}
                  style={{ marginRight: 12 }}
                >
                  <Ionicons name="create-outline" size={18} color={colors.brandPrimary} />
                </Pressable>
                {/* Iter 89 — Firm Master button. Opens the comprehensive
                    17-section firm profile editor pre-loaded with this
                    firm's company_id. Web only. */}
                {Platform.OS === "web" ? (
                  <Pressable
                    testID={`firm-master-${c.company_id}`}
                    onPress={(e) => {
                      e.stopPropagation();
                      router.push({
                        pathname: "/firm-master",
                        params: { company_id: c.company_id },
                      });
                    }}
                    hitSlop={8}
                    style={{ marginRight: 12 }}
                  >
                    <Ionicons name="clipboard-outline" size={18} color={colors.accent} />
                  </Pressable>
                ) : null}
                <Pressable
                  testID={`delete-company-${c.company_id}`}
                  onPress={(e) => { e.stopPropagation(); doDelete(c); }}
                  hitSlop={8}
                >
                  <Ionicons name="trash-outline" size={18} color={colors.error} />
                </Pressable>
              </View>

              {(c as any).enabled === false ? (
                <View style={styles.disabledPill} testID={`disabled-${c.company_id}`}>
                  <Ionicons name="pause-circle" size={11} color="#991B1B" />
                  <Text style={styles.disabledPillTxt}>DISABLED</Text>
                </View>
              ) : null}

              {c.business_category ? (
                <View style={styles.bizBadge} testID={`biz-${c.company_id}`}>
                  <Ionicons
                    name="briefcase-outline"
                    size={12}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.bizBadgeTxt} numberOfLines={1}>
                    {formatCategoryLabel(c.business_category, c.business_subcategory)}
                  </Text>
                </View>
              ) : null}

              <Pressable
                testID={`share-code-${c.company_id}`}
                style={styles.codeRow}
                onPress={(e) => {
                  e.stopPropagation();
                  const msg = `Join ${c.name} on S.K. Sharma & Co..\nYour company code: ${c.company_code}\n\n1. Install the app.\n2. Sign in with Google.\n3. Enter this code on the onboarding screen.`;
                  if (Platform.OS === "web") {
                    if (typeof navigator !== "undefined" && navigator.clipboard) {
                      navigator.clipboard.writeText(c.company_code);
                    }
                  } else {
                    Share.share({ message: msg });
                  }
                }}
              >
                <Ionicons name="key-outline" size={14} color={colors.onAccent} />
                <Text style={styles.codeLabel}>Employee code</Text>
                <Text style={styles.codeVal}>{c.company_code}</Text>
                <Ionicons name="share-outline" size={16} color={colors.onAccent} />
              </Pressable>
              {c.stats && (
                <View style={styles.statsRow}>
                  <Stat label="Employees" value={c.stats.employees} />
                  <Stat label="Present" value={c.stats.present_today} accent />
                  <Stat label="Pending" value={c.stats.pending_leaves} />
                </View>
              )}
              <View style={styles.geoRow}>
                <Ionicons name="location-outline" size={12} color={colors.onSurfaceTertiary} />
                <Text style={styles.geoTxt}>
                  {c.office_lat.toFixed(4)}, {c.office_lng.toFixed(4)} · {c.geofence_radius_m}m
                </Text>
              </View>
            </Pressable>
          ))
        )}
        <View style={{ height: 100 }} />
      </KeyboardAwareScrollView>

      <Pressable
        testID="add-company-fab"
        style={styles.fab}
        onPress={openCreate}
      >
        <Ionicons name="add" size={24} color="#fff" />
        <Text style={styles.fabTxt}>Add company</Text>
      </Pressable>

      <Modal
        transparent
        visible={open}
        animationType="slide"
        onRequestClose={() => setOpen(false)}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={styles.modalRoot}
        >
          <Pressable style={styles.backdrop} onPress={() => setOpen(false)} />
          <View style={styles.sheet}>
            <View style={styles.sheetGrip} />
            <Text style={styles.sheetTitle}>
              {editing ? "Edit company" : "Add new company"}
            </Text>

            <KeyboardAwareScrollView bottomOffset={62}
              style={styles.sheetScroll}
              contentContainerStyle={styles.sheetScrollInner}
              keyboardShouldPersistTaps="handled"
              showsVerticalScrollIndicator={false}
            >

            <Text style={styles.label}>Company name *</Text>
            <TextInput
              testID="company-name-input"
              value={name}
              onChangeText={setName}
              style={styles.input}
              placeholder="Acme Textiles Pvt Ltd"
              placeholderTextColor={colors.onSurfaceTertiary}
            />

            <Text style={styles.label}>Company Code (firm prefix)</Text>
            <TextInput
              testID="company-code-input"
              value={companyCode}
              onChangeText={(t) => setCompanyCode(t.toUpperCase())}
              style={styles.input}
              placeholder="SKS"
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="characters"
              autoCorrect={false}
              maxLength={8}
            />
            <Text style={styles.hint}>
              2–8 letters/digits. Used as the prefix for new employee codes,
              e.g. <Text style={styles.hintBold}>{(companyCode || "SKS").toUpperCase()}0001</Text>.
              Existing employee codes are not changed.
            </Text>

            <BusinessCategoryPicker
              label="Business type"
              value={businessCat}
              onChange={setBusinessCat}
              testID="company-biz-cat"
            />
            <Text style={styles.hint}>
              Helps segment client firms (Hospital, Hotel/Resort, Industry sub-type,
              IT, School, etc.). Optional but recommended.
            </Text>

            <Text style={styles.label}>Office location</Text>
            <Pressable
              testID="company-use-my-location"
              onPress={useMyLocation}
              disabled={gpsBusy}
              style={[styles.gpsBtnBig, gpsBusy && { opacity: 0.7 }]}
            >
              {gpsBusy ? (
                <ActivityIndicator size="small" color="#fff" />
              ) : (
                <>
                  <Ionicons name="locate" size={18} color="#fff" />
                  <Text style={styles.gpsBtnBigTxt}>Use my current location</Text>
                </>
              )}
            </Pressable>
            <Text style={styles.gpsHelperTxt}>
              Auto-fills address, latitude and longitude from your device GPS.
            </Text>

            <Text style={styles.label}>Address</Text>
            <View style={styles.addrRow}>
              <TextInput
                testID="company-address-input"
                value={address}
                onChangeText={setAddress}
                style={[styles.input, styles.addrInput]}
                placeholder="Sector 5, Noida, UP"
                placeholderTextColor={colors.onSurfaceTertiary}
                onSubmitEditing={() => searchAddress(false)}
                returnKeyType="search"
              />
              <Pressable
                testID="search-address-btn"
                style={styles.searchBtn}
                onPress={() => searchAddress(false)}
                disabled={searching}
              >
                {searching ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <Ionicons name="search" size={16} color="#fff" />
                )}
              </Pressable>
            </View>

            {gpsFilled && lat && lng ? (
              <View style={styles.autoBadge} testID="gps-latlng-badge">
                <Ionicons name="location" size={12} color="#0F5B22" />
                <Text style={styles.autoBadgeTxt}>
                  GPS captured — lat {lat}, lng {lng}
                </Text>
              </View>
            ) : autoLookedUp && lat && lng ? (
              <View style={styles.autoBadge} testID="auto-latlng-badge">
                <Ionicons name="location" size={12} color="#0F5B22" />
                <Text style={styles.autoBadgeTxt}>
                  Location auto-detected — lat {lat}, lng {lng}
                </Text>
              </View>
            ) : (
              <Text style={styles.searchHint}>
                {searching
                  ? "Detecting location…"
                  : "We&apos;ll auto-fill lat/lng as you finish typing the address. You can also tap the search icon."}
              </Text>
            )}

            {searchResults.length > 1 && (
              <View style={styles.resultsBox} testID="search-results">
                <Text style={styles.resultsLabel}>Choose the correct match</Text>
                {searchResults.map((r, i) => {
                  const isSelected =
                    lat === String(parseFloat(r.lat).toFixed(6)) &&
                    lng === String(parseFloat(r.lon).toFixed(6));
                  return (
                    <Pressable
                      key={`${r.place_id}-${i}`}
                      onPress={() => pickResult(r, false)}
                      style={[
                        styles.resultItem,
                        isSelected && styles.resultItemActive,
                      ]}
                      testID={`search-result-${i}`}
                    >
                      <Ionicons
                        name={isSelected ? "checkmark-circle" : "location-outline"}
                        size={16}
                        color={isSelected ? colors.accent : colors.onSurfaceTertiary}
                      />
                      <Text
                        style={[
                          styles.resultTxt,
                          isSelected && { color: colors.onSurface, fontWeight: "600" },
                        ]}
                        numberOfLines={2}
                      >
                        {r.display_name}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            )}

            <View style={styles.rowSplit}>
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Office latitude *</Text>
                <TextInput
                  testID="company-lat-input"
                  value={lat}
                  onChangeText={setLat}
                  style={styles.input}
                  placeholder="28.5355"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="numeric"
                />
              </View>
              <View style={{ width: 12 }} />
              <View style={{ flex: 1 }}>
                <Text style={styles.label}>Longitude *</Text>
                <TextInput
                  testID="company-lng-input"
                  value={lng}
                  onChangeText={setLng}
                  style={styles.input}
                  placeholder="77.3910"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="numeric"
                />
              </View>
            </View>

            <Text style={styles.label}>Geofence radius (metres) *</Text>
            <TextInput
              testID="company-radius-input"
              value={radiusM}
              onChangeText={setRadiusM}
              style={styles.input}
              placeholder="200"
              placeholderTextColor={colors.onSurfaceTertiary}
              keyboardType="numeric"
            />

            <Text style={styles.hint}>
              Employees can punch in only if they are within this radius from the office coordinates. Tip: fill the address and tap the search icon — coordinates are fetched automatically.
            </Text>

            <Pressable
              testID="toggle-compliance"
              style={styles.toggleRow}
              onPress={() => setComplianceEnabled((v) => !v)}
            >
              <View style={{ flex: 1 }}>
                <Text style={styles.toggleLabel}>Show compliance documents</Text>
                <Text style={styles.toggleHint}>
                  When ON, this company&apos;s employees see labour-law docs
                  (PF, ESI, Gratuity, etc.). Turn OFF if the client wants to
                  handle compliance externally.
                </Text>
              </View>
              <View
                style={[
                  styles.toggle,
                  complianceEnabled && styles.toggleOn,
                ]}
              >
                <View
                  style={[
                    styles.toggleKnob,
                    complianceEnabled && styles.toggleKnobOn,
                  ]}
                />
              </View>
            </Pressable>

            {!editing ? (
              <View style={styles.adminBlock}>
                <Text style={styles.adminBlockTitle}>Company admin login (optional)</Text>
                <Text style={styles.adminBlockHint}>
                  Fill this to auto-generate a temporary 6-digit PIN (for the mobile app)
                  and a temporary password (for the web portal). Both will be shown once
                  after saving and remain visible on the Company Details screen until the
                  admin changes them.
                </Text>
                <Text style={styles.label}>Admin name</Text>
                <TextInput
                  testID="cc-admin-name"
                  value={adminName}
                  onChangeText={setAdminName}
                  placeholder="e.g. Ankit Sharma"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={styles.input}
                />
                <Text style={styles.label}>Registered mobile</Text>
                <TextInput
                  testID="cc-admin-phone"
                  value={adminPhone}
                  onChangeText={setAdminPhone}
                  placeholder="+91 98765 43210"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="phone-pad"
                  style={styles.input}
                />
                <Text style={styles.label}>Admin email (needed for web password login)</Text>
                <TextInput
                  testID="cc-admin-email"
                  value={adminEmail}
                  onChangeText={setAdminEmail}
                  placeholder="admin@company.com"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  style={styles.input}
                />
              </View>
            ) : null}

            {liveErrors.length > 0 ? (
              <View
                style={{
                  backgroundColor: "#FEF2F2", borderWidth: 1, borderColor: "#FECACA",
                  borderRadius: 8, padding: 10, gap: 3, marginBottom: 4,
                }}
                testID="cc-live-errors"
              >
                <Text style={{ color: "#B91C1C", fontWeight: "800", fontSize: 12 }}>
                  ⚠ Please fix before saving — the company will NOT be created while these errors show:
                </Text>
                {liveErrors.map((er, i) => (
                  <Text key={i} style={{ color: "#B91C1C", fontSize: 12 }} testID={`cc-live-err-${i}`}>
                    • {er}
                  </Text>
                ))}
              </View>
            ) : null}
            {error && <Text style={styles.errTxt}>{error}</Text>}

            <Pressable
              testID="submit-company"
              style={[styles.submit, liveErrors.length > 0 && { opacity: 0.45 }]}
              onPress={submit}
              disabled={submitting || liveErrors.length > 0}
            >
              {submitting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.submitTxt}>
                  {editing ? "Save changes" : "Create company"}
                </Text>
              )}
            </Pressable>
            </KeyboardAwareScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: boolean }) {
  return (
    <View style={styles.stat}>
      <Text style={[styles.statVal, accent && { color: colors.accent }]}>{value}</Text>
      <Text style={styles.statLabel}>{label}</Text>
    </View>
  );
}

// Human-readable label for the business category badge on company cards.
// Kept in sync with the picker's build logic — capitalises the key when the
// exact taxonomy entry cannot be found on the client cache.
function formatCategoryLabel(
  cat?: string | null,
  sub?: string | null,
): string {
  if (!cat) return "";
  const nice = String(cat)
    .split("_")
    .map((p) => (p.length ? p[0].toUpperCase() + p.slice(1) : p))
    .join(" ")
    .replace("It Company", "IT Company")
    .replace("Hotel Resort", "Hotel / Resort");
  return sub ? `${nice} — ${sub}` : nice;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500" },
  sub: {
    fontSize: type.sm, color: colors.onSurfaceTertiary,
    paddingHorizontal: spacing.xl, paddingBottom: spacing.md,
  },
  scroll: { padding: spacing.xl },
  card: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md,
    padding: spacing.lg, borderWidth: 1, borderColor: colors.border,
    marginBottom: spacing.md,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: spacing.md },
  avatar: {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  cardName: { color: colors.onSurface, fontSize: type.lg, fontWeight: "500" },
  cardAddr: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  bizBadge: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: spacing.sm,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: radius.pill,
    backgroundColor: colors.brandTertiary,
    borderWidth: 1,
    borderColor: colors.border,
    maxWidth: "100%",
  },
  bizBadgeTxt: {
    color: colors.brandPrimary,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
  disabledPill: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: spacing.sm,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FCA5A5",
  },
  disabledPillTxt: {
    color: "#991B1B",
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.4,
  },
  codeRow: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.accent,
    paddingHorizontal: spacing.md,
    paddingVertical: 10,
    borderRadius: radius.md,
  },
  codeLabel: { color: colors.onAccent, fontSize: type.sm, fontWeight: "500" },
  codeVal: {
    flex: 1, color: colors.onAccent, fontSize: type.lg, fontWeight: "600",
    letterSpacing: 3, textAlign: "right", marginRight: 4,
  },
  statsRow: {
    flexDirection: "row", gap: spacing.md,
    marginTop: spacing.md, paddingTop: spacing.md,
    borderTopWidth: 1, borderTopColor: colors.divider,
  },
  stat: { flex: 1, alignItems: "flex-start" },
  statVal: { color: colors.onSurface, fontSize: type.xl, fontWeight: "500" },
  statLabel: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2 },
  geoRow: {
    flexDirection: "row", alignItems: "center", gap: 4,
    marginTop: spacing.md,
  },
  geoTxt: { color: colors.onSurfaceTertiary, fontSize: 11 },
  empty: { alignItems: "center", paddingVertical: 80, gap: 14 },
  emptyIcon: {
    width: 64, height: 64, borderRadius: 32,
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  emptyTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "500" },
  emptyBody: {
    color: colors.onSurfaceTertiary, fontSize: type.base, textAlign: "center",
    paddingHorizontal: spacing.xl, lineHeight: 20,
  },
  fab: {
    position: "absolute", bottom: 24, right: 24,
    backgroundColor: colors.brandPrimary, borderRadius: radius.pill,
    paddingHorizontal: 18, paddingVertical: 14,
    flexDirection: "row", alignItems: "center", gap: 6,
    elevation: 4,
    shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 10, shadowOffset: { width: 0, height: 4 },
  },
  fabTxt: { color: "#fff", fontSize: type.base, fontWeight: "500" },
  modalRoot: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: {
    backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24,
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.xl,
    paddingBottom: spacing.md,
    maxHeight: "88%",
    minHeight: "50%",
  },
  sheetScroll: { flexGrow: 0, flexShrink: 1 },
  sheetScrollInner: { paddingBottom: spacing.xl },
  sheetGrip: {
    alignSelf: "center", width: 40, height: 4,
    borderRadius: 2, backgroundColor: colors.borderStrong, marginBottom: spacing.md,
  },
  sheetTitle: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500", marginBottom: spacing.md },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.sm },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: type.base,
    marginTop: 6, backgroundColor: colors.surfaceSecondary,
  },
  rowSplit: { flexDirection: "row" },
  hint: {
    color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: spacing.md, lineHeight: 18,
  },
  hintBold: { color: colors.onSurface, fontWeight: "700" },
  addrRow: { flexDirection: "row", alignItems: "flex-end", gap: 8 },
  addrInput: { flex: 1 },
  searchBtn: {
    width: 46, height: 46, borderRadius: radius.md,
    backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center", marginTop: 6,
  },
  searchHint: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 4 },
  gpsBtn: {
    marginTop: 8,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    alignSelf: "flex-start",
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 6,
  },
  gpsBtnTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "700" },
  gpsBtnBig: {
    marginTop: 6,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    paddingHorizontal: 16,
  },
  gpsBtnBigTxt: { color: "#fff", fontSize: 14, fontWeight: "700" },
  gpsHelperTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 6,
    marginBottom: 6,
  },
  autoBadge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#E7F5EA",
    borderWidth: 1,
    borderColor: "#B7E0C0",
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 6,
    marginTop: 6,
    alignSelf: "flex-start",
  },
  autoBadgeTxt: { color: "#0F5B22", fontSize: 11, fontWeight: "600" },
  resultsBox: {
    marginTop: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceSecondary,
    padding: 8,
  },
  resultsLabel: {
    color: colors.onSurfaceTertiary, fontSize: type.sm,
    paddingHorizontal: 4, paddingVertical: 4, letterSpacing: 0.5,
  },
  resultItem: {
    flexDirection: "row", alignItems: "flex-start", gap: 8,
    paddingVertical: 8, paddingHorizontal: 8, borderRadius: radius.sm,
  },
  resultItemActive: { backgroundColor: colors.ctaTint },
  resultTxt: { flex: 1, color: colors.onSurfaceSecondary, fontSize: type.sm, lineHeight: 18 },
  toggleRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    marginTop: spacing.md,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    backgroundColor: colors.surfaceTertiary,
  },
  toggleLabel: { color: colors.onSurface, fontSize: type.base, fontWeight: "600" },
  toggleHint: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 2, lineHeight: 16 },
  toggle: {
    width: 48, height: 28, borderRadius: 14,
    backgroundColor: colors.borderStrong,
    justifyContent: "center",
    padding: 2,
  },
  toggleOn: { backgroundColor: colors.accent },
  toggleKnob: {
    width: 24, height: 24, borderRadius: 12,
    backgroundColor: "#fff",
  },
  toggleKnobOn: { alignSelf: "flex-end" },
  errTxt: { color: colors.error, fontSize: type.sm, marginTop: spacing.sm },
  submit: {
    marginTop: spacing.lg, backgroundColor: colors.cta,
    paddingVertical: 14, borderRadius: radius.pill, alignItems: "center",
  },
  submitTxt: { color: "#fff", fontSize: type.lg, fontWeight: "500" },
  forbidden: { alignItems: "center", paddingVertical: 80, gap: 12 },
  forbTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "500" },
  forbBody: {
    color: colors.onSurfaceTertiary, fontSize: type.base, textAlign: "center",
    paddingHorizontal: spacing.xl,
  },
});
