import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Modal,
  TextInput, KeyboardAvoidingView, Platform, ActivityIndicator, Alert,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import * as FileSystem from "expo-file-system";
import * as WebBrowser from "expo-web-browser";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { colors, radius, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

const CATS = ["hr", "payroll", "compliance", "it", "other"] as const;

const MAX_FILES = 5;
const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB
const ALLOWED_MIMES = new Set([
  "application/pdf",
  "image/jpeg",
  "image/jpg",
  "image/png",
]);

type LocalAttachment = {
  name: string;
  mime: string;
  size: number;
  data_base64: string;
};

type RemoteAttachmentMeta = {
  index: number;
  name: string;
  mime: string;
  size: number;
};

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function iconForMime(mime: string): keyof typeof Ionicons.glyphMap {
  if (mime === "application/pdf") return "document-text-outline";
  if (mime.startsWith("image/")) return "image-outline";
  return "attach-outline";
}

async function readAsBase64(uri: string): Promise<string> {
  // expo-file-system v19+ uses `readAsStringAsync` with EncodingType.Base64
  const b64 = await (FileSystem as any).readAsStringAsync(uri, {
    encoding: "base64",
  });
  return b64;
}

export default function TicketsScreen() {
  const { user } = useAuth();
  const router = useRouter();
  const isAdmin = user?.role !== "employee";

  const [scope, setScope] = useState<"mine" | "all">("mine");
  const [tickets, setTickets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [category, setCategory] = useState<(typeof CATS)[number]>("hr");
  const [subject, setSubject] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [attachments, setAttachments] = useState<LocalAttachment[]>([]);
  const [openingIdx, setOpeningIdx] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ tickets: any[] }>(`/tickets?scope=${scope}`);
      setTickets(r.tickets || []);
    } finally {
      setLoading(false);
    }
  }, [scope]);

  useEffect(() => { load(); }, [load]);
  useOnRefresh(load);

  const resetForm = () => {
    setOpen(false);
    setSubject("");
    setDescription("");
    setAttachments([]);
  };

  const alertErr = (msg: string) => {
    if (Platform.OS === "web") {
      window.alert(msg);
    } else {
      Alert.alert("Attachment error", msg);
    }
  };

  const pickPdf = async () => {
    if (attachments.length >= MAX_FILES) {
      alertErr(`You can attach at most ${MAX_FILES} files.`);
      return;
    }
    try {
      const res = await DocumentPicker.getDocumentAsync({
        type: "application/pdf",
        multiple: false,
        copyToCacheDirectory: true,
      });
      if (res.canceled) return;
      const asset = res.assets?.[0];
      if (!asset) return;
      const mime = (asset.mimeType || "application/pdf").toLowerCase();
      if (!ALLOWED_MIMES.has(mime)) {
        alertErr("Only PDF files are allowed here.");
        return;
      }
      const size = asset.size ?? 0;
      if (size > MAX_FILE_BYTES) {
        alertErr(`"${asset.name}" is ${fmtBytes(size)} — maximum is 5 MB per file.`);
        return;
      }
      const b64 = await readAsBase64(asset.uri);
      setAttachments((prev) => [
        ...prev,
        {
          name: asset.name || "document.pdf",
          mime,
          size: size || Math.ceil((b64.length * 3) / 4),
          data_base64: b64,
        },
      ]);
    } catch (e: any) {
      alertErr(e?.message || "Could not read the selected file.");
    }
  };

  const pickImage = async () => {
    if (attachments.length >= MAX_FILES) {
      alertErr(`You can attach at most ${MAX_FILES} files.`);
      return;
    }
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (perm.status !== "granted") {
        alertErr(
          "Photo library permission is required to attach images. You can enable it in your device settings.",
        );
        return;
      }
      const res = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsMultipleSelection: false,
        quality: 0.85,
        base64: true,
      });
      if (res.canceled) return;
      const asset = res.assets?.[0];
      if (!asset) return;
      const inferredMime =
        asset.mimeType?.toLowerCase() ||
        (asset.uri.toLowerCase().endsWith(".png") ? "image/png" : "image/jpeg");
      if (!ALLOWED_MIMES.has(inferredMime)) {
        alertErr("Only JPEG or PNG images are allowed.");
        return;
      }
      let b64 = asset.base64 || "";
      if (!b64) b64 = await readAsBase64(asset.uri);
      const approxSize = Math.ceil((b64.length * 3) / 4);
      if (approxSize > MAX_FILE_BYTES) {
        alertErr(
          `Selected image is ${fmtBytes(approxSize)} — maximum is 5 MB. Please pick a smaller image.`,
        );
        return;
      }
      const fileName =
        asset.fileName ||
        `photo-${new Date().getTime()}.${inferredMime === "image/png" ? "png" : "jpg"}`;
      setAttachments((prev) => [
        ...prev,
        {
          name: fileName,
          mime: inferredMime,
          size: approxSize,
          data_base64: b64,
        },
      ]);
    } catch (e: any) {
      alertErr(e?.message || "Could not read the selected image.");
    }
  };

  const removeAttachment = (idx: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== idx));
  };

  const submit = async () => {
    if (!subject || !description) return;
    setSubmitting(true);
    try {
      await api("/tickets", {
        method: "POST",
        body: {
          category,
          subject,
          description,
          attachments: attachments.map((a) => ({
            name: a.name,
            mime: a.mime,
            data_base64: a.data_base64,
          })),
        },
      });
      resetForm();
      await load();
    } catch (e: any) {
      alertErr(e?.message || "Could not submit ticket.");
    } finally {
      setSubmitting(false);
    }
  };

  const setStatus = async (id: string, status: string) => {
    await api(`/tickets/${id}`, { method: "PATCH", body: { status } });
    await load();
  };

  const openAttachment = async (
    ticketId: string,
    att: RemoteAttachmentMeta,
  ) => {
    const key = `${ticketId}-${att.index}`;
    setOpeningIdx(key);
    try {
      const r = await api<{
        name: string;
        mime: string;
        data_base64: string;
      }>(`/tickets/${ticketId}/attachments/${att.index}`);
      const dataUri = `data:${r.mime};base64,${r.data_base64}`;
      if (Platform.OS === "web") {
        // Open in a new browser tab
        const w = window.open();
        if (w) {
          if (r.mime === "application/pdf") {
            w.document.write(
              `<iframe src="${dataUri}" frameborder="0" style="width:100%;height:100vh"></iframe>`,
            );
          } else {
            w.document.write(
              `<img src="${dataUri}" style="max-width:100%;height:auto"/>`,
            );
          }
        }
      } else {
        // Native: write to cache and open with system viewer
        const ext = r.mime === "application/pdf" ? "pdf" : r.mime === "image/png" ? "png" : "jpg";
        const path = `${(FileSystem as any).cacheDirectory}${ticketId}-${att.index}.${ext}`;
        await (FileSystem as any).writeAsStringAsync(path, r.data_base64, {
          encoding: "base64",
        });
        await WebBrowser.openBrowserAsync(path);
      }
    } catch (e: any) {
      alertErr(e?.message || "Could not open attachment.");
    } finally {
      setOpeningIdx(null);
    }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Tickets</Text>
          <View style={{ width: 26 }} />
        </View>
        {isAdmin && (
          <View style={styles.seg}>
            <Pressable onPress={() => setScope("mine")} style={[styles.segItem, scope === "mine" && styles.segItemActive]}>
              <Text style={[styles.segTxt, scope === "mine" && styles.segTxtActive]}>Mine</Text>
            </Pressable>
            <Pressable onPress={() => setScope("all")} style={[styles.segItem, scope === "all" && styles.segItemActive]}>
              <Text style={[styles.segTxt, scope === "all" && styles.segTxtActive]}>All tickets</Text>
            </Pressable>
          </View>
        )}
      </SafeAreaView>

      <KeyboardAwareScrollView bottomOffset={62} contentContainerStyle={styles.scroll}>
        {loading ? <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} /> :
        tickets.length === 0 ? <Text style={styles.empty}>No tickets yet.</Text> :
        tickets.map((t) => (
          <View key={t.ticket_id} style={styles.card} testID={`ticket-${t.ticket_id}`}>
            <View style={styles.rowBetween}>
              <View style={styles.catChip}>
                <Text style={styles.catTxt}>{t.category.toUpperCase()}</Text>
              </View>
              <View style={[styles.statusChip, statusStyle(t.status)]}>
                <Text style={{ color: "#fff", fontSize: 11, fontWeight: "500", letterSpacing: 0.5 }}>{t.status}</Text>
              </View>
            </View>
            <Text style={styles.subject}>{t.subject}</Text>
            <Text style={styles.desc}>{t.description}</Text>
            {scope === "all" && <Text style={styles.who}>By {t.user_name}</Text>}

            {Array.isArray(t.attachments) && t.attachments.length > 0 ? (
              <View style={styles.attList} testID={`ticket-atts-${t.ticket_id}`}>
                {t.attachments.map((att: RemoteAttachmentMeta) => {
                  const key = `${t.ticket_id}-${att.index}`;
                  const busy = openingIdx === key;
                  return (
                    <Pressable
                      key={key}
                      onPress={() => openAttachment(t.ticket_id, att)}
                      style={styles.attChip}
                      disabled={busy}
                      testID={`ticket-att-${t.ticket_id}-${att.index}`}
                    >
                      {busy ? (
                        <ActivityIndicator size="small" color={colors.brandPrimary} />
                      ) : (
                        <Ionicons
                          name={iconForMime(att.mime)}
                          size={14}
                          color={colors.brandPrimary}
                        />
                      )}
                      <Text style={styles.attChipTxt} numberOfLines={1}>
                        {att.name}
                      </Text>
                      <Text style={styles.attChipSize}>{fmtBytes(att.size)}</Text>
                    </Pressable>
                  );
                })}
              </View>
            ) : null}

            {t.admin_reply && (
              <View style={styles.replyBox}>
                <Text style={styles.replyLabel}>Admin reply</Text>
                <Text style={styles.replyTxt}>{t.admin_reply}</Text>
              </View>
            )}
            {isAdmin && scope === "all" && (
              <View style={styles.actions}>
                {["in_progress", "resolved", "closed"].map((s) => (
                  <Pressable
                    key={s}
                    onPress={() => setStatus(t.ticket_id, s)}
                    style={styles.actionBtn}
                  >
                    <Text style={styles.actionTxt}>{s.replace("_", " ")}</Text>
                  </Pressable>
                ))}
              </View>
            )}
          </View>
        ))}
        <View style={{ height: 100 }} />
      </KeyboardAwareScrollView>

      <Pressable testID="new-ticket-fab" style={styles.fab} onPress={() => setOpen(true)}>
        <Ionicons name="add" size={24} color="#fff" />
        <Text style={styles.fabTxt}>New</Text>
      </Pressable>

      <Modal transparent visible={open} animationType="slide" onRequestClose={resetForm}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.modalRoot}>
          <Pressable style={styles.backdrop} onPress={resetForm} />
          <View style={styles.sheet}>
            <KeyboardAwareScrollView
              bottomOffset={62}
              contentContainerStyle={{ paddingBottom: spacing.md }}
              keyboardShouldPersistTaps="handled"
            >
              <View style={styles.sheetGrip} />
              <Text style={styles.sheetTitle}>Raise ticket</Text>
              <Text style={styles.label}>Category</Text>
              <View style={styles.typeRow}>
                {CATS.map((c) => (
                  <Pressable key={c} onPress={() => setCategory(c)}
                    style={[styles.typeChip, category === c && styles.typeChipActive]}>
                    <Text style={[styles.typeChipTxt, category === c && styles.typeChipTxtActive]}>{c}</Text>
                  </Pressable>
                ))}
              </View>
              <Text style={styles.label}>Subject</Text>
              <TextInput testID="subject-input" value={subject} onChangeText={setSubject}
                style={styles.input} placeholder="Short summary" placeholderTextColor={colors.onSurfaceTertiary} />
              <Text style={styles.label}>Description</Text>
              <TextInput testID="desc-input" value={description} onChangeText={setDescription}
                style={[styles.input, { height: 100 }]} multiline
                placeholder="Details of your query…" placeholderTextColor={colors.onSurfaceTertiary} />

              <View style={styles.attHeader}>
                <Text style={styles.label}>
                  Attachments{" "}
                  <Text style={styles.attHint}>
                    (PDF or JPEG, up to 5 files · 5 MB each)
                  </Text>
                </Text>
              </View>
              <View style={styles.attActions}>
                <Pressable
                  testID="pick-pdf"
                  style={[
                    styles.attActionBtn,
                    attachments.length >= MAX_FILES && { opacity: 0.5 },
                  ]}
                  disabled={attachments.length >= MAX_FILES}
                  onPress={pickPdf}
                >
                  <Ionicons
                    name="document-text-outline"
                    size={16}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.attActionTxt}>Attach PDF</Text>
                </Pressable>
                <Pressable
                  testID="pick-image"
                  style={[
                    styles.attActionBtn,
                    attachments.length >= MAX_FILES && { opacity: 0.5 },
                  ]}
                  disabled={attachments.length >= MAX_FILES}
                  onPress={pickImage}
                >
                  <Ionicons
                    name="image-outline"
                    size={16}
                    color={colors.brandPrimary}
                  />
                  <Text style={styles.attActionTxt}>Attach JPEG</Text>
                </Pressable>
              </View>

              {attachments.length > 0 ? (
                <View style={styles.attSelected} testID="attachments-selected">
                  {attachments.map((a, idx) => (
                    <View key={`a-${idx}`} style={styles.attRow}>
                      <Ionicons
                        name={iconForMime(a.mime)}
                        size={16}
                        color={colors.brandPrimary}
                      />
                      <View style={{ flex: 1 }}>
                        <Text style={styles.attRowName} numberOfLines={1}>
                          {a.name}
                        </Text>
                        <Text style={styles.attRowMeta}>
                          {a.mime.replace("application/", "").replace("image/", "")} · {fmtBytes(a.size)}
                        </Text>
                      </View>
                      <Pressable
                        onPress={() => removeAttachment(idx)}
                        hitSlop={8}
                        testID={`remove-att-${idx}`}
                      >
                        <Ionicons
                          name="close-circle"
                          size={20}
                          color={colors.error}
                        />
                      </Pressable>
                    </View>
                  ))}
                </View>
              ) : null}

              <Pressable
                testID="submit-ticket"
                style={[
                  styles.submit,
                  (submitting || !subject || !description) && { opacity: 0.6 },
                ]}
                onPress={submit}
                disabled={submitting || !subject || !description}
              >
                {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.submitTxt}>Submit</Text>}
              </Pressable>
            </KeyboardAwareScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>
    </View>
  );
}

