/**
 * Iter 100 — Embedded Gmail Mailbox (Super Admin, WEB PORTAL ONLY).
 * Connect once via Google OAuth; afterwards the inbox stays connected
 * (refresh token stored server-side). Read + reply from inside the portal.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  TextInput,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

type MsgLite = {
  id: string;
  thread_id?: string;
  snippet?: string;
  subject?: string;
  from?: string;
  date?: string;
  unread?: boolean;
};

type MsgFull = MsgLite & {
  to?: string;
  body_html?: string | null;
  body_text?: string | null;
  message_id_header?: string;
};

// Iter 126e — Gmail-style category tabs.
const CATEGORIES: { key: string; label: string; gmail: string }[] = [
  { key: "primary", label: "Primary", gmail: "CATEGORY_PERSONAL" },
  { key: "promotions", label: "Promotions", gmail: "CATEGORY_PROMOTIONS" },
  { key: "social", label: "Social", gmail: "CATEGORY_SOCIAL" },
  { key: "updates", label: "Updates", gmail: "CATEGORY_UPDATES" },
  { key: "spam", label: "Spam", gmail: "SPAM" },
];

export default function MailboxScreen() {
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();
  const [status, setStatus] = useState<{ connected: boolean; email?: string } | null>(null);
  const [msgs, setMsgs] = useState<MsgLite[]>([]);
  const [nextToken, setNextToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<MsgFull | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [reply, setReply] = useState("");
  const [sending, setSending] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [category, setCategory] = useState("primary");

  const showToast = (m: string) => {
    setToast(m);
    setTimeout(() => setToast(null), 3000);
  };

  const loadStatus = useCallback(async () => {
    try {
      const s = await api<{ connected: boolean; email?: string }>("/gmail/status");
      setStatus(s);
      return s;
    } catch {
      setStatus({ connected: false });
      return { connected: false };
    }
  }, []);

  const loadInbox = useCallback(async (q?: string, pageToken?: string | null, cat?: string) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (pageToken) params.set("page_token", pageToken);
      const catKey = cat || category;
      const gmailLabel =
        CATEGORIES.find((c) => c.key === catKey)?.gmail || "CATEGORY_PERSONAL";
      params.set("label", gmailLabel);
      const r = await api<{ messages: MsgLite[]; next_page_token?: string | null }>(
        `/gmail/messages${params.toString() ? `?${params}` : ""}`,
      );
      setMsgs((prev) => (pageToken ? [...prev, ...(r.messages || [])] : r.messages || []));
      setNextToken(r.next_page_token || null);
    } catch (e: any) {
      showToast(e?.message || "Failed to load inbox");
    } finally {
      setLoading(false);
    }
  }, [category]);

  useEffect(() => {
    if (!user || user.role !== "super_admin") return;
    (async () => {
      const s = await loadStatus();
      if (s.connected) loadInbox();
    })();
  }, [user?.role, loadStatus, loadInbox]);

  const connect = async () => {
    try {
      const r = await api<{ auth_url: string }>("/gmail/auth-url");
      if (Platform.OS === "web" && typeof window !== "undefined") {
        window.location.href = r.auth_url;
      }
    } catch (e: any) {
      showToast(e?.message || "Could not start Google sign-in");
    }
  };

  const openMsg = async (id: string) => {
    setDetailLoading(true);
    setReply("");
    try {
      const m = await api<MsgFull>(`/gmail/messages/${id}`);
      setDetail(m);
    } catch (e: any) {
      showToast(e?.message || "Could not open email");
    } finally {
      setDetailLoading(false);
    }
  };

  const sendReply = async () => {
    if (!detail || !reply.trim()) return;
    setSending(true);
    try {
      const fromAddr = (detail.from || "").match(/<(.+?)>/)?.[1] || detail.from || "";
      await api("/gmail/send", {
        method: "POST",
        body: {
          to: fromAddr,
          subject: detail.subject?.startsWith("Re:") ? detail.subject : `Re: ${detail.subject || ""}`,
          body: reply,
          thread_id: detail.thread_id,
          in_reply_to: detail.message_id_header,
        },
      });
      showToast("Reply sent ✓");
      setReply("");
    } catch (e: any) {
      showToast(e?.message || "Send failed");
    } finally {
      setSending(false);
    }
  };

  if (authLoading) return null;
  if (!user || user.role !== "super_admin") return <Redirect href="/" />;

  // WEB PORTAL ONLY — per user requirement.
  if (Platform.OS !== "web") {
    return (
      <SafeAreaView style={styles.safe} edges={["top"]}>
        <View style={styles.centerBox}>
          <Ionicons name="desktop-outline" size={40} color={colors.onSurfaceTertiary} />
          <Text style={styles.centerTxt}>
            Mailbox is available on the Web Portal only. Please open the portal on your computer.
          </Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="mb-back">
          <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.headerTitle}>
          Mailbox{status?.email ? ` · ${status.email}` : ""}
        </Text>
        {status?.connected ? (
          <Pressable onPress={() => loadInbox(search)} hitSlop={10} testID="mb-refresh">
            <Ionicons name="refresh" size={20} color={colors.brandPrimary} />
          </Pressable>
        ) : (
          <View style={{ width: 22 }} />
        )}
      </View>

      {!status ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
      ) : !status.connected ? (
        <View style={styles.centerBox}>
          <Ionicons name="mail-outline" size={44} color={colors.brandPrimary} />
          <Text style={styles.connectTitle}>Connect your Gmail</Text>
          <Text style={styles.centerTxt}>
            Sign in with Google ONCE — after that your inbox stays connected
            and opens right here every time.
          </Text>
          <Pressable style={styles.connectBtn} onPress={connect} testID="mb-connect">
            <Ionicons name="logo-google" size={16} color="#fff" />
            <Text style={styles.connectBtnTxt}>Connect Gmail</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.split}>
          {/* LEFT — inbox list */}
          <View style={styles.listPane}>
            {/* Iter 126e — Gmail category tabs */}
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              style={{ flexGrow: 0 }}
              contentContainerStyle={styles.catRow}
            >
              {CATEGORIES.map((c) => (
                <Pressable
                  key={c.key}
                  onPress={() => {
                    setCategory(c.key);
                    setDetail(null);
                    loadInbox(search, null, c.key);
                  }}
                  style={[styles.catChip, category === c.key && styles.catChipActive]}
                  testID={`mb-cat-${c.key}`}
                >
                  <Text
                    style={[styles.catChipTxt, category === c.key && styles.catChipTxtActive]}
                  >
                    {c.label}
                  </Text>
                </Pressable>
              ))}
            </ScrollView>
            <View style={styles.searchRow}>
              <TextInput
                style={styles.searchInput}
                placeholder="Search mail…"
                placeholderTextColor={colors.onSurfaceTertiary}
                value={search}
                onChangeText={setSearch}
                onSubmitEditing={() => loadInbox(search)}
                testID="mb-search"
              />
              <Pressable style={styles.searchBtn} onPress={() => loadInbox(search)}>
                <Ionicons name="search" size={16} color="#fff" />
              </Pressable>
            </View>
            <ScrollView>
              {loading && msgs.length === 0 ? (
                <ActivityIndicator style={{ marginTop: 30 }} color={colors.brandPrimary} />
              ) : msgs.length === 0 ? (
                <Text style={styles.empty}>No emails found.</Text>
              ) : (
                msgs.map((m) => (
                  <Pressable
                    key={m.id}
                    onPress={() => openMsg(m.id)}
                    style={[
                      styles.msgRow,
                      detail?.id === m.id && styles.msgRowActive,
                      m.unread && styles.msgRowUnread,
                    ]}
                    testID={`mb-msg-${m.id}`}
                  >
                    <Text style={[styles.msgFrom, m.unread && { fontWeight: "900" }]} numberOfLines={1}>
                      {(m.from || "").replace(/<.*>/, "").trim() || m.from}
                    </Text>
                    <Text style={[styles.msgSubject, m.unread && { fontWeight: "800" }]} numberOfLines={1}>
                      {m.subject || "(no subject)"}
                    </Text>
                    <Text style={styles.msgSnippet} numberOfLines={1}>{m.snippet}</Text>
                  </Pressable>
                ))
              )}
              {nextToken ? (
                <Pressable style={styles.moreBtn} onPress={() => loadInbox(search, nextToken)}>
                  <Text style={styles.moreBtnTxt}>{loading ? "Loading…" : "Load more"}</Text>
                </Pressable>
              ) : null}
            </ScrollView>
          </View>

          {/* RIGHT — reading pane */}
          <View style={styles.readPane}>
            {detailLoading ? (
              <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary} />
            ) : !detail ? (
              <View style={styles.centerBox}>
                <Ionicons name="mail-open-outline" size={36} color={colors.onSurfaceTertiary} />
                <Text style={styles.centerTxt}>Select an email to read it.</Text>
              </View>
            ) : (
              <ScrollView contentContainerStyle={{ padding: spacing.md }}>
                <Text style={styles.readSubject}>{detail.subject || "(no subject)"}</Text>
                <Text style={styles.readMeta}>From: {detail.from}</Text>
                <Text style={styles.readMeta}>Date: {detail.date}</Text>
                <View style={styles.readBody}>
                  {detail.body_html && Platform.OS === "web" ? (
                    <iframe
                      srcDoc={detail.body_html}
                      style={{ width: "100%", height: 520, border: "none", backgroundColor: "#fff" }}
                      sandbox=""
                      title="email-body"
                    />
                  ) : (
                    <Text style={styles.readText}>{detail.body_text || detail.snippet}</Text>
                  )}
                </View>
                <View style={styles.replyBox}>
                  <Text style={styles.replyLbl}>Reply</Text>
                  <TextInput
                    style={styles.replyInput}
                    multiline
                    value={reply}
                    onChangeText={setReply}
                    placeholder="Write your reply…"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    testID="mb-reply-input"
                  />
                  <Pressable
                    style={[styles.connectBtn, { alignSelf: "flex-end", opacity: sending ? 0.6 : 1 }]}
                    onPress={sendReply}
                    disabled={sending}
                    testID="mb-reply-send"
                  >
                    <Ionicons name="send" size={14} color="#fff" />
                    <Text style={styles.connectBtnTxt}>{sending ? "Sending…" : "Send Reply"}</Text>
                  </Pressable>
                </View>
              </ScrollView>
            )}
          </View>
        </View>
      )}

      {toast ? (
        <View style={styles.toast}><Text style={styles.toastTxt}>{toast}</Text></View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.surfaceSecondary },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerTitle: { color: colors.onSurface, fontSize: type.base, fontWeight: "800" },
  centerBox: { alignItems: "center", justifyContent: "center", padding: 40, gap: 10, flexGrow: 1 },
  centerTxt: { color: colors.onSurfaceSecondary, fontSize: type.sm, textAlign: "center", maxWidth: 420 },
  connectTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  connectBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 18,
    paddingVertical: 11,
    borderRadius: radius.sm,
    marginTop: 8,
  },
  connectBtnTxt: { color: "#fff", fontSize: type.sm, fontWeight: "800" },
  split: { flex: 1, flexDirection: "row" },
  listPane: {
    width: 360,
    borderRightWidth: 1,
    borderRightColor: colors.border,
    backgroundColor: colors.surface,
  },
  catRow: { flexDirection: "row", gap: 6, paddingHorizontal: 10, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.border },
  catChip: {
    paddingHorizontal: 12,
    paddingVertical: 6,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  catChipActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  catChipTxt: { fontSize: 12, fontWeight: "700", color: colors.onSurfaceSecondary },
  catChipTxtActive: { color: "#fff" },
  searchRow: { flexDirection: "row", gap: 6, padding: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  searchInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    color: colors.onSurface,
    fontSize: 13,
    backgroundColor: colors.surfaceSecondary,
  },
  searchBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    width: 38,
  },
  empty: { color: colors.onSurfaceTertiary, textAlign: "center", marginTop: 30, fontSize: type.sm },
  msgRow: { paddingHorizontal: 12, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: colors.border },
  msgRowActive: { backgroundColor: colors.brandTertiary },
  msgRowUnread: { backgroundColor: "#F0F7FF" },
  msgFrom: { color: colors.onSurface, fontSize: 12.5, fontWeight: "700" },
  msgSubject: { color: colors.onSurface, fontSize: 12.5, marginTop: 1 },
  msgSnippet: { color: colors.onSurfaceTertiary, fontSize: 11.5, marginTop: 1 },
  moreBtn: { padding: 12, alignItems: "center" },
  moreBtnTxt: { color: colors.brandPrimary, fontSize: 12.5, fontWeight: "800" },
  readPane: { flex: 1, backgroundColor: colors.surfaceSecondary },
  readSubject: { color: colors.onSurface, fontSize: type.lg, fontWeight: "800" },
  readMeta: { color: colors.onSurfaceSecondary, fontSize: 12, marginTop: 2 },
  readBody: {
    marginTop: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    overflow: "hidden",
    backgroundColor: "#fff",
  },
  readText: { color: colors.onSurface, fontSize: 13, padding: 12, lineHeight: 20 },
  replyBox: { marginTop: spacing.md, gap: 8 },
  replyLbl: { color: colors.onSurface, fontSize: 13, fontWeight: "800" },
  replyInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    minHeight: 90,
    padding: 10,
    color: colors.onSurface,
    fontSize: 13,
    backgroundColor: colors.surface,
    textAlignVertical: "top",
  },
  toast: {
    position: "absolute",
    bottom: 26,
    alignSelf: "center",
    backgroundColor: "#111827",
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: 999,
  },
  toastTxt: { color: "#fff", fontSize: type.sm },
});
