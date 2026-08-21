/**
 * Iter 669 — Notification Digest: "Yesterday at a glance".
 *
 * Summarizes yesterday's (IST) notification events — total, counts by
 * category and top highlights with View links. Two variants:
 *   - "full":    dashboard card, dismissible for the day (localStorage)
 *   - "compact": pinned summary inside the bell dropdown
 * Renders NOTHING when yesterday had zero notifications.
 */
import React, { useCallback, useEffect, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { catOf, NOTIF_CATEGORIES, PRIORITY_COLORS } from "@/src/utils/notifHelpers";

const DISMISS_KEY = "sks.notif.digest.dismissed.v1";

const todayKey = () => new Date().toISOString().slice(0, 10);

const isDismissedToday = (): boolean => {
  try {
    if (Platform.OS === "web" && typeof localStorage !== "undefined") {
      return localStorage.getItem(DISMISS_KEY) === todayKey();
    }
  } catch { /* noop */ }
  return false;
};

const rememberDismissed = () => {
  try {
    if (Platform.OS === "web" && typeof localStorage !== "undefined") {
      localStorage.setItem(DISMISS_KEY, todayKey());
    }
  } catch { /* noop */ }
};

type Digest = {
  date_label: string;
  total: number;
  by_category: Record<string, number>;
  highlights: any[];
  per_firm: { company_id: string; name: string; count: number }[];
};

export default function NotifDigestCard({ variant, onNavigate }: {
  variant: "full" | "compact";
  /** Called before router.push so parents can close dropdowns. */
  onNavigate?: () => void;
}) {
  const router = useRouter();
  const [digest, setDigest] = useState<Digest | null>(null);
  const [hidden, setHidden] = useState(variant === "full" && isDismissedToday());

  useEffect(() => {
    if (hidden) return;
    let alive = true;
    api<Digest>("/notifications/digest")
      .then((d) => { if (alive) setDigest(d); })
      .catch(() => { /* silent */ });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openHighlight = useCallback((n: any) => {
    if (n.notification_id) {
      api("/notifications/mark-read", { method: "POST", body: { ids: [n.notification_id] } })
        .catch(() => { /* non-blocking */ });
    }
    onNavigate?.();
    router.push((n.action_url || "/notifications") as any);
  }, [onNavigate, router]);

  // Iter 672 — STABLE SLOT: the outer View is ALWAYS rendered (even when
  // empty) so the card can never be inserted at a wrong DOM position by a
  // hydration mismatch on the pre-rendered dashboard HTML (user's live
  // portal showed the card squeezed INSIDE the Compliance panel).
  const empty = hidden || !digest || !digest.total;
  if (empty) {
    return <View style={{ width: "100%" }} testID={`notif-digest-slot-${variant}`} />;
  }

  const cats = Object.entries(digest.by_category).sort((a, b) => b[1] - a[1]);
  const compact = variant === "compact";
  const highlights = digest.highlights.slice(0, compact ? 2 : 4);

  return (
    <View style={{ width: "100%" }} testID={`notif-digest-slot-${variant}`}>
    <View style={[st.card, compact && st.cardCompact]} testID={`notif-digest-${variant}`}>
      <View style={st.head}>
        <View style={st.headIcon}>
          <Ionicons name="sunny-outline" size={compact ? 13 : 16} color="#B45309" />
        </View>
        <View style={{ flex: 1 }}>
          <Text style={[st.title, compact && { fontSize: 12 }]}>Yesterday at a glance</Text>
          <Text style={st.sub}>{digest.date_label} · {digest.total} notification{digest.total === 1 ? "" : "s"}</Text>
        </View>
        {variant === "full" ? (
          <Pressable
            onPress={() => { rememberDismissed(); setHidden(true); }}
            hitSlop={10}
            testID="notif-digest-dismiss"
          >
            <Ionicons name="close" size={16} color="#94A3B8" />
          </Pressable>
        ) : null}
      </View>

      {/* Category count chips */}
      <View style={st.chipRow}>
        {cats.map(([c, count]) => {
          const cat = NOTIF_CATEGORIES[c] || NOTIF_CATEGORIES.announcement;
          return (
            <View key={c} style={[st.chip, { backgroundColor: `${cat.color}12` }]}>
              <Ionicons name={cat.icon} size={11} color={cat.color} />
              <Text style={[st.chipTxt, { color: cat.color }]}>{count} {cat.label}</Text>
            </View>
          );
        })}
      </View>

      {/* Top highlights */}
      {highlights.map((n: any) => {
        const cat = catOf(n);
        const pr = PRIORITY_COLORS[String(n.priority || "normal")] || "transparent";
        return (
          <Pressable
            key={n.notification_id}
            onPress={() => openHighlight(n)}
            style={[st.hlRow, pr !== "transparent" && { borderLeftWidth: 3, borderLeftColor: pr }]}
            testID="notif-digest-highlight"
          >
            <Ionicons name={cat.icon} size={13} color={cat.color} />
            <View style={{ flex: 1 }}>
              <Text style={st.hlTitle} numberOfLines={1}>{n.title || "Notification"}</Text>
              {!compact ? (
                <Text style={st.hlBody} numberOfLines={1}>{n.body || n.message || ""}</Text>
              ) : null}
            </View>
            <Text style={st.hlView}>View →</Text>
          </Pressable>
        );
      })}

      {/* Per-firm breakdown (super admin only) */}
      {!compact && digest.per_firm.length ? (
        <View style={st.firmRow}>
          {digest.per_firm.slice(0, 4).map((f) => (
            <Text key={f.company_id} style={st.firmTxt} numberOfLines={1}>
              <Text style={{ fontWeight: "800" }}>{f.name}</Text> · {f.count}
            </Text>
          ))}
        </View>
      ) : null}
    </View>
    </View>
  );
}

const st = StyleSheet.create({
  card: {
    backgroundColor: "#FFFBEB", borderRadius: 14, borderWidth: 1,
    borderColor: "#FDE68A", padding: 12, marginBottom: 10,
    // Iter 670 — defensive layout hardening (user's live portal showed the
    // card overlapping dashboard panels under a stale cached bundle):
    // keep the card strictly in normal flow, full-width, clipped, and
    // painting ABOVE any absolutely-positioned chart labels of siblings.
    position: "relative", zIndex: 5, alignSelf: "stretch",
    width: "100%", maxWidth: "100%", overflow: "hidden",
  },
  cardCompact: {
    marginHorizontal: 10, marginTop: 8, marginBottom: 4, padding: 10, borderRadius: 10,
  },
  head: { flexDirection: "row", alignItems: "center", gap: 8 },
  headIcon: {
    width: 26, height: 26, borderRadius: 13, alignItems: "center",
    justifyContent: "center", backgroundColor: "#FEF3C7",
  },
  title: { fontSize: 13.5, fontWeight: "800", color: "#78350F" },
  sub: { fontSize: 10.5, color: "#A16207", marginTop: 1 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginTop: 8 },
  chip: {
    flexDirection: "row", alignItems: "center", gap: 4, borderRadius: 999,
    paddingHorizontal: 8, paddingVertical: 3,
  },
  chipTxt: { fontSize: 10.5, fontWeight: "700" },
  hlRow: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6,
    backgroundColor: "#FFFFFF", borderRadius: 8, borderWidth: 1,
    borderColor: "#FDE68A", paddingHorizontal: 8, paddingVertical: 6,
  },
  hlTitle: { fontSize: 11.5, fontWeight: "700", color: "#0F172A" },
  hlBody: { fontSize: 10.5, color: "#64748B", marginTop: 1 },
  hlView: { fontSize: 10.5, fontWeight: "800", color: "#B45309" },
  firmRow: { flexDirection: "row", flexWrap: "wrap", gap: 10, marginTop: 8 },
  firmTxt: { fontSize: 10.5, color: "#78350F" },
});
