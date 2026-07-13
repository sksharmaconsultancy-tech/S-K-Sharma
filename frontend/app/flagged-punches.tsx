/**
 * Admin review screen for punches that the face-match model flagged as
 * "not the same person". The punch itself was still recorded — the
 * flag exists so an admin can eyeball the two photos and clear it once
 * satisfied (or take offline HR action).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Image,
  Alert,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Flagged = {
  record_id: string;
  user_id: string;
  user_name?: string | null;
  employee_code?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  date: string;
  at: string;
  kind: "in" | "out";
  identity_confidence?: number;
  identity_reason?: string;
  latitude?: number | null;
  longitude?: number | null;
  branch_name?: string | null;
};

type PhotoBundle = {
  profile?: string | null;
  punch?: string | null;
};

const fmtWhen = (iso: string) => {
  try {
    const dt = new Date(iso);
    return dt.toLocaleString([], {
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
};

export default function FlaggedPunchesScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const [items, setItems] = useState<Flagged[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");
  const [busy, setBusy] = useState<string | null>(null);
  const [photos, setPhotos] = useState<Record<string, PhotoBundle>>({});

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Flagged punches", msg);
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q =
        isSuper && companyFilter !== "all"
          ? `?company_id=${companyFilter}`
          : "";
      const r = await api<{ flagged: Flagged[]; count: number }>(
        `/admin/attendance/flagged${q}`,
      );
      setItems(r.flagged || []);
    } catch (e: any) {
      showMsg(e?.message || "Could not load flagged punches.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyFilter, isSuper]);

  useEffect(() => {
    load();
  }, [load]);

  const clear = async (record_id: string) => {
    setBusy(record_id);
    try {
      await api(`/admin/attendance/${record_id}/clear-flag`, {
        method: "PATCH",
      });
      setItems((prev) => prev.filter((r) => r.record_id !== record_id));
    } catch (e: any) {
      showMsg(e?.message || "Could not clear the flag.");
    } finally {
      setBusy(null);
    }
  };

  const loadPhotos = async (rec: Flagged) => {
    if (photos[rec.record_id]) return;
    try {
      // Punch selfie via the record endpoint (super/admin-only)
      const punch = await api<{ selfie_base64?: string | null }>(
        `/admin/attendance/${rec.record_id}/selfie`,
      ).catch(() => null);
      const profile = await api<{ photo_base64?: string | null }>(
        `/admin/users/${rec.user_id}/photo`,
      ).catch(() => null);
      setPhotos((p) => ({
        ...p,
        [rec.record_id]: {
          punch: punch?.selfie_base64 || null,
          profile: profile?.photo_base64 || null,
        },
      }));
    } catch {}
  };

  const renderPhoto = (b64?: string | null): string | null => {
    if (!b64) return null;
    return b64.startsWith("data:") ? b64 : `data:image/jpeg;base64,${b64}`;
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} testID="fp-back">
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Flagged punches</Text>
            <Text style={styles.subtitle}>
              {items.length}{" "}
              {items.length === 1 ? "record" : "records"} awaiting review
            </Text>
          </View>
          <Pressable
            onPress={() => {
              setRefreshing(true);
              load();
            }}
            hitSlop={8}
            testID="fp-refresh"
          >
            <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </SafeAreaView>

      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              load();
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        {isSuper && (
          <View style={{ marginBottom: spacing.md }}>
            <CompanyPicker
              testID="fp-company-picker"
              value={companyFilter}
              onChange={setCompanyFilter}
              label=""
              compact={false}
            />
          </View>
        )}

        {loading ? (
          <ActivityIndicator
            style={{ marginTop: 60 }}
            color={colors.brandPrimary}
          />
        ) : items.length === 0 ? (
          <View style={styles.empty} testID="fp-empty">
            <Ionicons
              name="shield-checkmark-outline"
              size={40}
              color={colors.onSurfaceTertiary}
            />
            <Text style={styles.emptyT}>All clear</Text>
            <Text style={styles.emptyS}>
              No punches are currently flagged. Face-match verification is
              working normally.
            </Text>
          </View>
        ) : (
          items.map((rec) => {
            const photoBundle = photos[rec.record_id];
            const conf = Math.round((rec.identity_confidence || 0) * 100);
            const isBusy = busy === rec.record_id;
            return (
              <View
                key={rec.record_id}
                style={styles.card}
                testID={`fp-row-${rec.record_id}`}
              >
                <View style={styles.cardHead}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.name} numberOfLines={1}>
                      {rec.user_name || "Unknown"}
                    </Text>
                    <Text style={styles.meta} numberOfLines={1}>
                      {rec.employee_code ? `${rec.employee_code} · ` : ""}
                      {rec.company_name || ""}
                    </Text>
                  </View>
                  <View
                    style={[
                      styles.kindPill,
                      rec.kind === "in" ? styles.kindPillIn : styles.kindPillOut,
                    ]}
                  >
                    <Text
                      style={[
                        styles.kindPillTxt,
                        {
                          color: rec.kind === "in" ? "#0F5B22" : "#7A1B00",
                        },
                      ]}
                    >
                      {rec.kind === "in" ? "IN" : "OUT"}
                    </Text>
                  </View>
                </View>
                <Text style={styles.when}>{fmtWhen(rec.at)}</Text>

                <View style={styles.confRow}>
                  <Ionicons
                    name="alert-circle"
                    size={14}
                    color={colors.warning}
                  />
                  <Text style={styles.confTxt}>
                    Model confidence:{" "}
                    <Text style={{ fontWeight: "800" }}>{conf}%</Text>
                  </Text>
                </View>
                {rec.identity_reason ? (
                  <Text style={styles.reason} numberOfLines={3}>
                    “{rec.identity_reason}”
                  </Text>
                ) : null}

                {photoBundle ? (
                  <View style={styles.photosRow}>
                    <View style={styles.photoBox}>
                      <Text style={styles.photoLabel}>ENROLLED</Text>
                      {renderPhoto(photoBundle.profile) ? (
                        <Image
                          source={{ uri: renderPhoto(photoBundle.profile)! }}
                          style={styles.photo}
                          resizeMode="cover"
                        />
                      ) : (
                        <View style={[styles.photo, styles.photoEmpty]}>
                          <Ionicons
                            name="person-outline"
                            size={20}
                            color={colors.onSurfaceTertiary}
                          />
                        </View>
                      )}
                    </View>
                    <View style={styles.photoBox}>
                      <Text style={styles.photoLabel}>PUNCH SELFIE</Text>
                      {renderPhoto(photoBundle.punch) ? (
                        <Image
                          source={{ uri: renderPhoto(photoBundle.punch)! }}
                          style={styles.photo}
                          resizeMode="cover"
                        />
                      ) : (
                        <View style={[styles.photo, styles.photoEmpty]}>
                          <Ionicons
                            name="camera-outline"
                            size={20}
                            color={colors.onSurfaceTertiary}
                          />
                        </View>
                      )}
                    </View>
                  </View>
                ) : (
                  <Pressable
                    style={styles.loadBtn}
                    onPress={() => loadPhotos(rec)}
                    testID={`fp-load-${rec.record_id}`}
                  >
                    <Ionicons
                      name="images-outline"
                      size={14}
                      color={colors.brandPrimary}
                    />
                    <Text style={styles.loadBtnTxt}>Load photos</Text>
                  </Pressable>
                )}

                <View style={styles.actionsRow}>
                  <Pressable
                    onPress={() => clear(rec.record_id)}
                    disabled={isBusy}
                    style={[styles.actBtn, isBusy && { opacity: 0.6 }]}
                    testID={`fp-clear-${rec.record_id}`}
                  >
                    {isBusy ? (
                      <ActivityIndicator color={colors.brandPrimary} />
                    ) : (
                      <>
                        <Ionicons
                          name="checkmark-circle-outline"
                          size={16}
                          color={colors.brandPrimary}
                        />
                        <Text style={styles.actBtnTxt}>
                          Clear flag (looks OK)
                        </Text>
                      </>
                    )}
                  </Pressable>
                </View>
              </View>
            );
          })
        )}

        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
  },
  title: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  subtitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 2,
  },
  scroll: { padding: spacing.lg },
  empty: { alignItems: "center", padding: spacing.xl, marginTop: spacing.lg },
  emptyT: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "800",
    marginTop: 12,
  },
  emptyS: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 6,
    textAlign: "center",
    lineHeight: 20,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  meta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 2,
  },
  when: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 6,
  },
  kindPill: {
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  kindPillIn: { backgroundColor: "#E7F5EA" },
  kindPillOut: { backgroundColor: "#FDECE2" },
  kindPillTxt: {
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  confRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginTop: 10,
  },
  confTxt: { color: colors.onSurface, fontSize: type.sm },
  reason: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontStyle: "italic",
    marginTop: 4,
    lineHeight: 18,
  },
  photosRow: {
    flexDirection: "row",
    gap: 10,
    marginTop: 12,
  },
  photoBox: { flex: 1 },
  photoLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  photo: {
    width: "100%",
    aspectRatio: 1,
    borderRadius: 8,
    backgroundColor: colors.background,
  },
  photoEmpty: {
    alignItems: "center",
    justifyContent: "center",
  },
  loadBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: 10,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: colors.background,
  },
  loadBtnTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  actionsRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 12,
  },
  actBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  actBtnTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "800",
  },
});
