// Iter 172 — Bulk Punch Import via Excel (Punch Approvals screen).
// Flow: pick .xlsx → /admin/punch-import/preview (match by Bio Code or
// Name) → review matched/unmatched rows → /commit inserts approved
// In/Out punches straight into the punching report.
import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  Modal,
  ScrollView,
  ActivityIndicator,
  Platform,
  Alert,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as DocumentPicker from "expo-document-picker";

import { api } from "@/src/api/client";
import { colors, radius, type } from "@/src/theme";

type Row = {
  row_no: number;
  bio_code?: string;
  name?: string;
  date?: string | null;
  in_time?: string | null;
  out_time?: string | null;
  status: "matched" | "unmatched" | "error";
  matched_by?: string;
  user_id?: string;
  emp_name?: string;
  error?: string;
};

type Preview = {
  rows: Row[];
  columns?: {
    headers: string[];
    found: Record<string, boolean>;
    ot_detected: boolean;
  };
  summary: {
    total: number;
    matched: number;
    unmatched: number;
    errors: number;
    punches_to_create: number;
  };
};

type Props = {
  visible: boolean;
  companyId: string | null;
  onClose: () => void;
  onImported?: () => void;
};

const fmtDMY = (iso?: string | null) => {
  if (!iso || iso.length < 10) return "—";
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
};

