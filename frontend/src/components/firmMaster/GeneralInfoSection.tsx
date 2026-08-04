/**
 * Iter 484 — Firm Master → 1. General Information (ERP redesign).
 * Company identity only — NO contact fields (those live in Contact Details).
 * Responsive 2-column desktop / 1-column mobile grid, drag & drop logo with
 * crop-to-square, inline validation, company-code uniqueness check.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, Image, Platform, useWindowDimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api/client";
import DateField from "@/src/components/DateField";
import { colors, radius, spacing } from "@/src/theme";
import { Card, FieldV2, DropdownV2, MiniBtn } from "./primitives";

const COMPANY_CATEGORIES = [
  "Private Limited", "Public Limited", "Partnership", "Proprietorship",
  "LLP", "Trust", "Society", "HUF", "Government", "Co-operative", "Other",
];
const BUSINESS_NATURES = [
  "Manufacturing", "Textile / Weaving", "Construction", "Information Technology",
  "Trading", "Services", "Hospitality", "Healthcare", "Education", "Logistics",
  "Agriculture", "Mining", "Retail", "Real Estate", "Finance / NBFC",
  "Security Services", "Facility Management", "Consultancy", "Other",
];
const ESTABLISHMENT_TYPES = [
  "Factory", "Shop & Establishment", "Contractor Establishment",
  "Mines", "Plantation", "Construction Site", "Other",
];
const ORGANIZATION_TYPES = [
  "Principal Employer", "Contractor", "Sub-Contractor", "Consultant", "Other",
];
const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED"];
const TIMEZONES = ["Asia/Kolkata", "Asia/Dubai", "Asia/Singapore", "UTC"];
const LANGUAGES = ["English", "Hindi"];
const THEME_SWATCHES = ["", "#1D4ED8", "#059669", "#7C3AED", "#DC2626", "#D97706", "#0891B2", "#334155"];

function fyOptions(): string[] {
  const y = new Date().getFullYear();
  const out: string[] = [];
  for (let i = y + 1; i >= y - 10; i--) out.push(`${i}-${String(i + 1).slice(2)}`);
  return out;
}

export default function GeneralInfoSection({
  master, updateSection, companyId,
}: {
  master: any;
  updateSection: (section: string, patch: Record<string, any>) => void;
  companyId: string;
}) {
  const { width } = useWindowDimensions();
  const twoCol = width >= 900;
  const g = master.general || {};
  const [codeStatus, setCodeStatus] = useState<"" | "checking" | "unique" | "taken">("");
  const [codeClash, setCodeClash] = useState("");
  const codeTimer = useRef<any>(null);
  const dropRef = useRef<any>(null);
  const [dragOver, setDragOver] = useState(false);
  const [cropSquare, setCropSquare] = useState(true);

  // --- Company Code uniqueness (debounced) ---------------------------------
  const checkCode = (code: string) => {
    if (codeTimer.current) clearTimeout(codeTimer.current);
    const c = (code || "").trim();
    if (!c) { setCodeStatus(""); return; }
    setCodeStatus("checking");
    codeTimer.current = setTimeout(async () => {
      try {
        const r = await api<{ unique: boolean; clash_with?: string }>(
          `/admin/firm-master-check-code?code=${encodeURIComponent(c)}&company_id=${companyId}`);
        setCodeStatus(r.unique ? "unique" : "taken");
        setCodeClash(r.clash_with || "");
      } catch { setCodeStatus(""); }
    }, 600);
  };

  const genCode = () => {
    const base = (g.company_name || master.company_name || "FIRM")
      .replace(/[^A-Za-z]/g, "").slice(0, 4).toUpperCase() || "FIRM";
    const code = base + String(Math.floor(100 + Math.random() * 900));
    updateSection("general", { company_code: code });
    checkCode(code);
  };

  // --- Logo: file processing (resize / crop-to-square via canvas) ----------
  const processLogoFile = (file: File) => {
    if (!/^image\/(png|jpeg|webp)$/.test(file.type)) {
      window.alert("Logo must be PNG, JPG or WebP.");
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      window.alert("Logo must be under 2 MB. Please resize and try again.");
      return;
    }
    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = String(reader.result);
      if (!cropSquare) {
        updateSection("logo", { image_base64: dataUrl, mime_type: file.type });
        return;
      }
      // Crop to centre square + downscale to max 512×512 before upload.
      const img = new (globalThis as any).Image();
      img.onload = () => {
        const side = Math.min(img.width, img.height);
        const sx = (img.width - side) / 2;
        const sy = (img.height - side) / 2;
        const out = Math.min(side, 512);
        const canvas = (globalThis as any).document.createElement("canvas");
        canvas.width = out; canvas.height = out;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, sx, sy, side, side, 0, 0, out, out);
        updateSection("logo", {
          image_base64: canvas.toDataURL("image/png"),
          mime_type: "image/png",
        });
      };
      img.onerror = () => updateSection("logo", { image_base64: dataUrl, mime_type: file.type });
      img.src = dataUrl;
    };
    reader.readAsDataURL(file);
  };

  const pickLogo = () => {
    if (Platform.OS !== "web") return;
    const input = (globalThis as any).document?.createElement?.("input");
    if (!input) return;
    input.type = "file";
    input.accept = "image/png,image/jpeg,image/webp";
    input.onchange = (e: any) => {
      const file = e?.target?.files?.[0];
      if (file) processLogoFile(file);
    };
    input.click();
  };

  // Drag & drop (web only) — attach native listeners to the drop zone.
  useEffect(() => {
    if (Platform.OS !== "web") return;
    const node = dropRef.current as any;
    if (!node) return;
    const over = (e: any) => { e.preventDefault(); setDragOver(true); };
    const leave = () => setDragOver(false);
    const drop = (e: any) => {
      e.preventDefault(); setDragOver(false);
      const file = e.dataTransfer?.files?.[0];
      if (file) processLogoFile(file);
    };
    node.addEventListener("dragover", over);
    node.addEventListener("dragleave", leave);
    node.addEventListener("drop", drop);
    return () => {
      node.removeEventListener("dragover", over);
      node.removeEventListener("dragleave", leave);
      node.removeEventListener("drop", drop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dropRef.current, cropSquare]);

  // --- Inline validation ----------------------------------------------------
  const nameErr = !(g.company_name || "").trim() ? "Company Name is required" : null;
  const today = new Date().toISOString().slice(0, 10);
  const startErr = g.firm_start_date && g.firm_start_date > today
    ? "Start Date cannot be greater than today" : null;
  const codeErr = codeStatus === "taken"
    ? `Code already used${codeClash ? ` by ${codeClash}` : ""}` : null;
  const codeHint = codeStatus === "unique" ? "✓ Code is available"
    : codeStatus === "checking" ? "Checking availability..." : null;

  const row = (children: React.ReactNode) => (
    <View style={[styles.row, !twoCol && { flexDirection: "column" }]}>{children}</View>
  );

  return (
    <View style={{ gap: spacing.md }}>
      <Card icon="business" title="General Information"
            subtitle="Company identity & basic information — contact details live in the Contact Details section">
        {row(<>
          <FieldV2 label="Company Name" required value={g.company_name}
                   error={nameErr} testID="gi-company-name"
                   onChange={(v) => updateSection("general", { company_name: v })} />
          <FieldV2 label="Short Name" value={g.short_name}
                   placeholder="e.g. SKS"
                   onChange={(v) => updateSection("general", { short_name: v })} />
        </>)}
        {row(<>
          <FieldV2 label="Company Code" value={g.company_code}
                   autoCapitalize="characters" error={codeErr} hint={codeHint}
                   testID="gi-company-code"
                   onChange={(v) => {
                     updateSection("general", { company_code: v.toUpperCase() });
                     checkCode(v);
                   }}
                   rightSlot={
                     <MiniBtn icon="refresh" label="Auto" onPress={genCode} testID="gi-gen-code" />
                   } />
          <FieldV2 label="Branch Code" value={g.branch_code}
                   onChange={(v) => updateSection("general", { branch_code: v })} />
        </>)}
        {row(<>
          <DropdownV2 label="Company Category" value={g.company_category}
                      options={COMPANY_CATEGORIES}
                      onChange={(v) => updateSection("general", { company_category: v })} />
          <DropdownV2 label="Business Nature" value={g.business_nature}
                      options={BUSINESS_NATURES} searchable
                      onChange={(v) => updateSection("general", { business_nature: v })} />
        </>)}
        {row(<>
          <FieldV2 label="Industry Type" value={g.industry_type}
                   onChange={(v) => updateSection("general", { industry_type: v })} />
          <DropdownV2 label="Establishment Type" value={g.establishment_type}
                      options={ESTABLISHMENT_TYPES}
                      onChange={(v) => updateSection("general", { establishment_type: v })} />
        </>)}
        {row(<>
          <DropdownV2 label="Organization Type" value={g.organization_type}
                      options={ORGANIZATION_TYPES}
                      onChange={(v) => updateSection("general", { organization_type: v })} />
          <View style={styles.dateWrap}>
            <Text style={styles.dateLbl}>Date of Incorporation</Text>
            <DateField value={g.date_of_incorporation || ""}
                       onChangeISO={(v) => updateSection("general", { date_of_incorporation: v })} />
          </View>
        </>)}
        {row(<>
          <View style={styles.dateWrap}>
            <Text style={styles.dateLbl}>Firm Start Date</Text>
            <DateField value={g.firm_start_date || ""}
                       onChangeISO={(v) => updateSection("general", { firm_start_date: v })} />
            {startErr ? <Text style={styles.errTxt}>⚠ {startErr}</Text> : null}
          </View>
          <DropdownV2 label="Financial Year" value={g.financial_year}
                      options={fyOptions()}
                      onChange={(v) => updateSection("general", { financial_year: v })} />
        </>)}
        {row(<>
          <DropdownV2 label="Assessment Year" value={g.assessment_year}
                      options={fyOptions()}
                      onChange={(v) => updateSection("general", { assessment_year: v })} />
          <DropdownV2 label="Currency" value={g.currency || "INR"}
                      options={CURRENCIES}
                      onChange={(v) => updateSection("general", { currency: v || "INR" })} />
        </>)}
        {row(<>
          <DropdownV2 label="Time Zone" value={g.timezone || "Asia/Kolkata"}
                      options={TIMEZONES}
                      onChange={(v) => updateSection("general", { timezone: v || "Asia/Kolkata" })} />
          <DropdownV2 label="Language" value={g.language || "English"}
                      options={LANGUAGES}
                      onChange={(v) => updateSection("general", { language: v || "English" })} />
        </>)}
        {/* Company Status + Colour theme */}
        <View style={[styles.row, !twoCol && { flexDirection: "column" }]}>
          <View style={{ flex: 1 }}>
            <Text style={styles.dateLbl}>Company Status</Text>
            <View style={{ flexDirection: "row", gap: 8 }}>
              {["Active", "Inactive"].map((s) => {
                const on = (g.company_status || "Active") === s;
                return (
                  <Pressable key={s} testID={`gi-status-${s.toLowerCase()}`}
                    onPress={() => updateSection("general", { company_status: s })}
                    style={[styles.statusChip, on && {
                      backgroundColor: s === "Active" ? "#05966922" : "#DC262622",
                      borderColor: s === "Active" ? "#059669" : "#DC2626",
                    }]}>
                    <Ionicons name={on ? "radio-button-on" : "radio-button-off"} size={14}
                              color={on ? (s === "Active" ? "#059669" : "#DC2626") : colors.onSurfaceTertiary} />
                    <Text style={[styles.statusTxt, on && {
                      color: s === "Active" ? "#059669" : "#DC2626", fontWeight: "800",
                    }]}>{s}</Text>
                  </Pressable>
                );
              })}
            </View>
          </View>
          <View style={{ flex: 1 }}>
            <Text style={styles.dateLbl}>Company Color Theme (optional)</Text>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap" }}>
              {THEME_SWATCHES.map((c) => (
                <Pressable key={c || "none"}
                  onPress={() => updateSection("general", { color_theme: c })}
                  style={[styles.swatch,
                    c ? { backgroundColor: c } : { backgroundColor: colors.surface },
                    (g.color_theme || "") === c && styles.swatchOn]}>
                  {!c ? <Ionicons name="ban-outline" size={14} color={colors.onSurfaceTertiary} /> : null}
                </Pressable>
              ))}
            </View>
          </View>
        </View>
      </Card>

      {/* Logo card ---------------------------------------------------------- */}
      <Card icon="image" title="Company Logo"
            subtitle="Shown on the Web Portal, Mobile App, Salary Slips, Offer Letters, Reports & Email templates">
        <View style={{ flexDirection: twoCol ? "row" : "column", gap: spacing.lg, alignItems: twoCol ? "center" : "stretch" }}>
          <View style={styles.logoPreview}>
            {master.logo?.image_base64 ? (
              <Image source={{ uri: master.logo.image_base64 }}
                     style={{ width: 108, height: 108, borderRadius: 12 }}
                     resizeMode="contain" />
            ) : (
              <Ionicons name="business-outline" size={44} color={colors.onSurfaceTertiary} />
            )}
          </View>
          <View style={{ flex: 1, gap: 8 }}>
            <View
              ref={dropRef}
              style={[styles.dropZone, dragOver && {
                borderColor: colors.brandPrimary, backgroundColor: colors.brandTertiary,
              }]}
            >
              <Ionicons name="cloud-upload-outline" size={22} color={colors.brandPrimary} />
              <Text style={styles.dropTxt}>
                {dragOver ? "Drop to upload" : "Drag & drop the logo here, or"}
              </Text>
              <MiniBtn icon="folder-open-outline"
                       label={master.logo?.image_base64 ? "Replace Logo" : "Browse File"}
                       onPress={pickLogo} testID="gi-logo-browse" />
            </View>
            <Text style={styles.logoHint}>PNG / JPG / WebP · max 2 MB · recommended square 512×512</Text>
            <View style={{ flexDirection: "row", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
              <Pressable onPress={() => setCropSquare((v) => !v)}
                         style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <Ionicons name={cropSquare ? "checkbox" : "square-outline"} size={16}
                          color={cropSquare ? colors.brandPrimary : colors.onSurfaceTertiary} />
                <Text style={{ fontSize: 11.5, color: colors.onSurfaceSecondary }}>
                  Crop to square (512×512) before upload
                </Text>
              </Pressable>
              {master.logo?.image_base64 ? (
                <MiniBtn icon="trash-outline" label="Remove Logo" tone="danger"
                         onPress={() => updateSection("logo", { image_base64: null, mime_type: null })} />
              ) : null}
            </View>
          </View>
        </View>
      </Card>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", gap: spacing.md },
  dateWrap: { flex: 1, minWidth: 160 },
  dateLbl: { fontSize: 11.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginBottom: 4 },
  errTxt: { fontSize: 10.5, color: colors.error, marginTop: 3 },
  statusChip: {
    flexDirection: "row", alignItems: "center", gap: 6, borderWidth: 1.5,
    borderColor: colors.border, borderRadius: 999, paddingHorizontal: 14,
    paddingVertical: 8, backgroundColor: colors.surface,
  },
  statusTxt: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  swatch: {
    width: 30, height: 30, borderRadius: 8, borderWidth: 1.5,
    borderColor: colors.border, alignItems: "center", justifyContent: "center",
  },
  swatchOn: { borderColor: colors.onSurface, borderWidth: 2.5 },
  logoPreview: {
    width: 120, height: 120, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, backgroundColor: colors.surface,
    alignItems: "center", justifyContent: "center", alignSelf: "center",
  },
  dropZone: {
    borderWidth: 2, borderStyle: "dashed", borderColor: colors.border,
    borderRadius: radius.md, padding: 16, alignItems: "center", gap: 8,
    backgroundColor: colors.surface,
  },
  dropTxt: { fontSize: 12, color: colors.onSurfaceSecondary },
  logoHint: { fontSize: 11, color: colors.onSurfaceTertiary },
});
