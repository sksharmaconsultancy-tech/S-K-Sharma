// -----------------------------------------------------------------------------
// Iter 85 — Attractive Theme System (Super Admin only can switch)
//
// Each theme uses a rich primary hue paired with a vibrant but tasteful
// accent — designed to feel modern and premium for a B2B payroll portal.
//
// 7 presets, each with a distinct personality:
//   1. corporate_sapphire  — Navy Sapphire + Champagne Gold  (classic luxe)
//   2. executive_noir      — Rich Charcoal + Amber Glow      (sleek dark modern)
//   3. emerald_prestige    — Deep Emerald + Warm Copper       (executive nature)
//   4. royal_amethyst      — Royal Purple + Rose Pink         (bold SaaS)
//   5. ocean_breeze        — Deep Teal + Cyan Splash          (refreshing tech)
//   6. crimson_regal       — Regal Burgundy + Royal Gold      (Indian corporate)
//   7. slate_mint          — Cool Slate + Mint Fresh          (minimalist pro)
// -----------------------------------------------------------------------------

export type ThemeId =
  | "corporate_sapphire"
  | "executive_noir"
  | "emerald_prestige"
  | "royal_amethyst"
  | "ocean_breeze"
  | "crimson_regal"
  | "slate_mint"
  | "midnight_dark";

export type ThemeColors = {
  surface: string;
  onSurface: string;
  surfaceSecondary: string;
  onSurfaceSecondary: string;
  surfaceTertiary: string;
  onSurfaceTertiary: string;
  surfaceInverse: string;
  onSurfaceInverse: string;

  brand: string;
  brandPrimary: string;
  onBrandPrimary: string;
  brandSecondary: string;
  onBrandSecondary: string;
  brandTertiary: string;
  onBrandTertiary: string;

  cta: string;
  onCta: string;
  ctaTint: string;
  onCtaTint: string;

  accent: string;
  onAccent: string;
  accentTint: string;
  onAccentTint: string;

  success: string; onSuccess: string;
  warning: string; onWarning: string;
  error: string;   onError: string;
  info: string;    onInfo: string;

  border: string;
  borderStrong: string;
  divider: string;
};

type PresetDef = {
  id: ThemeId;
  name: string;
  vibe: string;
  description: string;
  primary: string;
  secondary: string;
  accent: string;
  colors: ThemeColors;
};

function buildPalette(
  primary: string,
  primarySoft: string,
  primaryTint: string,
  primaryTintText: string,
  accent: string,
  accentTint: string,
  accentTintText: string,
  surface = "#FAFAFB",
  surfaceTertiary = "#F1F0EC",
): ThemeColors {
  return {
    surface,
    onSurface: "#0F172A",
    surfaceSecondary: "#FFFFFF",
    onSurfaceSecondary: "#475569",
    surfaceTertiary,
    onSurfaceTertiary: "#6B7280",
    surfaceInverse: primary,
    onSurfaceInverse: "#FAFAFB",

    brand: primary,
    brandPrimary: primary,
    onBrandPrimary: "#FFFFFF",
    brandSecondary: primarySoft,
    onBrandSecondary: "#FFFFFF",
    brandTertiary: primaryTint,
    onBrandTertiary: primaryTintText,

    cta: accent,
    onCta: "#FFFFFF",
    ctaTint: accentTint,
    onCtaTint: accentTintText,

    accent: accent,
    onAccent: "#FFFFFF",
    accentTint: accentTint,
    onAccentTint: accentTintText,

    success: "#059669", onSuccess: "#FFFFFF",
    warning: "#D97706", onWarning: "#FFFFFF",
    error: "#DC2626",   onError:   "#FFFFFF",
    info: primary,      onInfo:    "#FFFFFF",

    border: "rgba(15,23,42,0.12)",
    borderStrong: "#B8BEBE",
    divider: "rgba(15,23,42,0.07)",
  };
}

