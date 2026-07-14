import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import {
  ddmmyyyyDashToISO,
  formatDateDash,
  isoToDDMMYYYYDash,
  parseDDMMYYYYDash,
} from "@/src/utils/date";

/** Progressive DD-MM-YYYY mask */
function maskDashDate(input: string): string {
  const d = (input || "").replace(/\D/g, "").slice(0, 8);
  if (d.length <= 2) return d;
  if (d.length <= 4) return `${d.slice(0, 2)}-${d.slice(2)}`;
  return `${d.slice(0, 2)}-${d.slice(2, 4)}-${d.slice(4)}`;
}

type FamilyMemberInput = {
  name: string;
  relation: string;
  dob: string; // DD-MM-YYYY display
  occupation: string;
  contact: string;
};

const RELATION_OPTIONS = [
  "Spouse",
  "Father",
  "Mother",
  "Son",
  "Daughter",
  "Brother",
  "Sister",
  "Other",
];

function emptyFamily(): FamilyMemberInput {
  return { name: "", relation: "", dob: "", occupation: "", contact: "" };
}

type EditReq = {
  request_id: string;
  status: "pending" | "approved" | "rejected";
  submitted_at: string;
  changes: Record<string, any>;
  reviewed_at?: string | null;
  review_note?: string | null;
};

