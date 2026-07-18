// Iter 180 — Premium ESS welcome header. Blue→indigo gradient with
// greeting, date, avatar, notification bell and dark-mode toggle.
import React from "react";
import { View, Text, StyleSheet, Pressable, Platform } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Ionicons } from "@expo/vector-icons";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme } from "@/src/context/ThemeContext";
import { isDarkTheme, DARK_THEME_ID } from "@/src/theme";

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good Morning";
  if (h < 17) return "Good Afternoon";
  return "Good Evening";
}

export default function EssWelcomeHeader({
  name, employeeCode, companyName, photoBase64, unread, onBell, shiftLabel,
}: {
  name: string;
  employeeCode?: string | null;
  companyName?: string | null;
  photoBase64?: string | null;
  unread: number;
  onBell: () => void;
  shiftLabel?: string | null;
}) {
  const { themeId, setThemeId } = useTheme();
  const insets = useSafeAreaInsets();
  const dark = isDarkTheme(themeId);
  const dateStr = new Date().toLocaleDateString("en-IN", {
    weekday: "long", day: "numeric", month: "long",
  });
  const photoUri = photoBase64
    ? (photoBase64.startsWith("data:") ? photoBase64 : `data:image/jpeg;base64,${photoBase64}`)
    : null;

  return (
    <LinearGradient
      colors={dark ? ["#1E3A8A", "#312E81"] : ["#2563EB", "#4338CA"]}
      start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}
      style={[st.grad, { paddingTop: insets.top + 10 }]}
    >
      <View style={st.row}>
        <View style={st.avatarWrap}>
          {photoUri ? (
            <Image source={{ uri: photoUri }} style={st.avatar} contentFit="cover" />
          ) : (
            <View style={[st.avatar, st.avatarFallback]}>
              <Text style={st.avatarTxt}>{(name || "?").slice(0, 1).toUpperCase()}</Text>
            </View>
          )}
        </View>
        <View style={{ flex: 1 }}>
          <Text style={st.greet} numberOfLines={1}>
            {greeting()}, {name?.split(" ")[0] || "there"} 👋
          </Text>
          <Text style={st.sub} numberOfLines={1}>
            {dateStr}{employeeCode ? ` · ID ${employeeCode}` : ""}
          </Text>
          {companyName ? (
            <Text style={st.sub2} numberOfLines={1}>
              {companyName}{shiftLabel ? ` · ${shiftLabel}` : ""}
            </Text>
          ) : null}
        </View>
        <Pressable
          onPress={() => setThemeId(dark ? "azure_light" : DARK_THEME_ID)}
          style={st.iconBtn} testID="ess-dark-toggle" hitSlop={6}
        >
          <Ionicons name={dark ? "sunny-outline" : "moon-outline"} size={18} color="#fff" />
        </Pressable>
        <Pressable onPress={onBell} style={st.iconBtn} testID="notif-bell" hitSlop={6}>
          <Ionicons name="notifications-outline" size={18} color="#fff" />
          {unread > 0 ? <View style={st.dot} /> : null}
        </Pressable>
      </View>
    </LinearGradient>
  );
}

const st = StyleSheet.create({
  grad: {
    paddingHorizontal: 16,
    paddingBottom: 56, // scroll content overlaps upward into this space
    borderBottomLeftRadius: 24,
    borderBottomRightRadius: 24,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 12 },
  avatarWrap: {
    borderRadius: 999, padding: 2,
    backgroundColor: "rgba(255,255,255,0.25)",
  },
  avatar: { width: 46, height: 46, borderRadius: 999 },
  avatarFallback: {
    backgroundColor: "rgba(255,255,255,0.2)",
    alignItems: "center", justifyContent: "center",
  },
  avatarTxt: { fontSize: 19, fontWeight: "800", color: "#fff" },
  greet: { fontSize: 17, fontWeight: "800", color: "#FFFFFF" },
  sub: { fontSize: 11.5, color: "rgba(255,255,255,0.85)", marginTop: 2 },
  sub2: { fontSize: 10.5, color: "rgba(255,255,255,0.7)", marginTop: 1 },
  iconBtn: {
    width: 38, height: 38, borderRadius: 12,
    backgroundColor: "rgba(255,255,255,0.16)",
    borderWidth: 1, borderColor: "rgba(255,255,255,0.22)",
    alignItems: "center", justifyContent: "center",
    ...(Platform.OS === "web" ? ({ backdropFilter: "blur(12px)" } as any) : null),
  },
  dot: {
    position: "absolute", top: 8, right: 9, width: 8, height: 8,
    borderRadius: 4, backgroundColor: "#F59E0B",
    borderWidth: 1.5, borderColor: "#2563EB",
  },
});