export default function PunchImportModal({ visible, companyId, onClose, onImported }: Props) {
  const [busy, setBusy] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [result, setResult] = useState<{ created: number; skipped_duplicates: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setFileName(null);
    setPreview(null);
    setResult(null);
    setError(null);
    setBusy(false);
  };
  const close = () => {
    reset();
    onClose();
  };

  const fileToBase64 = async (uri: string): Promise<string> => {
    const res = await fetch(uri);
    const blob = await res.blob();
    return await new Promise<string>((resolve, reject) => {
      const fr = new FileReader();
      fr.onload = () => {
        const s = String(fr.result || "");
        resolve(s.includes(",") ? s.split(",")[1] : s);
      };
      fr.onerror = reject;
      fr.readAsDataURL(blob);
    });
  };

  const downloadTemplate = async () => {
    try {
      const r = await api<{ filename: string; file_base64: string }>("/admin/punch-import/template");
      if (Platform.OS === "web") {
        const bytes = atob(r.file_base64);
        const arr = new Uint8Array(bytes.length);
        for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
        const blob = new Blob([arr], {
          type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = r.filename;
        a.click();
        URL.revokeObjectURL(url);
      } else {
        Alert.alert(
          "Template format",
          "Columns needed: Bio Code, Name, Date (DD-MM-YYYY), In Time (HH:MM), Out Time (HH:MM). Either Bio Code or Name is enough to match.",
        );
      }
    } catch (e: any) {
      setError(e?.message || "Could not download the template");
    }
  };

  const pickFile = async () => {
    if (!companyId) {
      setError("Select a firm first (top of screen), then import.");
      return;
    }
    const res = await DocumentPicker.getDocumentAsync({
      type: [
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      ],
      copyToCacheDirectory: true,
    });
    if (res.canceled || !res.assets?.length) return;
    const asset = res.assets[0];
    setBusy(true);
    setError(null);
    setResult(null);
    setPreview(null);
    try {
      const b64 = await fileToBase64(asset.uri);
      const p = await api<Preview>("/admin/punch-import/preview", {
        method: "POST",
        body: { company_id: companyId, file_base64: b64 },
      });
      setFileName(asset.name);
      setPreview(p);
    } catch (e: any) {
      setError(e?.message || "Could not read the Excel file");
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!preview || !companyId) return;
    const matched = preview.rows.filter((r) => r.status === "matched");
    if (!matched.length) return;
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ created: number; skipped_duplicates: number }>(
        "/admin/punch-import/commit",
        { method: "POST", body: { company_id: companyId, rows: matched } },
      );
      setResult(r);
      setPreview(null);
      onImported?.();
    } catch (e: any) {
      setError(e?.message || "Import failed");
    } finally {
      setBusy(false);
    }
  };

  const s = preview?.summary;

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={close}>
      <View style={st.overlay}>
        <View style={st.card}>
          <View style={st.head}>
            <Ionicons name="cloud-upload-outline" size={18} color={colors.brandPrimary} />
            <Text style={st.title}>Import Punches from Excel</Text>
            <Pressable onPress={close} hitSlop={10} testID="pimp-close">
              <Ionicons name="close" size={20} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>

          {result ? (
            <View style={st.doneBox}>
              <Ionicons name="checkmark-circle" size={40} color="#16A34A" />
              <Text style={st.doneTitle}>Import complete</Text>
              <Text style={st.doneTxt}>
                {result.created} punch{result.created === 1 ? "" : "es"} added to the punching report.
                {result.skipped_duplicates > 0
                  ? ` ${result.skipped_duplicates} duplicate punch(es) skipped.`
                  : ""}
              </Text>
              <Pressable onPress={close} style={st.primaryBtn} testID="pimp-done">
                <Text style={st.primaryBtnTxt}>Done</Text>
              </Pressable>
            </View>
          ) : (
            <>
              <Text style={st.hint}>
                Columns: <Text style={st.hintB}>Bio Code, Name, Date, In Time, Out Time</Text>.
                Rows are matched by Bio Code first, then by Name. Matched punches are added
                date-wise directly into the punching report.
              </Text>

              <View style={st.btnRow}>
                <Pressable onPress={downloadTemplate} style={st.ghostBtn} testID="pimp-template">
                  <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                  <Text style={st.ghostBtnTxt}>Sample template</Text>
                </Pressable>
                <Pressable
                  onPress={pickFile}
                  disabled={busy}
                  style={[st.primaryBtn, busy && { opacity: 0.6 }]}
                  testID="pimp-pick"
                >
                  {busy && !preview ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="document-attach-outline" size={14} color="#fff" />
                      <Text style={st.primaryBtnTxt}>
                        {preview ? "Choose another file" : "Choose Excel file"}
                      </Text>
                    </>
                  )}
                </Pressable>
              </View>

              {error ? <Text style={st.errTxt}>{error}</Text> : null}

              {preview && s ? (
                <>
                  <Text style={st.fileTxt} numberOfLines={1}>
                    <Ionicons name="document-outline" size={12} color={colors.onSurfaceSecondary} /> {fileName}
                  </Text>
                  <View style={st.sumRow}>
                    <View style={[st.sumChip, { backgroundColor: "#EFF6FF" }]}>
                      <Text style={[st.sumNum, { color: "#1D4ED8" }]}>{s.total}</Text>
                      <Text style={st.sumLbl}>Rows</Text>
                    </View>
                    <View style={[st.sumChip, { backgroundColor: "#F0FDF4" }]}>
                      <Text style={[st.sumNum, { color: "#16A34A" }]}>{s.matched}</Text>
                      <Text style={st.sumLbl}>Matched</Text>
                    </View>
                    <View style={[st.sumChip, { backgroundColor: "#FFFBEB" }]}>
                      <Text style={[st.sumNum, { color: "#B45309" }]}>{s.unmatched}</Text>
                      <Text style={st.sumLbl}>Unmatched</Text>
                    </View>
                    <View style={[st.sumChip, { backgroundColor: "#FEF2F2" }]}>
                      <Text style={[st.sumNum, { color: "#B91C1C" }]}>{s.errors}</Text>
                      <Text style={st.sumLbl}>Errors</Text>
                    </View>
                  </View>

                  {preview.columns ? (
                    preview.columns.ot_detected ? (
                      <View style={st.otOkBanner}>
                        <Ionicons name="checkmark-circle" size={14} color="#16A34A" />
                        <Text style={st.otOkTxt}>OT In / OT Out columns detected — night OT will be imported.</Text>
                      </View>
                    ) : (
                      <View style={st.otWarnBanner}>
                        <Ionicons name="warning" size={14} color="#B91C1C" />
                        <Text style={st.otWarnTxt}>
                          OT In / OT Out columns NOT found — OT punches will NOT be imported.
                          Headers found in your file: {preview.columns.headers.join(", ") || "none"}.
                          Rename your OT columns to &quot;OT In&quot; and &quot;OT Out&quot; (or download the sample template).
                        </Text>
                      </View>
                    )
                  ) : null}

                  <ScrollView style={st.rowsBox}>
                    <View style={st.tRow}>
                      <Text style={[st.tCell, st.tHead, { width: 34 }]}>Row</Text>
                      <Text style={[st.tCell, st.tHead, { width: 56 }]}>Bio</Text>
                      <Text style={[st.tCell, st.tHead, { flex: 1.2 }]}>Employee</Text>
                      <Text style={[st.tCell, st.tHead, { width: 78 }]}>Date</Text>
                      <Text style={[st.tCell, st.tHead, { width: 44 }]}>In</Text>
                      <Text style={[st.tCell, st.tHead, { width: 44 }]}>Out</Text>
                      <Text style={[st.tCell, st.tHead, { width: 44 }]}>OT In</Text>
                      <Text style={[st.tCell, st.tHead, { width: 44 }]}>OT Out</Text>
                      <Text style={[st.tCell, st.tHead, { flex: 1 }]}>Status</Text>
                    </View>
                    {preview.rows.map((r) => (
                      <View key={r.row_no} style={st.tRow}>
                        <Text style={[st.tCell, { width: 34 }]}>{r.row_no}</Text>
                        <Text style={[st.tCell, { width: 56 }]} numberOfLines={1}>{r.bio_code || "—"}</Text>
                        <Text style={[st.tCell, { flex: 1.2, fontWeight: "600" }]} numberOfLines={1}>
                          {r.emp_name || r.name || "—"}
                        </Text>
                        <Text style={[st.tCell, { width: 78 }]}>{fmtDMY(r.date)}</Text>
                        <Text style={[st.tCell, { width: 44 }]}>{r.in_time || "—"}</Text>
                        <Text style={[st.tCell, { width: 44 }]}>{r.out_time || "—"}</Text>
                        <Text style={[st.tCell, { width: 44 }]}>{(r as any).ot_in_time || "—"}</Text>
                        <Text style={[st.tCell, { width: 44 }]}>{(r as any).ot_out_time || "—"}</Text>
                        {r.status === "matched" ? (
                          <Text style={[st.tCell, { flex: 1, color: "#16A34A", fontWeight: "700" }]}>
                            ✓ {r.matched_by === "name" ? "by Name" : "by Bio Code"}
                          </Text>
                        ) : (
                          <Text style={[st.tCell, { flex: 1, color: "#B91C1C" }]} numberOfLines={2}>
                            {r.error || "—"}
                          </Text>
                        )}
                      </View>
                    ))}
                  </ScrollView>

                  <Pressable
                    onPress={commit}
                    disabled={busy || s.matched === 0}
                    style={[st.importBtn, (busy || s.matched === 0) && { opacity: 0.5 }]}
                    testID="pimp-commit"
                  >
                    {busy ? (
                      <ActivityIndicator size="small" color="#fff" />
                    ) : (
                      <>
                        <Ionicons name="checkmark-done-outline" size={15} color="#fff" />
                        <Text style={st.primaryBtnTxt}>
                          Import {s.punches_to_create} punch{s.punches_to_create === 1 ? "" : "es"} ({s.matched} rows)
                        </Text>
                      </>
                    )}
                  </Pressable>
                </>
              ) : null}
            </>
          )}
        </View>
      </View>
    </Modal>
  );
}

