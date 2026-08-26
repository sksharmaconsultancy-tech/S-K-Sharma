/**
 * Iter 737 — Branch Documents tab: statutory document register with
 * expiry indicators (Active / Expiring Soon / Expired), base64 upload
 * (same architecture as firm compliance docs), replace-with-history and
 * soft delete (history preserved).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { confirmYesNo } from "@/src/utils/confirm";
import { colors, radius, spacing } from "@/src/theme";
import {
  BmField, BmBtn, BmChipRow, BmToggle, bm, showWebMsg,
} from "@/src/components/firmMaster/branchMasterUi";

const EXPIRY_STYLE: Record<string, { bg: string; fg: string; label: string }> = {
  active: { bg: "#DCFCE7", fg: "#15803D", label: "Active" },
  expiring_soon: { bg: "#FEF3C7", fg: "#B45309", label: "Expiring Soon" },
  expired: { bg: "#FEE2E2", fg: "#B91C1C", label: "Expired" },
  replaced: { bg: "#E2E8F0", fg: "#475569", label: "Replaced" },
};

export default function BranchDocsTab({ branchId }: { branchId: string }) {
  const [docs, setDocs] = useState<any[]>([]);
  const [docTypes, setDocTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ documents: any[]; doc_types: string[] }>(
        `/admin/branch-master/${branchId}/documents`);
      setDocs(r.documents || []);
      setDocTypes(r.doc_types || []);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [branchId]);

  useEffect(() => { load(); }, [load]);

  const download = async (d: any) => {
    try {
      const r = await api<{ file_name: string; file_base64: string }>(
        `/admin/branch-master/documents/${d.doc_id}/file`);
      if (Platform.OS === "web") {
        const a = document.createElement("a");
        a.href = r.file_base64.startsWith("data:")
          ? r.file_base64
          : `data:application/octet-stream;base64,${r.file_base64}`;
        a.download = r.file_name || "document";
        a.click();
      }
    } catch (e: any) { showWebMsg(e?.message || "No file attached"); }
  };

  const remove = async (d: any) => {
    const ok = await confirmYesNo(
      `Remove "${d.doc_type}" (${d.doc_number || "no number"})? Document history is preserved (soft delete).`,
      "Remove document");
    if (!ok) return;
    try {
      await api(`/admin/branch-master/documents/${d.doc_id}`, { method: "DELETE" });
      load();
    } catch (e: any) { showWebMsg(e?.message || "Delete failed"); }
  };

  return (
    <View>
      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <Text style={styles.hint}>
          Statutory documents — expiry auto-flagged (60-day warning). Replaced
          docs history में रहते हैं.
        </Text>
        <BmBtn label="Add Document" icon="add" small
               onPress={() => setShowForm(!showForm)} testID="bd-add" />
      </View>

      {showForm ? (
        <DocForm branchId={branchId} docTypes={docTypes}
                 onSaved={() => { setShowForm(false); load(); }}
                 onCancel={() => setShowForm(false)} />
      ) : null}

      {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 14 }} /> :
        docs.length === 0 ? (
          <Text style={styles.hint}>No documents added yet.</Text>
        ) : docs.map((d) => {
          const st = EXPIRY_STYLE[d.expiry_status] || EXPIRY_STYLE.active;
          return (
            <View key={d.doc_id} style={styles.dRow} testID={`bd-doc-${d.doc_id}`}>
              <Ionicons name="document-text-outline" size={17} color={colors.brandPrimary} />
              <View style={{ flex: 1 }}>
                <Text style={styles.dTitle}>{d.doc_type}</Text>
                <Text style={styles.dMeta}>
                  {d.doc_number ? `No. ${d.doc_number} · ` : ""}
                  {d.issue_date ? `Issued ${d.issue_date}` : ""}
                  {d.expiry_date ? ` · Expires ${d.expiry_date}` : " · No expiry"}
                  {d.remarks ? ` · ${d.remarks}` : ""}
                </Text>
              </View>
              <View style={[styles.expPill, { backgroundColor: st.bg }]}>
                <Text style={[styles.expPillTxt, { color: st.fg }]}>{st.label}</Text>
              </View>
              {d.file_name ? (
                <Pressable onPress={() => download(d)} style={styles.iconBtn}
                           testID={`bd-download-${d.doc_id}`}>
                  <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                </Pressable>
              ) : null}
              <Pressable onPress={() => remove(d)} style={styles.iconBtn}
                         testID={`bd-delete-${d.doc_id}`}>
                <Ionicons name="trash-outline" size={14} color={colors.error} />
              </Pressable>
            </View>
          );
        })}
    </View>
  );
}

function DocForm({ branchId, docTypes, onSaved, onCancel }: {
  branchId: string;
  docTypes: string[];
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [docType, setDocType] = useState("");
  const [number, setNumber] = useState("");
  const [issue, setIssue] = useState("");
  const [expiry, setExpiry] = useState("");
  const [remarks, setRemarks] = useState("");
  const [fileName, setFileName] = useState("");
  const [fileB64, setFileB64] = useState<string | null>(null);
  const [replaceSame, setReplaceSame] = useState(true);
  const [busy, setBusy] = useState(false);

  const pickFile = () => {
    if (Platform.OS !== "web") return;
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".pdf,.jpg,.jpeg,.png,.doc,.docx,.xls,.xlsx";
    input.onchange = () => {
      const f = input.files?.[0];
      if (!f) return;
      if (f.size > 8 * 1024 * 1024) { showWebMsg("File too large (max 8 MB)"); return; }
      const reader = new FileReader();
      reader.onload = () => {
        setFileB64(String(reader.result));
        setFileName(f.name);
      };
      reader.readAsDataURL(f);
    };
    input.click();
  };

  const save = async () => {
    if (!docType) { showWebMsg("Document Type चुनें"); return; }
    if (issue && expiry && expiry < issue) {
      showWebMsg("Expiry date cannot be before issue date"); return;
    }
    setBusy(true);
    try {
      await api(`/admin/branch-master/${branchId}/documents`, {
        method: "POST",
        body: {
          doc_type: docType, doc_number: number, issue_date: issue,
          expiry_date: expiry, remarks,
          file_name: fileName || null, file_base64: fileB64,
          replace_same_type: replaceSame,
        },
      });
      onSaved();
    } catch (e: any) { showWebMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  return (
    <View style={styles.form} testID="bd-form">
      <Text style={styles.formTitle}>Add Branch Document</Text>
      <BmChipRow label="Document Type *" options={docTypes} value={docType}
                 onChange={setDocType} testID="bd-type" />
      <View style={bm.row}>
        <BmField label="Document Number" value={number} onChangeText={setNumber}
                 testID="bd-number" />
        <BmField label="Issue Date (YYYY-MM-DD)" value={issue} onChangeText={setIssue}
                 placeholder="2025-04-01" width={180} testID="bd-issue" />
        <BmField label="Expiry Date (YYYY-MM-DD)" value={expiry} onChangeText={setExpiry}
                 placeholder="2027-03-31" width={180} testID="bd-expiry" />
      </View>
      <BmField label="Remarks" value={remarks} onChangeText={setRemarks} />
      <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <BmBtn label={fileName ? `📎 ${fileName}` : "Upload Document"} kind="ghost"
               icon="cloud-upload-outline" small onPress={pickFile} testID="bd-upload" />
        <BmToggle label="Replace older doc of same type (history kept)"
                  value={replaceSame} onChange={setReplaceSame} />
      </View>
      <View style={{ flexDirection: "row", gap: 8, justifyContent: "flex-end", marginTop: 6 }}>
        <BmBtn label="Cancel" kind="ghost" onPress={onCancel} />
        <BmBtn label="Save Document" onPress={save} busy={busy} testID="bd-save" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary, flex: 1, marginRight: 8 },
  dRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, marginBottom: 6,
    backgroundColor: colors.surfaceSecondary,
  },
  dTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  dMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
  expPill: { borderRadius: 10, paddingHorizontal: 8, paddingVertical: 3 },
  expPillTxt: { fontSize: 10, fontWeight: "800" },
  iconBtn: {
    width: 28, height: 28, borderRadius: 7, alignItems: "center", justifyContent: "center",
    borderWidth: 1, borderColor: colors.border, backgroundColor: colors.surface,
  },
  form: {
    borderWidth: 1, borderColor: colors.brandPrimary, borderRadius: radius.md,
    padding: spacing.sm, marginBottom: spacing.sm, backgroundColor: colors.surface,
  },
  formTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: 8 },
});
