/**
 * Iter 294 — AI Payroll Assistant (chat + voice commands).
 *
 * Floating button (bottom-right of the admin shell) opens a chat panel.
 * Commands are parsed server-side (POST /admin/ai-assistant/command) into
 * intents; sensitive actions (payroll runs) come back as CONFIRM buttons —
 * nothing executes without an explicit click. Voice input uses the
 * browser's SpeechRecognition (Chrome / Edge; en-IN + hi-IN).
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ScrollView,
  ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { useT, useLang } from "@/src/i18n";

type Action =
  | { type: "navigate"; route: string; label?: string }
  | { type: "confirm_api"; method: string; endpoint: string; body: any; label: string; navigate_after?: string };

type Msg = { who: "user" | "assistant"; text: string; action?: Action | null; done?: boolean };

const SUGGESTIONS = [
  "Process July payroll",
  "Who is present today?",
  "Pending approvals",
  "Open attendance report",
];

export default function AiAssistant({
  open, onToggle,
}: { open: boolean; onToggle: (v: boolean) => void }) {
  const router = useRouter();
  const { selectedCompanyId } = useSelectedCompany();
  const tr = useT();
  const lang = useLang();
  const [input, setInput] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [voiceSupported, setVoiceSupported] = useState(false);
  const recRef = useRef<any>(null);
  const scrollRef = useRef<ScrollView | null>(null);

  useEffect(() => {
    if (Platform.OS === "web") {
      const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
      setVoiceSupported(!!SR);
    }
  }, []);

  const send = async (text: string) => {
    const cmd = text.trim();
    if (!cmd || busy) return;
    setInput("");
    setMsgs((m) => [...m, { who: "user", text: cmd }]);
    setBusy(true);
    try {
      const r = await api<{ reply: string; action: Action | null }>(
        "/admin/ai-assistant/command",
        { method: "POST", body: { text: cmd, company_id: selectedCompanyId || null } },
      );
      setMsgs((m) => [...m, { who: "assistant", text: r.reply, action: r.action }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { who: "assistant", text: e?.message || "Something went wrong. Try again." }]);
    } finally {
      setBusy(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
    }
  };

  const runAction = async (a: Action, idx: number) => {
    if (a.type === "navigate") {
      onToggle(false);
      router.push(a.route as any);
      return;
    }
    // confirm_api — execute the prepared call
    setBusy(true);
    try {
      await api(a.endpoint, { method: a.method as any, body: a.body });
      setMsgs((m) => m.map((msg, i) => (i === idx ? { ...msg, done: true } : msg)));
      setMsgs((m) => [...m, {
        who: "assistant",
        text: "✅ Done! Payroll processed successfully.",
        action: a.navigate_after
          ? { type: "navigate", route: a.navigate_after, label: "View Result" }
          : null,
      }]);
    } catch (e: any) {
      setMsgs((m) => [...m, { who: "assistant", text: `❌ ${e?.message || "Action failed."}` }]);
    } finally {
      setBusy(false);
      setTimeout(() => scrollRef.current?.scrollToEnd({ animated: true }), 80);
    }
  };

  const toggleVoice = () => {
    if (Platform.OS !== "web") return;
    if (listening) {
      recRef.current?.stop();
      setListening(false);
      return;
    }
    const SR = (window as any).webkitSpeechRecognition || (window as any).SpeechRecognition;
    if (!SR) return;
    const rec = new SR();
    rec.lang = lang === "hi" ? "hi-IN" : "en-IN";
    rec.interimResults = true;
    rec.continuous = false;
    rec.onresult = (ev: any) => {
      let final = "";
      let interim = "";
      for (let i = 0; i < ev.results.length; i++) {
        if (ev.results[i].isFinal) final += ev.results[i][0].transcript;
        else interim += ev.results[i][0].transcript;
      }
      setInput(final || interim);
      if (final) {
        setListening(false);
        send(final);
      }
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec;
    setListening(true);
    rec.start();
  };

  if (!open) {
    return (
      <Pressable onPress={() => onToggle(true)} style={styles.fab} testID="ai-assistant-fab">
        <Ionicons name="sparkles" size={22} color="#fff" />
      </Pressable>
    );
  }

  return (
    <View style={styles.panel} testID="ai-assistant-panel">
      <View style={styles.head}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
          <View style={styles.headIcon}><Ionicons name="sparkles" size={14} color="#fff" /></View>
          <Text style={styles.headTitle}>{tr("AI Assistant")}</Text>
        </View>
        <Pressable onPress={() => onToggle(false)} hitSlop={8} testID="ai-assistant-close">
          <Ionicons name="close" size={20} color="#94A3B8" />
        </Pressable>
      </View>

      <ScrollView ref={scrollRef} style={styles.body} contentContainerStyle={{ padding: 12, gap: 8 }}>
        {msgs.length === 0 ? (
          <View style={{ gap: 8 }}>
            <Text style={styles.hint}>
              Try a command — type or press the mic:
            </Text>
            {SUGGESTIONS.map((s) => (
              <Pressable key={s} onPress={() => send(s)} style={styles.sugg} testID={`ai-sugg-${s.slice(0, 10)}`}>
                <Ionicons name="flash-outline" size={13} color="#2563EB" />
                <Text style={styles.suggTxt}>{s}</Text>
              </Pressable>
            ))}
          </View>
        ) : null}
        {msgs.map((m, i) => (
          <View key={i} style={[styles.bubble, m.who === "user" ? styles.bubbleUser : styles.bubbleAi]}>
            <Text style={m.who === "user" ? styles.bubbleUserTxt : styles.bubbleAiTxt}>
              {m.text.replace(/\*\*/g, "")}
            </Text>
            {m.action && !m.done ? (
              <Pressable
                onPress={() => runAction(m.action!, i)}
                style={[styles.actionBtn,
                  m.action.type === "confirm_api" && { backgroundColor: "#22C55E" }]}
                testID={`ai-action-${i}`}
              >
                <Ionicons
                  name={m.action.type === "confirm_api" ? "checkmark-circle" : "open-outline"}
                  size={14} color="#fff" />
                <Text style={styles.actionBtnTxt}>
                  {m.action.type === "confirm_api"
                    ? `Confirm: ${(m.action as any).label}`
                    : (m.action as any).label || "Open"}
                </Text>
              </Pressable>
            ) : null}
          </View>
        ))}
        {busy ? <ActivityIndicator size="small" color="#2563EB" style={{ marginTop: 4 }} /> : null}
      </ScrollView>

      <View style={styles.inputRow}>
        {voiceSupported ? (
          <Pressable
            onPress={toggleVoice}
            style={[styles.micBtn, listening && styles.micBtnActive]}
            testID="ai-voice-btn"
          >
            <Ionicons name={listening ? "mic" : "mic-outline"} size={18}
              color={listening ? "#fff" : "#2563EB"} />
          </Pressable>
        ) : null}
        <TextInput
          style={styles.input}
          placeholder={listening ? "Listening…" : tr("Ask AI — e.g. \"Process July payroll\"")}
          placeholderTextColor="#94A3B8"
          value={input}
          onChangeText={setInput}
          onSubmitEditing={() => send(input)}
          testID="ai-input"
        />
        <Pressable onPress={() => send(input)} style={styles.sendBtn} testID="ai-send">
          <Ionicons name="send" size={16} color="#fff" />
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  fab: {
    position: "absolute", right: 24, bottom: 24, width: 52, height: 52,
    borderRadius: 26, backgroundColor: "#2563EB", alignItems: "center",
    justifyContent: "center", zIndex: 9000,
    shadowColor: "#0F172A", shadowOpacity: 0.3, shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
  },
  panel: {
    position: "absolute", right: 24, bottom: 24, width: 380, height: 520,
    backgroundColor: "#FFFFFF", borderRadius: 16, zIndex: 9000,
    borderWidth: 1, borderColor: "#E2E8F0", overflow: "hidden",
    shadowColor: "#0F172A", shadowOpacity: 0.25, shadowRadius: 24,
    shadowOffset: { width: 0, height: 12 },
  },
  head: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: 14, paddingVertical: 12, backgroundColor: "#0F172A",
  },
  headIcon: {
    width: 24, height: 24, borderRadius: 12, backgroundColor: "#2563EB",
    alignItems: "center", justifyContent: "center",
  },
  headTitle: { color: "#fff", fontWeight: "800", fontSize: 14 },
  body: { flex: 1, backgroundColor: "#F8FAFC" },
  hint: { fontSize: 12, color: "#64748B", marginBottom: 2 },
  sugg: {
    flexDirection: "row", alignItems: "center", gap: 8,
    backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#DBEAFE",
    borderRadius: 10, paddingHorizontal: 12, paddingVertical: 9,
  },
  suggTxt: { fontSize: 12.5, color: "#1F2937", fontWeight: "600" },
  bubble: { maxWidth: "88%", borderRadius: 12, padding: 10 },
  bubbleUser: { alignSelf: "flex-end", backgroundColor: "#2563EB" },
  bubbleAi: { alignSelf: "flex-start", backgroundColor: "#FFFFFF", borderWidth: 1, borderColor: "#E2E8F0" },
  bubbleUserTxt: { color: "#fff", fontSize: 13 },
  bubbleAiTxt: { color: "#1F2937", fontSize: 13, lineHeight: 19 },
  actionBtn: {
    flexDirection: "row", alignItems: "center", gap: 6, marginTop: 8,
    backgroundColor: "#2563EB", borderRadius: 8, paddingHorizontal: 12,
    paddingVertical: 8, alignSelf: "flex-start",
  },
  actionBtnTxt: { color: "#fff", fontSize: 12, fontWeight: "700" },
  inputRow: {
    flexDirection: "row", alignItems: "center", gap: 8, padding: 10,
    borderTopWidth: 1, borderTopColor: "#E2E8F0", backgroundColor: "#FFFFFF",
  },
  micBtn: {
    width: 36, height: 36, borderRadius: 18, alignItems: "center",
    justifyContent: "center", borderWidth: 1, borderColor: "#BFDBFE",
    backgroundColor: "#EFF6FF",
  },
  micBtnActive: { backgroundColor: "#EF4444", borderColor: "#EF4444" },
  input: {
    flex: 1, height: 36, fontSize: 13, color: "#1F2937",
    ...(Platform.OS === "web" ? ({ outlineStyle: "none" } as any) : null),
  },
  sendBtn: {
    width: 36, height: 36, borderRadius: 18, backgroundColor: "#2563EB",
    alignItems: "center", justifyContent: "center",
  },
});
