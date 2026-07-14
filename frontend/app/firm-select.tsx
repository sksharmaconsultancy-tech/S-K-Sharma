/**
 * Firm Selection Landing — Iter 67.
 *
 * SUB-ADMIN ONLY gate.  Super Admins and Company Admins never see this
 * screen (they are redirected to /(tabs) immediately by app/index.tsx).
 *
 * When a Sub-Admin logs in without a persisted firm selection they land
 * here and MUST pick a firm before entering the dashboard.  The pick is
 * saved to localStorage and cleared on logout, so returning users skip
 * this gate for the rest of their session.  Sub-Admins can switch firms
 * any time via the GlobalCompanyPicker in the top-right of every screen,
 * or by pressing the “Switch firm” link in the sidebar footer.
 */
import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  TextInput,
  Platform,
  useWindowDimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { radius, spacing } from "@/src/theme";

export default function FirmSelectScreen() {
  const router = useRouter();
  const { user, loading, logout } = useAuth();
  const { companies, companiesLoading, setSelectedCompanyId, selectedCompanyId } =
    useSelectedCompany();
  const [query, setQuery] = useState("");
  const { width } = useWindowDimensions();

  const isSubAdmin = (user?.role as string) === "sub_admin";

  // Iter 126 — "Remember last firm": when the server-side restore kicks in
  // (SelectedCompanyContext fetches /me/last-company after login) while the
  // sub admin is parked on this gate, jump straight to the dashboard.
  // Only when the screen was ENTERED without a selection (fresh login) and
  // the user hasn't manually picked — deliberate "Switch firm" visits
  // (selection already set on mount) are left alone.
  const initialCidRef = useRef(selectedCompanyId);
  const manualPickRef = useRef(false);
  useEffect(() => {
    if (!isSubAdmin) return;
    if (manualPickRef.current) return;
    if (initialCidRef.current) return;
    if (selectedCompanyId) router.replace("/");
  }, [selectedCompanyId, isSubAdmin, router]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return companies;
    return companies.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.company_code || "").toLowerCase().includes(q),
    );
  }, [companies, query]);

  if (loading) {
    return (
      <View style={styles.centerRoot}>
        <ActivityIndicator size="large" color="#0EA5E9" />
      </View>
    );
  }
  if (!user) return <Redirect href="/" />;
  // Only Sub-Admins are gated by this screen.  Every other role goes
  // straight to their dashboard so nothing about their existing flow
  // changes.
  if (!isSubAdmin) return <Redirect href="/(tabs)" />;

  const handleSelect = (cid: string) => {
    manualPickRef.current = true;
    setSelectedCompanyId(cid);
    router.replace("/");
  };

  const isNarrow = width < 720;
  const cols = width >= 1200 ? 3 : width >= 720 ? 2 : 1;

  return (
    <View style={styles.root} testID="firm-select-screen">
      <View style={styles.blob1} />
      <View style={styles.blob2} />

      <ScrollView
        contentContainerStyle={[
          styles.scroll,
          isNarrow && { paddingHorizontal: spacing.md, paddingVertical: spacing.lg },
        ]}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.header}>
          <View style={styles.logoBadge}>
            <Text style={styles.logoTxt}>SKS</Text>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.brandTitle}>S.K. Sharma & Co.</Text>
            <Text style={styles.brandSub}>
              Signed in as <Text style={styles.brandSubBold}>{user.name || user.email}</Text>
              {" · Sub-Admin"}
            </Text>
          </View>
          <Pressable
            onPress={logout}
            style={({ pressed }) => [styles.signOutBtn, pressed && { opacity: 0.85 }]}
            testID="firm-select-signout"
          >
            <Ionicons name="log-out-outline" size={16} color="#DC2626" />
            <Text style={styles.signOutTxt}>Sign out</Text>
          </Pressable>
        </View>

        <View style={styles.hero}>
          <View style={styles.heroBadge}>
            <Ionicons name="business" size={12} color="#0369A1" />
            <Text style={styles.heroBadgeTxt}>Firm workspace</Text>
          </View>
          <Text style={styles.heroTitle}>Choose a firm to continue</Text>
          <Text style={styles.heroSub}>
            The entire portal — attendance, payroll, compliance, reports —
            will filter to the firm you pick.  You can switch firms any time
            from the picker at the top of every page.
          </Text>
        </View>

        <View style={styles.searchBar}>
          <Ionicons name="search-outline" size={16} color="#64748B" />
          <TextInput
            testID="firm-select-search"
            value={query}
            onChangeText={setQuery}
            placeholder="Search firms by name or code…"
            placeholderTextColor="#94A3B8"
            style={styles.searchInput}
          />
          {query.length > 0 && (
            <Pressable onPress={() => setQuery("")} hitSlop={8}>
              <Ionicons name="close-circle" size={18} color="#94A3B8" />
            </Pressable>
          )}
        </View>

        {companiesLoading ? (
          <View style={styles.stateBox}>
            <ActivityIndicator color="#0EA5E9" />
            <Text style={styles.stateTxt}>Loading your firms…</Text>
          </View>
        ) : companies.length === 0 ? (
          <View style={styles.stateBox}>
            <Ionicons name="alert-circle-outline" size={40} color="#DC2626" />
            <Text style={[styles.stateTxt, { color: "#DC2626", fontWeight: "700" }]}>
              No firms linked to your account
            </Text>
            <Text style={styles.stateHint}>
              Please contact the Super Admin to be linked to a firm before
              you can use the portal.
            </Text>
          </View>
        ) : filtered.length === 0 ? (
          <View style={styles.stateBox}>
            <Ionicons name="search" size={36} color="#94A3B8" />
            <Text style={styles.stateTxt}>No firms match your search.</Text>
          </View>
        ) : (
          <View style={styles.grid}>
            {filtered.map((c) => {
              const active = selectedCompanyId === c.company_id;
              const cardW = isNarrow ? "100%" : `${100 / cols - 1.5}%`;
              return (
                <Pressable
                  key={c.company_id}
                  onPress={() => handleSelect(c.company_id)}
                  style={({ pressed }) => [
                    styles.card,
                    { width: cardW as any },
                    active && styles.cardActive,
                    pressed && { transform: [{ scale: 0.985 }], opacity: 0.96 },
                  ]}
                  testID={`firm-card-${c.company_id}`}
                >
                  <View style={styles.cardTopRow}>
                    <View style={styles.cardBadge}>
                      <Text style={styles.cardBadgeTxt}>
                        {(c.name || "?").trim().charAt(0).toUpperCase()}
                      </Text>
                    </View>
                    <View style={styles.cardStatus}>
                      <View style={styles.cardStatusDot} />
                      <Text style={styles.cardStatusTxt}>Active</Text>
                    </View>
                  </View>
                  <Text style={styles.cardTitle} numberOfLines={2}>
                    {c.name}
                  </Text>
                  {c.company_code ? (
                    <Text style={styles.cardCode}>Code · {c.company_code}</Text>
                  ) : null}
                  <View style={styles.cardCta}>
                    <Text style={styles.cardCtaTxt}>Open workspace</Text>
                    <Ionicons name="arrow-forward" size={16} color="#0EA5E9" />
                  </View>
                </Pressable>
              );
            })}
          </View>
        )}

        <View style={styles.footer}>
          <Ionicons name="information-circle-outline" size={14} color="#64748B" />
          <Text style={styles.footerTxt}>
            Master data (Groups, Departments, Designations) stays global and
            is available across every firm.
          </Text>
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: "#F0F9FF",
    minHeight: Platform.OS === "web" ? ("100vh" as unknown as number) : "100%",
    overflow: "hidden",
  },
  centerRoot: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#F0F9FF",
  },
  blob1: {
    position: "absolute",
    top: -160,
    right: -140,
    width: 480,
    height: 480,
    borderRadius: 240,
    backgroundColor: "#BAE6FD",
    opacity: 0.55,
  },
  blob2: {
    position: "absolute",
    bottom: -180,
    left: -160,
    width: 520,
    height: 520,
    borderRadius: 260,
    backgroundColor: "#DBEAFE",
    opacity: 0.6,
  },
  scroll: {
    padding: spacing.xl,
    maxWidth: 1240,
    width: "100%",
    alignSelf: "center",
    paddingBottom: spacing.xxl,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    marginBottom: spacing.xl,
  },
  logoBadge: {
    width: 52,
    height: 52,
    borderRadius: 14,
    backgroundColor: "#0EA5E9",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#0EA5E9",
    shadowOpacity: 0.28,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 6 },
  },
  logoTxt: { color: "#ffffff", fontWeight: "800", fontSize: 14, letterSpacing: 1.2 },
  brandTitle: { color: "#0F172A", fontSize: 22, fontWeight: "800", letterSpacing: -0.4 },
  brandSub: { color: "#475569", fontSize: 12, marginTop: 2, fontWeight: "500" },
  brandSubBold: { color: "#0F172A", fontWeight: "700" },
  signOutBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: radius.pill,
    backgroundColor: "#FEF2F2",
    borderWidth: 1,
    borderColor: "#FECACA",
  },
  signOutTxt: { color: "#DC2626", fontSize: 12, fontWeight: "700" },
  hero: {
    backgroundColor: "#ffffff",
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "#E0F2FE",
    padding: spacing.xl,
    marginBottom: spacing.lg,
    shadowColor: "#0F172A",
    shadowOpacity: 0.05,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
  },
  heroBadge: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#E0F2FE",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 4,
    marginBottom: 12,
  },
  heroBadgeTxt: {
    color: "#0369A1",
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 0.6,
    textTransform: "uppercase",
  },
  heroTitle: {
    color: "#0F172A",
    fontSize: 30,
    fontWeight: "800",
    letterSpacing: -0.8,
    lineHeight: 36,
  },
  heroSub: {
    color: "#475569",
    fontSize: 14,
    lineHeight: 22,
    marginTop: 8,
    maxWidth: 720,
  },
  searchBar: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: "#ffffff",
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    marginBottom: spacing.lg,
  },
  searchInput: {
    flex: 1,
    fontSize: 14,
    color: "#0F172A",
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : {}),
  },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 16 },
  card: {
    backgroundColor: "#ffffff",
    borderRadius: 18,
    padding: spacing.lg,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    minHeight: 180,
    shadowColor: "#0F172A",
    shadowOpacity: 0.05,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
  },
  cardActive: {
    borderColor: "#0EA5E9",
    borderWidth: 2,
    backgroundColor: "#F0F9FF",
  },
  cardTopRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 14,
  },
  cardBadge: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: "#DBEAFE",
    alignItems: "center",
    justifyContent: "center",
  },
  cardBadgeTxt: { color: "#0369A1", fontSize: 18, fontWeight: "800" },
  cardStatus: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    paddingHorizontal: 8,
    paddingVertical: 3,
    backgroundColor: "#ECFDF5",
    borderRadius: 999,
  },
  cardStatusDot: { width: 6, height: 6, borderRadius: 3, backgroundColor: "#10B981" },
  cardStatusTxt: {
    color: "#059669",
    fontSize: 10,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  cardTitle: {
    color: "#0F172A",
    fontSize: 17,
    fontWeight: "800",
    letterSpacing: -0.2,
    lineHeight: 22,
  },
  cardCode: { color: "#64748B", fontSize: 12, fontWeight: "600", marginTop: 4 },
  cardCta: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginTop: 18,
    paddingTop: 14,
    borderTopWidth: 1,
    borderTopColor: "#F1F5F9",
  },
  cardCtaTxt: { color: "#0EA5E9", fontSize: 13, fontWeight: "700" },
  stateBox: {
    backgroundColor: "#ffffff",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "#E2E8F0",
    padding: spacing.xl,
    alignItems: "center",
    gap: 12,
  },
  stateTxt: { color: "#334155", fontSize: 14, fontWeight: "600" },
  stateHint: {
    color: "#64748B",
    fontSize: 13,
    lineHeight: 20,
    textAlign: "center",
    maxWidth: 460,
  },
  footer: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
    marginTop: spacing.xl,
    paddingHorizontal: spacing.md,
  },
  footerTxt: { flex: 1, color: "#64748B", fontSize: 12, lineHeight: 18 },
});
