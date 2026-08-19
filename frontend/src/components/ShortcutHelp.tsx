/**
 * Iter 592 — Keyboard Shortcuts help overlay ("?" or the keyboard icon).
 * Searchable list of every registered shortcut, grouped by category.
 * Iter 619 (Phase 3) — click the ✎ next to any shortcut to record your own
 * key for it (saved on this device); "Reset to defaults" restores everything.
 */
import React, { useEffect, useState } from "react";
import { Modal, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import {
  applyOverride, comboOf, listShortcuts, resetOverrides, setCaptureMode,
} from "@/src/utils/shortcuts";

export default function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [, setTick] = useState(0); // re-render after remap/reset
  const [editing, setEditing] = useState<string | null>(null); // `${scope}|${defaultCombo}`
  const [err, setErr] = useState("");

  // Record the next key press while a row is in "set key" mode.
  useEffect(() => {
    if (!editing || Platform.OS !== "web" || typeof window === "undefined") return;
    setCaptureMode(true);
    const onKey = (e: KeyboardEvent) => {
      e.preventDefault();
      e.stopPropagation();
      const combo = comboOf(e);
      if (!combo) return; // modifier only — keep waiting
      if (combo === "escape") { setEditing(null); setErr(""); return; }
      const at = editing.indexOf("|");
      const msg = applyOverride(editing.slice(0, at), editing.slice(at + 1), combo);
      if (msg) { setErr(msg); return; }
      setEditing(null);
      setErr("");
      setTick((t) => t + 1);
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      setCaptureMode(false);
    };
  }, [editing]);

  const all = listShortcuts().filter((s) =>
    !q.trim()
    || s.label.toLowerCase().includes(q.toLowerCase())
    || s.combo.includes(q.toLowerCase()));
  const groups: Record<string, typeof all> = {};
  all.forEach((s) => {
    const g = s.category || "General";
    (groups[g] = groups[g] || []).push(s);
  });
  const fmt = (c: string) => c.split("+").map((p) =>
    p === "ctrl" ? "Ctrl" : p === "alt" ? "Alt" : p === "shift" ? "Shift" : p.toUpperCase(),
  ).join(" + ");
  return (
    <Modal visible={open} transparent animationType="fade" onRequestClose={onClose}>
      <Pressable style={st.backdrop} onPress={onClose}>
        <Pressable style={st.panel} onPress={() => {}}>
          <View style={st.head}>
            <Ionicons name="keypad-outline" size={16} color="#2563EB" />
            <Text style={st.title}>Keyboard Shortcuts</Text>
            <View style={{ flex: 1 }} />
            <Pressable onPress={onClose} hitSlop={8} testID="sh-close">
              <Ionicons name="close" size={20} color="#64748B" />
            </Pressable>
          </View>
          <TextInput style={st.search} value={q} onChangeText={setQ}
            placeholder="Search shortcuts…" placeholderTextColor="#94A3B8"
            testID="sh-search" />
          <ScrollView style={{ maxHeight: 420 }} contentContainerStyle={{ gap: 4, paddingBottom: 8 }}>
            {Object.entries(groups).map(([g, items]) => (
              <View key={g} style={{ gap: 2 }}>
                <Text style={st.group}>{g}</Text>
                {items.map((s) => {
                  const id = `${s.scope}|${s.defaultCombo}`;
                  const isEditing = editing === id;
                  const custom = s.combo !== s.defaultCombo;
                  return (
                    <View key={id} style={st.row}>
                      <View style={{ flex: 1 }}>
                        <Text style={st.label}>{s.label}</Text>
                        {custom ? (
                          <Text style={st.defHint}>default: {fmt(s.defaultCombo)}</Text>
                        ) : null}
                      </View>
                      <View style={[st.kbd, isEditing && st.kbdEditing, custom && !isEditing && st.kbdCustom]}>
                        <Text style={[st.kbdTxt, isEditing && st.kbdTxtEditing]}>
                          {isEditing ? "Press keys… (Esc)" : fmt(s.combo)}
                        </Text>
                      </View>
                      <Pressable
                        hitSlop={8}
                        testID={`sh-edit-${s.defaultCombo}`}
                        onPress={() => { setErr(""); setEditing(isEditing ? null : id); }}
                      >
                        <Ionicons name={isEditing ? "close-circle" : "pencil"} size={15}
                          color={isEditing ? "#DC2626" : "#94A3B8"} />
                      </Pressable>
                    </View>
                  );
                })}
              </View>
            ))}
            {all.length === 0 ? <Text style={st.empty}>No shortcuts match.</Text> : null}
          </ScrollView>
          {err ? <Text style={st.err}>{err}</Text> : null}
          <View style={st.footer}>
            <Text style={[st.hint, { flex: 1 }]}>
              Press ? anywhere to open this list. Click ✎ to set your own key.
              Tip: press g then d/e/a/p/r/b/m for quick navigation.
            </Text>
            <Pressable
              testID="sh-reset"
              onPress={() => { resetOverrides(); setEditing(null); setErr(""); setTick((t) => t + 1); }}
            >
              <Text style={st.reset}>Reset to defaults</Text>
            </Pressable>
          </View>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

const st = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", alignItems: "center", justifyContent: "center", padding: 20 },
  panel: { width: 520, maxWidth: "100%", backgroundColor: "#fff", borderRadius: 14, padding: 16, gap: 10 },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  title: { fontSize: 15, fontWeight: "800", color: "#0F172A" },
  search: {
    borderWidth: 1, borderColor: "#E2E8F0", borderRadius: 8, paddingHorizontal: 10,
    paddingVertical: 8, fontSize: 13, color: "#0F172A",
  },
  group: { fontSize: 11, fontWeight: "800", color: "#64748B", marginTop: 6, textTransform: "uppercase" },
  row: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: "#F1F5F9" },
  label: { fontSize: 13, color: "#0F172A" },
  defHint: { fontSize: 10.5, color: "#94A3B8", marginTop: 1 },
  kbd: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3, backgroundColor: "#F8FAFC" },
  kbdCustom: { borderColor: "#2563EB", backgroundColor: "#EFF6FF" },
  kbdEditing: { borderColor: "#D97706", backgroundColor: "#FFFBEB" },
  kbdTxt: { fontSize: 11.5, fontWeight: "800", color: "#334155" },
  kbdTxtEditing: { color: "#B45309" },
  empty: { fontSize: 12.5, color: "#94A3B8", textAlign: "center", marginTop: 12 },
  err: { fontSize: 11.5, color: "#DC2626", fontWeight: "700" },
  footer: { flexDirection: "row", alignItems: "center", gap: 10 },
  hint: { fontSize: 11, color: "#94A3B8" },
  reset: { fontSize: 11.5, fontWeight: "800", color: "#2563EB" },
});
