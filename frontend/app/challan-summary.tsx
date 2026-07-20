/**
 * Iter 127 — Monthly Challan Summary (Reports ▸ Monthly Challan Summary).
 *
 * One sheet per month listing ALL ACTIVE firms with:
 *   • Compliance salary finalize status (Draft / Finalized)
 *   • PF / ESIC challan amounts — manual entry OR auto-fetched from the
 *     challans uploaded on the PF/ESIC Challans screen (+ uploader name)
 *   • Remark — typing "Audit" LOCKS the firm: no data entry anywhere in
 *     the app until the Super Admin clears the remark
 *   • Email + WhatsApp send buttons (with confirmation popups)
 *
 * Accessible to Super Admins AND Sub Admins (user directive).
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  TextInput,
  ActivityIndicator,
  Platform,
  Linking,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useRefreshBus } from "@/src/context/RefreshBusContext";
import MonthPicker from "@/src/components/MonthPicker";
import DateField from "@/src/components/DateField";
import { colors, radius, spacing } from "@/src/theme";

type Row = {
  company_id: string;
  firm_name: string;
  salary_status: "finalized" | "draft" | "not_processed";
  remark: string;
  is_audit: boolean;
  pf_amount: number | null;
  pf_source: "manual" | "auto" | null;
  pf_by_name: string;
  esic_amount: number | null;
  esic_source: "manual" | "auto" | null;
  esic_by_name: string;
  pf_date: string | null;
  esic_date: string | null;
  reg_email: string;
  reg_whatsapp: string;
};

type Edit = { pf: string; esic: string; remark: string; pfDate: string; esicDate: string };

function prevMonth(): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() - 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function ChallanSummaryScreen() {
  const { user } = useAuth();
  const { refreshedAt } = useRefreshBus();
  const isSuper = user?.role === "super_admin" || (user?.role as string) === "sub_admin";

  const [month, setMonth] = useState(prevMonth());
  const [rows, setRows] = useState<Row[]>([]);
  const [edits, setEdits] = useState<Record<string, Edit>>({});
  const [loading, setLoading] = useState(true);
  const [rowStatus, setRowStatus] = useState<Record<string, "saving" | "saved" | "error">>({});
  const [banner, setBanner] = useState<{ kind: "ok" | "err"; msg: string } | null>(null);
  // Auto-save plumbing — debounce timers + latest edits/baselines per firm.
  const timersRef = React.useRef<Record<string, any>>({});
  const editsRef = React.useRef<Record<string, Edit>>({});
  const baselineRef = React.useRef<Record<string, Edit>>({});
  editsRef.current = edits;
  // Per-firm send modal (email / whatsapp to the firm's registered contact)
  const [sendModal, setSendModal] = useState<{ kind: "email" | "wa"; row: Row } | null>(null);
  const [sendTarget, setSendTarget] = useState("");
  const [sendingFirm, setSendingFirm] = useState(false);

  // Send modals
  const [emailModal, setEmailModal] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [sendingEmail, setSendingEmail] = useState(false);
  const [waModal, setWaModal] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ rows: Row[] }>(`/admin/challan-summary?month=${month}`);
      const list = r?.rows || [];
      setRows(list);
      const e: Record<string, Edit> = {};
      for (const row of list) {
        e[row.company_id] = {
          pf: row.pf_amount != null ? String(row.pf_amount) : "",
          esic: row.esic_amount != null ? String(row.esic_amount) : "",
          remark: row.remark || "",
          pfDate: row.pf_date || "",
          esicDate: row.esic_date || "",
        };
      }
      // Reset auto-save baselines + cancel pending timers from the old month.
      for (const t of Object.values(timersRef.current)) clearTimeout(t);
      timersRef.current = {};
      baselineRef.current = JSON.parse(JSON.stringify(e));
      setEdits(e);
      setRowStatus({});
    } catch (err: any) {
      setBanner({ kind: "err", msg: err?.message || "Failed to load summary" });
    } finally {
      setLoading(false);
    }
  }, [month]);

  useEffect(() => {
    load();
  }, [load, refreshedAt]);

  useEffect(() => {
    if (user?.email && !emailTo) setEmailTo(user.email);
  }, [user?.email]); // eslint-disable-line react-hooks/exhaustive-deps

  // Dates may arrive mid-typing (web date inputs emit years like "0002"
  // while the user types "2026"; native lets users type DD-MM-YYYY).
  // Only auto-save complete, sane dates; convert DD-MM-YYYY → ISO.
  const normDate = (v: string): string | undefined => {
    const s = (v || "").trim();
    if (s === "") return "";
    let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (m) return Number(m[1]) >= 2000 && Number(m[1]) <= 2099 ? s : undefined;
    m = /^(\d{2})[-/](\d{2})[-/](\d{4})$/.exec(s);
    if (m && Number(m[3]) >= 2000 && Number(m[3]) <= 2099) {
      return `${m[3]}-${m[2]}-${m[1]}`;
    }
    return undefined; // incomplete — retry on the next edit/save
  };

  const autoSave = useCallback(async (cid: string) => {
    const e = editsRef.current[cid];
    const b = baselineRef.current[cid];
    if (!e || !b) return;
    const payload: any = {};
    if (e.pf !== b.pf) payload.pf_amount = e.pf.trim() === "" ? null : Number(e.pf);
    if (e.esic !== b.esic) payload.esic_amount = e.esic.trim() === "" ? null : Number(e.esic);
    if (e.remark !== b.remark) payload.remark = e.remark;
    if (e.pfDate !== b.pfDate) {
      const nd = normDate(e.pfDate);
      if (nd !== undefined) payload.pf_date = nd || null;
    }
    if (e.esicDate !== b.esicDate) {
      const nd = normDate(e.esicDate);
      if (nd !== undefined) payload.esic_date = nd || null;
    }
    if (Object.keys(payload).length === 0) return;
    if (
      ("pf_amount" in payload && payload.pf_amount != null && !Number.isFinite(payload.pf_amount)) ||
      ("esic_amount" in payload && payload.esic_amount != null && !Number.isFinite(payload.esic_amount))
    ) {
      setRowStatus((s) => ({ ...s, [cid]: "error" }));
      setBanner({ kind: "err", msg: "PF / ESIC amounts must be numbers" });
      return;
    }
    setRowStatus((s) => ({ ...s, [cid]: "saving" }));
    try {
      const r = await api<{ ok: boolean; is_audit: boolean }>(
        `/admin/challan-summary/${cid}/${month}`,
        { method: "PATCH", body: payload },
      );
      baselineRef.current[cid] = { ...editsRef.current[cid] };
      setRowStatus((s) => ({ ...s, [cid]: "saved" }));
      const myName = user?.name || user?.email || "";
      setRows((prev) =>
        prev.map((row) =>
          row.company_id !== cid
            ? row
            : {
                ...row,
                is_audit: !!r.is_audit,
                remark: "remark" in payload ? e.remark : row.remark,
                pf_by_name: "pf_amount" in payload ? myName : row.pf_by_name,
                pf_source: "pf_amount" in payload ? ("manual" as const) : row.pf_source,
                esic_by_name: "esic_amount" in payload ? myName : row.esic_by_name,
                esic_source: "esic_amount" in payload ? ("manual" as const) : row.esic_source,
              },
        ),
      );
      if (r.is_audit) {
        setBanner({ kind: "ok", msg: "Saved — firm is now under AUDIT LOCK" });
      }
    } catch (err: any) {
      setRowStatus((s) => ({ ...s, [cid]: "error" }));
      setBanner({ kind: "err", msg: err?.message || "Auto-save failed" });
    }
  }, [month, user]);

  // Every edit AUTO-SAVES ~0.9s after the user stops typing (user request
  // — no manual Save button).
  const setEdit = (cid: string, patch: Partial<Edit>) => {
    setEdits((prev) => {
      const next = {
        ...prev,
        [cid]: {
          ...(prev[cid] || { pf: "", esic: "", remark: "", pfDate: "", esicDate: "" }),
          ...patch,
        },
      };
      editsRef.current = next;
      return next;
    });
    if (timersRef.current[cid]) clearTimeout(timersRef.current[cid]);
    timersRef.current[cid] = setTimeout(() => autoSave(cid), 900);
  };

  const buildFirmText = (r: Row) => {
    const status =
      r.salary_status === "finalized" ? "FINALIZED" :
      r.salary_status === "draft" ? "DRAFT" : "NOT PROCESSED";
    const lines = [
      `Challan Summary — ${r.firm_name} — ${month}`,
      `Salary Status: ${status}`,
      `PF Challan: ${r.pf_amount != null ? `₹${r.pf_amount}` : "—"}` +
        (r.pf_date ? ` | Date: ${r.pf_date}` : "") +
        (r.pf_by_name ? ` | By: ${r.pf_by_name}` : ""),
      `ESIC Challan: ${r.esic_amount != null ? `₹${r.esic_amount}` : "—"}` +
        (r.esic_date ? ` | Date: ${r.esic_date}` : "") +
        (r.esic_by_name ? ` | By: ${r.esic_by_name}` : ""),
    ];
    if (r.remark) lines.push(`Remark: ${r.remark}`);
    if (r.is_audit) lines.push("⚠ FIRM UNDER AUDIT LOCK");
    return lines.join("\n");
  };

  const openFirmSend = (kind: "email" | "wa", row: Row) => {
    setSendTarget(kind === "email" ? row.reg_email || "" : row.reg_whatsapp || "");
    setSendModal({ kind, row });
  };

  const confirmFirmSend = async () => {
    if (!sendModal) return;
    const { kind, row } = sendModal;
    if (kind === "email") {
      if (!sendTarget.trim()) {
        setBanner({
          kind: "err",
          msg: "No registered email — type one in the popup or add it in Firm Master.",
        });
        return;
      }
      setSendingFirm(true);
      try {
        const r = await api<{ ok: boolean; to: string; error?: string }>(
          `/admin/challan-summary/${row.company_id}/${month}/send-email`,
          { method: "POST", body: { to: sendTarget.trim() } },
        );
        setSendModal(null);
        setBanner(
          r.ok
            ? { kind: "ok", msg: `${row.firm_name} summary emailed to ${r.to}` }
            : { kind: "err", msg: r.error || "Email failed" },
        );
      } catch (err: any) {
        setBanner({ kind: "err", msg: err?.message || "Email failed" });
      } finally {
        setSendingFirm(false);
      }
    } else {
      const digits = sendTarget.replace(/\D/g, "");
      const phone = digits.length === 10 ? `91${digits}` : digits;
      const text = buildFirmText(row);
      const url = phone
        ? `https://wa.me/${phone}?text=${encodeURIComponent(text)}`
        : `https://wa.me/?text=${encodeURIComponent(text)}`;
      setSendModal(null);
      if (Platform.OS === "web") {
        (globalThis as any).window?.open(url, "_blank");
      } else {
        Linking.openURL(url).catch(() =>
          setBanner({ kind: "err", msg: "Could not open WhatsApp" }),
        );
      }
    }
  };

  const summaryText = useMemo(() => {
    const lines = [`Monthly Challan Summary — ${month}`, ""];
    for (const r of rows) {
      const status =
        r.salary_status === "finalized" ? "FINALIZED" :
        r.salary_status === "draft" ? "DRAFT" : "NOT PROCESSED";
      let l = `• ${r.firm_name} — Salary: ${status}`;
      l += r.pf_amount != null
        ? ` | PF: ₹${r.pf_amount}${r.pf_by_name ? ` (${r.pf_by_name})` : ""}`
        : " | PF: —";
      l += r.esic_amount != null
        ? ` | ESIC: ₹${r.esic_amount}${r.esic_by_name ? ` (${r.esic_by_name})` : ""}`
        : " | ESIC: —";
      if (r.remark) l += ` | Remark: ${r.remark}`;
      if (r.is_audit) l += " | ⚠ AUDIT LOCK";
      lines.push(l);
    }
    return lines.join("\n");
  }, [rows, month]);

  const sendEmail = async () => {
    setSendingEmail(true);
    setBanner(null);
    try {
      const r = await api<{ ok: boolean; to: string; error?: string }>(
        "/admin/challan-summary/email",
        { method: "POST", body: { month, to: emailTo.trim() } },
      );
      setEmailModal(false);
      setBanner(
        r.ok
          ? { kind: "ok", msg: `Summary emailed to ${r.to}` }
          : { kind: "err", msg: r.error || "Email failed" },
      );
    } catch (err: any) {
      setBanner({ kind: "err", msg: err?.message || "Email failed" });
    } finally {
      setSendingEmail(false);
    }
  };

  const sendWhatsApp = () => {
    setWaModal(false);
    const url = `https://wa.me/?text=${encodeURIComponent(summaryText)}`;
    if (Platform.OS === "web") {
      (globalThis as any).window?.open(url, "_blank");
    } else {
      Linking.openURL(url).catch(() =>
        setBanner({ kind: "err", msg: "Could not open WhatsApp" }),
      );
    }
  };

  const statusBadge = (s: Row["salary_status"]) => {
    const map = {
      finalized: { txt: "FINALIZED 🔒", bg: "#DCFCE7", fg: "#166534" },
      draft: { txt: "DRAFT", bg: "#FEF3C7", fg: "#92400E" },
      not_processed: { txt: "NOT PROCESSED", bg: "#F1F5F9", fg: "#64748B" },
    } as const;
    const m = map[s] || map.not_processed;
    return (
      <View style={[styles.badge, { backgroundColor: m.bg }]}>
        <Text style={[styles.badgeTxt, { color: m.fg }]}>{m.txt}</Text>
      </View>
    );
  };

  return (
    <SafeAreaView style={styles.safe} edges={["top"]}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.headRow}>
          <View style={{ flex: 1, minWidth: 220 }}>
            <Text style={styles.title}>Monthly Challan Summary</Text>
            <Text style={styles.sub}>
              All active firms — salary finalize status, PF / ESIC challan amounts
              (auto-fetched from uploads or entered manually) and remarks.
            </Text>
          </View>
          <View style={styles.headActions}>
            <View style={{ minWidth: 190 }}>
              <MonthPicker value={month} onChange={setMonth} testID="challan-summary-month" />
            </View>
            <Pressable
              style={[styles.actionBtn, { backgroundColor: colors.brandPrimary }]}
              onPress={() => setEmailModal(true)}
              testID="challan-summary-email-btn"
            >
              <Ionicons name="mail-outline" size={15} color="#fff" />
              <Text style={styles.actionBtnTxt}>Email</Text>
            </Pressable>
            <Pressable
              style={[styles.actionBtn, { backgroundColor: "#16A34A" }]}
              onPress={() => setWaModal(true)}
              testID="challan-summary-wa-btn"
            >
              <Ionicons name="logo-whatsapp" size={15} color="#fff" />
              <Text style={styles.actionBtnTxt}>WhatsApp</Text>
            </Pressable>
          </View>
        </View>

        <View style={styles.hintCard}>
          <Ionicons name="information-circle-outline" size={16} color="#92400E" />
          <Text style={styles.hintTxt}>
            Type <Text style={{ fontWeight: "800" }}>Audit</Text> in a firm&apos;s remark to
            LOCK it — no data entry anywhere in the portal for that firm until the
            Super Admin clears the remark. Changes{" "}
            <Text style={{ fontWeight: "800" }}>auto-save</Text> as you type — no Save
            button needed.
          </Text>
        </View>

        {banner ? (
          <View
            style={[
              styles.banner,
              banner.kind === "ok" ? styles.bannerOk : styles.bannerErr,
            ]}
            testID="challan-summary-banner"
          >
            <Ionicons
              name={banner.kind === "ok" ? "checkmark-circle" : "alert-circle"}
              size={16}
              color={banner.kind === "ok" ? "#166534" : "#B91C1C"}
            />
            <Text
              style={{
                color: banner.kind === "ok" ? "#166534" : "#B91C1C",
                fontSize: 12,
                fontWeight: "600",
                flex: 1,
              }}
            >
              {banner.msg}
            </Text>
          </View>
        ) : null}

        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : (
          <View style={styles.table}>
            {/* Header */}
            <View style={[styles.tr, styles.thRow]}>
              <Text style={[styles.th, { flex: 2 }]}>Firm Name</Text>
              <Text style={[styles.th, { flex: 1.3 }]}>Salary Status</Text>
              <Text style={[styles.th, { flex: 1.6 }]}>PF Challan (₹ / Date)</Text>
              <Text style={[styles.th, { flex: 1.6 }]}>ESIC Challan (₹ / Date)</Text>
              <Text style={[styles.th, { flex: 1.6 }]}>Remark</Text>
              <Text style={[styles.th, { width: 70, textAlign: "center" }]}>Auto</Text>
            </View>

            {rows.length === 0 ? (
              <Text style={styles.empty}>No active firms found.</Text>
            ) : (
              rows.map((row) => {
                const e =
                  edits[row.company_id] ||
                  { pf: "", esic: "", remark: "", pfDate: "", esicDate: "" };
                const locked = row.is_audit && !isSuper;
                const st = rowStatus[row.company_id];
                return (
                  <View
                    key={row.company_id}
                    style={[styles.tr, row.is_audit && styles.trAudit]}
                    testID={`challan-row-${row.company_id}`}
                  >
                    <View style={{ flex: 2, paddingRight: 8 }}>
                      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                        <Pressable
                          style={styles.rowSendBtn}
                          onPress={() => openFirmSend("email", row)}
                          testID={`row-email-${row.company_id}`}
                        >
                          <Ionicons name="mail-outline" size={13} color={colors.brandPrimary} />
                        </Pressable>
                        <Pressable
                          style={[styles.rowSendBtn, { borderColor: "#86EFAC", backgroundColor: "#F0FDF4" }]}
                          onPress={() => openFirmSend("wa", row)}
                          testID={`row-wa-${row.company_id}`}
                        >
                          <Ionicons name="logo-whatsapp" size={13} color="#16A34A" />
                        </Pressable>
                        {row.is_audit ? (
                          <Ionicons name="lock-closed" size={13} color="#B91C1C" />
                        ) : null}
                        <Text style={styles.firmName} numberOfLines={2}>
                          {row.firm_name}
                        </Text>
                      </View>
                      {row.is_audit ? (
                        <Text style={styles.auditTag}>AUDIT LOCK — data entry disabled</Text>
                      ) : null}
                    </View>

                    <View style={{ flex: 1.3 }}>{statusBadge(row.salary_status)}</View>

                    <View style={{ flex: 1.6, paddingRight: 8 }}>
                      <TextInput
                        style={[styles.input, locked && styles.inputLocked]}
                        value={e.pf}
                        onChangeText={(v) => setEdit(row.company_id, { pf: v })}
                        placeholder={row.pf_source === "auto" ? "auto" : "—"}
                        placeholderTextColor={colors.onSurfaceTertiary}
                        keyboardType="numeric"
                        editable={!locked}
                        testID={`pf-input-${row.company_id}`}
                      />
                      <View
                        style={{ marginTop: 4 }}
                        pointerEvents={locked ? "none" : "auto"}
                      >
                        <DateField
                          value={e.pfDate}
                          onChangeISO={(iso) => setEdit(row.company_id, { pfDate: iso })}
                          compact
                          testID={`pf-date-${row.company_id}`}
                        />
                      </View>
                      {row.pf_by_name ? (
                        <Text style={styles.byTxt} numberOfLines={1}>
                          {row.pf_source === "auto" ? "⤓ " : ""}by {row.pf_by_name}
                        </Text>
                      ) : null}
                    </View>

                    <View style={{ flex: 1.6, paddingRight: 8 }}>
                      <TextInput
                        style={[styles.input, locked && styles.inputLocked]}
                        value={e.esic}
                        onChangeText={(v) => setEdit(row.company_id, { esic: v })}
                        placeholder={row.esic_source === "auto" ? "auto" : "—"}
                        placeholderTextColor={colors.onSurfaceTertiary}
                        keyboardType="numeric"
                        editable={!locked}
                        testID={`esic-input-${row.company_id}`}
                      />
                      <View
                        style={{ marginTop: 4 }}
                        pointerEvents={locked ? "none" : "auto"}
                      >
                        <DateField
                          value={e.esicDate}
                          onChangeISO={(iso) => setEdit(row.company_id, { esicDate: iso })}
                          compact
                          testID={`esic-date-${row.company_id}`}
                        />
                      </View>
                      {row.esic_by_name ? (
                        <Text style={styles.byTxt} numberOfLines={1}>
                          {row.esic_source === "auto" ? "⤓ " : ""}by {row.esic_by_name}
                        </Text>
                      ) : null}
                    </View>

                    <View style={{ flex: 1.6, paddingRight: 8 }}>
                      <TextInput
                        style={[styles.input, locked && styles.inputLocked]}
                        value={e.remark}
                        onChangeText={(v) => setEdit(row.company_id, { remark: v })}
                        placeholder='e.g. "Audit"'
                        placeholderTextColor={colors.onSurfaceTertiary}
                        editable={!locked}
                        testID={`remark-input-${row.company_id}`}
                      />
                    </View>

                    <View
                      style={{ width: 70, alignItems: "center" }}
                      testID={`row-status-${row.company_id}`}
                    >
                      {st === "saving" ? (
                        <ActivityIndicator size="small" color={colors.brandPrimary} />
                      ) : st === "saved" ? (
                        <Text style={styles.savedTxt}>✓ Saved</Text>
                      ) : st === "error" ? (
                        <Text style={styles.errorTxt}>Failed</Text>
                      ) : (
                        <Ionicons name="flash-outline" size={14} color={colors.onSurfaceTertiary} />
                      )}
                    </View>
                  </View>
                );
              })
            )}
          </View>
        )}
      </ScrollView>

      {/* Email confirmation modal */}
      {emailModal ? (
        <View style={styles.overlay} testID="email-confirm-modal">
          <Pressable style={StyleSheet.absoluteFill} onPress={() => setEmailModal(false)} />
          <View style={styles.modal}>
            <Text style={styles.modalTitle}>Email this summary?</Text>
            <Text style={styles.modalSub}>
              The Monthly Challan Summary for {month} will be sent via the configured SMTP sender.
            </Text>
            <Text style={styles.modalLabel}>Recipient email</Text>
            <TextInput
              style={styles.modalInput}
              value={emailTo}
              onChangeText={setEmailTo}
              placeholder="name@example.com"
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="none"
              keyboardType="email-address"
              testID="email-to-input"
            />
            <View style={styles.modalActions}>
              <Pressable style={styles.modalCancel} onPress={() => setEmailModal(false)}>
                <Text style={styles.modalCancelTxt}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.modalConfirm, { backgroundColor: colors.brandPrimary }]}
                onPress={sendEmail}
                disabled={sendingEmail || !emailTo.trim()}
                testID="email-confirm-send"
              >
                {sendingEmail ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text style={styles.modalConfirmTxt}>Yes, Send Email</Text>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      ) : null}

      {/* WhatsApp confirmation modal */}
      {waModal ? (
        <View style={styles.overlay} testID="wa-confirm-modal">
          <Pressable style={StyleSheet.absoluteFill} onPress={() => setWaModal(false)} />
          <View style={styles.modal}>
            <Text style={styles.modalTitle}>Send via WhatsApp?</Text>
            <Text style={styles.modalSub}>
              WhatsApp will open with the {month} summary pre-filled — choose the
              contact / group there and press send.
            </Text>
            <View style={styles.modalActions}>
              <Pressable style={styles.modalCancel} onPress={() => setWaModal(false)}>
                <Text style={styles.modalCancelTxt}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[styles.modalConfirm, { backgroundColor: "#16A34A" }]}
                onPress={sendWhatsApp}
                testID="wa-confirm-send"
              >
                <Ionicons name="logo-whatsapp" size={15} color="#fff" />
                <Text style={styles.modalConfirmTxt}>Yes, Open WhatsApp</Text>
              </Pressable>
            </View>
          </View>
        </View>
      ) : null}

      {/* Per-firm Email / WhatsApp confirmation modal */}
      {sendModal ? (
        <View style={styles.overlay} testID="firm-send-modal">
          <Pressable style={StyleSheet.absoluteFill} onPress={() => setSendModal(null)} />
          <View style={styles.modal}>
            <Text style={styles.modalTitle}>
              {sendModal.kind === "email" ? "Email" : "WhatsApp"} — {sendModal.row.firm_name}
            </Text>
            <Text style={styles.modalSub}>
              Send this firm&apos;s {month} challan summary to its registered{" "}
              {sendModal.kind === "email" ? "email" : "WhatsApp number"}.
            </Text>
            <Text style={styles.modalLabel}>
              {sendModal.kind === "email" ? "Registered email" : "Registered WhatsApp number"}
            </Text>
            <TextInput
              style={styles.modalInput}
              value={sendTarget}
              onChangeText={setSendTarget}
              placeholder={sendModal.kind === "email" ? "name@example.com" : "+91 98XXXXXXXX"}
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="none"
              keyboardType={sendModal.kind === "email" ? "email-address" : "phone-pad"}
              testID="firm-send-target"
            />
            {!sendTarget.trim() ? (
              <Text style={styles.noRegTxt}>
                No registered {sendModal.kind === "email" ? "email" : "mobile"} found in
                Firm Master — type one above
                {sendModal.kind === "wa"
                  ? " or leave blank to pick a contact in WhatsApp"
                  : ""}
                .
              </Text>
            ) : null}
            <View style={styles.modalActions}>
              <Pressable style={styles.modalCancel} onPress={() => setSendModal(null)}>
                <Text style={styles.modalCancelTxt}>Cancel</Text>
              </Pressable>
              <Pressable
                style={[
                  styles.modalConfirm,
                  { backgroundColor: sendModal.kind === "email" ? colors.brandPrimary : "#16A34A" },
                ]}
                onPress={confirmFirmSend}
                disabled={sendingFirm || (sendModal.kind === "email" && !sendTarget.trim())}
                testID="firm-send-confirm"
              >
                {sendingFirm ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <>
                    <Ionicons
                      name={sendModal.kind === "email" ? "mail-outline" : "logo-whatsapp"}
                      size={15}
                      color="#fff"
                    />
                    <Text style={styles.modalConfirmTxt}>
                      {sendModal.kind === "email" ? "Yes, Send Email" : "Yes, Open WhatsApp"}
                    </Text>
                  </>
                )}
              </Pressable>
            </View>
          </View>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#F4F7F7" },
  scroll: { padding: spacing.lg, paddingBottom: 60 },
  headRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "flex-start",
    gap: 12,
    marginBottom: spacing.md,
  },
  title: { fontSize: 20, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 4, maxWidth: 560 },
  headActions: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  actionBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: radius.md,
  },
  actionBtnTxt: { color: "#fff", fontSize: 13, fontWeight: "700" },
  hintCard: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "#FFFBEB",
    borderWidth: 1,
    borderColor: "#FCD34D",
    borderRadius: radius.md,
    padding: 10,
    marginBottom: spacing.md,
  },
  hintTxt: { flex: 1, fontSize: 12, color: "#92400E" },
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    padding: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    marginBottom: spacing.md,
  },
  bannerOk: { backgroundColor: "#DCFCE7", borderColor: "#86EFAC" },
  bannerErr: { backgroundColor: "#FEE2E2", borderColor: "#FCA5A5" },
  table: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  tr: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  trAudit: { backgroundColor: "#FEF2F2" },
  thRow: { backgroundColor: "#F8FAFC" },
  th: {
    fontSize: 11,
    fontWeight: "800",
    color: colors.onSurfaceSecondary,
    letterSpacing: 0.4,
    textTransform: "uppercase",
  },
  firmName: { fontSize: 13, fontWeight: "700", color: colors.onSurface, flexShrink: 1 },
  auditTag: { fontSize: 10, fontWeight: "800", color: "#B91C1C", marginTop: 2 },
  badge: {
    alignSelf: "flex-start",
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: radius.pill,
  },
  badgeTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.3 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 10,
    paddingVertical: Platform.OS === "web" ? 8 : 6,
    fontSize: 13,
    color: colors.onSurface,
    backgroundColor: "#fff",
    minHeight: 36,
  },
  inputLocked: { backgroundColor: "#F1F5F9", color: colors.onSurfaceTertiary },
  byTxt: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 3 },
  rowSendBtn: {
    width: 26,
    height: 26,
    borderRadius: 13,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.brandTertiary,
    alignItems: "center",
    justifyContent: "center",
  },
  savedTxt: { fontSize: 10, fontWeight: "800", color: "#166534" },
  errorTxt: { fontSize: 10, fontWeight: "800", color: "#B91C1C" },
  noRegTxt: { fontSize: 11, color: "#B45309", marginTop: 6 },
  empty: {
    padding: 24,
    textAlign: "center",
    color: colors.onSurfaceSecondary,
    fontSize: 13,
  },
  overlay: {
    position: "absolute",
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: "rgba(15,23,42,0.55)",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  },
  modal: {
    width: 420,
    maxWidth: "92%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
    ...(Platform.OS === "web"
      ? ({ boxShadow: "0 24px 48px rgba(0,0,0,0.25)" } as any)
      : { elevation: 12 }),
  },
  modalTitle: { fontSize: 17, fontWeight: "800", color: colors.onSurface },
  modalSub: { fontSize: 12, color: colors.onSurfaceSecondary, marginTop: 6, marginBottom: 12 },
  modalLabel: { fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  modalInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.onSurface,
    backgroundColor: "#fff",
  },
  modalActions: { flexDirection: "row", justifyContent: "flex-end", gap: 10, marginTop: 16 },
  modalCancel: { paddingHorizontal: 14, paddingVertical: 10 },
  modalCancelTxt: { color: colors.onSurfaceSecondary, fontSize: 13, fontWeight: "700" },
  modalConfirm: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 16,
    paddingVertical: 10,
    borderRadius: radius.md,
  },
  modalConfirmTxt: { color: "#fff", fontSize: 13, fontWeight: "800" },
});
