/**
 * Theme preview — non-destructive
 *
 * Shows the current palette side-by-side with four proposed
 * professional alternatives. NO real theme is changed by this screen —
 * once you pick one, the main agent applies it globally.
 *
 * Reach it at /theme-preview from any signed-in state.
 */
import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

type Palette = {
  id: string;
  name: string;
  tagline: string;
  surface: string;
  onSurface: string;
  onSurfaceSecondary: string;
  brandPrimary: string;
  brandTertiary: string;
  onBrandTertiary: string;
  cta: string;
  onCta: string;
  success: string;
  warning: string;
  error: string;
  border: string;
  card: string;
};

const CURRENT: Palette = {
  id: "current",
  name: "Current — Navy & Amber",
  tagline: "Today's palette (unchanged if you keep this)",
  surface: "#FBFBF9",
  onSurface: "#12294F",
  onSurfaceSecondary: "#4B5A76",
  brandPrimary: "#1B3A6E",
  brandTertiary: "#E8ECF3",
  onBrandTertiary: "#1B3A6E",
  cta: "#E39A2A",
  onCta: "#FFFFFF",
  success: "#2D7A4F",
  warning: "#E39A2A",
  error: "#D32F2F",
  border: "rgba(27,58,110,0.10)",
  card: "#FFFFFF",
};

const OPTIONS: Palette[] = [
  {
    id: "corporate-teal",
    name: "1. Corporate Deep Teal",
    tagline: "Fintech & consulting — sophisticated, understated",
    surface: "#FAFAF9",
    onSurface: "#0F172A",
    onSurfaceSecondary: "#475569",
    brandPrimary: "#0F3D3E",
    brandTertiary: "#E6EDED",
    onBrandTertiary: "#0F3D3E",
    cta: "#B8860B",
    onCta: "#FFFFFF",
    success: "#059669",
    warning: "#D97706",
    error: "#DC2626",
    border: "rgba(15,61,62,0.12)",
    card: "#FFFFFF",
  },
  {
    id: "executive-charcoal",
    name: "2. Executive Charcoal",
    tagline: "Modern SaaS — minimal, monochrome + electric accent",
    surface: "#FFFFFF",
    onSurface: "#0F172A",
    onSurfaceSecondary: "#475569",
    brandPrimary: "#111827",
    brandTertiary: "#EEF2F7",
    onBrandTertiary: "#111827",
    cta: "#2563EB",
    onCta: "#FFFFFF",
    success: "#059669",
    warning: "#F59E0B",
    error: "#E11D48",
    border: "rgba(17,24,39,0.10)",
    card: "#F9FAFB",
  },
  {
    id: "enterprise-blue",
    name: "3. Enterprise Blue Refresh",
    tagline: "Trust & clarity — IBM/HP style",
    surface: "#F8FAFC",
    onSurface: "#0F172A",
    onSurfaceSecondary: "#475569",
    brandPrimary: "#1E40AF",
    brandTertiary: "#DBEAFE",
    onBrandTertiary: "#1E3A8A",
    cta: "#10B981",
    onCta: "#FFFFFF",
    success: "#059669",
    warning: "#F59E0B",
    error: "#E11D48",
    border: "rgba(30,64,175,0.12)",
    card: "#FFFFFF",
  },
  {
    id: "boutique-sage",
    name: "4. Boutique Sage",
    tagline: "Warm & premium — hospitality / boutique feel",
    surface: "#FAFAF9",
    onSurface: "#1C1917",
    onSurfaceSecondary: "#57534E",
    brandPrimary: "#14532D",
    brandTertiary: "#E7F1EA",
    onBrandTertiary: "#14532D",
    cta: "#EA580C",
    onCta: "#FFFFFF",
    success: "#15803D",
    warning: "#D97706",
    error: "#DC2626",
    border: "rgba(20,83,45,0.12)",
    card: "#FFFFFF",
  },
];

