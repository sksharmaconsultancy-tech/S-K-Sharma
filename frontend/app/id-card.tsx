/**
 * Employee ID Card — Iter 74.
 *
 * A polished, front-only photo-ID card the employee can show at the gate
 * or share as a screenshot. Data comes from `/api/me/id-card` and a QR
 * code encodes ``SKSCO|<company_code>|<employee_code>|<user_id>`` so the
 * turnstile scanner (or an admin phone) can look the person up quickly.
 *
 * The card is a plain React Native View — no native canvas — so it
 * renders identically on iOS, Android and Web.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Platform,
  Alert,
  ScrollView,
  Image,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";
import QRCode from "react-native-qrcode-svg";
import { LinearGradient } from "expo-linear-gradient";

import { api } from "@/src/api/client";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { formatDate } from "@/src/utils/date";
import * as Print from "expo-print";
import * as Sharing from "expo-sharing";

type IdCard = {
  employee: {
    user_id?: string;
    name?: string;
    employee_code?: string;
    designation?: string;
    department?: string;
    doj?: string;
    phone?: string;
    email?: string;
    picture?: string;
    blood_group?: string;
    // Iter 85 — Address shown on the downloadable ID card.
    address?: string;
  };
  company: {
    name?: string;
    company_code?: string;
    logo_base64?: string;
    address?: string;
  };
  qr_payload: string;
  generated_at?: string;
};

function initials(name?: string): string {
  if (!name) return "SK";
  const parts = name.trim().split(/\s+/);
  const a = parts[0]?.[0] || "";
  const b = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (a + b).toUpperCase() || "SK";
}

// Iter 85 — Delegates to the centralised DD-MM-YYYY formatter so every
// screen uses the same date rendering.
function fmtDate(iso?: string): string {
  return formatDate(iso);
}

// Iter 85 — HTML-safe escape for values interpolated into the PDF template.
function escapeHtml(s: any): string {
  const v = s === null || s === undefined ? "" : String(s);
  return v
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function picUri(pic?: string): string | undefined {
  if (!pic) return undefined;
  if (pic.startsWith("data:") || pic.startsWith("http")) return pic;
  return `data:image/jpeg;base64,${pic}`;
}

export default function IdCardScreen() {
  const router = useRouter();
  const [data, setData] = useState<IdCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const res = await api<IdCard>("/me/id-card");
      setData(res);
    } catch (e: any) {
      setErr(e?.message || "Could not load your ID card");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const [downloading, setDownloading] = useState(false);

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") globalThis.alert(msg);
    else Alert.alert("ID Card", msg);
  };

  /**
   * Iter 85 — Generate a printable PDF of the employee ID card.
   * We render a self-contained HTML template (photo, logo, name,
   * company, DOJ, phone, email, address, QR) and hand it to
   * expo-print → PDF, then share it via the OS sheet (mobile) or
   * download it directly in the browser (web).
   */
  const onDownload = async () => {
    if (!data || downloading) return;
    setDownloading(true);
    try {
      const emp = data.employee || {};
      const co = data.company || {};
      const photo = picUri(emp.picture);
      const logo = picUri(co.logo_base64);
      const html = `
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    * { box-sizing: border-box; }
    body { font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
           margin: 0; padding: 24px; background: #FAFAFA; color: #0F172A; }
    .card { width: 380px; margin: 0 auto; border-radius: 14px;
            background: #fff; overflow: hidden;
            box-shadow: 0 8px 24px rgba(0,0,0,0.12);
            border: 1px solid rgba(0,0,0,0.06); }
    .hdr { padding: 14px 16px; color: #fff;
           background: linear-gradient(135deg, ${colors.brandPrimary}, ${colors.brandSecondary});
           display: flex; align-items: center; gap: 10px; }
    .hdr img { width: 36px; height: 36px; border-radius: 8px;
               background: #fff; object-fit: contain; }
    .hdr .name { flex: 1; font-weight: 800; font-size: 14px; }
    .hdr .code { font-size: 10px; opacity: 0.85; margin-top: 2px; }
    .hdr .badge { font-size: 9px; font-weight: 800; letter-spacing: 1px;
                  background: rgba(255,255,255,0.18); padding: 4px 8px;
                  border-radius: 999px; }
    .body { padding: 18px; text-align: center; }
    .photo { width: 108px; height: 108px; border-radius: 54px;
             margin: 0 auto 12px; background: #E5E7EB;
             object-fit: cover; border: 3px solid ${colors.accent}; }
    .photo-fallback { width: 108px; height: 108px; border-radius: 54px;
             margin: 0 auto 12px; background: ${colors.brandTertiary};
             color: ${colors.brandPrimary}; font-weight: 800; font-size: 34px;
             display: flex; align-items: center; justify-content: center;
             border: 3px solid ${colors.accent}; }
    .n { font-size: 18px; font-weight: 800; margin: 0; }
    .d { font-size: 12px; color: #6B7280; margin-top: 2px; }
    .meta { margin-top: 14px; text-align: left; font-size: 11px;
            color: #374151; line-height: 1.5; }
    .meta div { display: flex; padding: 4px 0;
                border-bottom: 1px dashed rgba(0,0,0,0.08); }
    .meta div span:first-child { flex: 0 0 100px; color: #6B7280;
                                  text-transform: uppercase; font-weight: 700;
                                  font-size: 10px; letter-spacing: 0.4px; }
    .meta div span:last-child { flex: 1; color: #0F172A; font-weight: 600; }
    .ftr { padding: 10px 16px; text-align: center; font-size: 9px;
           color: #9CA3AF; border-top: 1px dashed rgba(0,0,0,0.08); }
  </style>
</head>
<body>
  <div class="card">
    <div class="hdr">
      ${logo ? `<img src="${logo}" />` : `<div class="hdr img" style="background:#fff;color:${colors.brandPrimary};width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:800;">SK</div>`}
      <div class="name">
        ${escapeHtml(co.name || "S.K. Sharma & Co.")}
        ${co.company_code ? `<div class="code">${escapeHtml(co.company_code)}</div>` : ""}
      </div>
      <div class="badge">EMPLOYEE ID</div>
    </div>
    <div class="body">
      ${photo
        ? `<img class="photo" src="${photo}" />`
        : `<div class="photo-fallback">${escapeHtml(initials(emp.name))}</div>`
      }
      <div class="n">${escapeHtml(emp.name || "—")}</div>
      ${emp.designation ? `<div class="d">${escapeHtml(emp.designation)}</div>` : ""}

      <div class="meta">
        <div><span>Employee ID</span><span>${escapeHtml(emp.employee_code || "—")}</span></div>
        <div><span>Company</span><span>${escapeHtml(co.name || "—")}</span></div>
        <div><span>Date of Joining</span><span>${escapeHtml(formatDate(emp.doj))}</span></div>
        <div><span>Contact No.</span><span>${escapeHtml(emp.phone || "—")}</span></div>
        ${emp.email ? `<div><span>Email</span><span>${escapeHtml(emp.email)}</span></div>` : ""}
        ${emp.blood_group ? `<div><span>Blood Group</span><span>${escapeHtml(emp.blood_group)}</span></div>` : ""}
        <div><span>Address</span><span>${escapeHtml(emp.address || co.address || "—")}</span></div>
      </div>
    </div>
    <div class="ftr">
      Issued by ${escapeHtml(co.name || "S.K. Sharma & Co.")}
      · If found, please return to the head office.
    </div>
  </div>
</body>
</html>`;

      const { uri } = await Print.printToFileAsync({ html, base64: false });
      const filename = `ID_Card_${(emp.employee_code || emp.name || "employee").replace(/[^A-Za-z0-9_-]+/g, "_")}.pdf`;

      if (Platform.OS === "web") {
        // On web, expo-print returns a blob URL — trigger a browser download.
        const a = document.createElement("a");
        a.href = uri;
        a.download = filename;
        a.click();
        setTimeout(() => { try { URL.revokeObjectURL(uri); } catch { /* noop */ } }, 30_000);
      } else {
        const canShare = await Sharing.isAvailableAsync();
        if (canShare) {
          await Sharing.shareAsync(uri, {
            mimeType: "application/pdf",
            dialogTitle: "Employee ID Card",
            UTI: "com.adobe.pdf",
          });
        } else {
          showMsg(`Saved to ${uri}`);
        }
      }
    } catch (e: any) {
      showMsg(e?.message || "Could not generate PDF");
    } finally {
      setDownloading(false);
    }
  };

  if (loading) {
    return (
      <SafeAreaView style={styles.centerScreen}>
        <ActivityIndicator color={colors.brandPrimary} size="large" />
      </SafeAreaView>
    );
  }

  if (err || !data) {
    return (
      <SafeAreaView style={styles.centerScreen}>
        <Ionicons name="alert-circle-outline" size={40} color={colors.error} />
        <Text style={styles.errTitle}>Unable to load ID card</Text>
        <Text style={styles.errBody}>{err || "Try again in a moment."}</Text>
        <Pressable style={styles.retryBtn} onPress={load}>
          <Text style={styles.retryBtnTxt}>Retry</Text>
        </Pressable>
      </SafeAreaView>
    );
  }

  const emp = data.employee;
  const co = data.company || {};
  const photo = picUri(emp.picture);
  const logo = picUri(co.logo_base64);

  return (
    <SafeAreaView style={styles.wrap} edges={["top", "left", "right"]}>
      {/* Top bar */}
      <View style={styles.topBar}>
        <Pressable
          onPress={() => router.back()}
          style={styles.iconBtn}
          hitSlop={8}
        >
          <Ionicons name="chevron-back" size={22} color={colors.onSurface} />
        </Pressable>
        <Text style={styles.topTitle}>My ID Card</Text>
        <Pressable
          onPress={onDownload}
          style={styles.iconBtn}
          hitSlop={8}
          disabled={downloading}
          testID="id-card-download"
        >
          {downloading ? (
            <ActivityIndicator size="small" color={colors.brandPrimary} />
          ) : (
            <Ionicons name="download-outline" size={20} color={colors.onSurface} />
          )}
        </Pressable>
      </View>

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Card */}
        <View style={styles.card} testID="id-card">
          <LinearGradient
            colors={[colors.brandPrimary, colors.brandSecondary]}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 1 }}
            style={styles.cardHeader}
          >
            <View style={styles.logoRow}>
              {logo ? (
                <Image source={{ uri: logo }} style={styles.logoImg} />
              ) : (
                <View style={styles.logoFallback}>
                  <Text style={styles.logoFallbackTxt}>SK</Text>
                </View>
              )}
              <View style={{ flex: 1 }}>
                <Text style={styles.companyName} numberOfLines={1}>
                  {co.name || "S.K. Sharma & Co."}
                </Text>
                {co.company_code ? (
                  <Text style={styles.companyCode}>{co.company_code}</Text>
                ) : null}
              </View>
            </View>
            <Text style={styles.headerBadge}>EMPLOYEE ID</Text>
          </LinearGradient>

          <View style={styles.cardBody}>
            <View style={styles.photoWrap}>
              {photo ? (
                <Image source={{ uri: photo }} style={styles.photo} />
              ) : (
                <View style={styles.photoFallback}>
                  <Text style={styles.photoInitials}>{initials(emp.name)}</Text>
                </View>
              )}
            </View>

            <Text style={styles.name} numberOfLines={2}>{emp.name || "—"}</Text>
            {emp.designation ? (
              <Text style={styles.designation}>{emp.designation}</Text>
            ) : null}

            <View style={styles.metaGrid}>
              <MetaRow label="Employee ID" value={emp.employee_code || "—"} />
              {emp.designation ? (
                <MetaRow label="Designation" value={emp.designation} />
              ) : emp.department ? (
                <MetaRow label="Designation" value={emp.department} />
              ) : null}
              <MetaRow label="Date of Joining" value={fmtDate(emp.doj)} />
              {emp.blood_group ? (
                <MetaRow label="Blood Group" value={emp.blood_group} />
              ) : null}
              {emp.phone ? <MetaRow label="Phone" value={emp.phone} /> : null}
            </View>

            {/* QR */}
            <View style={styles.qrWrap}>
              <QRCode
                value={data.qr_payload}
                size={140}
                backgroundColor="#fff"
                color={colors.onSurface}
              />
              <Text style={styles.qrHint}>
                Scan at the gate to check-in
              </Text>
            </View>

            <View style={styles.footerRow}>
              <Text style={styles.footerTxt}>
                Issued by {co.name || "S.K. Sharma & Co."}
              </Text>
              <Text style={styles.footerTxt}>
                If found, please return to the head office.
              </Text>
            </View>
          </View>
        </View>

        <Text style={styles.helpText}>
          Show this card to the security desk. The QR encodes your employee
          code and is unique to you — do not share it.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaRow}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flex: 1, backgroundColor: colors.surface },
  centerScreen: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.lg,
    backgroundColor: colors.surface,
    gap: spacing.sm,
  },
  errTitle: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700" },
  errBody: { color: colors.onSurfaceSecondary, textAlign: "center" },
  retryBtn: {
    marginTop: spacing.md,
    backgroundColor: colors.brand,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
    borderRadius: radius.pill,
  },
  retryBtnTxt: { color: colors.onBrandPrimary, fontWeight: "700" },

  topBar: {
    height: 52,
    paddingHorizontal: spacing.md,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  iconBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
  },
  topTitle: {
    fontSize: type.lg,
    fontWeight: "700",
    color: colors.onSurface,
  },

  scroll: {
    padding: spacing.lg,
    alignItems: "center",
    gap: spacing.md,
  },
  card: {
    width: "100%",
    maxWidth: 380,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.xl,
    overflow: "hidden",
    ...shadow.card,
  },
  cardHeader: {
    padding: spacing.md,
    gap: spacing.sm,
  },
  logoRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  logoImg: {
    width: 44,
    height: 44,
    borderRadius: 8,
    backgroundColor: "#fff",
  },
  logoFallback: {
    width: 44,
    height: 44,
    borderRadius: 8,
    backgroundColor: "rgba(255,255,255,0.14)",
    alignItems: "center",
    justifyContent: "center",
  },
  logoFallbackTxt: { color: "#fff", fontWeight: "800" },
  companyName: {
    color: "#fff",
    fontSize: type.lg,
    fontWeight: "700",
  },
  companyCode: { color: "rgba(255,255,255,0.7)", fontSize: type.sm },
  headerBadge: {
    color: "rgba(255,255,255,0.85)",
    fontSize: 11,
    letterSpacing: 2,
    fontWeight: "700",
    marginTop: 4,
  },

  cardBody: {
    padding: spacing.lg,
    alignItems: "center",
    gap: spacing.sm,
  },
  photoWrap: {
    width: 110,
    height: 110,
    borderRadius: 55,
    borderWidth: 4,
    borderColor: colors.brandTertiary,
    overflow: "hidden",
    backgroundColor: colors.surfaceTertiary,
    marginTop: -50,
  },
  photo: { width: "100%", height: "100%" },
  photoFallback: {
    width: "100%",
    height: "100%",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.brand,
  },
  photoInitials: {
    color: colors.onBrandPrimary,
    fontSize: 34,
    fontWeight: "800",
  },

  name: {
    fontSize: type.xl,
    fontWeight: "800",
    color: colors.onSurface,
    textAlign: "center",
  },
  designation: {
    color: colors.onSurfaceSecondary,
    fontSize: type.base,
    marginTop: -4,
  },
  metaGrid: {
    width: "100%",
    marginTop: spacing.sm,
    gap: 6,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: 1,
    borderBottomColor: colors.divider,
  },
  metaLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    fontWeight: "600",
  },
  metaValue: {
    color: colors.onSurface,
    fontSize: type.sm,
    fontWeight: "600",
    maxWidth: "60%",
    textAlign: "right",
  },

  qrWrap: {
    marginTop: spacing.md,
    alignItems: "center",
    gap: 6,
  },
  qrHint: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
  },
  footerRow: {
    marginTop: spacing.md,
    alignItems: "center",
    gap: 2,
  },
  footerTxt: {
    color: colors.onSurfaceTertiary,
    fontSize: 11,
    textAlign: "center",
  },

  helpText: {
    color: colors.onSurfaceTertiary,
    fontSize: type.sm,
    textAlign: "center",
    marginTop: spacing.md,
    maxWidth: 380,
  },
});
