/**
 * Iter 163 — Generic ONE-TIME format editor for regular PDF reports
 * (Utilities → PDF Report Formats, SUPER ADMIN only).
 *
 * Works for any report registered in backend routes/report_formats.py:
 *  - tabular reports (PF ECR, ESIC Contribution) → column picker with
 *    order / rename / width + title / orientation / font size;
 *  - fixed statutory reports (PF Challan, ESIC Challan) → title /
 *    orientation / font size only.
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

type Props = {
  visible: boolean;
  onClose: () => void;
  reportId: string;
  reportLabel: string;
  onSaved?: () => void;
};

export default function ReportFormatEditor({ visible, onClose, reportId, reportLabel, onSaved }: Props) {
  const [cols, setCols] = useState<Col[] | null>(null); // null = fixed-format report
  const [title, setTitle] = useState("");
  const [defTitle, setDefTitle] = useState("");
  const [orientation, setOrientation] = useState<"portrait" | "landscape">("portrait");
  const [fontSize, setFontSize] = useState("");
  const [defFont, setDefFont] = useState(0);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!visible) return;
    setLoading(true); setMsg("");
    (async () => {
      try {
        const r = await api<any>(`/admin/report-formats/${reportId}`);
        const fmt = r.format || {};
        const defs = r.defaults || {};
        setDefTitle(defs.title || "");
        setTitle(fmt.title || defs.title || "");
        setOrientation(fmt.orientation || defs.orientation || "portrait");
        setDefFont(Number(defs.font_size) || 0);
        setFontSize(String(fmt.font_size ?? defs.font_size ?? ""));
        if (r.catalog) {
          const saved: any[] = fmt.columns || [];
          const savedKeys = saved.map((c) => c.key);
          const ordered = [
            ...savedKeys.map((k: string) => r.catalog.find((c: any) => c.key === k)).filter(Boolean),
            ...r.catalog.filter((c: any) => !savedKeys.includes(c.key)),
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
        } else {
          setCols(null);
        }
      } catch (e: any) { setMsg(e?.message || "Failed to load"); }
      finally { setLoading(false); }
    })();
  }, [visible, reportId]);

  const move = (i: number, dir: -1 | 1) => {
    if (!cols) return;
    const j = i + dir;
    if (j < 0 || j >= cols.length) return;
    const next = [...cols];
    [next[i], next[j]] = [next[j], next[i]];
    setCols(next);
  };

  const save = async () => {
    const body: any = {
      orientation,
      font_size: Number(fontSize) > 0 ? Number(fontSize) : undefined,
      title: title.trim() || undefined,
    };
    if (cols) {
      const chosen = cols.filter((c) => c.include);
      if (!chosen.length) { setMsg("Select at least one column"); return; }
      body.columns = chosen.map((c) => ({
        key: c.key, heading: c.heading.trim() || undefined,
        width: Number(c.width) > 0 ? Number(c.width) : undefined,
      }));
    }
    setSaving(true); setMsg("");
    try {
      await api(`/admin/report-formats/${reportId}`, { method: "PUT", body });
      setMsg("Saved ✓ — every future download of this report uses this format.");
      onSaved?.();
    } catch (e: any) { setMsg(e?.message || "Save failed"); }
    finally { setSaving(false); }
  };

  const reset = async () => {
    setSaving(true); setMsg("");
    try {
      await api(`/admin/report-formats/${reportId}`, { method: "DELETE" });
      if (cols) setCols(cols.map((c) => ({ ...c, include: true, heading: c.defHeading, width: String(c.defWidth) })));
      setTitle(defTitle);
      setFontSize(defFont ? String(defFont) : "");
      setMsg("Reset to default format ✓");
      onSaved?.();
    } catch (e: any) { setMsg(e?.message || "Reset failed"); }
    finally { setSaving(false); }
  };

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.backdrop}>
        <View style={styles.sheet}>
          <View style={styles.head}>
            <Text style={styles.title} numberOfLines={2}>{reportLabel} — format (one-time setting)</Text>
            <Pressable onPress={onClose} testID="rfe-close"><Ionicons name="close" size={22} color={colors.onSurface} /></Pressable>
          </View>
          {loading ? <ActivityIndicator style={{ marginVertical: 30 }} color={colors.brandPrimary} /> : (
            <ScrollView style={{ maxHeight: Platform.OS === "web" ? 480 : 420 }}>
              {/* -------- general options -------- */}
              <Text style={styles.h}>Report main heading (title)</Text>
              <TextInput value={title} onChangeText={setTitle} style={styles.input}
                placeholder={defTitle} placeholderTextColor={colors.onSurfaceTertiary} testID="rfe-title" />
              <View style={{ flexDirection: "row", gap: 16, marginTop: 10 }}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.h}>Page orientation</Text>
                  <View style={{ flexDirection: "row", gap: 8, marginTop: 4 }}>
                    {(["portrait", "landscape"] as const).map((o) => (
                      <Pressable key={o} onPress={() => setOrientation(o)}
                        style={[styles.seg, orientation === o && styles.segOn]} testID={`rfe-orient-${o}`}>
                        <Ionicons name={o === "portrait" ? "phone-portrait-outline" : "phone-landscape-outline"}
                          size={14} color={orientation === o ? "#fff" : colors.onSurfaceSecondary} />
                        <Text style={[styles.segTxt, orientation === o && { color: "#fff" }]}>
                          {o === "portrait" ? "Portrait" : "Landscape"}
                        </Text>
                      </Pressable>
                    ))}
                  </View>
                </View>
                <View style={{ width: 110 }}>
                  <Text style={styles.h}>Font size (pt)</Text>
                  <TextInput value={fontSize}
                    onChangeText={(v) => setFontSize(v.replace(/[^0-9.]/g, ""))}
                    keyboardType="numeric" style={[styles.input, { textAlign: "center" }]}
                    placeholder={defFont ? String(defFont) : ""} placeholderTextColor={colors.onSurfaceTertiary}
                    testID="rfe-font" />
                </View>
              </View>

              {/* -------- columns (tabular reports only) -------- */}
              {cols ? (
                <>
                  <View style={[styles.row, { marginTop: 14 }]}>
                    <Text style={[styles.h, { width: 30 }]}>✓</Text>
                    <Text style={[styles.h, { flex: 2 }]}>Heading (rename)</Text>
                    <Text style={[styles.h, { width: 64 }]}>Width</Text>
                    <Text style={[styles.h, { width: 70 }]}>Order</Text>
                  </View>
                  {cols.map((c, i) => (
                    <View key={c.key} style={[styles.row, !c.include && { opacity: 0.45 }]}>
                      <Pressable
                        onPress={() => setCols(cols.map((x, j) => j === i ? { ...x, include: !x.include } : x))}
                        style={{ width: 30 }} testID={`rfe-inc-${c.key}`}
                      >
                        <Ionicons name={c.include ? "checkbox" : "square-outline"} size={19}
                          color={c.include ? colors.brandPrimary : colors.onSurfaceTertiary} />
                      </Pressable>
                      <View style={{ flex: 2 }}>
                        <TextInput
                          value={c.heading}
                          onChangeText={(v) => setCols(cols.map((x, j) => j === i ? { ...x, heading: v } : x))}
                          style={styles.input} testID={`rfe-h-${c.key}`}
                        />
                        <Text style={styles.sub}>{c.defHeading}</Text>
                      </View>
                      <TextInput
                        value={c.width}
                        onChangeText={(v) => setCols(cols.map((x, j) => j === i ? { ...x, width: v.replace(/[^0-9.]/g, "") } : x))}
                        keyboardType="numeric"
                        style={[styles.input, { width: 56, textAlign: "center" }]}
                        testID={`rfe-w-${c.key}`}
                      />
                      <View style={{ width: 70, flexDirection: "row", gap: 6, justifyContent: "center" }}>
                        <Pressable onPress={() => move(i, -1)} style={styles.arrow}><Ionicons name="arrow-up" size={15} color={colors.onSurface} /></Pressable>
                        <Pressable onPress={() => move(i, 1)} style={styles.arrow}><Ionicons name="arrow-down" size={15} color={colors.onSurface} /></Pressable>
                      </View>
                    </View>
                  ))}
                  <Text style={styles.sub}>
                    Widths are proportions — the table always stretches to the full printable page width.
                  </Text>
                </>
              ) : (
                <Text style={[styles.sub, { marginTop: 12 }]}>
                  This is a fixed statutory layout — the table structure cannot be
                  changed, but the title, orientation and font size above are applied.
                </Text>
              )}
            </ScrollView>
          )}
          {msg ? <Text style={styles.msg}>{msg}</Text> : null}
          <View style={{ flexDirection: "row", gap: 10, marginTop: 12 }}>
            <Pressable onPress={save} disabled={saving || loading} style={[styles.btn, (saving || loading) && { opacity: 0.6 }]} testID="rfe-save">
              {saving ? <ActivityIndicator size="small" color="#fff" /> : <Text style={styles.btnTxt}>Save Format</Text>}
            </Pressable>
            <Pressable onPress={reset} disabled={saving || loading} style={[styles.btn, { backgroundColor: "#64748B" }]} testID="rfe-reset">
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
  head: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 10, gap: 10 },
  title: { fontSize: 15, fontWeight: "800", color: colors.onSurface, flex: 1 },
  row: { flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 5, borderBottomWidth: 1, borderBottomColor: colors.border },
  h: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary },
  sub: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 2 },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.sm,
    paddingHorizontal: 8, paddingVertical: 6, fontSize: 12, color: colors.onSurface,
    backgroundColor: colors.surfaceSecondary, marginTop: 4,
  },
  seg: {
    flexDirection: "row", alignItems: "center", gap: 5,
    paddingHorizontal: 10, paddingVertical: 7, borderRadius: radius.sm,
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surfaceSecondary,
  },
  segOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  segTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  arrow: { padding: 6, borderWidth: 1, borderColor: colors.border, borderRadius: 6 },
  msg: { marginTop: 8, fontSize: 12, fontWeight: "600", color: colors.brandPrimary },
  btn: {
    backgroundColor: colors.brandPrimary, paddingHorizontal: 16, paddingVertical: 10,
    borderRadius: radius.sm, alignItems: "center",
  },
  btnTxt: { color: "#fff", fontSize: 13, fontWeight: "700" },
});