export const THEME_PRESETS: PresetDef[] = [
  {
    id: "corporate_sapphire",
    name: "Corporate Sapphire",
    vibe: "Classic Luxe",
    description: "Deep sapphire blue with champagne gold — timeless banking authority.",
    primary: "#0A2540",
    secondary: "#1E3A8A",
    accent: "#FFC96B",
    colors: buildPalette(
      "#0A2540", "#1E3A8A", "#DBE4F0", "#0A2540",
      "#FFC96B", "#FFF3D6", "#7C5900",
      "#FAFBFC", "#EEF2F7",
    ),
  },
  {
    id: "executive_noir",
    name: "Executive Noir",
    vibe: "Sleek Dark",
    description: "Rich charcoal with amber glow — modern boardroom sophistication.",
    primary: "#1F1F23",
    secondary: "#3F3F46",
    accent: "#F59E0B",
    colors: buildPalette(
      "#1F1F23", "#3F3F46", "#E4E4E7", "#1F1F23",
      "#F59E0B", "#FEF3C7", "#92400E",
      "#FAFAFB", "#EEEDEB",
    ),
  },
  {
    id: "emerald_prestige",
    name: "Emerald Prestige",
    vibe: "Nature Executive",
    description: "Deep emerald with warm copper — grounded and premium.",
    primary: "#064E3B",
    secondary: "#047857",
    accent: "#EA8B47",
    colors: buildPalette(
      "#064E3B", "#047857", "#D1FAE5", "#064E3B",
      "#EA8B47", "#FDE4CE", "#7C3A0F",
      "#F9FBFA", "#EBEEEA",
    ),
  },
  {
    id: "royal_amethyst",
    name: "Royal Amethyst",
    vibe: "Bold Creative",
    description: "Royal purple with rose pink — bold modern SaaS energy.",
    primary: "#5B21B6",
    secondary: "#7C3AED",
    accent: "#EC4899",
    colors: buildPalette(
      "#5B21B6", "#7C3AED", "#EDE9FE", "#4C1D95",
      "#EC4899", "#FCE7F3", "#9F1239",
      "#FBFAFC", "#F0EDF4",
    ),
  },
  {
    id: "ocean_breeze",
    name: "Ocean Breeze",
    vibe: "Refreshing Tech",
    description: "Deep teal with cyan splash — refreshing yet corporate.",
    primary: "#0E7490",
    secondary: "#0891B2",
    accent: "#22D3EE",
    colors: buildPalette(
      "#0E7490", "#0891B2", "#CFFAFE", "#164E63",
      "#22D3EE", "#ECFEFF", "#155E75",
      "#F7FBFC", "#E8EFF1",
    ),
  },
  {
    id: "crimson_regal",
    name: "Crimson Regal",
    vibe: "Indian Corporate",
    description: "Regal burgundy with royal gold — traditional Indian executive.",
    primary: "#7F1D1D",
    secondary: "#991B1B",
    accent: "#F5B301",
    colors: buildPalette(
      "#7F1D1D", "#991B1B", "#FEE2E2", "#7F1D1D",
      "#F5B301", "#FEF3C7", "#78350F",
      "#FBFAFA", "#F3EEED",
    ),
  },
  {
    id: "slate_mint",
    name: "Slate Mint",
    vibe: "Minimalist Pro",
    description: "Cool slate with mint fresh — clean minimalist analytics.",
    primary: "#334155",
    secondary: "#475569",
    accent: "#10B981",
    colors: buildPalette(
      "#334155", "#475569", "#E2E8F0", "#1E293B",
      "#10B981", "#D1FAE5", "#065F46",
      "#F8FAFC", "#EEF2F6",
    ),
  },
  // Iter 89 — True Dark Mode preset. Inverts every surface + text token
  // so the whole portal (both admin web shell and employee mobile app)
  // adopts a proper night palette. Accent stays a soft indigo so CTAs
  // still pop against the near-black surface.
  {
    id: "midnight_dark",
    name: "Midnight Dark",
    vibe: "True Dark Mode",
    description: "Full dark palette with indigo accent — night-shift friendly.",
    primary: "#818CF8",
    secondary: "#A5B4FC",
    accent: "#F59E0B",
    colors: {
      // Surfaces (near-black stack, so the admin sidebar + cards read as
      // layered gray-on-black rather than a single flat sheet).
      surface: "#0B1120",
      onSurface: "#E5E7EB",
      surfaceSecondary: "#111827",
      onSurfaceSecondary: "#CBD5E1",
      surfaceTertiary: "#1F2937",
      onSurfaceTertiary: "#94A3B8",
      surfaceInverse: "#F8FAFC",
      onSurfaceInverse: "#0F172A",

      brand: "#818CF8",
      brandPrimary: "#818CF8",
      onBrandPrimary: "#0B1120",
      brandSecondary: "#6366F1",
      onBrandSecondary: "#FFFFFF",
      brandTertiary: "#312E81",
      onBrandTertiary: "#E0E7FF",

      cta: "#F59E0B",
      onCta: "#0B1120",
      ctaTint: "#78350F",
      onCtaTint: "#FEF3C7",

      accent: "#F59E0B",
      onAccent: "#0B1120",
      accentTint: "#78350F",
      onAccentTint: "#FEF3C7",

      success: "#10B981", onSuccess: "#0B1120",
      warning: "#F59E0B", onWarning: "#0B1120",
      error: "#F87171",   onError:   "#0B1120",
      info: "#60A5FA",    onInfo:    "#0B1120",

      border: "rgba(226,232,240,0.14)",
      borderStrong: "#334155",
      divider: "rgba(226,232,240,0.08)",
    },
  },
];

