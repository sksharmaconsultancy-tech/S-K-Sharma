/**
 * Iter 438 (user request) — after Save / Finalize on the Compliance &
 * Actual Salary screens, offer to DOWNLOAD or MAIL the run's reports in
 * PDF / Excel / CSV / All formats.
 */
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Modal,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

export type ReportFormat = string;
export type FormatOption = { key: ReportFormat; label: string };
const DEFAULT_FORMATS: FormatOption[] = [
  { key: "pdf", label: "PDF" },
  { key: "xlsx", label: "Excel" },
  { key: "csv", label: "CSV" },
];

type Props = {
  visible: boolean;
  onClose: () => void;
  title: string; // e.g. "Compliance Salary — 2026-06"
  subtitle?: string; // e.g. "Saved as draft ✓" / "Finalized 🔒"
  employeeGroup?: string; // Iter 439 — group the run was processed for
  formatOptions?: FormatOption[]; // Iter 439 — e.g. PDF Format 1 / Format 2
  companyId?: string; // Iter 440 — fetch Firm Master registered email ids
  extraBody?: Record<string, any>; // Iter 442 — merged into the email POST
  defaultEmail?: string;
  emailEndpoint: string; // POST {to, formats}
  onDownload: (formats: ReportFormat[]) => Promise<void>;
};

