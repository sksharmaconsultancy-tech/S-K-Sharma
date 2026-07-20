import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Platform,
  Alert,
  TextInput,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";
import { formatDateDash } from "@/src/utils/date";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

type ProfileReq = {
  request_id: string;
  user_id: string;
  company_id?: string | null;
  status: "pending" | "approved" | "rejected";
  submitted_at: string;
  changes: Record<string, any>;
  note?: string | null;
  employee?: {
    name?: string | null;
    father_name?: string | null;
    dob?: string | null;
    doj?: string | null;
    designation?: string | null;
    present_address?: string | null;
    permanent_address?: string | null;
    family_members?: any[] | null;
    employee_code?: string | null;
  } | null;
};

const KEY_LABEL: Record<string, string> = {
  name: "Name",
  father_name: "Father name",
  dob: "DOB",
  doj: "DOJ",
  designation: "Designation",
  present_address: "Present address",
  permanent_address: "Permanent address",
  family_members: "Family members",
};

function fmtFamily(v: any): string {
  if (!Array.isArray(v)) return String(v ?? "—");
  if (v.length === 0) return "0 members";
  return v
    .map((m: any) => {
      const nm = m?.name || "?";
      const rel = m?.relation ? ` (${m.relation})` : "";
      return `${nm}${rel}`;
    })
    .join(", ");
}

