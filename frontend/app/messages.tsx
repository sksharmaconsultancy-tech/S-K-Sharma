/**
 * In-app messaging
 *
 * Single screen with three modes:
 *   • Inbox  — every user sees messages they were sent
 *   • Sent   — admins see the messages they composed (with read counts)
 *   • Compose (modal, admin-only) — pick recipients or "All employees"
 *     and hit send.
 *
 * Messaging is one-way (admin → employee) for this MVP. Delivery is
 * in-app only; no email / push side-channels.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Modal,
  TextInput,
  Alert,
  Platform,
  KeyboardAvoidingView,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";
import * as DocumentPicker from "expo-document-picker";
import * as ImagePicker from "expo-image-picker";
import * as FileSystemNS from "expo-file-system";
import * as Sharing from "expo-sharing";

import { api, apiBinary } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";

const FileSystem: any = FileSystemNS as any;

type MessageAttachment = {
  attachment_id: string;
  filename: string;
  mime_type: string;
  size_bytes?: number | null;
};

type MessageIn = {
  message_id: string;
  subject: string;
  body: string;
  sender_name?: string | null;
  sender_role?: string | null;
  sent_at: string;
  is_broadcast?: boolean;
  read?: boolean;
  attachments?: MessageAttachment[];
  attachment_count?: number;
};

type MessageSent = {
  message_id: string;
  subject: string;
  body: string;
  sent_at: string;
  is_broadcast?: boolean;
  recipient_count: number;
  read_count: number;
  attachments?: MessageAttachment[];
  attachment_count?: number;
};

type Employee = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  company_id?: string | null;
};

const fmtWhen = (iso?: string | null) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString([], {
      hour: "2-digit",
      minute: "2-digit",
      day: "2-digit",
      month: "short",
    });
  } catch {
    return iso;
  }
};

const showMsg = (title: string, body: string) => {
  if (Platform.OS === "web") window.alert(`${title}\n\n${body}`);
  else Alert.alert(title, body);
};

function fmtSize(n?: number | null): string {
  if (!n || n <= 0) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

// Iter 74 — Attachment chip list surfaced on inbox / sent rows.
function AttachmentList({
  messageId,
  attachments,
  onOpen,
}: {
  messageId: string;
  attachments: MessageAttachment[];
  onOpen: (messageId: string, att: MessageAttachment) => void;
}) {
  return (
    <View style={styles.attRow}>
      {attachments.map((a) => (
        <Pressable
          key={a.attachment_id}
          onPress={() => onOpen(messageId, a)}
          style={styles.attChip}
          testID={`msg-att-${a.attachment_id}`}
        >
          <Ionicons
            name={a.mime_type?.startsWith("image/") ? "image-outline" : "document-outline"}
            size={14}
            color={colors.brandPrimary}
          />
          <Text style={styles.attChipTxt} numberOfLines={1}>
            {a.filename}
          </Text>
          <Text style={styles.attChipSize}>{fmtSize(a.size_bytes)}</Text>
        </Pressable>
      ))}
    </View>
  );
}

export default function MessagesScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isAdmin = user?.role !== "employee";
  const isSuper = user?.role === "super_admin";

  const [tab, setTab] = useState<"inbox" | "sent">("inbox");
  const [inbox, setInbox] = useState<MessageIn[]>([]);
  const [sent, setSent] = useState<MessageSent[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const [composeOpen, setComposeOpen] = useState(false);

  // Compose state
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [broadcast, setBroadcast] = useState(true);
  const [companyFilter, setCompanyFilter] = useState<string | "all">("all");
  const { selectedCompanyId: globalCid } = useSelectedCompany();
  useEffect(() => {
    if (globalCid) setCompanyFilter(globalCid);
  }, [globalCid]);
  const [recipients, setRecipients] = useState<Employee[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [searchQ, setSearchQ] = useState("");
  const [sending, setSending] = useState(false);

  // Iter 74 — Compose attachments (image/PDF, ≤5 MB, up to 3).
  type PendingAttachment = {
    filename: string;
    mime_type: string;
    base64: string;
    size_bytes: number;
    previewUri?: string;
  };
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attaching, setAttaching] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const inboxRes = await api<{ messages: MessageIn[] }>("/messages/inbox");
      setInbox(inboxRes.messages || []);
      if (isAdmin) {
        const sentRes = await api<{ messages: MessageSent[] }>(
          "/messages/sent",
        );
        setSent(sentRes.messages || []);
      }
    } catch (e: any) {
      showMsg("Messages", e?.message || "Could not load messages.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [isAdmin]);

  useEffect(() => {
    load();
  }, [load]);

  // ---- recipient picker: fetch when compose opens or company changes ----
  const loadRecipients = useCallback(async () => {
    try {
      const params = new URLSearchParams();
      if (isSuper && companyFilter !== "all") {
        params.set("company_id", companyFilter as string);
      }
      if (searchQ.trim()) params.set("q", searchQ.trim());
      const qs = params.toString() ? `?${params}` : "";
      const r = await api<{ employees: Employee[] }>(
        `/messages/recipients${qs}`,
      );
      setRecipients(r.employees || []);
    } catch {
      setRecipients([]);
    }
  }, [companyFilter, isSuper, searchQ]);

  useEffect(() => {
    if (composeOpen && !broadcast) loadRecipients();
  }, [composeOpen, broadcast, loadRecipients]);

  const toggleRecipient = (uid: string) => {
    setSelectedIds((prev) =>
      prev.includes(uid) ? prev.filter((x) => x !== uid) : [...prev, uid],
    );
  };

  const filteredRecipients = useMemo(() => {
    const q = searchQ.trim().toLowerCase();
    if (!q) return recipients;
    return recipients.filter(
      (e) =>
        (e.name || "").toLowerCase().includes(q) ||
        (e.employee_code || "").toLowerCase().includes(q),
    );
  }, [recipients, searchQ]);

  const resetCompose = () => {
    setComposeOpen(false);
    setSubject("");
    setBody("");
    setBroadcast(true);
    setSelectedIds([]);
    setSearchQ("");
    setPendingAttachments([]);
  };

  const canSend =
    subject.trim().length > 0 &&
    body.trim().length > 0 &&
    (broadcast || selectedIds.length > 0);

  // Iter 74 — add attachment via file picker or camera. Enforces the
  // 5 MB / 3-file limits client-side so the API returns fast.
  const readAsBase64 = async (uri: string): Promise<string> => {
    if (Platform.OS === "web") {
      const resp = await fetch(uri);
      const blob = await resp.blob();
      return await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => {
          const dataUrl = String(reader.result || "");
          const idx = dataUrl.indexOf(",");
          resolve(idx >= 0 ? dataUrl.slice(idx + 1) : dataUrl);
        };
        reader.onerror = () => reject(new Error("Could not read file"));
        reader.readAsDataURL(blob);
      });
    }
    return await FileSystem.readAsStringAsync(uri, { encoding: "base64" });
  };

  const addAttachment = async (source: "file" | "camera") => {
    if (pendingAttachments.length >= 3) {
      showMsg("Attachments", "You can attach at most 3 files per message.");
      return;
    }
    setAttaching(true);
    try {
      let uri: string;
      let mime: string;
      let name = "";
      let size = 0;

      if (source === "camera") {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (!perm.granted) {
          throw new Error("Camera permission is required to attach a photo.");
        }
        const res = await ImagePicker.launchCameraAsync({
          mediaTypes: ImagePicker.MediaTypeOptions.Images,
          quality: 0.75,
        });
        if (res.canceled || !res.assets?.[0]) return;
        const a = res.assets[0];
        uri = a.uri;
        mime = a.mimeType || "image/jpeg";
        name = a.fileName || `photo_${Date.now()}.jpg`;
        size = a.fileSize || 0;
      } else {
        const res = await DocumentPicker.getDocumentAsync({
          type: ["image/jpeg", "image/png", "image/webp", "application/pdf"],
          multiple: false,
          copyToCacheDirectory: true,
        });
        if (res.canceled || !res.assets?.[0]) return;
        const a = res.assets[0];
        uri = a.uri;
        mime = a.mimeType ||
          (a.name?.toLowerCase().endsWith(".pdf") ? "application/pdf" : "image/jpeg");
        name = a.name;
        size = a.size || 0;
      }

      if (size && size > 5 * 1024 * 1024) {
        throw new Error("Each attachment must be 5 MB or less.");
      }

      const base64 = await readAsBase64(uri);
      const approxBytes = Math.floor((base64.length * 3) / 4);
      if (approxBytes > 5 * 1024 * 1024) {
        throw new Error("Each attachment must be 5 MB or less.");
      }
      setPendingAttachments((prev) => [
        ...prev,
        {
          filename: name || "attachment",
          mime_type: mime,
          base64,
          size_bytes: size || approxBytes,
          previewUri: mime.startsWith("image/") ? uri : undefined,
        },
      ]);
    } catch (e: any) {
      showMsg("Attach failed", e?.message || "Could not attach the file.");
    } finally {
      setAttaching(false);
    }
  };

  const removeAttachment = (idx: number) => {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== idx));
  };

  const send = async () => {
    if (!canSend) return;
    setSending(true);
    try {
      const payload: any = {
        subject: subject.trim(),
        body: body.trim(),
        broadcast,
      };
      if (!broadcast) payload.recipient_user_ids = selectedIds;
      if (isSuper && companyFilter !== "all") payload.company_id = companyFilter;
      if (pendingAttachments.length > 0) {
        payload.attachments = pendingAttachments.map((a) => ({
          filename: a.filename,
          mime_type: a.mime_type,
          base64: a.base64,
          size_bytes: a.size_bytes,
        }));
      }
      await api("/messages", { method: "POST", body: payload });
      resetCompose();
      setTab("sent");
      await load();
    } catch (e: any) {
      showMsg("Send failed", e?.message || "Could not send message.");
    } finally {
      setSending(false);
    }
  };

  // Iter 74 — Download / open an attachment (recipient or sender view).
  const openAttachment = async (messageId: string, att: MessageAttachment) => {
    try {
      const res = await apiBinary(
        `/messages/${messageId}/attachments/${att.attachment_id}?inline=true`,
      );
      if (Platform.OS === "web") {
        if (res.webBlobUrl) window.open(res.webBlobUrl, "_blank");
      } else {
        const ext =
          att.mime_type === "application/pdf"
            ? "pdf"
            : att.mime_type === "image/png"
              ? "png"
              : att.mime_type === "image/webp"
                ? "webp"
                : "jpg";
        const path = `${FileSystem.cacheDirectory}${att.attachment_id}.${ext}`;
        await FileSystem.writeAsStringAsync(path, res.base64, { encoding: "base64" });
        if (await Sharing.isAvailableAsync()) {
          await Sharing.shareAsync(path, {
            mimeType: att.mime_type,
            dialogTitle: att.filename,
          });
        } else {
          showMsg("Attachment", `Saved to ${path}`);
        }
      }
    } catch (e: any) {
      showMsg("Attachment", e?.message || "Could not open attachment.");
    }
  };

  const markRead = async (id: string) => {
    try {
      await api(`/messages/${id}/read`, { method: "POST" });
      setInbox((prev) =>
        prev.map((m) => (m.message_id === id ? { ...m, read: true } : m)),
      );
    } catch {}
  };

  const openMessage = (m: MessageIn) => {
    setOpenId(openId === m.message_id ? null : m.message_id);
    if (openId !== m.message_id && !m.read) markRead(m.message_id);
  };

  const unreadCount = inbox.filter((m) => !m.read).length;

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} testID="msg-back">
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Messages</Text>
            <Text style={styles.subtitle}>
              {tab === "inbox"
                ? `${inbox.length} in inbox${unreadCount ? ` · ${unreadCount} unread` : ""}`
                : `${sent.length} sent`}
            </Text>
          </View>
          <Pressable
            onPress={() => {
              setRefreshing(true);
              load();
            }}
            hitSlop={8}
            testID="msg-refresh"
          >
            <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
          </Pressable>
        </View>

        {isAdmin ? (
          <View style={styles.tabs}>
            <Pressable
              style={[styles.tab, tab === "inbox" && styles.tabOn]}
              onPress={() => setTab("inbox")}
              testID="msg-tab-inbox"
            >
              <Text
                style={[styles.tabTxt, tab === "inbox" && styles.tabTxtOn]}
              >
                Inbox{unreadCount ? ` (${unreadCount})` : ""}
              </Text>
            </Pressable>
            <Pressable
              style={[styles.tab, tab === "sent" && styles.tabOn]}
              onPress={() => setTab("sent")}
              testID="msg-tab-sent"
            >
              <Text style={[styles.tabTxt, tab === "sent" && styles.tabTxtOn]}>
                Sent
              </Text>
            </Pressable>
          </View>
        ) : null}
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
        {loading ? (
          <ActivityIndicator
            style={{ marginTop: 60 }}
            color={colors.brandPrimary}
          />
        ) : tab === "inbox" ? (
          inbox.length === 0 ? (
            <View style={styles.empty} testID="msg-empty-inbox">
              <Ionicons
                name="mail-outline"
                size={42}
                color={colors.onSurfaceTertiary}
              />
              <Text style={styles.emptyT}>No messages yet</Text>
              <Text style={styles.emptyS}>
                Announcements and messages from your admin will appear here.
              </Text>
            </View>
          ) : (
            inbox.map((m) => {
              const isOpen = openId === m.message_id;
              return (
                <Pressable
                  key={m.message_id}
                  onPress={() => openMessage(m)}
                  style={[styles.card, !m.read && styles.cardUnread]}
                  testID={`msg-row-${m.message_id}`}
                >
                  <View style={styles.cardHead}>
                    {!m.read ? <View style={styles.unreadDot} /> : null}
                    <Text
                      style={[styles.subject, !m.read && styles.subjectUnread]}
                      numberOfLines={isOpen ? undefined : 1}
                    >
                      {m.subject}
                    </Text>
                    {m.is_broadcast ? (
                      <View style={styles.bcastPill}>
                        <Text style={styles.bcastPillTxt}>ALL</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.meta}>
                    From {m.sender_name || "Admin"} · {fmtWhen(m.sent_at)}
                  </Text>
                  <Text
                    style={styles.body}
                    numberOfLines={isOpen ? undefined : 2}
                  >
                    {m.body}
                  </Text>
                  {m.attachments && m.attachments.length > 0 && (
                    <AttachmentList
                      messageId={m.message_id}
                      attachments={m.attachments}
                      onOpen={openAttachment}
                    />
                  )}
                </Pressable>
              );
            })
          )
        ) : sent.length === 0 ? (
          <View style={styles.empty} testID="msg-empty-sent">
            <Ionicons
              name="paper-plane-outline"
              size={42}
              color={colors.onSurfaceTertiary}
            />
            <Text style={styles.emptyT}>Nothing sent yet</Text>
            <Text style={styles.emptyS}>
              Tap the pencil button to send your first message.
            </Text>
          </View>
        ) : (
          sent.map((m) => (
            <View
              key={m.message_id}
              style={styles.card}
              testID={`msg-sent-${m.message_id}`}
            >
              <View style={styles.cardHead}>
                <Text style={styles.subject} numberOfLines={1}>
                  {m.subject}
                </Text>
                {m.is_broadcast ? (
                  <View style={styles.bcastPill}>
                    <Text style={styles.bcastPillTxt}>ALL</Text>
                  </View>
                ) : null}
              </View>
              <Text style={styles.meta}>{fmtWhen(m.sent_at)}</Text>
              <Text style={styles.body} numberOfLines={2}>
                {m.body}
              </Text>
              {m.attachments && m.attachments.length > 0 && (
                <AttachmentList
                  messageId={m.message_id}
                  attachments={m.attachments}
                  onOpen={openAttachment}
                />
              )}
              <View style={styles.readsRow}>
                <Ionicons
                  name="eye-outline"
                  size={13}
                  color={colors.onSurfaceTertiary}
                />
                <Text style={styles.readsTxt}>
                  Read by {m.read_count} of {m.recipient_count}
                </Text>
              </View>
            </View>
          ))
        )}

        <View style={{ height: 100 }} />
      </ScrollView>

      {/* FAB — admins only */}
      {isAdmin ? (
        <Pressable
          testID="msg-compose-fab"
          onPress={() => setComposeOpen(true)}
          style={styles.fab}
        >
          <Ionicons name="create-outline" size={22} color="#fff" />
          <Text style={styles.fabTxt}>Compose</Text>
        </Pressable>
      ) : null}

      {/* Compose modal */}
      <Modal
        visible={composeOpen}
        animationType="slide"
        transparent
        onRequestClose={resetCompose}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : undefined}
          style={styles.modalRoot}
        >
          <Pressable style={styles.backdrop} onPress={resetCompose} />
          <View style={styles.sheet}>
            <View style={styles.sheetGrip} />
            <KeyboardAwareScrollView
              contentContainerStyle={{ paddingBottom: spacing.lg }}
              bottomOffset={62}
              keyboardShouldPersistTaps="handled"
            >
              <Text style={styles.sheetTitle}>New message</Text>

              {isSuper ? (
                <View style={{ marginBottom: spacing.sm }}>
                  <CompanyPicker
                    testID="msg-company-picker"
                    value={companyFilter}
                    onChange={(v) => {
                      setCompanyFilter(v);
                      setSelectedIds([]);
                    }}
                    label="Send within company"
                    compact
                  />
                </View>
              ) : null}

              <View style={styles.audienceRow}>
                <Pressable
                  onPress={() => setBroadcast(true)}
                  style={[styles.audChip, broadcast && styles.audChipOn]}
                  testID="msg-audience-all"
                >
                  <Ionicons
                    name="megaphone-outline"
                    size={14}
                    color={broadcast ? "#fff" : colors.brandPrimary}
                  />
                  <Text
                    style={[styles.audChipTxt, broadcast && styles.audChipTxtOn]}
                  >
                    All employees
                  </Text>
                </Pressable>
                <Pressable
                  onPress={() => setBroadcast(false)}
                  style={[styles.audChip, !broadcast && styles.audChipOn]}
                  testID="msg-audience-select"
                >
                  <Ionicons
                    name="people-outline"
                    size={14}
                    color={!broadcast ? "#fff" : colors.brandPrimary}
                  />
                  <Text
                    style={[
                      styles.audChipTxt,
                      !broadcast && styles.audChipTxtOn,
                    ]}
                  >
                    Select recipients{selectedIds.length ? ` (${selectedIds.length})` : ""}
                  </Text>
                </Pressable>
              </View>

              {!broadcast ? (
                <View style={styles.pickerBox}>
                  <TextInput
                    testID="msg-recipient-search"
                    value={searchQ}
                    onChangeText={setSearchQ}
                    placeholder="Search by name or employee code"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    style={styles.input}
                    autoCapitalize="none"
                    autoCorrect={false}
                  />
                  <View style={styles.pickerList}>
                    {filteredRecipients.length === 0 ? (
                      <Text style={styles.emptyPicker}>
                        No employees match your search.
                      </Text>
                    ) : (
                      filteredRecipients.map((e) => {
                        const on = selectedIds.includes(e.user_id);
                        return (
                          <Pressable
                            key={e.user_id}
                            onPress={() => toggleRecipient(e.user_id)}
                            style={styles.pickerRow}
                            testID={`msg-pick-${e.user_id}`}
                          >
                            <View
                              style={[styles.checkbox, on && styles.checkboxOn]}
                            >
                              {on ? (
                                <Ionicons name="checkmark" size={12} color="#fff" />
                              ) : null}
                            </View>
                            <View style={{ flex: 1 }}>
                              <Text style={styles.pickerName}>{e.name}</Text>
                              {e.employee_code ? (
                                <Text style={styles.pickerCode}>
                                  {e.employee_code}
                                </Text>
                              ) : null}
                            </View>
                          </Pressable>
                        );
                      })
                    )}
                  </View>
                </View>
              ) : null}

              <Text style={styles.label}>Subject</Text>
              <TextInput
                testID="msg-subject"
                value={subject}
                onChangeText={setSubject}
                placeholder="Short summary"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={styles.input}
                maxLength={200}
              />

              <Text style={styles.label}>Message</Text>
              <TextInput
                testID="msg-body"
                value={body}
                onChangeText={setBody}
                placeholder="Write your announcement or message here…"
                placeholderTextColor={colors.onSurfaceTertiary}
                style={[styles.input, { minHeight: 140, textAlignVertical: "top" }]}
                multiline
                maxLength={5000}
              />

              {/* Iter 74 — Attachments (images / PDF, ≤5 MB, up to 3) */}
              <Text style={styles.label}>
                Attachments {pendingAttachments.length > 0 ? `(${pendingAttachments.length}/3)` : ""}
              </Text>
              <View style={styles.attachPickRow}>
                <Pressable
                  onPress={() => addAttachment("file")}
                  disabled={attaching || pendingAttachments.length >= 3}
                  style={[
                    styles.attachAddBtn,
                    (attaching || pendingAttachments.length >= 3) && { opacity: 0.5 },
                  ]}
                  testID="msg-attach-file"
                >
                  <Ionicons name="attach" size={16} color={colors.brandPrimary} />
                  <Text style={styles.attachAddBtnTxt}>Attach file</Text>
                </Pressable>
                {Platform.OS !== "web" && (
                  <Pressable
                    onPress={() => addAttachment("camera")}
                    disabled={attaching || pendingAttachments.length >= 3}
                    style={[
                      styles.attachAddBtn,
                      (attaching || pendingAttachments.length >= 3) && { opacity: 0.5 },
                    ]}
                    testID="msg-attach-camera"
                  >
                    <Ionicons name="camera-outline" size={16} color={colors.brandPrimary} />
                    <Text style={styles.attachAddBtnTxt}>Camera</Text>
                  </Pressable>
                )}
                {attaching ? (
                  <ActivityIndicator size="small" color={colors.brandPrimary} />
                ) : null}
              </View>
              {pendingAttachments.length > 0 && (
                <View style={styles.attachPreviewRow}>
                  {pendingAttachments.map((a, idx) => (
                    <View key={`pending-${idx}`} style={styles.attachPreview}>
                      {a.previewUri ? (
                        <Image
                          source={{ uri: a.previewUri }}
                          style={styles.attachPreviewImg}
                        />
                      ) : (
                        <View style={[styles.attachPreviewImg, styles.attachPreviewFallback]}>
                          <Ionicons
                            name="document-outline"
                            size={22}
                            color={colors.brandPrimary}
                          />
                        </View>
                      )}
                      <View style={{ flex: 1 }}>
                        <Text style={styles.attachPreviewName} numberOfLines={1}>
                          {a.filename}
                        </Text>
                        <Text style={styles.attachPreviewSize}>
                          {fmtSize(a.size_bytes)} · {a.mime_type}
                        </Text>
                      </View>
                      <Pressable
                        onPress={() => removeAttachment(idx)}
                        hitSlop={8}
                        testID={`msg-attach-remove-${idx}`}
                      >
                        <Ionicons name="close-circle" size={22} color={colors.error} />
                      </Pressable>
                    </View>
                  ))}
                </View>
              )}
              <Text style={styles.attachHint}>
                Images (JPG/PNG/WebP) or PDF · max 5 MB each · up to 3 files.
              </Text>

              <Pressable
                testID="msg-send"
                onPress={send}
                disabled={!canSend || sending}
                style={[styles.sendBtn, (!canSend || sending) && { opacity: 0.5 }]}
              >
                {sending ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="paper-plane" size={16} color="#fff" />
                    <Text style={styles.sendBtnTxt}>Send</Text>
                  </>
                )}
              </Pressable>
            </KeyboardAwareScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>
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
  tabs: {
    flexDirection: "row",
    backgroundColor: colors.background,
    padding: 4,
    marginHorizontal: spacing.lg,
    marginBottom: spacing.md,
    borderRadius: radius.pill,
    gap: 4,
  },
  tab: { flex: 1, alignItems: "center", paddingVertical: 8, borderRadius: radius.pill },
  tabOn: { backgroundColor: colors.brandPrimary },
  tabTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "700" },
  tabTxtOn: { color: "#fff" },

  scroll: { padding: spacing.lg },
  empty: { alignItems: "center", padding: spacing.xl, marginTop: spacing.md },
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
    borderLeftWidth: 3,
    borderLeftColor: "transparent",
  },
  cardUnread: {
    borderLeftColor: colors.brandPrimary,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 8 },
  unreadDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: colors.brandPrimary,
  },
  subject: {
    flex: 1,
    color: colors.onSurface,
    fontSize: type.base,
    fontWeight: "600",
  },
  subjectUnread: { fontWeight: "800" },
  meta: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 4,
  },
  body: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 8,
    lineHeight: 20,
  },
  readsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    marginTop: 10,
    paddingTop: 10,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
  },
  readsTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    fontWeight: "700",
  },
  bcastPill: {
    backgroundColor: colors.brandTertiary,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
  },
  bcastPillTxt: {
    color: colors.onBrandTertiary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
  },

  fab: {
    position: "absolute",
    right: spacing.lg,
    bottom: spacing.xl,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.pill,
    paddingHorizontal: 18,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    elevation: 6,
    shadowColor: "#000",
    shadowOpacity: 0.2,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 3 },
  },
  fabTxt: { color: "#fff", fontSize: type.base, fontWeight: "800" },

  modalRoot: { flex: 1, justifyContent: "flex-end" },
  backdrop: { flex: 1, backgroundColor: "rgba(0,0,0,0.35)" },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.sm,
    maxHeight: "88%",
  },
  sheetGrip: {
    width: 44,
    height: 4,
    backgroundColor: colors.border,
    borderRadius: 2,
    alignSelf: "center",
    marginBottom: spacing.md,
  },
  sheetTitle: {
    color: colors.onSurface,
    fontSize: type.xl,
    fontWeight: "800",
    marginBottom: spacing.md,
  },

  audienceRow: {
    flexDirection: "row",
    gap: 8,
    marginBottom: spacing.md,
  },
  audChip: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: radius.pill,
    paddingVertical: 10,
    backgroundColor: colors.surface,
  },
  audChipOn: { backgroundColor: colors.brandPrimary },
  audChipTxt: {
    color: colors.brandPrimary,
    fontSize: type.sm,
    fontWeight: "700",
  },
  audChipTxtOn: { color: "#fff" },

  pickerBox: {
    backgroundColor: colors.background,
    borderRadius: radius.md,
    padding: spacing.sm,
    marginBottom: spacing.md,
    maxHeight: 260,
  },
  pickerList: { marginTop: 8, gap: 4 },
  pickerRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingVertical: 8,
    paddingHorizontal: 6,
  },
  pickerName: { color: colors.onSurface, fontSize: type.sm, fontWeight: "700" },
  pickerCode: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  emptyPicker: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    padding: spacing.md,
    textAlign: "center",
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

  label: {
    color: colors.onSurfaceSecondary,
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 0.4,
    textTransform: "uppercase",
    marginTop: spacing.sm,
    marginBottom: 6,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: colors.onSurface,
    fontSize: type.base,
  },
  sendBtn: {
    marginTop: spacing.lg,
    backgroundColor: colors.brandPrimary,
    paddingVertical: 14,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 8,
  },
  sendBtnTxt: { color: "#fff", fontSize: type.base, fontWeight: "800" },

  // Iter 74 — attachment styles
  attRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 6,
    marginTop: 10,
  },
  attChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
    paddingVertical: 6,
    paddingHorizontal: 10,
    maxWidth: 240,
  },
  attChipTxt: {
    color: colors.onBrandTertiary,
    fontSize: type.sm,
    fontWeight: "600",
    flexShrink: 1,
  },
  attChipSize: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
  },
  attachPickRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: 6,
  },
  attachAddBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 8,
    paddingHorizontal: 12,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
  },
  attachAddBtnTxt: {
    color: colors.brandPrimary,
    fontWeight: "700",
    fontSize: type.sm,
  },
  attachPreviewRow: {
    marginTop: spacing.sm,
    gap: 8,
  },
  attachPreview: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    backgroundColor: colors.surfaceSecondary,
    padding: 8,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  attachPreviewImg: {
    width: 44,
    height: 44,
    borderRadius: 6,
  },
  attachPreviewFallback: {
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  attachPreviewName: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "600",
  },
  attachPreviewSize: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 2,
  },
  attachHint: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    marginTop: 6,
  },
});