const st = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center",
    justifyContent: "center",
    padding: 16,
  },
  card: {
    width: "100%",
    maxWidth: 720,
    maxHeight: "90%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: 16,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 8 },
  title: { ...type.h3, flex: 1, color: colors.onSurface },
  hint: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: 10, lineHeight: 17 },
  hintB: { fontWeight: "700", color: colors.onSurface },
  btnRow: { flexDirection: "row", gap: 8, marginBottom: 8, flexWrap: "wrap" },
  ghostBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  ghostBtnTxt: { fontSize: 12, fontWeight: "700", color: colors.brandPrimary },
  primaryBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  primaryBtnTxt: { fontSize: 12.5, fontWeight: "700", color: "#fff" },
  importBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#16A34A",
    borderRadius: radius.md,
    paddingVertical: 11,
    marginTop: 10,
  },
  errTxt: { fontSize: 12, color: colors.error, marginBottom: 6 },
  fileTxt: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: 6 },
  sumRow: { flexDirection: "row", gap: 8, marginBottom: 8 },
  sumChip: {
    flex: 1,
    alignItems: "center",
    borderRadius: radius.md,
    paddingVertical: 6,
  },
  sumNum: { fontSize: 16, fontWeight: "800" },
  sumLbl: { fontSize: 10.5, color: colors.onSurfaceSecondary },
  otOkBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    backgroundColor: "#F0FDF4",
    borderRadius: radius.md,
    paddingHorizontal: 8,
    paddingVertical: 5,
    marginBottom: 8,
  },
  otOkTxt: { fontSize: 11.5, color: "#15803D", fontWeight: "600", flex: 1 },
  otWarnBanner: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 6,
    backgroundColor: "#FEF2F2",
    borderWidth: 1,
    borderColor: "#FECACA",
    borderRadius: radius.md,
    paddingHorizontal: 8,
    paddingVertical: 6,
    marginBottom: 8,
  },
  otWarnTxt: { fontSize: 11.5, color: "#B91C1C", fontWeight: "600", flex: 1, lineHeight: 16 },
  rowsBox: {
    maxHeight: 320,
    borderWidth: 1,
    borderColor: colors.divider,
    borderRadius: radius.md,
  },
  tRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 8,
    paddingVertical: 5,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
    gap: 4,
  },
  tCell: { fontSize: 11.5, color: colors.onSurface },
  tHead: { fontWeight: "800", color: colors.onSurfaceSecondary, fontSize: 10.5 },
  doneBox: { alignItems: "center", paddingVertical: 20, gap: 8 },
  doneTitle: { ...type.h3, color: colors.onSurface },
  doneTxt: { fontSize: 12.5, color: colors.onSurfaceSecondary, textAlign: "center", marginBottom: 8 },
});