export default function ProfileEditReviewScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";
  const [items, setItems] = useState<ProfileReq[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [company, setCompany] = useState<string | "all">("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams({ status: "pending" });
      if (isSuper && company !== "all") q.set("company_id", company);
      const r = await api<{ requests: ProfileReq[] }>(
        `/admin/profile-edits?${q.toString()}`,
      );
      setItems(r.requests || []);
    } finally {
      setLoading(false);
    }
  }, [company, isSuper]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (
    req: ProfileReq,
    status: "approved" | "rejected",
    review_note?: string,
  ) => {
    setBusy(req.request_id);
    try {
      await api(`/admin/profile-edits/${req.request_id}`, {
        method: "PATCH",
        body: { status, review_note: review_note || undefined },
      });
      setItems((prev) => prev.filter((x) => x.request_id !== req.request_id));
    } catch (e: any) {
      if (Platform.OS === "web") window.alert(e?.message || "Could not update");
      else Alert.alert("Failed", e?.message || "Could not update");
    } finally {
      setBusy(null);
    }
  };

  const askReject = (req: ProfileReq) => {
    if (Platform.OS === "web") {
      const note = window.prompt("Reason for rejection (optional):") || "";
      void decide(req, "rejected", note);
      return;
    }
    Alert.prompt?.(
      "Reject request",
      "Optional note (visible to employee):",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Reject",
          style: "destructive",
          onPress: (v) => void decide(req, "rejected", v || undefined),
        },
      ],
    );
    // Fallback for Android — no Alert.prompt.
    if (!Alert.prompt) {
      Alert.alert("Reject request?", "This cannot be undone.", [
        { text: "Cancel", style: "cancel" },
        {
          text: "Reject",
          style: "destructive",
          onPress: () => void decide(req, "rejected"),
        },
      ]);
    }
  };

  const askApprove = (req: ProfileReq) => {
    const msg = "Apply these changes to the employee's record?";
    if (Platform.OS === "web") {
      if (window.confirm(msg)) void decide(req, "approved");
      return;
    }
    Alert.alert("Approve changes?", msg, [
      { text: "Cancel", style: "cancel" },
      { text: "Approve", onPress: () => void decide(req, "approved") },
    ]);
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable
            onPress={() => router.back()}
            hitSlop={12}
            testID="pedit-review-back"
          >
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Profile edits</Text>
            <Text style={styles.subtitle}>
              Review employee profile change requests
            </Text>
          </View>
          <Pressable onPress={load} hitSlop={12} testID="pedit-review-refresh">
            <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
          </Pressable>
        </View>
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {isSuper && (
          <View style={{ marginBottom: spacing.md }}>
            <CompanyPicker
              testID="pedit-review-company"
              value={company}
              onChange={setCompany}
              label=""
            />
          </View>
        )}

        {loading ? (
          <ActivityIndicator
            style={{ marginTop: 40 }}
            color={colors.brandPrimary}
          />
        ) : items.length === 0 ? (
          <View style={styles.empty} testID="pedit-review-empty">
            <Ionicons
              name="checkmark-done-outline"
              size={40}
              color={colors.onSurfaceTertiary}
            />
            <Text style={styles.emptyTitle}>All caught up!</Text>
            <Text style={styles.emptyBody}>
              There are no pending profile-edit requests to review.
            </Text>
          </View>
        ) : (
          items.map((r) => (
            <View
              key={r.request_id}
              style={styles.card}
              testID={`pedit-item-${r.request_id}`}
            >
              <View style={styles.head}>
                <View style={styles.avatar}>
                  <Ionicons
                    name="person"
                    size={18}
                    color={colors.brandPrimary}
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name}>
                    {r.employee?.name || "Employee"}
                  </Text>
                  <Text style={styles.meta}>
                    {r.employee?.employee_code
                      ? `${r.employee.employee_code} · `
                      : ""}
                    Submitted {formatDateDash(r.submitted_at)}
                  </Text>
                </View>
              </View>

              <View style={styles.changesBox}>
                {Object.entries(r.changes || {}).map(([k, v]) => {
                  const current = (r.employee as any)?.[k] ?? null;
                  const isDate = k === "dob" || k === "doj";
                  const isFamily = k === "family_members";
                  return (
                    <View key={k} style={styles.changeRow}>
                      <Text style={styles.changeKey}>{KEY_LABEL[k] || k}</Text>
                      <View style={styles.changeVals}>
                        <Text style={styles.changeCur} numberOfLines={3}>
                          {isFamily
                            ? fmtFamily(current)
                            : current
                              ? isDate
                                ? formatDateDash(current)
                                : String(current)
                              : "—"}
                        </Text>
                        <Ionicons
                          name="arrow-forward"
                          size={12}
                          color={colors.onSurfaceTertiary}
                        />
                        <Text style={styles.changeNew} numberOfLines={4}>
                          {isFamily
                            ? fmtFamily(v)
                            : isDate
                              ? formatDateDash(v as string)
                              : String(v)}
                        </Text>
                      </View>
                    </View>
                  );
                })}
              </View>

              {r.note ? (
                <Text style={styles.note}>Employee note: “{r.note}”</Text>
              ) : null}

              <View style={styles.actions}>
                <Pressable
                  testID={`pedit-reject-${r.request_id}`}
                  onPress={() => askReject(r)}
                  disabled={busy === r.request_id}
                  style={[styles.btn, styles.btnReject]}
                >
                  {busy === r.request_id ? (
                    <ActivityIndicator size="small" color={colors.error} />
                  ) : (
                    <>
                      <Ionicons
                        name="close"
                        size={14}
                        color={colors.error}
                      />
                      <Text style={styles.btnRejectTxt}>Reject</Text>
                    </>
                  )}
                </Pressable>
                <Pressable
                  testID={`pedit-approve-${r.request_id}`}
                  onPress={() => askApprove(r)}
                  disabled={busy === r.request_id}
                  style={[styles.btn, styles.btnApprove]}
                >
                  {busy === r.request_id ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={14} color="#fff" />
                      <Text style={styles.btnApproveTxt}>Approve</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          ))
        )}
        <View style={{ height: 40 }} />
      </KeyboardAwareScrollView>
      {/* silence unused TextInput import */}
      <View style={{ height: 0 }}>
        <TextInput style={{ display: "none" }} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
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
  empty: { alignItems: "center", padding: spacing.xl },
  emptyTitle: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "700",
    marginTop: 12,
  },
  emptyBody: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 6,
    textAlign: "center",
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  head: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  name: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "700",
  },
  meta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 2,
  },
  changesBox: {
    marginTop: spacing.md,
    backgroundColor: colors.background,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: 6,
  },
  changeRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
  },
  changeKey: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "700",
    minWidth: 90,
  },
  changeVals: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    flex: 1,
    justifyContent: "flex-end",
  },
  changeCur: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    textDecorationLine: "line-through",
  },
  changeNew: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  note: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontStyle: "italic",
    marginTop: 8,
  },
  actions: {
    flexDirection: "row",
    gap: 8,
    marginTop: spacing.md,
  },
  btn: {
    flex: 1,
    borderRadius: radius.pill,
    paddingVertical: 10,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
  },
  btnReject: {
    borderWidth: 1,
    borderColor: colors.error,
    backgroundColor: "#FFF5F5",
  },
  btnRejectTxt: { color: colors.error, fontWeight: "800", fontSize: type.sm },
  btnApprove: { backgroundColor: colors.brandPrimary },
  btnApproveTxt: { color: "#fff", fontWeight: "800", fontSize: type.sm },
});