function statusStyle(s: string) {
  if (s === "resolved" || s === "closed") return { backgroundColor: colors.success };
  if (s === "in_progress") return { backgroundColor: colors.warning };
  return { backgroundColor: colors.info };
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: spacing.lg, paddingVertical: spacing.md },
  h1: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500" },
  seg: { marginHorizontal: spacing.xl, backgroundColor: colors.surfaceTertiary, borderRadius: radius.md, padding: 4, flexDirection: "row" },
  segItem: { flex: 1, paddingVertical: 8, alignItems: "center", borderRadius: radius.sm },
  segItemActive: { backgroundColor: colors.surfaceSecondary },
  segTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, fontWeight: "500" },
  segTxtActive: { color: colors.onSurface },
  scroll: { padding: spacing.xl },
  empty: { color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 60 },
  card: { backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, padding: spacing.lg, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md },
  rowBetween: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  catChip: { backgroundColor: colors.brandTertiary, paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  catTxt: { color: colors.onBrandTertiary, fontSize: 11, fontWeight: "500", letterSpacing: 0.5 },
  statusChip: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: radius.pill },
  subject: { color: colors.onSurface, fontSize: type.lg, fontWeight: "500", marginTop: spacing.sm },
  desc: { color: colors.onSurfaceSecondary, fontSize: type.base, marginTop: 4 },
  who: { color: colors.onSurfaceTertiary, fontSize: type.sm, marginTop: 4 },
  replyBox: { marginTop: spacing.md, backgroundColor: colors.surfaceTertiary, borderRadius: radius.md, padding: spacing.md },
  replyLabel: { color: colors.onSurfaceTertiary, fontSize: 11, letterSpacing: 1 },
  replyTxt: { color: colors.onSurface, fontSize: type.base, marginTop: 2 },
  actions: { flexDirection: "row", gap: 8, marginTop: spacing.md, flexWrap: "wrap" },
  actionBtn: { backgroundColor: colors.brandTertiary, paddingHorizontal: 12, paddingVertical: 8, borderRadius: radius.pill },
  actionTxt: { color: colors.onBrandTertiary, fontSize: type.sm, textTransform: "capitalize", fontWeight: "500" },
  fab: { position: "absolute", bottom: 24, right: 24, backgroundColor: colors.brandPrimary, borderRadius: radius.pill, paddingHorizontal: 18, paddingVertical: 14, flexDirection: "row", alignItems: "center", gap: 6, elevation: 4 },
  fabTxt: { color: "#fff", fontSize: type.base, fontWeight: "500" },
  modalRoot: { flex: 1, justifyContent: "flex-end" },
  backdrop: { ...StyleSheet.absoluteFillObject, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: spacing.xl },
  sheetGrip: { alignSelf: "center", width: 40, height: 4, borderRadius: 2, backgroundColor: colors.borderStrong, marginBottom: spacing.md },
  sheetTitle: { fontSize: type.xl, color: colors.onSurface, fontWeight: "500", marginBottom: spacing.md },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.sm },
  typeRow: { flexDirection: "row", gap: 8, marginTop: 6, flexWrap: "wrap" },
  typeChip: { paddingHorizontal: spacing.md, paddingVertical: 8, borderRadius: radius.pill, backgroundColor: colors.surfaceTertiary },
  typeChipActive: { backgroundColor: colors.brandPrimary },
  typeChipTxt: { color: colors.onSurfaceTertiary, fontSize: type.sm, textTransform: "capitalize" },
  typeChipTxtActive: { color: "#fff" },
  input: { borderWidth: 1, borderColor: colors.border, borderRadius: radius.md, padding: spacing.md, color: colors.onSurface, fontSize: type.base, marginTop: 6, backgroundColor: colors.surfaceSecondary },
  submit: { marginTop: spacing.lg, backgroundColor: colors.cta, paddingVertical: 14, borderRadius: radius.pill, alignItems: "center" },
  submitTxt: { color: "#fff", fontSize: type.lg, fontWeight: "500" },
  attList: {
    marginTop: spacing.md,
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
  },
  attChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
    paddingHorizontal: 10,
    paddingVertical: 6,
    maxWidth: "100%",
  },
  attChipTxt: {
    color: colors.onBrandTertiary,
    fontSize: 12,
    fontWeight: "700",
    maxWidth: 160,
  },
  attChipSize: {
    color: colors.onBrandTertiary,
    fontSize: 10,
    opacity: 0.8,
    fontWeight: "600",
  },
  attHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-end",
    marginTop: spacing.md,
  },
  attHint: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    fontWeight: "600",
  },
  attActions: {
    flexDirection: "row",
    gap: 8,
    marginTop: 6,
  },
  attActionBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 10,
    backgroundColor: colors.surface,
  },
  attActionTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  attSelected: {
    marginTop: spacing.sm,
    gap: 6,
  },
  attRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: colors.border,
  },
  attRowName: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "700",
  },
  attRowMeta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 1,
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
});
