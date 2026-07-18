// Iter 180 — ESS quick-access service grid (Zoho People style).
import React from "react";
import { View, Text, StyleSheet, Pressable, Alert, Platform } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { colors, shadow } from "@/src/theme";

export type QuickCard = {
  icon: string; label: string; color: string; route?: string;
  comingSoon?: boolean; testID?: string;
};

export default function QuickCardsGrid({ cards }: { cards: QuickCard[] }) {
  const router = useRouter();
  const open = (c: QuickCard) => {
    if (c.comingSoon) {
      const msg = `${c.label} is coming soon.`;
      if (Platform.OS === "web") window.alert(msg); else Alert.alert("Coming soon", msg);
      return;
    }
    if (c.route) router.push(c.route as any);
  };
  return (
    <View style={st.grid}>
      {cards.map((c) => (
        <Pressable key={c.label} onPress={() => open(c)}
          testID={c.testID || `ess-card-${c.label.toLowerCase().replace(/\s+/g, "-")}`}
          style={({ pressed }) => [st.card, pressed && { transform: [{ scale: 0.96 }] },
            c.comingSoon && { opacity: 0.55 }]}>
          <View style={[st.iconWrap, { backgroundColor: `${c.color}16` }]}>
            <Ionicons name={c.icon as any} size={20} color={c.color} />
          </View>
          <Text style={st.label} numberOfLines={2}>{c.label}</Text>
          {c.comingSoon ? <Text style={st.soon}>SOON</Text> : null}
        </Pressable>
      ))}
    </View>
  );
}

const st = StyleSheet.create({
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  card: {
    width: "22.6%", minWidth: 76, flexGrow: 1,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: 16, borderWidth: 1, borderColor: colors.border,
    paddingVertical: 14, paddingHorizontal: 6, alignItems: "center",
    ...shadow.card,
  },
  iconWrap: {
    width: 42, height: 42, borderRadius: 14,
    alignItems: "center", justifyContent: "center", marginBottom: 8,
  },
  label: {
    fontSize: 10.5, fontWeight: "700", color: colors.onSurface,
    textAlign: "center", lineHeight: 13,
  },
  soon: {
    fontSize: 7.5, fontWeight: "800", color: colors.warning, marginTop: 3,
    letterSpacing: 0.5,
  },
});
