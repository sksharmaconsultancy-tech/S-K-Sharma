/**
 * Iter 461 — Chrome-style WORKSPACE TABS for the admin web portal.
 *
 * Multiple payroll modules (Dashboard, Employee Master, Attendance, Salary
 * Process, PF/ESIC Upload, Reports…) stay open as tabs in the SAME window.
 * Each tab remembers its exact route (incl. query params); switching tabs
 * instantly restores that screen. The tab set + active tab persist in
 * localStorage so the workspace is restored on the next login.
 */
import React from "react";
import { Platform, Pressable, ScrollView, Text, View, StyleSheet } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

export type WorkspaceTab = { id: string; route: string; label: string };

const LS_KEY = "sks_workspace_tabs_v1";
const MAX_TABS = 10;
const HOME = "/portal-dashboard";

function loadState(): { tabs: WorkspaceTab[]; active: string } | null {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return null;
    const j = JSON.parse(raw);
    if (Array.isArray(j?.tabs) && j.tabs.length) return j;
  } catch { /* corrupt state — start fresh */ }
  return null;
}

function saveState(tabs: WorkspaceTab[], active: string) {
  try { localStorage.setItem(LS_KEY, JSON.stringify({ tabs, active })); } catch { /* full */ }
}

function newId() { return Math.random().toString(36).slice(2, 9); }

export default function WorkspaceTabs({
  pathname,
  labelFor,
  colors,
}: {
  pathname: string;
  labelFor: (route: string) => string;
  colors: any;
}) {
  const router = useRouter();
  const [tabs, setTabs] = React.useState<WorkspaceTab[]>([]);
  const [active, setActive] = React.useState("");
  // While a tab switch is in flight the pathname lags behind — don't let the
  // pathname-follow effect overwrite the target tab's route.
  const switching = React.useRef<string | null>(null);

  const fullRoute = React.useCallback(() => {
    if (Platform.OS === "web" && typeof window !== "undefined") {
      // Strip the internal ?_r refresh nonce so stored tab routes stay clean.
      const sp = new URLSearchParams(window.location.search || "");
      sp.delete("_r");
      const q = sp.toString();
      return window.location.pathname + (q ? `?${q}` : "");
    }
    return pathname;
  }, [pathname]);

  // Boot: restore the saved workspace (or start with the current screen).
  React.useEffect(() => {
    const saved = loadState();
    if (saved) {
      setTabs(saved.tabs);
      setActive(saved.active && saved.tabs.some((t) => t.id === saved.active)
        ? saved.active : saved.tabs[0].id);
    } else {
      const t = { id: newId(), route: fullRoute(), label: labelFor(pathname) };
      setTabs([t]);
      setActive(t.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Follow in-tab navigation: the ACTIVE tab always tracks the current route.
  React.useEffect(() => {
    if (!active || !tabs.length) return;
    if (switching.current) {
      if (switching.current.split("?")[0] === pathname) switching.current = null;
      else return;
    }
    const route = fullRoute();
    const label = labelFor(pathname);
    setTabs((prev) => {
      const next = prev.map((t) =>
        t.id === active && (t.route !== route || t.label !== label)
          ? { ...t, route, label }
          : t);
      saveState(next, active);
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, active]);

  const switchTab = (t: WorkspaceTab) => {
    if (t.id === active) {
      // Iter 464 (user request) — clicking the ACTIVE tab REFRESHES the
      // page it is already on (remount + refetch), never jumps elsewhere.
      switching.current = t.route;
      const p = t.route.split("?")[0];
      router.replace((p + "?_r=" + Date.now()) as any);
      return;
    }
    setActive(t.id);
    saveState(tabs, t.id);
    switching.current = t.route;
    router.replace(t.route as any);
  };

  const addTab = () => {
    if (tabs.length >= MAX_TABS) return;
    const t = { id: newId(), route: HOME, label: labelFor(HOME) };
    const next = [...tabs, t];
    setTabs(next);
    setActive(t.id);
    saveState(next, t.id);
    switching.current = HOME;
    router.replace(HOME as any);
  };

  const closeTab = (t: WorkspaceTab) => {
    if (tabs.length <= 1) return;
    const idx = tabs.findIndex((x) => x.id === t.id);
    const next = tabs.filter((x) => x.id !== t.id);
    let act = active;
    if (t.id === active) {
      const neighbor = next[Math.max(0, idx - 1)];
      act = neighbor.id;
      switching.current = neighbor.route;
      router.replace(neighbor.route as any);
    }
    setTabs(next);
    setActive(act);
    saveState(next, act);
  };

  if (Platform.OS !== "web" || !tabs.length) return null;

  return (
    <View style={[s.bar, { backgroundColor: colors.brandPrimary + "14", borderBottomColor: colors.border }]} testID="workspace-tabs">
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.scroll}>
        {tabs.map((t) => {
          const on = t.id === active;
          return (
            <Pressable
              key={t.id}
              onPress={() => switchTab(t)}
              style={[s.tab,
                on
                  ? { backgroundColor: colors.surface, borderColor: colors.border, borderBottomColor: colors.surface }
                  : { backgroundColor: "transparent", borderColor: "transparent" }]}
              testID={`ws-tab-${t.label.replace(/\s+/g, "-").toLowerCase()}`}
            >
              <View style={[s.dot, { backgroundColor: on ? "#2563EB" : "#94A3B8" }]} />
              <Text
                numberOfLines={1}
                style={[s.tabTxt, { color: on ? colors.onSurface : colors.onSurfaceSecondary, fontWeight: on ? "800" : "600" }]}
              >
                {t.label}
              </Text>
              {tabs.length > 1 ? (
                <Pressable onPress={() => closeTab(t)} hitSlop={6} style={s.closeBtn} testID={`ws-tab-close-${t.id}`}>
                  <Ionicons name="close" size={12} color={on ? colors.onSurfaceSecondary : "#94A3B8"} />
                </Pressable>
              ) : null}
            </Pressable>
          );
        })}
        {tabs.length < MAX_TABS ? (
          <Pressable onPress={addTab} style={s.addBtn} testID="ws-tab-add" hitSlop={6}>
            <Ionicons name="add" size={16} color={colors.brandPrimary} />
          </Pressable>
        ) : null}
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  bar: { borderBottomWidth: 1, paddingHorizontal: 8, paddingTop: 6 },
  scroll: { alignItems: "flex-end", gap: 2 },
  tab: {
    flexDirection: "row", alignItems: "center", gap: 6,
    paddingHorizontal: 12, paddingVertical: 7, maxWidth: 200, minWidth: 110,
    borderTopLeftRadius: 9, borderTopRightRadius: 9,
    borderWidth: 1, borderBottomWidth: 0,
  },
  dot: { width: 7, height: 7, borderRadius: 4 },
  tabTxt: { fontSize: 12, flexShrink: 1 },
  closeBtn: { marginLeft: 2, padding: 2, borderRadius: 6 },
  addBtn: {
    width: 26, height: 26, borderRadius: 13, alignItems: "center", justifyContent: "center",
    marginLeft: 4, marginBottom: 4, backgroundColor: "rgba(37,99,235,0.10)",
  },
});
