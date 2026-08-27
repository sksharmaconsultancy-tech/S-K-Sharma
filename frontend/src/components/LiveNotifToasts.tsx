/**
 * Iter 668 — Live Notification Popup (stackable toasts).
 *
 * Renders NEW notifications as non-blocking toast cards, stacked
 * vertically in the BOTTOM-RIGHT corner (newest on top). Behaviour:
 *   - max 4 visible at once (older ones drop off the bottom)
 *   - each toast slides in from the right + fades, auto-dismisses in 6 s
 *   - hovering a toast pauses its dismiss timer (web)
 *   - "View" marks the notification read + deep-links to action_url
 *   - "✕" only closes the popup — it does NOT mark the item read
 *   - pure overlay (absolute, pointerEvents box-none): never steals
 *     focus, never reloads the page, never blocks forms / salary grids.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Animated, Easing, Platform, Pressable, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { catOf, PRIORITY_COLORS } from "@/src/utils/notifHelpers";

const MAX_VISIBLE = 4;
// Iter 671 (user request) — window auto-hides after 10 seconds.
const AUTO_DISMISS_MS = 10000;

function timeAgo(iso?: string): string {
  if (!iso) return "just now";
  try {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "just now";
    const diff = Math.max(0, Date.now() - then);
    const m = Math.floor(diff / 60_000);
    if (m < 1) return "just now";
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch { return "just now"; }
}

function ToastCard({ n, onDismiss, onView }: {
  n: any;
  onDismiss: (id: string) => void;
  onView: (n: any) => void;
}) {
  const anim = useRef(new Animated.Value(0)).current;
  const timerRef = useRef<any>(null);
  const closingRef = useRef(false);

  const close = useCallback(() => {
    if (closingRef.current) return;
    closingRef.current = true;
    if (timerRef.current) clearTimeout(timerRef.current);
    Animated.timing(anim, {
      toValue: 0, duration: 180, easing: Easing.in(Easing.quad),
      useNativeDriver: Platform.OS !== "web",
    }).start(() => onDismiss(n.notification_id));
  }, [anim, n.notification_id, onDismiss]);

  const startTimer = useCallback((ms: number) => {
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(close, ms);
  }, [close]);

  useEffect(() => {
    Animated.timing(anim, {
      toValue: 1, duration: 260, easing: Easing.out(Easing.cubic),
      useNativeDriver: Platform.OS !== "web",
    }).start();
    startTimer(AUTO_DISMISS_MS);
    return () => { if (timerRef.current) clearTimeout(timerRef.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const cat = catOf(n);
  const accent = PRIORITY_COLORS[String(n.priority || "normal")] !== "transparent"
    ? PRIORITY_COLORS[String(n.priority)] : cat.color;

  return (
    <Animated.View
      style={{
        opacity: anim,
        transform: [
          // Iter 671 — slides in from the LEFT (stack lives bottom-left now).
          { translateX: anim.interpolate({ inputRange: [0, 1], outputRange: [-72, 0] }) },
        ],
        marginTop: 8,
      }}
    >
      <Pressable
        // Hover pauses the auto-dismiss timer (web only, no-op on native).
        onHoverIn={() => { if (timerRef.current) clearTimeout(timerRef.current); }}
        onHoverOut={() => startTimer(2500)}
        style={{
          width: 340, maxWidth: 340,
          backgroundColor: "#FFFFFF", borderRadius: 12, padding: 12,
          flexDirection: "row", gap: 10, alignItems: "flex-start",
          borderWidth: 1, borderColor: "#E2E8F0",
          borderLeftWidth: 4, borderLeftColor: accent,
          shadowColor: "#0F172A", shadowOpacity: 0.18, shadowRadius: 14,
          shadowOffset: { width: 0, height: 6 }, elevation: 8,
        }}
        testID="live-notif-toast"
      >
        <View style={{
          width: 30, height: 30, borderRadius: 15, alignItems: "center",
          justifyContent: "center", backgroundColor: `${cat.color}18`,
        }}>
          <Ionicons name={cat.icon} size={16} color={cat.color} />
        </View>
        <View style={{ flex: 1 }}>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Text style={{ flex: 1, fontSize: 13, fontWeight: "800", color: "#0F172A" }} numberOfLines={1}>
              {n.title || "Notification"}
            </Text>
            <Text style={{ fontSize: 10, color: "#94A3B8", fontWeight: "600" }}>
              {timeAgo(n.created_at)}
            </Text>
          </View>
          <Text style={{ fontSize: 12, color: "#475569", marginTop: 2, lineHeight: 16 }} numberOfLines={2}>
            {n.message || n.body || ""}
          </Text>
          {/* Iter 753 (user request) — Firm · kisne kiya · kiski detail badli */}
          {(n.firm_name || n.actor_name || n.subject_name) ? (
            <Text style={{ fontSize: 11, color: "#64748B", marginTop: 3, fontWeight: "600" }} numberOfLines={2}>
              {[n.firm_name ? `🏢 ${n.firm_name}` : null,
                n.actor_name ? `👤 By: ${n.actor_name}` : null,
                n.subject_name ? `📝 For: ${n.subject_name}` : null]
                .filter(Boolean).join("  ·  ")}
            </Text>
          ) : null}
          <Pressable
            onPress={() => { close(); onView(n); }}
            style={{ alignSelf: "flex-start", marginTop: 6, paddingVertical: 3, paddingHorizontal: 10,
                     borderRadius: 6, backgroundColor: `${cat.color}14`,
                     flexDirection: "row", alignItems: "center", gap: 4 }}
            testID="live-notif-toast-view"
          >
            <Text style={{ fontSize: 12, fontWeight: "700", color: cat.color }}>View</Text>
            <Ionicons name="arrow-forward" size={11} color={cat.color} />
          </Pressable>
        </View>
        {/* Close ONLY hides the popup — item stays unread in the bell. */}
        <Pressable onPress={close} hitSlop={10} testID="live-notif-toast-close">
          <Ionicons name="close" size={15} color="#94A3B8" />
        </Pressable>
      </Pressable>
    </Animated.View>
  );
}