export default function ProfileEditScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [name, setName] = useState("");
  const [father, setFather] = useState("");
  const [dob, setDob] = useState("");
  const [doj, setDoj] = useState("");
  const [designation, setDesignation] = useState("");
  const [presentAddress, setPresentAddress] = useState("");
  const [permanentAddress, setPermanentAddress] = useState("");
  const [sameAddress, setSameAddress] = useState(false);
  const [family, setFamily] = useState<FamilyMemberInput[]>([]);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<EditReq | null>(null);
  const [lastReview, setLastReview] = useState<EditReq | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [okMsg, setOkMsg] = useState<string | null>(null);

  const loadCurrent = async () => {
    setErr(null);
    try {
      const r = await api<{ request: EditReq | null }>("/me/profile-edit");
      const req = r.request;
      if (req && req.status === "pending") {
        setPending(req);
        setLastReview(null);
      } else {
        setPending(null);
        setLastReview(req);
      }
    } catch {}
    // Prefill from live user values
    setName((user?.name || "").trim());
    setFather(((user as any)?.father_name || "").trim());
    setDob(isoToDDMMYYYYDash((user as any)?.dob));
    setDoj(isoToDDMMYYYYDash((user as any)?.doj));
    setDesignation(((user as any)?.designation || "").trim());
    const pres = ((user as any)?.present_address || "").trim();
    const perm = ((user as any)?.permanent_address || "").trim();
    setPresentAddress(pres);
    setPermanentAddress(perm);
    setSameAddress(pres.length > 0 && pres === perm);
    const fam = ((user as any)?.family_members || []) as any[];
    if (Array.isArray(fam) && fam.length > 0) {
      setFamily(
        fam.map((m) => ({
          name: (m?.name || "").toString(),
          relation: (m?.relation || "").toString(),
          dob: isoToDDMMYYYYDash(m?.dob),
          occupation: (m?.occupation || "").toString(),
          contact: (m?.contact || "").toString(),
        })),
      );
    } else {
      setFamily([]);
    }
  };

  useEffect(() => {
    loadCurrent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.user_id]);

  const updateFamily = (idx: number, patch: Partial<FamilyMemberInput>) => {
    setFamily((prev) => prev.map((m, i) => (i === idx ? { ...m, ...patch } : m)));
  };
  const removeFamily = (idx: number) => {
    setFamily((prev) => prev.filter((_, i) => i !== idx));
  };
  const addFamily = () => {
    setFamily((prev) => [...prev, emptyFamily()]);
  };

  const submit = async () => {
    setErr(null);
    setOkMsg(null);
    if (!name.trim()) {
      setErr("Name cannot be empty.");
      return;
    }
    if (dob && !parseDDMMYYYYDash(dob)) {
      setErr("Date of birth must be a valid DD-MM-YYYY date.");
      return;
    }
    if (doj && !parseDDMMYYYYDash(doj)) {
      setErr("Date of joining must be a valid DD-MM-YYYY date.");
      return;
    }

    // Validate + normalize family members. Drop empty rows silently.
    const familyPayload: any[] = [];
    for (let i = 0; i < family.length; i++) {
      const m = family[i];
      const nm = (m.name || "").trim();
      const rel = (m.relation || "").trim();
      const dobIso = ddmmyyyyDashToISO(m.dob);
      if (!nm && !rel && !m.dob && !m.occupation && !m.contact) continue;
      if (!nm) {
        setErr(`Family member #${i + 1} needs a name.`);
        return;
      }
      if (m.dob && !dobIso) {
        setErr(`Family member "${nm}" — DOB must be DD-MM-YYYY.`);
        return;
      }
      familyPayload.push({
        name: nm,
        relation: rel || undefined,
        dob: dobIso || undefined,
        occupation: (m.occupation || "").trim() || undefined,
        contact: (m.contact || "").trim() || undefined,
      });
    }

    const permAddr = sameAddress ? presentAddress : permanentAddress;

    setSaving(true);
    try {
      await api("/me/profile-edit", {
        method: "POST",
        body: {
          name: name.trim(),
          father_name: father.trim(),
          dob: ddmmyyyyDashToISO(dob) || undefined,
          doj: ddmmyyyyDashToISO(doj) || undefined,
          designation: designation.trim(),
          present_address: presentAddress.trim(),
          permanent_address: permAddr.trim(),
          family_members: familyPayload,
          note: note.trim() || undefined,
        },
      });
      setOkMsg(
        "Changes submitted for company admin approval. You'll see the updated details once approved.",
      );
      await loadCurrent();
    } catch (e: any) {
      setErr(e?.message || "Could not submit. Please try again.");
    } finally {
      setSaving(false);
    }
  };

  const askSubmit = () => {
    const msg =
      "These changes will be sent to your company admin for approval. You'll only see the new values on your profile after approval.";
    if (Platform.OS === "web") {
      if (window.confirm(msg)) void submit();
      return;
    }
    Alert.alert("Submit changes?", msg, [
      { text: "Cancel", style: "cancel" },
      { text: "Submit", onPress: submit },
    ]);
  };

  return (
    <View style={{ flex: 1, backgroundColor: colors.background }}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable
            onPress={() => router.back()}
            hitSlop={12}
            testID="pedit-back"
          >
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Edit profile</Text>
            <Text style={styles.subtitle}>
              Company admin must approve any change
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <KeyboardAwareScrollView bottomOffset={62}
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          {pending ? (
            <View style={styles.pendingCard} testID="pending-card">
              <View style={styles.pendingHead}>
                <Ionicons
                  name="hourglass-outline"
                  size={16}
                  color={colors.warning}
                />
                <Text style={styles.pendingTitle}>Pending approval</Text>
              </View>
              <Text style={styles.pendingSub}>
                Submitted on {formatDateDash(pending.submitted_at)}. Waiting
                for your company admin.
              </Text>
              {Object.entries(pending.changes || {}).map(([k, v]) => (
                <View key={k} style={styles.pendingLine}>
                  <Text style={styles.pendingKey}>{labelFor(k)}</Text>
                  <Text style={styles.pendingVal}>
                    →{" "}
                    {k === "dob" || k === "doj"
                      ? formatDateDash(v as string)
                      : k === "family_members" && Array.isArray(v)
                        ? `${(v as any[]).length} member${
                            (v as any[]).length === 1 ? "" : "s"
                          }`
                        : String(v)}
                  </Text>
                </View>
              ))}
            </View>
          ) : lastReview && lastReview.status === "rejected" ? (
            <View style={[styles.pendingCard, styles.rejectedCard]}>
              <View style={styles.pendingHead}>
                <Ionicons
                  name="close-circle-outline"
                  size={16}
                  color={colors.error}
                />
                <Text style={styles.pendingTitle}>Last request rejected</Text>
              </View>
              {lastReview.review_note ? (
                <Text style={styles.pendingSub}>
                  Reviewer note: “{lastReview.review_note}”
                </Text>
              ) : null}
            </View>
          ) : null}

          <View style={styles.card}>
            <Text style={styles.label}>Name</Text>
            <TextInput
              testID="pedit-name"
              value={name}
              onChangeText={setName}
              autoCapitalize="words"
              placeholder="Your name"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />
            <Text style={styles.label}>Father name</Text>
            <TextInput
              testID="pedit-father"
              value={father}
              onChangeText={setFather}
              autoCapitalize="words"
              placeholder="Father's name"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />
            <Text style={styles.label}>Date of birth</Text>
            <TextInput
              testID="pedit-dob"
              value={dob}
              onChangeText={(t) => setDob(maskDashDate(t))}
              placeholder="DD-MM-YYYY"
              keyboardType="number-pad"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
              maxLength={10}
            />
            <Text style={styles.label}>Date of joining</Text>
            <TextInput
              testID="pedit-doj"
              value={doj}
              onChangeText={(t) => setDoj(maskDashDate(t))}
              placeholder="DD-MM-YYYY"
              keyboardType="number-pad"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
              maxLength={10}
            />

            <Text style={styles.label}>Designation</Text>
            <TextInput
              testID="pedit-designation"
              value={designation}
              onChangeText={setDesignation}
              autoCapitalize="words"
              placeholder="e.g. Senior Accountant"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.input}
            />

            <Text style={styles.label}>Registered mobile number</Text>
            <View style={styles.readonlyRow} testID="pedit-phone">
              <Ionicons
                name="call-outline"
                size={14}
                color={colors.onSurfaceTertiary}
              />
              <Text style={styles.readonlyVal}>
                {(user as any)?.phone || "—"}
              </Text>
              <Text style={styles.readonlyBadge}>from signup</Text>
            </View>

            <Text style={styles.label}>Reason / note (optional)</Text>
            <TextInput
              testID="pedit-note"
              value={note}
              onChangeText={setNote}
              placeholder="Why these changes are needed"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={[styles.input, { minHeight: 60 }]}
              multiline
            />
          </View>

          {/* Address block */}
          <View style={styles.card}>
            <View style={styles.cardHead}>
              <Ionicons
                name="home-outline"
                size={16}
                color={colors.brandPrimary}
              />
              <Text style={styles.cardHeadTitle}>Address</Text>
            </View>
            <Text style={styles.label}>Present address</Text>
            <TextInput
              testID="pedit-present-address"
              value={presentAddress}
              onChangeText={(t) => {
                setPresentAddress(t);
                if (sameAddress) setPermanentAddress(t);
              }}
              placeholder="Where you currently stay"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={[styles.input, { minHeight: 72 }]}
              multiline
            />

            <Pressable
              testID="pedit-same-address"
              onPress={() => {
                const next = !sameAddress;
                setSameAddress(next);
                if (next) setPermanentAddress(presentAddress);
              }}
              style={styles.checkboxRow}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: sameAddress }}
            >
              <View
                style={[
                  styles.checkbox,
                  sameAddress && styles.checkboxOn,
                ]}
              >
                {sameAddress ? (
                  <Ionicons name="checkmark" size={12} color="#fff" />
                ) : null}
              </View>
              <Text style={styles.checkboxTxt}>
                Permanent address is same as present address
              </Text>
            </Pressable>

            {!sameAddress ? (
              <>
                <Text style={styles.label}>Permanent address</Text>
                <TextInput
                  testID="pedit-permanent-address"
                  value={permanentAddress}
                  onChangeText={setPermanentAddress}
                  placeholder="Your permanent home address"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  style={[styles.input, { minHeight: 72 }]}
                  multiline
                />
              </>
            ) : null}
          </View>

          {/* Family details block */}
          <View style={styles.card}>
            <View style={styles.cardHead}>
              <Ionicons
                name="people-outline"
                size={16}
                color={colors.brandPrimary}
              />
              <Text style={styles.cardHeadTitle}>Family details</Text>
            </View>
            <Text style={styles.helperTxt}>
              Add one or more family members with their relation. Contact and
              DOB are optional.
            </Text>

            {family.length === 0 ? (
              <View style={styles.emptyFamily} testID="pedit-family-empty">
                <Ionicons
                  name="person-add-outline"
                  size={22}
                  color={colors.onSurfaceTertiary}
                />
                <Text style={styles.emptyFamilyTxt}>
                  No family members added yet.
                </Text>
              </View>
            ) : (
              family.map((m, idx) => (
                <View
                  key={`family-${idx}`}
                  style={styles.familyRow}
                  testID={`pedit-family-${idx}`}
                >
                  <View style={styles.familyRowHead}>
                    <Text style={styles.familyRowTitle}>
                      Member #{idx + 1}
                    </Text>
                    <Pressable
                      onPress={() => removeFamily(idx)}
                      hitSlop={8}
                      testID={`pedit-family-remove-${idx}`}
                    >
                      <Ionicons
                        name="trash-outline"
                        size={16}
                        color={colors.error}
                      />
                    </Pressable>
                  </View>

                  <Text style={styles.miniLabel}>Name</Text>
                  <TextInput
                    testID={`pedit-family-name-${idx}`}
                    value={m.name}
                    onChangeText={(t) => updateFamily(idx, { name: t })}
                    placeholder="Full name"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={styles.input}
                    autoCapitalize="words"
                  />

                  <Text style={styles.miniLabel}>Relation</Text>
                  <View style={styles.chipRow}>
                    {RELATION_OPTIONS.map((rel) => {
                      const active = m.relation === rel;
                      return (
                        <Pressable
                          key={rel}
                          onPress={() => updateFamily(idx, { relation: rel })}
                          style={[styles.chip, active && styles.chipOn]}
                          testID={`pedit-family-relation-${idx}-${rel}`}
                        >
                          <Text
                            style={[
                              styles.chipTxt,
                              active && styles.chipTxtOn,
                            ]}
                          >
                            {rel}
                          </Text>
                        </Pressable>
                      );
                    })}
                  </View>

                  <Text style={styles.miniLabel}>Date of birth (optional)</Text>
                  <TextInput
                    testID={`pedit-family-dob-${idx}`}
                    value={m.dob}
                    onChangeText={(t) =>
                      updateFamily(idx, { dob: maskDashDate(t) })
                    }
                    placeholder="DD-MM-YYYY"
                    keyboardType="number-pad"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={styles.input}
                    maxLength={10}
                  />

                  <Text style={styles.miniLabel}>Occupation (optional)</Text>
                  <TextInput
                    testID={`pedit-family-occupation-${idx}`}
                    value={m.occupation}
                    onChangeText={(t) => updateFamily(idx, { occupation: t })}
                    placeholder="e.g. Home-maker, Student"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={styles.input}
                  />

                  <Text style={styles.miniLabel}>Contact (optional)</Text>
                  <TextInput
                    testID={`pedit-family-contact-${idx}`}
                    value={m.contact}
                    onChangeText={(t) => updateFamily(idx, { contact: t })}
                    placeholder="Phone number"
                    keyboardType="phone-pad"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={styles.input}
                  />
                </View>
              ))
            )}

            <Pressable
              testID="pedit-family-add"
              onPress={addFamily}
              style={styles.addFamilyBtn}
            >
              <Ionicons
                name="add-circle-outline"
                size={16}
                color={colors.brandPrimary}
              />
              <Text style={styles.addFamilyTxt}>Add family member</Text>
            </Pressable>
          </View>

          {err ? (
            <View style={styles.errBox} testID="pedit-error">
              <Ionicons name="alert-circle" size={16} color={colors.error} />
              <Text style={styles.errTxt}>{err}</Text>
            </View>
          ) : null}
          {okMsg ? (
            <View style={styles.okBox} testID="pedit-ok">
              <Ionicons
                name="checkmark-circle"
                size={16}
                color="#0F5B22"
              />
              <Text style={styles.okTxt}>{okMsg}</Text>
            </View>
          ) : null}

          <Pressable
            testID="pedit-submit"
            onPress={askSubmit}
            disabled={saving || !!pending}
            style={[
              styles.cta,
              (saving || !!pending) && { opacity: 0.6 },
            ]}
          >
            {saving ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="send-outline" size={16} color="#fff" />
                <Text style={styles.ctaTxt}>
                  {pending
                    ? "Waiting for approval…"
                    : "Submit for approval"}
                </Text>
              </>
            )}
          </Pressable>
          {pending ? (
            <Text style={styles.footNote}>
              Tap Cancel below to withdraw and start over.
            </Text>
          ) : null}
          {pending ? (
            <Pressable
              testID="pedit-withdraw"
              style={styles.withdraw}
              onPress={async () => {
                // Submit an "empty" replace by resubmitting current values so
                // the server rejects it? Simpler: use the delete endpoint if
                // we had one. For MVP we just DELETE via the API using PATCH
                // approval flow — not exposed to employees. So we prompt an
                // admin to reject instead.
                Alert.alert(
                  "Cancel pending request",
                  "Please ask your admin to reject this request if you want to change or cancel it.",
                );
              }}
            >
              <Text style={styles.withdrawTxt}>Cancel pending request</Text>
            </Pressable>
          ) : null}

          {/* Live values reference */}
          <View style={styles.currentCard}>
            <Text style={styles.currentTitle}>Current on record</Text>
            <Line label="Name" value={user?.name} />
            <Line label="Father" value={(user as any)?.father_name} />
            <Line
              label="DOB"
              value={
                (user as any)?.dob ? formatDateDash((user as any).dob) : "—"
              }
            />
            <Line
              label="DOJ"
              value={
                (user as any)?.doj ? formatDateDash((user as any).doj) : "—"
              }
            />
            <Line
              label="Designation"
              value={(user as any)?.designation || "—"}
            />
            <Line label="Mobile" value={(user as any)?.phone || "—"} />
            <Line
              label="Present address"
              value={(user as any)?.present_address || "—"}
            />
            <Line
              label="Permanent address"
              value={(user as any)?.permanent_address || "—"}
            />
            <Line
              label="Family members"
              value={
                Array.isArray((user as any)?.family_members) &&
                (user as any).family_members.length > 0
                  ? `${(user as any).family_members.length} on record`
                  : "—"
              }
            />
          </View>

          <Pressable
            style={styles.refreshBtn}
            onPress={async () => {
              await refresh();
              await loadCurrent();
            }}
            testID="pedit-refresh"
          >
            <Ionicons name="refresh" size={14} color={colors.brandPrimary} />
            <Text style={styles.refreshTxt}>Refresh</Text>
          </Pressable>
        </KeyboardAwareScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