export const DEFAULT_THEME_ID: ThemeId = "corporate_sapphire";

/**
 * Iter 85 (fix) — Read the persisted choice SYNCHRONOUSLY at module load
 * so the first StyleSheet.create() call in any screen already sees the
 * user's preferred palette. On web we tap directly into localStorage
 * (no async). On native we can't peek at AsyncStorage synchronously,
 * so the ThemeProvider will still call applyThemePreset() during boot
 * — a hard reload after Save re-runs this snippet with the new id.
 */
const _STORAGE_KEY = "sksharma.theme.id.v1";
function _bootThemeSync(): ThemeId {
  try {
    if (typeof globalThis !== "undefined" && (globalThis as any).localStorage) {
      const saved = (globalThis as any).localStorage.getItem(_STORAGE_KEY);
      if (saved && THEME_PRESETS.find(p => p.id === saved)) {
        return saved as ThemeId;
      }
    }
  } catch { /* noop */ }
  return DEFAULT_THEME_ID;
}
const _BOOT_ID = _bootThemeSync();
const _BOOT_PRESET = THEME_PRESETS.find(p => p.id === _BOOT_ID) || THEME_PRESETS[0];

/**
 * The colors object every screen imports. It's mutated in-place by
 * `applyThemePreset()` — combined with a version bump in ThemeContext,
 * this triggers a full re-render of the app.
 */
export const colors: ThemeColors = { ..._BOOT_PRESET.colors };

/**
 * Shadow presets (mutable — shadowColor updates with the brand hue).
 */
export const shadow = {
  card: {
    shadowColor: colors.brandPrimary,
    shadowOpacity: 0.08,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 3,
  },
  cta: {
    shadowColor: colors.accent,
    shadowOpacity: 0.28,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 6,
  },
  tabPunch: {
    shadowColor: colors.accent,
    shadowOpacity: 0.32,
    shadowRadius: 16,
    shadowOffset: { width: 0, height: 6 },
    elevation: 8,
  },
};

/** Apply a preset by id — mutates `colors` and `shadow` in-place. */
export function applyThemePreset(id: ThemeId): void {
  const preset = THEME_PRESETS.find(p => p.id === id) || THEME_PRESETS[0];
  const c = preset.colors;
  (Object.keys(c) as (keyof ThemeColors)[]).forEach((k) => {
    (colors as any)[k] = c[k];
  });
  shadow.card.shadowColor = colors.brandPrimary;
  shadow.cta.shadowColor = colors.accent;
  shadow.tabPunch.shadowColor = colors.accent;
}

/* ---------------------------------------------------------------- */
/*  Static (theme-independent) tokens                               */
/* ---------------------------------------------------------------- */

export const spacing = {
  xs: 4, sm: 8, md: 16, lg: 24, xl: 32, xxl: 48, xxxl: 64,
};

export const radius = { sm: 8, md: 12, lg: 16, xl: 24, pill: 999 };

export const type = {
  h1: { fontSize: 28, fontWeight: "700" as const, lineHeight: 34 },
  h2: { fontSize: 24, fontWeight: "700" as const, lineHeight: 30 },
  h3: { fontSize: 20, fontWeight: "700" as const, lineHeight: 26 },
  h4: { fontSize: 18, fontWeight: "700" as const, lineHeight: 24 },
  h5: { fontSize: 16, fontWeight: "700" as const, lineHeight: 22 },
  h6: { fontSize: 14, fontWeight: "700" as const, lineHeight: 20 },
  body:    { fontSize: 14, fontWeight: "400" as const, lineHeight: 20 },
  label:   { fontSize: 13, fontWeight: "600" as const, lineHeight: 18 },
  caption: { fontSize: 12, fontWeight: "400" as const, lineHeight: 16 },
  tiny:    { fontSize: 11, fontWeight: "500" as const, lineHeight: 14 },

  // Legacy plain-number aliases — some older screens still use these.
  sm: 12,
  base: 14,
  md: 14,
  lg: 16,
  xl: 20,
  xxl: 24,
};