function Swatch({ label, color, textColor }: { label: string; color: string; textColor?: string }) {
  return (
    <View style={[swatchStyles.swatch, { backgroundColor: color }]}>
      <Text style={[swatchStyles.label, { color: textColor || "#fff" }]}>{label}</Text>
    </View>
  );
}

const swatchStyles = StyleSheet.create({
  swatch: {
    width: 68,
    height: 42,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(0,0,0,0.06)",
  },
  label: {
    fontSize: 9,
    fontWeight: "700",
    letterSpacing: 0.3,
  },
});

function PalettePreview({ p }: { p: Palette }) {
  return (
    <View
      style={[
        cardStyles.card,
        { backgroundColor: p.surface, borderColor: p.border },
      ]}
    >
      <Text style={[cardStyles.name, { color: p.onSurface }]}>{p.name}</Text>
      <Text style={[cardStyles.tagline, { color: p.onSurfaceSecondary }]}>
        {p.tagline}
      </Text>

      {/* Swatch row */}
      <View style={cardStyles.swatchRow}>
        <Swatch label="PRIMARY" color={p.brandPrimary} />
        <Swatch label="CTA" color={p.cta} textColor={p.onCta} />
        <Swatch label="OK" color={p.success} />
        <Swatch label="WARN" color={p.warning} />
        <Swatch label="ERR" color={p.error} />
      </View>

      {/* Mock header */}
      <View style={[cardStyles.mockHeader, { backgroundColor: p.brandPrimary }]}>
        <Ionicons name="home" size={16} color="#fff" />
        <Text style={cardStyles.mockHeaderTxt}>Dashboard</Text>
      </View>

      {/* Mock bento tile */}
      <View style={cardStyles.row}>
        <View
          style={[
            cardStyles.tile,
            { backgroundColor: p.brandTertiary },
          ]}
        >
          <Ionicons
            name="people-outline"
            size={16}
            color={p.onBrandTertiary}
          />
          <Text style={[cardStyles.tileNum, { color: p.onBrandTertiary }]}>
            48
          </Text>
          <Text style={[cardStyles.tileLbl, { color: p.onBrandTertiary }]}>
            Employees
          </Text>
        </View>
        <View style={[cardStyles.tile, { backgroundColor: p.brandPrimary }]}>
          <Ionicons name="finger-print" size={16} color="#fff" />
          <Text style={[cardStyles.tileNum, { color: "#fff" }]}>32</Text>
          <Text style={[cardStyles.tileLbl, { color: "#fff" }]}>Present</Text>
        </View>
      </View>

      {/* Mock CTA button + secondary */}
      <View style={cardStyles.btnRow}>
        <View style={[cardStyles.ctaBtn, { backgroundColor: p.cta }]}>
          <Text style={[cardStyles.ctaTxt, { color: p.onCta }]}>Punch IN</Text>
        </View>
        <View
          style={[
            cardStyles.secondaryBtn,
            { borderColor: p.brandPrimary },
          ]}
        >
          <Text style={[cardStyles.secondaryTxt, { color: p.brandPrimary }]}>
            View history
          </Text>
        </View>
      </View>

      {/* Mock list row */}
      <View style={[cardStyles.listRow, { backgroundColor: p.card, borderColor: p.border }]}>
        <View
          style={[
            cardStyles.avatar,
            { backgroundColor: p.brandTertiary },
          ]}
        >
          <Ionicons
            name="person"
            size={16}
            color={p.onBrandTertiary}
          />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[cardStyles.rowName, { color: p.onSurface }]}>
            Aakash Verma
          </Text>
          <Text style={[cardStyles.rowMeta, { color: p.onSurfaceSecondary }]}>
            EMP-0142 · 09:02 AM
          </Text>
        </View>
        <View style={[cardStyles.pill, { backgroundColor: p.success + "20" }]}>
          <Text style={[cardStyles.pillTxt, { color: p.success }]}>Still in</Text>
        </View>
      </View>
    </View>
  );
}

