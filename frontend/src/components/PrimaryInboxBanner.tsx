/**
 * Iter 127 — "New email in Primary Inbox" ping shown on the HOME screen
 * of every Super Admin and Sub Admin (web portal + app dashboard).
 * Tapping opens the Mailbox; the ✕ dismisses until NEW mail arrives.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { useAuth } from "@/src/context/AuthContext";
import { usePrimaryInbox } from "@/src/hooks/usePrimaryInbox";
import { colors, radius, spacing } from "@/src/theme";

export default function PrimaryInboxBanner() {
  const { user } = useAuth();
  const router = useRouter();
  const enabled = user?.role === "super_admin" || user?.role === "sub_admin";
  const { fresh, count, dismiss } = usePrimaryInbox(enabled);

  if (!enabled || fresh.length === 0) return null;

  return (
    <View style={styles.card} testID="primary-inbox-banner">
      <Pressable
        style={styles.body}
        onPress={() => router.push("/mailbox" as any)}
        testID="primary-inbox-open"
      >
        <View style={styles.iconWrap}>
          <Ionicons name="mail-unread" size={20} color="#fff" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.title}>
            {count > 1
              ? `${count} new emails in Primary Inbox`
              : "New email in Primary Inbox"}
          </Text>
          {fresh.slice(0, 3).map((m) => (
            <Text key={m.id} style={styles.line} numberOfLines={1}>
              • {String(m.from || "").replace(/<[^>]*>/g, "").trim() || "Unknown sender"}
              {"  —  "}
              {m.subject || "(no subject)"}
            </Text>
          ))}
          <Text style={styles.open}>Tap to open Mailbox →</Text>
        </View>
      </Pressable>
      <Pressable
        onPress={dismiss}
        hitSlop={10}
        style={styles.close}
        testID="primary-inbox-dismiss"
      >
        <Ionicons name="close" size={16} color="#92400E" />
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    flexDirection: "row",
    alignItems: "flex-start",
    backgroundColor: "#FFFBEB",
    borderWidth: 1,
    borderColor: "#FCD34D",
    borderRadius: radius.lg,
    marginBottom: spacing.md,
    padding: 12,
  },
  body: {
    flex: 1,
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
  },
  iconWrap: {
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "#D97706",
    alignItems: "center",
    justifyContent: "center",
  },
  title: {
    fontSize: 14,
    fontWeight: "800",
    color: "#92400E",
  },
  line: {
    fontSize: 12,
    color: "#78350F",
    marginTop: 3,
  },
  open: {
    fontSize: 11,
    fontWeight: "700",
    color: colors.brandPrimary,
    marginTop: 6,
  },
  close: {
    width: 26,
    height: 26,
    borderRadius: 13,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FEF3C7",
    marginLeft: 8,
  },
});
