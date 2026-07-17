/**
 * Iter 162 — ONE-TIME layout editor for the Compliance Salary Register
 * PDF (Option 2): choose columns, order, rename headings, set column
 * widths, rows-per-page and row height. Saved globally; every download
 * applies it automatically.
 */
import React, { useEffect, useState } from "react";
import {
  Modal, View, Text, StyleSheet, ScrollView, Pressable,
  TextInput, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type Col = { key: string; heading: string; width: string; include: boolean; defHeading: string; defWidth: number };

export default function RegisterLayoutEditor({ visible, onClose }: { visible: boolean; onClose: () => void }) {
  const [cols, setCols] = useState<Col[]>([]);
  const [perPage, setPerPage] = useState("10");
  const [rowHeight, setRowHeight] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!visible) return;
    setLoading(true); setMsg("");
    (async () => {
      try {
        const r = await api<any>("/admin/compliance-register-layout");
        const saved: any[] = r.layout?.columns || [];
        const savedKeys = saved.map((c) => c.key);
        const catalog: any[] = r.catalog || [];
        const ordered = [
          ...savedKeys.map((k) => catalog.find((c) => c.key === k)).filter(Boolean),
          ...catalog.filter((c) => !savedKeys.includes(c.key)),
        ];
        setCols(ordered.map((c: any) => {
          const s = saved.find((x) => x.key === c.key);
          return {
            key: c.key, defHeading: c.heading, defWidth: c.width,
            heading: s?.heading || c.heading,
            width: String(s?.width ?? c.width),
            include: saved.length === 0 ? true : !!s,
          };
        }));
        setPerPage(String(r.layout?.per_page ?? 10));
        setRowHeight(r.layout?.row_height ? String(r.layout.row_height) : "");
      } catch { /* keep empty */ }
      finally { setLoading(false); }
    })();
  }, [visible]);

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= cols.length) return;
    const next = [...cols];
    [next[i], next[j]] = [next[j], next[i]];
    setCols(next);
  };

  const save = async () => {
    const chosen = cols.filter((c) => c.include);
    if (!chosen.length) { setMsg("Select at least one column"); return; }
    setSaving(true); setMsg("");
    try {
      await api("/admin/compliance-register-layout", {
        method: "PUT",
        body: {
          columns: chosen.map((c) => ({
            key: c.key, heading: c.heading.trim() || undefined,
            width: Number(c.width) > 0 ? Number(c.width) : undefined,
          })),
          per_page: Number(perPage) || 10,
          row_height: Number(rowHeight) > 0 ? Number(rowHeight) : undefined,
        },
      });
      setMsg("Saved ✓ — every 'PDF (Option 2)' download now uses this layout.");
    } catch (e: any) { setMsg(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const reset = async () => {
    setSaving(true); setMsg("");
    try {
      await api("/admin/compliance-register-layout", { method: "DELETE" });
      setCols(cols.map((c) => ({ ...c, include: true, heading: c.defHeading, width: String(c.defWidth) })));
      setPerPage("10"); setRowHeight("");
      setMsg("Reset to default layout ✓");
    } catch (e: any) { setMsg(e?.message || "Reset failed"); }
    finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.head}>
            <Text style={styles.title}>Register PDF Layout (one-time setting)</Text>
            <Pressable onPress={onClose} testID="rle-close"><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
          </View>
          {loading ? <ActivityIndicator style={{ marginVertical: 30 }} color={colors.brandPrimary} /> : (
            <ScrollView style={{ maxHeight: Platform.OS === "web" ? 480 : 420 }}>
              <View style={styles.row}>
                <Text style={[styles.h, { width: 30 }]}>✓</Text>
                <Text style={[styles.h, { flex: 2 }]}>Heading (rename)</Text>
                <Text style={[styles.h, { width: 64 }]}>Width</Text>
                <Text style={[styles.h, { width: 70 }]}>Order</Text>
              </View>
              {cols.map((c, i) => (
                <View key={c.key} style={[styles.row, !c.include && { opacity: 0.45 }]}>
                  <Pressable
                    onPress={() => setCols(cols.map((x, j) => j === i ? { ...x, include: !x.include } : x))}
                    style={{ width: 30 }} testID={`rle-inc-${c.key}`}
                  >
                    <Ionicons name={c.include ? "checkbox" : "square-outline"} size={19}
                      color={c.include ? colors.brandPrimary : colors.onSurfaceTertiary} />
                  </Pressable>
                  <View style={{ flex: 2 }}>
                    <TextInput
                      value={c.heading}
                      onChangeText={(v) => setCols(cols.map((x, j) => j === i ? { ...x, heading: v } : x))}
                      style={styles.input} testID={`rle-h-${c.key}`}
                    />
                    <Text style={styles.sub}>{c.defHeading}</Text>
                  </View>
                  <TextInput
                    value={c.width}
                    onChangeText={(v) => setCols(cols.map((x, j) => j === i ? { ...x, width: v.replace(/[^0-9.]/g, "") } : x))}
                    keyboardType="numeric"
                    style={[styles.input, { width: 56, textAlign: "center" }]}
                    testID={`rle-w-${c.key}`}
                  />
                  <View style={{ width: 70, flexDirection: "row", gap: 6, justifyContent: "center" }}>
                    <Pressable onPress={() => move(i, -1)} style={styles.arrow}><Ionicons name="arrow-up" size={15} color={colors.onSurface} /></Pressable>
                    <Pressable onPress={() => move(i, 1)} style={styles.arrow}><Ionicons name="arrow-down" size={15} color={colors.onSurface} /></Pressable>
                  </View>
                </View>
              ))}
              <View style={[styles.row, { marginTop: 8 }]}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.h}>Employees per page (height of table)</Text>
                  <TextInput value={perPage} onChangeText={(v) => setPerPage(v.replace(/\D/g, ""))}
                    keyboardType="numeric" style={[styles.input, { width: 80 }]} testID="rle-perpage" />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.h}>Row height in mm (blank = auto)</Text>
                  <TextInput value={rowHeight} onChangeText={(v) => setRowHeight(v.replace(/[^0-9.]/g, ""))}
                    keyboardType="numeric" style={[styles.input, { width: 80 }]} testID="rle-rowh" />
                </View>
              </View>
              <Text style={styles.sub}>
                Widths are proportions — the table always stretches to the full A4-landscape width.
              </Text>
            </ScrollView>
          )}
          {msg ? <Text style={styles.msg}>{msg}</Text> : null}
          <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
            <Pressable onPress={save} disabled={saving} style={[styles.btn, saving && { opacity: 0.6 }]} testID="rle-save">
              {saving ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.btnTxt}>Save Layout</Text>}
            </Pressable>
            <Pressable onPress={reset} disabled={saving} style={[styles.btn, { backgroundColor: "#64748B" }]} testID="rle-reset">
              <Text style={styles.btnTxt}>Reset to Default</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: "rgba(15,23,42,0.5)", justifyContent: "center", alignItems: "center", padding: 16 },
  sheet: {
    width: "100%", maxWidth: 640, backgroundColor: colors.surface,
    borderRadius: radius.md, padding: 16,
  },
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 10 },
  title: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  row: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: colors.border },
  h: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  sub: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 2 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 6, fontSize: 12, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary,
  },
  arrow: { padding: 6, borderWidth: 1, borderColor: colors.border, borderRadius: 6 },
  msg: { marginTop: 8, fontSize: 12, fontWeight: "600", color: colors.brandPrimary },
  btn: {
    backgroundColor: colors.brandPrimary, paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.sm, alignItems: "center",
  },
  btnTxt: { color: "#fff", fontSize: 13, fontWeight: "700" },
});
