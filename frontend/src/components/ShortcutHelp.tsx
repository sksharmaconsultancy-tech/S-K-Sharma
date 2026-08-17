/**
 * Iter 592 — Keyboard Shortcuts help overlay ("?" or the keyboard icon).
 * Searchable list of every registered shortcut, grouped by category.
 */
import React, { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { listShortcuts } from "@/src/utils/shortcuts";

export default function ShortcutHelp({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [q, setQ] = useState("");
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
                {items.map((s) => (
                  <View key={s.combo} style={st.row}>
                    <Text style={st.label}>{s.label}</Text>
                    <View style={st.kbd}><Text style={st.kbdTxt}>{fmt(s.combo)}</Text></View>
                  </View>
                ))}
              </View>
            ))}
            {all.length === 0 ? <Text style={st.empty}>No shortcuts match.</Text> : null}
          </ScrollView>
          <Text style={st.hint}>Press ? anywhere to open this list. Shortcuts never fire while you are typing.</Text>
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
  row: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: "#F1F5F9" },
  label: { fontSize: 13, color: "#0F172A", flex: 1 },
  kbd: { borderWidth: 1, borderColor: "#CBD5E1", borderRadius: 6, paddingHorizontal: 8, paddingVertical: 3, backgroundColor: "#F8FAFC" },
  kbdTxt: { fontSize: 11.5, fontWeight: "800", color: "#334155" },
  empty: { fontSize: 12.5, color: "#94A3B8", textAlign: "center", marginTop: 12 },
  hint: { fontSize: 11, color: "#94A3B8" },
});
