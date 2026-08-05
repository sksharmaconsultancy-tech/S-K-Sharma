/**
 * Iter 494 — EmployeePhoto (enhancement only).
 *
 * Reusable avatar for every attendance / verification / search grid:
 *  • Batched, debounced thumbnail loading (one POST for a whole grid).
 *  • Module-level cache — a photo is fetched once per session (browser
 *    keeps it in memory; grids stay fast with 100k+ employees because
 *    only VISIBLE rows request thumbs).
 *  • Initials avatar when the employee has no photo.
 *  • "Unknown employee" icon variant when there is no user_id match.
 *  • Tap → full-size preview modal (original loads only on demand).
 */
import React, { useEffect, useState } from "react";
import {
  ActivityIndicator,
  Image,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api/client";

// ---- module-level thumb cache + batch loader -----------------------------
const cache = new Map<string, string | null>(); // user_id -> b64 | null
const listeners = new Map<string, Set<() => void>>();
let pending = new Set<string>();
let timer: ReturnType<typeof setTimeout> | null = null;

function notify(uid: string) {
  (listeners.get(uid) || []).forEach((fn) => fn());
}

async function flush() {
  const ids = Array.from(pending).slice(0, 300);
  pending = new Set(Array.from(pending).slice(300));
  if (pending.size > 0) schedule();
  if (ids.length === 0) return;
  try {
    const r = await api<{ thumbs: Record<string, string | null> }>(
      "/admin/employee-photos/thumbs",
      { method: "POST", body: JSON.stringify({ user_ids: ids }) },
    );
    ids.forEach((uid) => {
      cache.set(uid, r.thumbs?.[uid] ?? null);
      notify(uid);
    });
  } catch {
    ids.forEach((uid) => {
      cache.set(uid, null);
      notify(uid);
    });
  }
}

function schedule() {
  if (timer) return;
  timer = setTimeout(() => {
    timer = null;
    flush();
  }, 150);
}

function useThumb(userId?: string | null): string | null | undefined {
  const [, force] = useState(0);
  useEffect(() => {
    if (!userId) return;
    if (cache.has(userId)) return;
    const fn = () => force((x) => x + 1);
    if (!listeners.has(userId)) listeners.set(userId, new Set());
    listeners.get(userId)!.add(fn);
    pending.add(userId);
    schedule();
    return () => {
      listeners.get(userId)?.delete(fn);
    };
  }, [userId]);
  if (!userId) return null;
  return cache.get(userId); // undefined = loading
}

// ---- component ------------------------------------------------------------
const PALETTE = ["#2563EB", "#7C3AED", "#DB2777", "#EA580C", "#059669",
                 "#0891B2", "#4F46E5", "#B45309"];

function initialsOf(name?: string | null): string {
  const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return ((parts[0][0] || "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export default function EmployeePhoto({
  userId,
  name,
  code,
  size = 40,
  preview = true,
  machine,
}: {
  userId?: string | null;
  name?: string | null;
  code?: string | null;
  size?: number;
  preview?: boolean;
  machine?: string | null;
}) {
  const thumb = useThumb(userId);
  const [open, setOpen] = useState(false);
  const [full, setFull] = useState<string | null>(null);
  const [loadingFull, setLoadingFull] = useState(false);

  const openPreview = async () => {
    if (!preview) return;
    setOpen(true);
    if (userId && !full) {
      setLoadingFull(true);
      try {
        const r = await api<{ photo?: string | null }>(
          `/admin/employee-photos/${userId}/full`,
        );
        setFull(r.photo || null);
      } catch {
        setFull(null);
      } finally {
        setLoadingFull(false);
      }
    }
  };

  const radius = size / 2;
  let inner: React.ReactNode;
  if (!userId) {
    // Unknown employee — punch matched no one in the Employee Master.
    inner = (
      <View style={[st.circle, { width: size, height: size, borderRadius: radius, backgroundColor: "#E5E7EB" }]}>
        <Ionicons name="person-outline" size={size * 0.55} color="#6B7280" />
      </View>
    );
  } else if (thumb) {
    inner = (
      <Image
        source={{ uri: `data:image/jpeg;base64,${thumb}` }}
        style={{ width: size, height: size, borderRadius: radius, backgroundColor: "#F3F4F6" }}
      />
    );
  } else {
    const color = PALETTE[(String(name || userId).charCodeAt(0) || 0) % PALETTE.length];
    inner = (
      <View style={[st.circle, { width: size, height: size, borderRadius: radius, backgroundColor: color }]}>
        <Text style={{ color: "#fff", fontWeight: "800", fontSize: size * 0.38 }}>
          {initialsOf(name)}
        </Text>
      </View>
    );
  }

  return (
    <>
      <Pressable
        onPress={openPreview}
        disabled={!preview}
        testID="employee-photo"
        style={Platform.OS === "web" ? ({ cursor: preview ? "pointer" : "default" } as any) : undefined}
      >
        {inner}
      </Pressable>
      {open && (
        <Modal transparent animationType="fade" onRequestClose={() => setOpen(false)}>
          <Pressable style={st.backdrop} onPress={() => setOpen(false)}>
            <View style={st.card}>
              {loadingFull ? (
                <ActivityIndicator size="large" color="#2563EB" style={{ margin: 60 }} />
              ) : full || thumb ? (
                <Image
                  source={{ uri: `data:image/jpeg;base64,${full || thumb}` }}
                  style={st.big}
                  resizeMode="contain"
                />
              ) : (
                <View style={[st.big, st.circle, { backgroundColor: "#F3F4F6" }]}>
                  <Ionicons name="person-outline" size={90} color="#9CA3AF" />
                  <Text style={{ color: "#6B7280", marginTop: 8 }}>No photo on file</Text>
                </View>
              )}
              <Text style={st.name}>{userId ? (name || "—") : "Unknown Employee"}</Text>
              <Text style={st.meta}>
                {code ? `Code: ${code}` : ""}{code && machine ? "  ·  " : ""}
                {machine ? `Machine: ${machine}` : ""}
              </Text>
            </View>
          </Pressable>
        </Modal>
      )}
    </>
  );
}

const st = StyleSheet.create({
  circle: { alignItems: "center", justifyContent: "center", overflow: "hidden" },
  backdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.72)",
    alignItems: "center", justifyContent: "center", padding: 24,
  },
  card: {
    backgroundColor: "#fff", borderRadius: 14, padding: 16,
    alignItems: "center", maxWidth: 420, width: "100%",
  },
  big: {
    width: 320, height: 320, borderRadius: 10,
    alignItems: "center", justifyContent: "center",
  },
  name: { fontSize: 16, fontWeight: "800", color: "#111827", marginTop: 10 },
  meta: { fontSize: 12.5, color: "#6B7280", marginTop: 2 },
});
