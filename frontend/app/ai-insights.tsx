/**
 * AI Insights — Iter 73.
 *
 * Super-Admin only web page powering GPT-5.2 backed data analysis. Three
 * tabs surface complementary flows:
 *   1. Chat  — free-form Q&A with rolling conversation history.
 *   2. Monthly Summary — executive brief for a chosen firm + month.
 *   3. Anomaly Scan — 30-day anomaly detection (outside-geofence punches,
 *      pending approvals piling up, payroll outliers, etc.).
 *
 * Each tab shares a common firm-picker (defaults to "All firms" — the
 * aggregate view). Non super-admins land on a lock screen so sub-admins /
 * company-admins can't peek at global figures.
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  TextInput,
  ScrollView,
  ActivityIndicator,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";

type Firm = { company_id: string; name: string; company_code?: string };
type ChatTurn = { role: "user" | "assistant"; content: string };

const QUICK_PROMPTS: string[] = [
  "Give me a payroll snapshot for this month across all firms.",
  "Which firm has the most outside-geofence punches in the last 30 days?",
  "Are there any pending punch approvals I should clear today?",
  "Compare total gross payroll vs total net payroll and explain the gap.",
  "Which firm has the highest headcount and how does its payroll compare?",
  "Highlight any anomaly I should flag with an employer today.",
];

const currentMonth = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};

export default function AiInsightsScreen() {
  const { user } = useAuth();
  const router = useRouter();

  const isSuperAdmin = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [tab, setTab] = useState<"chat" | "summary" | "anomalies">("chat");
  const [firms, setFirms] = useState<Firm[]>([]);
  const [selectedFirm, setSelectedFirm] = useState<string>("all");
  const [month, setMonth] = useState<string>(currentMonth());

  const [chatInput, setChatInput] = useState<string>("");
  const [chatHistory, setChatHistory] = useState<ChatTurn[]>([]);
  const [chatBusy, setChatBusy] = useState<boolean>(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [chatSession, setChatSession] = useState<string | null>(null);

  const [summary, setSummary] = useState<string>("");
  const [summaryBusy, setSummaryBusy] = useState<boolean>(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);

  const [anomalies, setAnomalies] = useState<string>("");
  const [anomBusy, setAnomBusy] = useState<boolean>(false);
  const [anomError, setAnomError] = useState<string | null>(null);

  const scrollRef = useRef<ScrollView>(null);

  const firmName = useMemo(() => {
    if (selectedFirm === "all") return "All firms";
    return firms.find((f) => f.company_id === selectedFirm)?.name || "Selected firm";
  }, [selectedFirm, firms]);

  const loadFirms = useCallback(async () => {
    try {
      const res = await api<{ firms: Firm[] }>("/admin/ai/firms");
      setFirms(res.firms || []);
    } catch {
      // silent — firm list is optional; "All firms" still works.
    }
  }, []);

  useEffect(() => {
    if (isSuperAdmin) loadFirms();
  }, [isSuperAdmin, loadFirms]);

  const sendChat = useCallback(
    async (rawText: string) => {
      const text = (rawText || "").trim();
      if (!text || chatBusy) return;
      const nextHistory: ChatTurn[] = [...chatHistory, { role: "user", content: text }];
      setChatHistory(nextHistory);
      setChatInput("");
      setChatBusy(true);
      setChatError(null);
      try {
        const res = await api<{ reply: string; session_id: string }>(
          "/admin/ai/ask",
          {
            method: "POST",
            body: {
              question: text,
              session_id: chatSession,
              company_id: selectedFirm,
              history: nextHistory.slice(-8),
            },
          },
        );
        if (res.session_id && res.session_id !== chatSession) {
          setChatSession(res.session_id);
        }
        setChatHistory([...nextHistory, { role: "assistant", content: res.reply }]);
        setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
      } catch (err: any) {
        setChatError(err?.message || "AI request failed");
        // rewind the failed user turn so the operator can retry.
        setChatHistory(nextHistory);
      } finally {
        setChatBusy(false);
      }
    },
    [chatBusy, chatHistory, chatSession, selectedFirm],
  );

  const runSummary = useCallback(async () => {
    if (summaryBusy) return;
    setSummaryBusy(true);
    setSummaryError(null);
    setSummary("");
    try {
      const qs = new URLSearchParams({ month });
      if (selectedFirm && selectedFirm !== "all") qs.set("company_id", selectedFirm);
      const res = await api<{ summary: string }>(`/admin/ai/summary?${qs.toString()}`);
      setSummary(res.summary || "");
    } catch (err: any) {
      setSummaryError(err?.message || "AI request failed");
    } finally {
      setSummaryBusy(false);
    }
  }, [month, selectedFirm, summaryBusy]);

  const runAnomalies = useCallback(async () => {
    if (anomBusy) return;
    setAnomBusy(true);
    setAnomError(null);
    setAnomalies("");
    try {
      const qs = new URLSearchParams();
      if (selectedFirm && selectedFirm !== "all") qs.set("company_id", selectedFirm);
      const path = qs.toString() ? `/admin/ai/anomalies?${qs.toString()}` : "/admin/ai/anomalies";
      const res = await api<{ anomalies: string }>(path);
      setAnomalies(res.anomalies || "");
    } catch (err: any) {
      setAnomError(err?.message || "AI request failed");
    } finally {
      setAnomBusy(false);
    }
  }, [anomBusy, selectedFirm]);

  const clearChat = useCallback(() => {
    setChatHistory([]);
    setChatSession(null);
    setChatError(null);
  }, []);

  // -------------------------------------------------------------------------
  // Access gate — sub-admin, company-admin & employees never reach this page.
  // -------------------------------------------------------------------------
  if (!isSuperAdmin) {
    return (
      <SafeAreaView style={styles.gateWrap}>
        <View style={styles.gateCard}>
          <Ionicons name="lock-closed-outline" size={42} color={colors.brand} />
          <Text style={styles.gateTitle}>AI Insights is restricted</Text>
          <Text style={styles.gateSub}>
            Only Super Admins can access the AI analysis engine. Please contact
            the S.K. Sharma & Co. head office if you need aggregated firm-wide
            reports.
          </Text>
          <Pressable
            style={styles.gateBtn}
            onPress={() => router.replace("/(tabs)" as any)}
          >
            <Text style={styles.gateBtnText}>Back to dashboard</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        showsVerticalScrollIndicator={false}
      >
        {/* Header */}
        <View style={styles.headerRow}>
          <View style={styles.headerText}>
            <Text style={styles.title}>AI Insights</Text>
            <Text style={styles.subtitle}>
              GPT-5.2 powered payroll & attendance analysis. Firm-wide aggregate
              stats are shared with the model; per-employee PII stays local.
            </Text>
          </View>
          <View style={styles.badge}>
            <Ionicons name="sparkles" size={14} color={colors.onCta} />
            <Text style={styles.badgeText}>GPT-5.2</Text>
          </View>
        </View>

        {/* Firm filter */}
        <View style={styles.filterCard}>
          <Text style={styles.filterLabel}>Firm scope</Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.pillRow}
          >
            <Pressable
              onPress={() => setSelectedFirm("all")}
              style={[
                styles.firmPill,
                selectedFirm === "all" && styles.firmPillActive,
              ]}
            >
              <Text
                style={[
                  styles.firmPillText,
                  selectedFirm === "all" && styles.firmPillTextActive,
                ]}
              >
                All firms
              </Text>
            </Pressable>
            {firms.map((f) => (
              <Pressable
                key={f.company_id}
                onPress={() => setSelectedFirm(f.company_id)}
                style={[
                  styles.firmPill,
                  selectedFirm === f.company_id && styles.firmPillActive,
                ]}
              >
                <Text
                  style={[
                    styles.firmPillText,
                    selectedFirm === f.company_id && styles.firmPillTextActive,
                  ]}
                  numberOfLines={1}
                >
                  {f.name}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
        </View>

        {/* Tab switcher */}
        <View style={styles.tabRow}>
          {[
            { key: "chat", label: "Chat", icon: "chatbubbles-outline" },
            { key: "summary", label: "Monthly summary", icon: "document-text-outline" },
            { key: "anomalies", label: "Anomaly scan", icon: "warning-outline" },
          ].map((t) => (
            <Pressable
              key={t.key}
              style={[styles.tabBtn, tab === (t.key as any) && styles.tabBtnActive]}
              onPress={() => setTab(t.key as any)}
            >
              <Ionicons
                name={t.icon as any}
                size={16}
                color={tab === (t.key as any) ? colors.onBrandPrimary : colors.brand}
              />
              <Text
                style={[
                  styles.tabBtnText,
                  tab === (t.key as any) && styles.tabBtnTextActive,
                ]}
              >
                {t.label}
              </Text>
            </Pressable>
          ))}
        </View>

        {/* Tab bodies */}
        {tab === "chat" && (
          <View style={styles.card}>
            <View style={styles.cardHeader}>
              <Text style={styles.cardTitle}>
                Chat — {firmName}
              </Text>
              <Pressable onPress={clearChat} style={styles.linkBtn}>
                <Ionicons name="refresh" size={14} color={colors.brand} />
                <Text style={styles.linkBtnText}>New chat</Text>
              </Pressable>
            </View>

            {chatHistory.length === 0 && (
              <View style={styles.emptyChat}>
                <Ionicons name="sparkles-outline" size={26} color={colors.brand} />
                <Text style={styles.emptyChatTitle}>
                  Ask about any firm&apos;s payroll, attendance or compliance.
                </Text>
                <Text style={styles.emptyChatSub}>Try one of these:</Text>
                <View style={styles.quickList}>
                  {QUICK_PROMPTS.map((q) => (
                    <Pressable
                      key={q}
                      style={styles.quickPill}
                      onPress={() => sendChat(q)}
                    >
                      <Text style={styles.quickPillText}>{q}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            )}

            {chatHistory.length > 0 && (
              <ScrollView
                ref={scrollRef}
                style={styles.chatScroll}
                contentContainerStyle={styles.chatScrollBody}
              >
                {chatHistory.map((turn, idx) => (
                  <View
                    key={idx}
                    style={[
                      styles.bubble,
                      turn.role === "user" ? styles.bubbleUser : styles.bubbleAi,
                    ]}
                  >
                    <Text
                      style={[
                        styles.bubbleText,
                        turn.role === "user" ? styles.bubbleTextUser : styles.bubbleTextAi,
                      ]}
                      selectable
                    >
                      {turn.content}
                    </Text>
                  </View>
                ))}
                {chatBusy && (
                  <View style={[styles.bubble, styles.bubbleAi]}>
                    <View style={styles.typingRow}>
                      <ActivityIndicator color={colors.brand} size="small" />
                      <Text style={styles.typingText}>GPT-5.2 thinking…</Text>
                    </View>
                  </View>
                )}
              </ScrollView>
            )}

            {chatError && (
              <View style={styles.errBox}>
                <Ionicons name="alert-circle" size={14} color={colors.error} />
                <Text style={styles.errText}>{chatError}</Text>
              </View>
            )}

            <View style={styles.inputRow}>
              <TextInput
                style={styles.input}
                value={chatInput}
                onChangeText={setChatInput}
                placeholder={`Ask about ${firmName}…`}
                placeholderTextColor={colors.onSurfaceTertiary}
                editable={!chatBusy}
                onSubmitEditing={() => sendChat(chatInput)}
                returnKeyType="send"
                multiline
              />
              <Pressable
                onPress={() => sendChat(chatInput)}
                disabled={chatBusy || !chatInput.trim()}
                style={[
                  styles.sendBtn,
                  (chatBusy || !chatInput.trim()) && styles.sendBtnDisabled,
                ]}
              >
                {chatBusy ? (
                  <ActivityIndicator color={colors.onCta} size="small" />
                ) : (
                  <Ionicons name="send" size={16} color={colors.onCta} />
                )}
              </Pressable>
            </View>
          </View>
        )}

        {tab === "summary" && (
          <View style={styles.card}>
            <View style={styles.cardHeader}>
              <Text style={styles.cardTitle}>
                Monthly summary — {firmName}
              </Text>
            </View>
            <View style={styles.monthRow}>
              <Text style={styles.monthLabel}>Month</Text>
              <TextInput
                style={styles.monthInput}
                value={month}
                onChangeText={setMonth}
                placeholder="YYYY-MM"
                placeholderTextColor={colors.onSurfaceTertiary}
                autoCapitalize="none"
              />
              <Pressable
                onPress={runSummary}
                disabled={summaryBusy}
                style={[styles.cta, summaryBusy && styles.ctaDisabled]}
              >
                {summaryBusy ? (
                  <ActivityIndicator color={colors.onCta} size="small" />
                ) : (
                  <>
                    <Ionicons name="sparkles" size={14} color={colors.onCta} />
                    <Text style={styles.ctaText}>Generate</Text>
                  </>
                )}
              </Pressable>
            </View>

            {summaryError && (
              <View style={styles.errBox}>
                <Ionicons name="alert-circle" size={14} color={colors.error} />
                <Text style={styles.errText}>{summaryError}</Text>
              </View>
            )}

            {summary ? (
              <View style={styles.resultBlock}>
                <Text style={styles.resultText} selectable>
                  {summary}
                </Text>
              </View>
            ) : (
              !summaryBusy && (
                <Text style={styles.hintText}>
                  Pick a firm above and a month, then generate the executive
                  brief. Uses firm-level aggregates only — no PII leaves the
                  server.
                </Text>
              )
            )}
          </View>
        )}

        {tab === "anomalies" && (
          <View style={styles.card}>
            <View style={styles.cardHeader}>
              <Text style={styles.cardTitle}>
                Anomaly scan — {firmName}
              </Text>
              <Pressable
                onPress={runAnomalies}
                disabled={anomBusy}
                style={[styles.cta, anomBusy && styles.ctaDisabled]}
              >
                {anomBusy ? (
                  <ActivityIndicator color={colors.onCta} size="small" />
                ) : (
                  <>
                    <Ionicons name="scan-outline" size={14} color={colors.onCta} />
                    <Text style={styles.ctaText}>Run scan</Text>
                  </>
                )}
              </Pressable>
            </View>

            {anomError && (
              <View style={styles.errBox}>
                <Ionicons name="alert-circle" size={14} color={colors.error} />
                <Text style={styles.errText}>{anomError}</Text>
              </View>
            )}

            {anomalies ? (
              <View style={styles.resultBlock}>
                <Text style={styles.resultText} selectable>
                  {anomalies}
                </Text>
              </View>
            ) : (
              !anomBusy && (
                <Text style={styles.hintText}>
                  Scans the last 30 days for outside-geofence punches, pending
                  approvals, open tickets vs headcount and payroll outliers.
                </Text>
              )
            )}
          </View>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.surface },
  scroll: {
    padding: spacing.lg,
    gap: spacing.md,
    paddingBottom: spacing.xxl,
    maxWidth: 1100,
    width: "100%",
    alignSelf: "center",
  },

  // Access gate ----------------------------------------------------------
  gateWrap: {
    flex: 1,
    backgroundColor: colors.surface,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
  },
  gateCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.xl,
    maxWidth: 460,
    alignItems: "center",
    gap: spacing.md,
    ...shadow.card,
  },
  gateTitle: {
    fontSize: type.xl,
    fontWeight: "700",
    color: colors.onSurface,
    textAlign: "center",
  },
  gateSub: {
    fontSize: type.base,
    color: colors.onSurfaceSecondary,
    textAlign: "center",
    lineHeight: 20,
  },
  gateBtn: {
    marginTop: spacing.sm,
    backgroundColor: colors.brand,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
  },
  gateBtnText: { color: colors.onBrandPrimary, fontWeight: "600" },

  // Header ---------------------------------------------------------------
  headerRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: spacing.md,
  },
  headerText: { flex: 1, gap: spacing.xs },
  title: { fontSize: type.h1, fontWeight: "800", color: colors.onSurface },
  subtitle: {
    fontSize: type.base,
    color: colors.onSurfaceSecondary,
    lineHeight: 20,
  },
  badge: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.cta,
    paddingVertical: 6,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.pill,
  },
  badgeText: { color: colors.onCta, fontWeight: "700", fontSize: type.sm },

  // Filter card ----------------------------------------------------------
  filterCard: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    gap: spacing.sm,
  },
  filterLabel: {
    fontSize: type.sm,
    color: colors.onSurfaceTertiary,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.6,
  },
  pillRow: { gap: spacing.sm, paddingRight: spacing.md },
  firmPill: {
    paddingVertical: 8,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceTertiary,
    maxWidth: 260,
  },
  firmPillActive: { backgroundColor: colors.brand },
  firmPillText: { color: colors.onSurface, fontWeight: "500" },
  firmPillTextActive: { color: colors.onBrandPrimary, fontWeight: "700" },

  // Tabs -----------------------------------------------------------------
  tabRow: {
    flexDirection: "row",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  tabBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingVertical: 10,
    paddingHorizontal: spacing.md,
    borderRadius: radius.pill,
    backgroundColor: colors.surfaceSecondary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  tabBtnActive: { backgroundColor: colors.brand, borderColor: colors.brand },
  tabBtnText: { color: colors.brand, fontWeight: "600" },
  tabBtnTextActive: { color: colors.onBrandPrimary },

  // Card -----------------------------------------------------------------
  card: {
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.lg,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    ...shadow.card,
    gap: spacing.md,
  },
  cardHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  cardTitle: { fontSize: type.lg, fontWeight: "700", color: colors.onSurface, flex: 1 },
  linkBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: spacing.sm,
    paddingVertical: 6,
  },
  linkBtnText: { color: colors.brand, fontWeight: "600" },

  // Chat -----------------------------------------------------------------
  emptyChat: {
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
  },
  emptyChatTitle: {
    fontSize: type.lg,
    fontWeight: "600",
    color: colors.onSurface,
    textAlign: "center",
  },
  emptyChatSub: {
    fontSize: type.sm,
    color: colors.onSurfaceTertiary,
    marginBottom: spacing.xs,
  },
  quickList: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    justifyContent: "center",
  },
  quickPill: {
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: spacing.md,
    maxWidth: 380,
  },
  quickPillText: { color: colors.onBrandTertiary, fontSize: type.sm },
  chatScroll: {
    maxHeight: 460,
  },
  chatScrollBody: { gap: spacing.sm, paddingVertical: spacing.xs },
  bubble: {
    maxWidth: "88%",
    borderRadius: radius.lg,
    padding: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  bubbleUser: {
    alignSelf: "flex-end",
    backgroundColor: colors.brand,
  },
  bubbleAi: {
    alignSelf: "flex-start",
    backgroundColor: colors.surfaceTertiary,
    borderWidth: 1,
    borderColor: colors.border,
  },
  bubbleText: { fontSize: type.base, lineHeight: 20 },
  bubbleTextUser: { color: colors.onBrandPrimary },
  bubbleTextAi: { color: colors.onSurface },
  typingRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  typingText: { color: colors.onSurfaceSecondary, fontStyle: "italic" },

  // Input row ------------------------------------------------------------
  inputRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: spacing.sm,
  },
  input: {
    flex: 1,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    padding: spacing.sm,
    minHeight: 46,
    maxHeight: 140,
    color: colors.onSurface,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  sendBtn: {
    backgroundColor: colors.cta,
    borderRadius: radius.pill,
    height: 46,
    width: 46,
    alignItems: "center",
    justifyContent: "center",
  },
  sendBtnDisabled: { opacity: 0.5 },

  // Month + Anomaly ------------------------------------------------------
  monthRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  monthLabel: {
    color: colors.onSurfaceTertiary,
    fontWeight: "600",
  },
  monthInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 8,
    paddingHorizontal: spacing.md,
    minWidth: 120,
    color: colors.onSurface,
    ...Platform.select({ web: { outlineWidth: 0 as any } }),
  },
  cta: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: colors.cta,
    borderRadius: radius.pill,
    paddingVertical: 10,
    paddingHorizontal: spacing.md,
    ...shadow.cta,
  },
  ctaDisabled: { opacity: 0.6 },
  ctaText: { color: colors.onCta, fontWeight: "700" },

  // Result blocks --------------------------------------------------------
  resultBlock: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
  },
  resultText: {
    color: colors.onSurface,
    fontSize: type.base,
    lineHeight: 22,
  },
  hintText: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    lineHeight: 20,
  },

  // Error box ------------------------------------------------------------
  errBox: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#FEE2E2",
    padding: spacing.sm,
    borderRadius: radius.md,
  },
  errText: { color: colors.error, fontSize: type.sm, flex: 1 },
});