export default function LiveNotifToasts({ incoming, onConsumed, onView }: {
  incoming: any[];
  onConsumed: () => void;
  onView: (n: any) => void;
}) {
  const [toasts, setToasts] = useState<any[]>([]);

  useEffect(() => {
    if (!incoming?.length) return;
    setToasts((prev) => {
      const have = new Set(prev.map((t) => t.notification_id));
      const fresh = incoming.filter((n) => n?.notification_id && !have.has(n.notification_id));
      if (!fresh.length) return prev;
      // Newest first; cap the visible stack.
      return [...fresh, ...prev].slice(0, MAX_VISIBLE);
    });
    onConsumed();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [incoming]);

  const dismiss = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.notification_id !== id));
  }, []);

  // Iter 672 — the absolute container is ALWAYS mounted (empty when no
  // toasts) so popups can never be inserted at a wrong DOM position by a
  // hydration mismatch on pre-rendered pages.
  return (
    <View
      pointerEvents="box-none"
      style={{
        // Iter 671 (user request) — moved to the BOTTOM-LEFT corner.
        position: "absolute", left: 16, bottom: 44, zIndex: 950,
        alignItems: "flex-start",
        // Render newest closest to the corner.
        flexDirection: "column-reverse",
      }}
      testID="live-notif-toast-stack"
    >
      {toasts.map((n) => (
        <ToastCard key={n.notification_id} n={n} onDismiss={dismiss} onView={onView} />
      ))}
      {/* Iter 671 — HIDE button: closes the whole popup window at once.
          It auto-unhides the moment a NEW notification arrives, and each
          window auto-hides again ~10 s later. Hiding does NOT mark
          anything read — items stay unread in the bell. */}
      {toasts.length ? (
      <Pressable
        onPress={() => setToasts([])}
        style={{
          flexDirection: "row", alignItems: "center", gap: 4,
          alignSelf: "flex-start", backgroundColor: "#0F172A",
          borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4,
          marginTop: 8, opacity: 0.85,
        }}
        testID="live-notif-toast-hide-all"
      >
        <Ionicons name="eye-off-outline" size={12} color="#FFFFFF" />
        <Text style={{ fontSize: 11, fontWeight: "700", color: "#FFFFFF" }}>Hide</Text>
      </Pressable>
      ) : null}
    </View>
  );
}