function Line({ label, value }: { label: string; value?: string | null }) {
  return (
    <View style={styles.line}>
      <Text style={styles.lineLabel}>{label}</Text>
      <Text style={styles.lineVal}>{value || "—"}</Text>
    </View>
  );
}

function labelFor(k: string): string {
  switch (k) {
    case "name":
      return "Name";
    case "father_name":
      return "Father name";
    case "dob":
      return "DOB";
    case "doj":
      return "DOJ";
    case "designation":
      return "Designation";
    case "present_address":
      return "Present address";
    case "permanent_address":
      return "Permanent address";
    case "family_members":
      return "Family members";
    default:
      return k;
  }
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
  scroll: { padding: spacing.lg, paddingBottom: 40 },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  label: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
    marginTop: spacing.md,
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: Platform.OS === "ios" ? 12 : 8,
    color: colors.onSurface,
    fontSize: type.base,
  },
  pendingCard: {
    backgroundColor: "#FFF6E5",
    borderColor: "#F5C56B",
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  rejectedCard: {
    backgroundColor: "#FEECEC",
    borderColor: "#F3B4B4",
  },
  pendingHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 6,
  },
  pendingTitle: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "800",
  },
  pendingSub: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginBottom: 8,
  },
  pendingLine: {
    flexDirection: "row",
    alignItems: "center",
    marginTop: 4,
    gap: 4,
  },
  pendingKey: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "700",
    minWidth: 90,
  },
  pendingVal: { color: colors.onSurface, fontSize: type.sm, flex: 1 },
  cta: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.pill,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    marginTop: spacing.md,
  },
  ctaTxt: { color: "#fff", fontSize: type.base, fontWeight: "800" },
  footNote: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    marginTop: 6,
    textAlign: "center",
  },
  withdraw: {
    marginTop: 8,
    alignItems: "center",
  },
  withdrawTxt: {
    color: colors.error,
    fontSize: type.sm,
    fontWeight: "700",
    textDecorationLine: "underline",
  },
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEECEC",
    borderColor: "#F3B4B4",
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: 6,
  },
  errTxt: { color: colors.error, fontSize: type.sm, flex: 1 },
  okBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#E7F5EA",
    borderColor: "#B7E0C0",
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: 6,
  },
  okTxt: { color: "#0F5B22", fontSize: type.sm, flex: 1 },
  currentCard: {
    marginTop: spacing.lg,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.md,
  },
  currentTitle: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "800",
    marginBottom: 8,
  },
  line: {
    flexDirection: "row",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  lineLabel: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "600",
  },
  lineVal: { color: colors.onSurface, fontSize: type.sm },
  refreshBtn: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 4,
  },
  refreshTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  cardHead: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: 4,
  },
  cardHeadTitle: {
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "800",
  },
  helperTxt: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 4,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  readonlyRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.background,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  readonlyVal: {
    flex: 1,
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "700",
  },
  readonlyBadge: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.4,
    textTransform: "uppercase",
    backgroundColor: colors.surface,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 4,
  },
  checkboxRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginTop: spacing.sm,
  },
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.surface,
  },
  checkboxOn: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  checkboxTxt: {
    flex: 1,
    color: colors.onSurface,
    fontSize: type.sm,
  },
  familyRow: {
    backgroundColor: colors.background,
    borderRadius: radius.md,
    padding: spacing.md,
    marginTop: spacing.sm,
    gap: 2,
  },
  familyRowHead: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 4,
  },
  familyRowTitle: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontWeight: "800",
    letterSpacing: 0.3,
  },
  miniLabel: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontWeight: "700",
    marginTop: 8,
    marginBottom: 4,
    textTransform: "uppercase",
    letterSpacing: 0.4,
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginBottom: 4,
  },
  chip: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 5,
    backgroundColor: colors.surface,
  },
  chipOn: {
    backgroundColor: colors.brandPrimary,
    borderColor: colors.brandPrimary,
  },
  chipTxt: {
    color: colors.onSurface,
    fontSize: 12,
    fontWeight: "700",
  },
  chipTxtOn: {
    color: "#fff",
  },
  emptyFamily: {
    alignItems: "center",
    padding: spacing.md,
    gap: 6,
    backgroundColor: colors.background,
    borderRadius: radius.md,
    marginTop: spacing.sm,
  },
  emptyFamilyTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
  },
  addFamilyBtn: {
    marginTop: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderStyle: "dashed",
  },
  addFamilyTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "800",
  },
});
