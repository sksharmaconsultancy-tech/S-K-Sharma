/**
 * Iter 739 — LICENSES & STATUTORY COMPLIANCE DOCUMENTS (branch-wise).
 * Compliance-wise summary (Applicable | Registration | Attached) + alerts,
 * category → document-type from the configurable Statutory Document
 * Master, effective/expiry dates (No-Expiry supported), configurable
 * warning period (30/60/90), attachment view/download/replace (history
 * kept), filters, renewal-with-history and firm-wide register export.
 * Existing payroll/compliance engines untouched — master data only.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api, apiBinary } from "@/src/api/client";
import { confirmYesNo } from "@/src/utils/confirm";
import { colors, radius, spacing } from "@/src/theme";
import {
  BmField, BmBtn, BmChip, BmChipRow, BmToggle, bm, showWebMsg,
} from "@/src/components/firmMaster/branchMasterUi";

const ST: Record<string, { bg: string; fg: string; label: string }> = {
  active: { bg: "#DCFCE7", fg: "#15803D", label: "Active" },
  expiring_soon: { bg: "#FEF3C7", fg: "#B45309", label: "Expiring Soon" },
  expired: { bg: "#FEE2E2", fg: "#B91C1C", label: "Expired" },
  not_applicable: { bg: "#E2E8F0", fg: "#475569", label: "Not Applicable" },
  replaced: { bg: "#E2E8F0", fg: "#64748B", label: "Replaced (history)" },
  missing: { bg: "#FEE2E2", fg: "#B91C1C", label: "Missing" },
  none: { bg: "#F1F5F9", fg: "#94A3B8", label: "—" },
};

type Cat = { category: string; types: { doc_type: string; active: boolean; custom: boolean }[] };

export default function BranchDocsTab({ branchId, companyId }: {
  branchId: string; companyId: string;
}) {
  const [docs, setDocs] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [compl, setCompl] = useState<any>(null);
  const [cats, setCats] = useState<Cat[]>([]);
  const [warnDays, setWarnDays] = useState(60);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<any>(null);
  // filters
  const [q, setQ] = useState("");
  const [fCat, setFCat] = useState("");
  const [fStatus, setFStatus] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const qs = new URLSearchParams();
      if (q.trim()) qs.set("search", q.trim());
      if (fCat) qs.set("category", fCat);
      if (fStatus) qs.set("status", fStatus);
      const [r, cs] = await Promise.all([
        api<any>(`/admin/branch-master/${branchId}/licenses?${qs.toString()}`),
        api<any>(`/admin/branch-master/${branchId}/compliance-summary`),
      ]);
      setDocs(r.documents || []);
      setSummary(r.summary || null);
      setWarnDays(r.warn_days || 60);
      setCompl(cs);
    } catch { /* ignore */ } finally { setLoading(false); }
  }, [branchId, q, fCat, fStatus]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    api<{ categories: Cat[] }>(`/admin/branch-master/statutory/catalog?company_id=${companyId}`)
      .then((r) => setCats(r.categories || [])).catch(() => {});
  }, [companyId]);

  const setWarn = async (d: number) => {
    try {
      await api("/admin/branch-master/statutory/warn-days", {
        method: "POST", body: { company_id: companyId, days: d },
      });
      setWarnDays(d);
      load();
    } catch (e: any) { showWebMsg(e?.message || "Failed"); }
  };

  const download = async (d: any) => {
    try {
      const r = await api<{ file_name: string; file_base64: string }>(
        `/admin/branch-master/documents/${d.doc_id}/file`);
      if (Platform.OS === "web") {
        const a = document.createElement("a");
        a.href = r.file_base64.startsWith("data:") ? r.file_base64
          : `data:application/octet-stream;base64,${r.file_base64}`;
        a.download = r.file_name || "document";
        a.click();
      }
    } catch (e: any) { showWebMsg(e?.message || "No file attached"); }
  };

  const remove = async (d: any) => {
    const ok = await confirmYesNo(
      `Remove "${d.doc_type}"? History is preserved (soft delete).`, "Remove document");
    if (!ok) return;
    try {
      await api(`/admin/branch-master/documents/${d.doc_id}`, { method: "DELETE" });
      load();
    } catch (e: any) { showWebMsg(e?.message || "Delete failed"); }
  };

  const exportRegister = async () => {
    try {
      const r = await apiBinary(`/admin/branch-master/statutory/register?company_id=${companyId}&fmt=xlsx`);
      if (Platform.OS === "web" && r.webBlobUrl) {
        const a = document.createElement("a");
        a.href = r.webBlobUrl;
        a.download = "Statutory_Compliance_Register.xlsx";
        a.click();
      }
    } catch (e: any) { showWebMsg(e?.message || "Export failed"); }
  };

  return (
    <View>
      {/* Compliance-wise summary strip (§11/§14/§22) */}
      {compl ? (
        <View style={styles.complWrap}>
          {(compl.compliances || []).map((c: any) => {
            const s = ST[c.registration] || ST.none;
            return (
              <View key={c.compliance} style={styles.complCard}
                    testID={`stc-${c.compliance.replace(/\W+/g, "-")}`}>
                <Text style={styles.complName}>{c.compliance}</Text>
                <Text style={styles.complLine}>
                  Applicable: {c.applicable === true ? "Yes" : c.applicable === false ? "No" : "—"}
                </Text>
                <View style={[styles.pill, { backgroundColor: s.bg }]}>
                  <Text style={[styles.pillTxt, { color: s.fg }]}>{s.label}</Text>
                </View>
                <Text style={styles.complLine}>
                  Doc: {c.attached ? "Attached ✓" : c.docs_count ? "Not attached" : "—"}
                </Text>
              </View>
            );
          })}
        </View>
      ) : null}

      {/* Alerts (§15) */}
      {compl && (compl.alerts || []).length > 0 ? (
        <View style={styles.alertBox} testID="stc-alerts">
          {(compl.alerts || []).slice(0, 8).map((a: string, i: number) => (
            <Text key={i} style={styles.alertTxt}>⚠ {a}</Text>
          ))}
        </View>
      ) : null}

      {/* Toolbar */}
      <View style={styles.toolbar}>
        <View style={styles.searchRow}>
          <Ionicons name="search" size={13} color={colors.onSurfaceTertiary} />
          <TextInput value={q} onChangeText={setQ}
                     placeholder="Search document / number / authority…"
                     placeholderTextColor={colors.onSurfaceTertiary}
                     style={styles.searchInput} testID="stc-search" />
        </View>
        <BmBtn label="Register (Excel)" kind="ghost" icon="download-outline" small
               onPress={exportRegister} testID="stc-register" />
        <BmBtn label="Add License / Document" icon="add" small
               onPress={() => { setEditing(null); setShowForm(true); }}
               testID="stc-add" />
      </View>
      <View style={[bm.chipsWrap, { marginBottom: 6 }]}>
        <Text style={styles.fLbl}>Status:</Text>
        {["", "active", "expiring_soon", "expired"].map((s) => (
          <BmChip key={s || "all"} label={s ? ST[s].label : "All"} on={fStatus === s}
                  onPress={() => setFStatus(s)} />
        ))}
        <Text style={[styles.fLbl, { marginLeft: 10 }]}>Expiry warning:</Text>
        {[30, 60, 90].map((d) => (
          <BmChip key={d} label={`${d} days`} on={warnDays === d}
                  onPress={() => setWarn(d)} testID={`stc-warn-${d}`} />
        ))}
      </View>
      <View style={[bm.chipsWrap, { marginBottom: 8 }]}>
        <Text style={styles.fLbl}>Compliance:</Text>
        <BmChip label="All" on={fCat === ""} onPress={() => setFCat("")} />
        {cats.map((c) => (
          <BmChip key={c.category} label={c.category} on={fCat === c.category}
                  onPress={() => setFCat(fCat === c.category ? "" : c.category)} />
        ))}
      </View>

      {showForm ? (
        <LicenseForm
          branchId={branchId} cats={cats} initial={editing}
          onSaved={() => { setShowForm(false); setEditing(null); load(); }}
          onCancel={() => { setShowForm(false); setEditing(null); }}
        />
      ) : null}

      {summary ? (
        <Text style={styles.sumTxt}>
          {summary.total} document(s) · {summary.active} Active · {summary.expiring_soon} Expiring Soon · {summary.expired} Expired
        </Text>
      ) : null}

      {loading ? <ActivityIndicator color={colors.brandPrimary} style={{ marginVertical: 14 }} /> :
        docs.length === 0 ? <Text style={styles.hint}>No licenses / documents yet.</Text> :
          docs.map((d) => {
            const s = ST[d.expiry_status] || ST.active;
            return (
              <View key={d.doc_id} style={[styles.dRow, d.expiry_status === "replaced" && { opacity: 0.55 }]}
                    testID={`stc-doc-${d.doc_id}`}>
                <Ionicons name="document-text-outline" size={17} color={colors.brandPrimary} />
                <View style={{ flex: 1 }}>
                  <Text style={styles.dTitle}>
                    {d.doc_type}{d.doc_name ? ` — ${d.doc_name}` : ""}
                  </Text>
                  <Text style={styles.dMeta}>
                    {d.category ? `${d.category} · ` : ""}
                    {d.doc_number ? `No. ${d.doc_number} · ` : ""}
                    {d.issuing_authority ? `${d.issuing_authority} · ` : ""}
                    {d.state ? `${d.state} · ` : ""}
                    {d.effective_from ? `From ${d.effective_from}` : ""}
                    {d.no_expiry ? " · No Expiry" : d.expiry_date ? ` · Expires ${d.expiry_date}` : ""}
                  </Text>
                  {d.uploaded_by_name ? (
                    <Text style={styles.dMeta}>
                      📎 {d.file_name} · {String(d.uploaded_at || "").slice(0, 10)} · by {d.uploaded_by_name}
                    </Text>
                  ) : null}
                </View>
                <View style={[styles.pill, { backgroundColor: s.bg }]}>
                  <Text style={[styles.pillTxt, { color: s.fg }]}>{s.label}</Text>
                </View>
                {d.has_file ? (
                  <Pressable onPress={() => download(d)} style={styles.iconBtn}
                             testID={`stc-download-${d.doc_id}`}>
                    <Ionicons name="download-outline" size={14} color={colors.brandPrimary} />
                  </Pressable>
                ) : null}
                <Pressable onPress={() => { setEditing(d); setShowForm(true); }}
                           style={styles.iconBtn} testID={`stc-edit-${d.doc_id}`}>
                  <Ionicons name="create-outline" size={14} color={colors.brandPrimary} />
                </Pressable>
                <Pressable onPress={() => remove(d)} style={styles.iconBtn}
                           testID={`stc-delete-${d.doc_id}`}>
                  <Ionicons name="trash-outline" size={14} color={colors.error} />
                </Pressable>
              </View>
            );
          })}
    </View>
  );
}