export default function ReportsShareModal({
  visible,
  onClose,
  title,
  subtitle,
  employeeGroup,
  formatOptions,
  companyId,
  extraBody,
  defaultEmail,
  emailEndpoint,
  onDownload,
}: Props) {
  const OPTS = formatOptions?.length ? formatOptions : DEFAULT_FORMATS;
  const ALL = OPTS.map((o) => o.key);
  const LABELS: Record<string, string> = Object.fromEntries(
    OPTS.map((o) => [o.key, o.label]),
  );
  const [sel, setSel] = useState<ReportFormat[]>([...ALL]);
  const [email, setEmail] = useState("");
  // Iter 440 (user request) — Firm Master registered email id(s); pick
  // one / several / all before Send.
  const [firmEmails, setFirmEmails] = useState<string[]>([]);
  const [selEmails, setSelEmails] = useState<string[]>([]);
  const [downloading, setDownloading] = useState(false);
  const [mailing, setMailing] = useState(false);
  const [status, setStatus] = useState("");

  useEffect(() => {
    if (!visible) return;
    setSel(OPTS.map((o) => o.key));
    setStatus("");
    setEmail("");
    setFirmEmails([]);
    setSelEmails([]);
    (async () => {
      try {
        if (companyId) {
          const r = await api<{ emails: string[] }>(
            `/admin/firm-emails/${companyId}`,
          );
          const list = r.emails || [];
          setFirmEmails(list);
          setSelEmails([...list]); // default: all registered ids selected
          if (!list.length) setEmail(defaultEmail || "");
        } else {
          setEmail(defaultEmail || "");
        }
      } catch {
        setEmail(defaultEmail || "");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, companyId, defaultEmail]);

  const allOn = sel.length === ALL.length;
  const toggle = (f: ReportFormat) =>
    setSel((prev) =>
      prev.includes(f) ? prev.filter((x) => x !== f) : [...prev, f],
    );

  const doDownload = async () => {
    if (downloading) return;
    if (!sel.length) {
      setStatus("Select at least one report format first.");
      return;
    }
    setDownloading(true);
    setStatus("");
    try {
      await onDownload(sel);
      setStatus(
        `Downloaded ${sel.map((f) => LABELS[f]).join(", ")} ✓`,
      );
    } catch (e: any) {
      setStatus(e?.message || "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  const doMail = async () => {
    if (mailing) return;
    // Iter 440 (user request) — a format selection is MANDATORY; the mail
    // carries EXACTLY the selected formats.
    if (!sel.length) {
      setStatus("Select at least one report format first.");
      return;
    }
    const typed = email.trim();
    const recipients = [...selEmails];
    if (typed && typed.includes("@") && !recipients.includes(typed)) {
      recipients.push(typed);
    }
    if (!recipients.length) {
      setStatus(firmEmails.length
        ? "Pick at least one registered email (or type one)."
        : "Enter a valid email address first.");
      return;
    }
    setMailing(true);
    setStatus("");
    try {
      const r = await api<{ ok: boolean; message?: string }>(emailEndpoint, {
        method: "POST",
        body: { to: recipients, formats: sel, ...(extraBody || {}) },
      });
      setStatus(r.message || `Report emailed to ${recipients.join(", ")} ✓`);
    } catch (e: any) {
      setStatus(e?.message || "Email failed");
    } finally {
      setMailing(false);
    }
  };

  return (
    <Modal
      visible={visible}
      transparent
      animationType="none"
      onRequestClose={onClose}
    >
      <View
        style={{
          flex: 1,
          backgroundColor: "rgba(15,23,42,0.45)",
          alignItems: "center",
          justifyContent: "center",
          padding: 20,
        }}
      >
        <View
          style={{
            backgroundColor: colors.surface,
            borderRadius: 14,
            padding: 18,
            width: "100%",
            maxWidth: 480,
          }}
        >
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              marginBottom: 4,
            }}
          >
            <Ionicons
              name="document-attach-outline"
              size={18}
              color={colors.brandPrimary}
            />
            <Text
              style={{
                flex: 1,
                marginLeft: 8,
                fontWeight: "800",
                color: colors.onSurface,
                fontSize: 14,
              }}
            >
              Download / Mail Reports
            </Text>
            <Pressable onPress={onClose} hitSlop={8} testID="rsm-close">
              <Ionicons name="close" size={20} color={colors.onSurfaceTertiary} />
            </Pressable>
          </View>
          <Text
            style={{
              color: colors.onSurfaceSecondary,
              fontSize: 12.5,
              marginBottom: employeeGroup ? 6 : 12,
            }}
          >
            {title}
            {subtitle ? ` · ${subtitle}` : ""}
          </Text>
          {employeeGroup ? (
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                alignSelf: "flex-start",
                backgroundColor: colors.brandTertiary,
                borderRadius: 999,
                paddingVertical: 4,
                paddingHorizontal: 10,
                marginBottom: 12,
              }}
              testID="rsm-group"
            >
              <Ionicons name="people-outline" size={12} color={colors.brandPrimary} />
              <Text
                style={{
                  fontSize: 11.5,
                  fontWeight: "800",
                  color: colors.brandPrimary,
                }}
              >
                Employee Group: {employeeGroup}
              </Text>
            </View>
          ) : null}

          <Text
            style={{
              fontSize: 11,
              fontWeight: "800",
              color: colors.onSurfaceTertiary,
              marginBottom: 6,
              textTransform: "uppercase",
            }}
          >
            Report format
          </Text>
          <View
            style={{
              flexDirection: "row",
              flexWrap: "wrap",
              gap: 8,
              marginBottom: 14,
            }}
          >
            <Pressable
              onPress={() => setSel(allOn ? [] : [...ALL])}
              style={{
                paddingVertical: 7,
                paddingHorizontal: 14,
                borderRadius: 999,
                borderWidth: 1,
                borderColor: allOn ? colors.brandPrimary : colors.divider,
                backgroundColor: allOn ? colors.brandPrimary : colors.surface,
              }}
              testID="rsm-fmt-all"
            >
              <Text
                style={{
                  fontSize: 12.5,
                  fontWeight: "800",
                  color: allOn ? "#FFF" : colors.onSurfaceSecondary,
                }}
              >
                All
              </Text>
            </Pressable>
            {ALL.map((f) => {
              const on = sel.includes(f);
              return (
                <Pressable
                  key={f}
                  onPress={() => toggle(f)}
                  style={{
                    paddingVertical: 7,
                    paddingHorizontal: 14,
                    borderRadius: 999,
                    borderWidth: 1,
                    borderColor: on ? colors.brandPrimary : colors.divider,
                    backgroundColor: on ? colors.brandTertiary : colors.surface,
                  }}
                  testID={`rsm-fmt-${f}`}
                >
                  <Text
                    style={{
                      fontSize: 12.5,
                      fontWeight: "800",
                      color: on ? colors.brandPrimary : colors.onSurfaceSecondary,
                    }}
                  >
                    {LABELS[f]}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <Pressable
            onPress={doDownload}
            disabled={downloading}
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              paddingVertical: 11,
              borderRadius: 10,
              backgroundColor: sel.length ? colors.brandPrimary : colors.divider,
              marginBottom: 12,
            }}
            testID="rsm-download"
          >
            {downloading ? (
              <ActivityIndicator color="#FFF" size="small" />
            ) : (
              <Ionicons name="download-outline" size={16} color="#FFF" />
            )}
            <Text style={{ color: "#FFF", fontWeight: "800", fontSize: 13 }}>
              Download {sel.length === ALL.length ? "All" : sel.map((f) => LABELS[f]).join(" + ") || "…"}
            </Text>
          </Pressable>

          <Text
            style={{
              fontSize: 11,
              fontWeight: "800",
              color: colors.onSurfaceTertiary,
              marginBottom: 6,
              textTransform: "uppercase",
            }}
          >
            Or mail the reports
          </Text>
          {firmEmails.length > 0 && (
            <View
              style={{
                flexDirection: "row",
                flexWrap: "wrap",
                gap: 8,
                marginBottom: 8,
              }}
            >
              <Pressable
                onPress={() =>
                  setSelEmails(
                    selEmails.length === firmEmails.length ? [] : [...firmEmails],
                  )
                }
                style={{
                  paddingVertical: 6,
                  paddingHorizontal: 12,
                  borderRadius: 999,
                  borderWidth: 1,
                  borderColor:
                    selEmails.length === firmEmails.length
                      ? "#166534"
                      : colors.divider,
                  backgroundColor:
                    selEmails.length === firmEmails.length
                      ? "#166534"
                      : colors.surface,
                }}
                testID="rsm-mailto-all"
              >
                <Text
                  style={{
                    fontSize: 11.5,
                    fontWeight: "800",
                    color:
                      selEmails.length === firmEmails.length
                        ? "#FFF"
                        : colors.onSurfaceSecondary,
                  }}
                >
                  All Firm Emails
                </Text>
              </Pressable>
              {firmEmails.map((fe) => {
                const on = selEmails.includes(fe);
                return (
                  <Pressable
                    key={fe}
                    onPress={() =>
                      setSelEmails((prev) =>
                        on ? prev.filter((x) => x !== fe) : [...prev, fe],
                      )
                    }
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: 5,
                      paddingVertical: 6,
                      paddingHorizontal: 12,
                      borderRadius: 999,
                      borderWidth: 1,
                      borderColor: on ? "#166534" : colors.divider,
                      backgroundColor: on ? "#DCFCE7" : colors.surface,
                    }}
                    testID={`rsm-mailto-${fe}`}
                  >
                    <Ionicons
                      name={on ? "checkmark-circle" : "ellipse-outline"}
                      size={13}
                      color={on ? "#166534" : colors.onSurfaceTertiary}
                    />
                    <Text
                      style={{
                        fontSize: 11.5,
                        fontWeight: "700",
                        color: on ? "#166534" : colors.onSurfaceSecondary,
                      }}
                    >
                      {fe}
                    </Text>
                  </Pressable>
                );
              })}
            </View>
          )}
          <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}>
            <TextInput
              value={email}
              onChangeText={setEmail}
              placeholder={firmEmails.length
                ? "add another email (optional)"
                : "recipient@email.com"}
              placeholderTextColor={colors.onSurfaceTertiary}
              autoCapitalize="none"
              keyboardType="email-address"
              style={{
                flex: 1,
                borderWidth: 1,
                borderColor: colors.divider,
                borderRadius: 10,
                paddingVertical: 9,
                paddingHorizontal: 12,
                fontSize: 13,
                color: colors.onSurface,
              }}
              testID="rsm-email"
            />
            <Pressable
              onPress={doMail}
              disabled={mailing}
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: 6,
                paddingVertical: 10,
                paddingHorizontal: 14,
                borderRadius: 10,
                backgroundColor: "#166534",
                opacity: mailing || !sel.length ? 0.6 : 1,
              }}
              testID="rsm-send"
            >
              {mailing ? (
                <ActivityIndicator color="#FFF" size="small" />
              ) : (
                <Ionicons name="mail-outline" size={15} color="#FFF" />
              )}
              <Text style={{ color: "#FFF", fontWeight: "800", fontSize: 12.5 }}>
                Send
              </Text>
            </Pressable>
          </View>
          {status ? (
            <Text
              style={{
                marginTop: 10,
                fontSize: 12,
                fontWeight: "700",
                color: /fail|valid|error/i.test(status)
                  ? "#B91C1C"
                  : "#166534",
              }}
              testID="rsm-status"
            >
              {status}
            </Text>
          ) : null}
        </View>
      </View>
    </Modal>
  );
}
