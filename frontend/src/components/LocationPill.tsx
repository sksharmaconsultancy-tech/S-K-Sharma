/**
 * LocationPill — Iter 64.
 *
 * A small badge shown next to every punch to indicate where the record
 * was captured relative to the office:
 *
 *   • Inside     — green, GPS confirmed the employee was in the geofence
 *   • Outside    — amber, GPS confirmed the employee was outside the fence
 *   • No-GPS     — grey,  biometric-only punch (GPS was off / not required)
 *
 * Kept intentionally small so it fits inline in list rows on both mobile
 * and desktop.
 */
import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { colors } from "@/src/theme";

type Status = "inside" | "outside" | "no-gps" | string;

type Props = {
  status?: Status | null;
  distanceM?: number | null;
  size?: "sm" | "md";
  showDistance?: boolean;
};

const CONFIG: Record<
  "inside" | "outside" | "no-gps",
  { label: string; icon: keyof typeof Ionicons.glyphMap; bg: string; fg: string }
> = {
  inside: {
    label: "Inside office",
    icon: "checkmark-circle",
    bg: "#DCFCE7",
    fg: "#166534",
  },
  outside: {
    label: "Outside office",
    icon: "alert-circle",
    bg: "#FEF3C7",
    fg: "#92400E",
  },
  "no-gps": {
    label: "Biometric only",
    icon: "shield-checkmark-outline",
    bg: "#E5E7EB",
    fg: "#374151",
  },
};

export default function LocationPill({
  status,
  distanceM,
  size = "sm",
  showDistance = false,
}: Props) {
  const key = (status || "no-gps").toString().toLowerCase();
  const cfg = CONFIG[key as "inside" | "outside" | "no-gps"] || CONFIG["no-gps"];
  const iconSize = size === "md" ? 14 : 12;
  const fontSize = size === "md" ? 11 : 10;

  return (
    <View style={[styles.wrap, { backgroundColor: cfg.bg }]}>
      <Ionicons name={cfg.icon} size={iconSize} color={cfg.fg} />
      <Text style={[styles.txt, { color: cfg.fg, fontSize }]}>
        {cfg.label}
        {showDistance && typeof distanceM === "number" && distanceM > 0
          ? ` · ${Math.round(distanceM)}m`
          : ""}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    paddingHorizontal: 6,
    paddingVertical: 3,
    borderRadius: 999,
    alignSelf: "flex-start",
  },
  txt: { fontWeight: "700" },
});

// Silence unused colors import — the file may inline colours below if we
// add themed variants later.
void colors;