const cardStyles = StyleSheet.create({
  card: {
    borderRadius: 16,
    padding: 16,
    marginBottom: 20,
    borderWidth: 1,
    gap: 12,
  },
  name: { fontSize: 16, fontWeight: "800" },
  tagline: { fontSize: 12, marginTop: 2 },
  swatchRow: {
    flexDirection: "row",
    gap: 6,
  },
  mockHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderRadius: 8,
  },
  mockHeaderTxt: { color: "#fff", fontSize: 14, fontWeight: "700" },
  row: { flexDirection: "row", gap: 8 },
  tile: {
    flex: 1,
    borderRadius: 12,
    padding: 12,
    gap: 4,
  },
  tileNum: { fontSize: 22, fontWeight: "800" },
  tileLbl: { fontSize: 11, fontWeight: "600" },
  btnRow: { flexDirection: "row", gap: 8 },
  ctaBtn: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  ctaTxt: { fontSize: 13, fontWeight: "800" },
  secondaryBtn: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
    borderWidth: 1,
  },
  secondaryTxt: { fontSize: 13, fontWeight: "700" },
  listRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: 10,
    borderRadius: 10,
    borderWidth: 1,
  },
  avatar: {
    width: 34,
    height: 34,
    borderRadius: 8,
    alignItems: "center",
    justifyContent: "center",
  },
  rowName: { fontSize: 13, fontWeight: "700" },
  rowMeta: { fontSize: 11, marginTop: 2 },
  pill: {
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
  },
  pillTxt: { fontSize: 10, fontWeight: "800" },
});

export default function ThemePreviewScreen() {
  const router = useRouter();
  const [selected, setSelected] = useState<string>(CURRENT.id);
  const palettes = [CURRENT, ...OPTIONS];

  return (
    <View style={rootStyles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: "#fff" }}>
        <View style={rootStyles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="arrow-back" size={22} color="#0F172A" />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={rootStyles.title}>Theme preview</Text>
            <Text style={rootStyles.sub}>
              Tap a palette to mark your choice. Nothing is applied until you
              tell the agent.
            </Text>
          </View>
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={rootStyles.scroll}>
        {palettes.map((p) => {
          const isSel = selected === p.id;
          return (
            <Pressable
              key={p.id}
              onPress={() => setSelected(p.id)}
              style={[
                rootStyles.pickable,
                isSel && { borderColor: p.brandPrimary, borderWidth: 2 },
              ]}
              testID={`palette-${p.id}`}
            >
              <PalettePreview p={p} />
              <View style={rootStyles.selRow}>
                <View
                  style={[
                    rootStyles.radio,
                    isSel && { backgroundColor: p.brandPrimary, borderColor: p.brandPrimary },
                  ]}
                >
                  {isSel ? (
                    <Ionicons name="checkmark" size={14} color="#fff" />
                  ) : null}
                </View>
                <Text style={rootStyles.selTxt}>
                  {isSel ? "Selected — tell the agent to apply" : "Tap to select this palette"}
                </Text>
              </View>
            </Pressable>
          );
        })}
        <View style={{ height: 40 }} />
      </ScrollView>
    </View>
  );
}

const rootStyles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#F1F2F5" },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingHorizontal: 20,
    paddingVertical: 14,
    backgroundColor: "#fff",
  },
  title: { color: "#0F172A", fontSize: 20, fontWeight: "800" },
  sub: { color: "#4B5A76", fontSize: 12, marginTop: 2 },
  scroll: { padding: 16 },
  pickable: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: "transparent",
    marginBottom: 16,
  },
  selRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    paddingHorizontal: 16,
    paddingBottom: 14,
    marginTop: -14,
  },
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: "#B9BEC8",
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#fff",
  },
  selTxt: { color: "#4B5A76", fontSize: 12, fontWeight: "700" },
});