/* ------------------------------------------------------------------ */

function LicenseForm({ branchId, cats, initial, onSaved, onCancel }: {
  branchId: string;
  cats: Cat[];
  initial: any;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [category, setCategory] = useState(initial?.category || "");
  const [docType, setDocType] = useState(initial?.doc_type || "");
  const [docName, setDocName] = useState(initial?.doc_name || "");
  const [number, setNumber] = useState(initial?.doc_number || "");
  const [estCode, setEstCode] = useState(initial?.establishment_code || "");
  const [authority, setAuthority] = useState(initial?.issuing_authority || "");
  const [stateName, setStateName] = useState(initial?.state || "");
  const [effFrom, setEffFrom] = useState(initial?.effective_from || "");
  const [expiry, setExpiry] = useState(initial?.expiry_date || "");
  const [noExpiry, setNoExpiry] = useState(!!initial?.no_expiry);
  const [applicable, setApplicable] = useState(initial ? initial.applicable !== false : true);
  const [remarks, setRemarks] = useState(initial?.remarks || "");
  const [fileName, setFileName] = useState("");
  const [fileB64, setFileB64] = useState<string | null>(null);
  const [replaceSame, setReplaceSame] = useState(!initial);
  const [newType, setNewType] = useState("");
  const [busy, setBusy] = useState(false);

  const catTypes = (cats.find((c) => c.category === category)?.types || [])
    .filter((t) => t.active).map((t) => t.doc_type);

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
      reader.onload = () => { setFileB64(String(reader.result)); setFileName(f.name); };
      reader.readAsDataURL(f);
    };
    input.click();
  };

  const addCustomType = async () => {
    if (!category || !newType.trim()) { showWebMsg("Category और नया type name दोनों चाहिए"); return; }
    try {
      await api("/admin/branch-master/statutory/catalog", {
        method: "POST", body: { category, doc_type: newType.trim() },
      });
      setDocType(newType.trim());
      setNewType("");
      showWebMsg("Document type master में add हो गया ✓ (page reload पर list में दिखेगा)");
    } catch (e: any) { showWebMsg(e?.message || "Failed"); }
  };

  const save = async () => {
    if (!category) { showWebMsg("Compliance Category चुनें"); return; }
    if (!docType.trim()) { showWebMsg("Document Type चुनें"); return; }
    if (!noExpiry && effFrom && expiry && expiry < effFrom) {
      showWebMsg("Expiry Date cannot be before Effective From"); return;
    }
    setBusy(true);
    try {
      const body: any = {
        category, doc_type: docType, doc_name: docName, doc_number: number,
        establishment_code: estCode, issuing_authority: authority,
        state: stateName, effective_from: effFrom,
        expiry_date: noExpiry ? null : expiry, no_expiry: noExpiry,
        applicable, remarks,
        file_name: fileName || null, file_base64: fileB64,
      };
      if (initial) {
        await api(`/admin/branch-master/licenses/${initial.doc_id}`, {
          method: "PATCH", body,
        });
      } else {
        await api(`/admin/branch-master/${branchId}/licenses`, {
          method: "POST", body: { ...body, replace_same_type: replaceSame },
        });
      }
      onSaved();
    } catch (e: any) { showWebMsg(e?.message || "Save failed"); }
    finally { setBusy(false); }
  };

  return (
    <View style={styles.form} testID="stc-form">
      <Text style={styles.formTitle}>
        {initial ? "Edit License / Document" : "Add License / Document"}
      </Text>
      <BmChipRow label="Compliance Category *" options={cats.map((c) => c.category)}
                 value={category} onChange={(v) => { setCategory(v); setDocType(""); }}
                 testID="stc-cat" />
      {category ? (
        <>
          <BmChipRow label="Document Type *" options={catTypes} value={docType}
                     onChange={setDocType} testID="stc-type" />
          <View style={{ flexDirection: "row", gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
            <BmField label="Or add a new type to the master" value={newType}
                     onChangeText={setNewType} placeholder="New document type…" width={240} />
            <BmBtn label="Add Type" kind="ghost" small onPress={addCustomType}
                   testID="stc-add-type" />
          </View>
        </>
      ) : null}
      <View style={bm.row}>
        <BmField label="Document Name" value={docName} onChangeText={setDocName}
                 placeholder="Optional display name" />
        <BmField label="Registration / License No." value={number}
                 onChangeText={setNumber} testID="stc-number" />
        <BmField label="Establishment / Employer Code" value={estCode}
                 onChangeText={setEstCode} />
      </View>
      <View style={bm.row}>
        <BmField label="Issuing Authority" value={authority} onChangeText={setAuthority} />
        <BmField label="State" value={stateName} onChangeText={setStateName}
                 placeholder="e.g. Rajasthan" width={160} />
      </View>
      <View style={bm.row}>
        <BmField label="Effective From (YYYY-MM-DD)" value={effFrom}
                 onChangeText={setEffFrom} placeholder="2026-04-01" width={190}
                 testID="stc-eff" />
        {!noExpiry ? (
          <BmField label="Expiring Date / Valid Till (YYYY-MM-DD)" value={expiry}
                   onChangeText={setExpiry} placeholder="2027-03-31" width={220}
                   testID="stc-exp" />
        ) : null}
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
        <BmToggle label="No Expiry / Lifetime" value={noExpiry}
                  onChange={setNoExpiry} testID="stc-noexp" />
        <BmToggle label="Applicable" value={applicable}
                  onChange={setApplicable} testID="stc-applicable" />
        {!initial ? (
          <BmToggle label="Renewal — mark older doc of same type as history"
                    value={replaceSame} onChange={setReplaceSame} />
        ) : null}
      </View>
      <BmField label="Remarks" value={remarks} onChangeText={setRemarks} />
      <View style={{ flexDirection: "row", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
        <BmBtn label={fileName ? `📎 ${fileName}` : (initial?.file_name ? `Replace attachment (📎 ${initial.file_name})` : "Upload Attachment")}
               kind="ghost" icon="cloud-upload-outline" small onPress={pickFile}
               testID="stc-upload" />
        <Text style={styles.hint}>PDF / JPG / PNG / DOC · max 8 MB</Text>
      </View>
      <View style={{ flexDirection: "row", gap: 8, justifyContent: "flex-end", marginTop: 6 }}>
        <BmBtn label="Cancel" kind="ghost" onPress={onCancel} />
        <BmBtn label={initial ? "Save Changes" : "Save Document"} onPress={save}
               busy={busy} testID="stc-save" />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  complWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginBottom: 8 },
  complCard: {
    minWidth: 128, flexGrow: 1, borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md, padding: 8, backgroundColor: colors.surfaceSecondary, gap: 3,
  },
  complName: { fontSize: 11.5, fontWeight: "800", color: colors.onSurface },
  complLine: { fontSize: 10.5, color: colors.onSurfaceTertiary },
  pill: { borderRadius: 10, paddingHorizontal: 7, paddingVertical: 2, alignSelf: "flex-start" },
  pillTxt: { fontSize: 10, fontWeight: "800" },
  alertBox: {
    borderWidth: 1, borderColor: "#F59E0B", backgroundColor: "#FFFBEB",
    borderRadius: radius.md, padding: spacing.sm, marginBottom: 8, gap: 2,
  },
  alertTxt: { fontSize: 11.5, fontWeight: "700", color: "#B45309" },
  toolbar: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 6 },
  searchRow: {
    flexDirection: "row", alignItems: "center", gap: 6, flex: 1, minWidth: 200,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 9, paddingVertical: 6, backgroundColor: colors.surfaceSecondary,
  },
  searchInput: { flex: 1, fontSize: 12.5, color: colors.onSurface,
    ...(Platform.OS === "web" ? { outlineStyle: "none" } as any : {}) },
  fLbl: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceTertiary, alignSelf: "center" },
  sumTxt: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 6 },
  hint: { fontSize: 11.5, color: colors.onSurfaceTertiary },
  dRow: {
    flexDirection: "row", alignItems: "center", gap: 8,
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    paddingHorizontal: 10, paddingVertical: 8, marginBottom: 6,
    backgroundColor: colors.surfaceSecondary,
  },
  dTitle: { fontSize: 12.5, fontWeight: "800", color: colors.onSurface },
  dMeta: { fontSize: 11, color: colors.onSurfaceTertiary, marginTop: 1 },
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
