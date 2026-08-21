/** Iter 666 — notification categories, priorities, prefs & toast helpers. */
import { Platform } from "react-native";

export const NOTIF_CATEGORIES: Record<string, { icon: any; label: string; color: string }> = {
  attendance: { icon: "time-outline", label: "Attendance", color: "#0891B2" },
  leave: { icon: "airplane-outline", label: "Leave", color: "#7C3AED" },
  salary: { icon: "cash-outline", label: "Salary", color: "#059669" },
  compliance: { icon: "scale-outline", label: "Compliance", color: "#B45309" },
  expense: { icon: "card-outline", label: "Expense", color: "#DB2777" },
  employee: { icon: "person-outline", label: "Employee", color: "#2563EB" },
  import: { icon: "download-outline", label: "Import", color: "#4F46E5" },
  system: { icon: "settings-outline", label: "System", color: "#64748B" },
  announcement: { icon: "megaphone-outline", label: "Announcement", color: "#DC2626" },
};

export const catOf = (n: any) =>
  NOTIF_CATEGORIES[String(n?.category || "announcement")] || NOTIF_CATEGORIES.announcement;

export const PRIORITY_COLORS: Record<string, string> = {
  normal: "transparent",
  important: "#F59E0B",
  critical: "#DC2626",
};

const PREFS_KEY = "sks.notif.prefs.v1";
export type NotifPrefs = {
  toasts: boolean; sound: boolean;
  categories: Record<string, boolean>;
};
export const defaultPrefs = (): NotifPrefs => ({
  toasts: true, sound: false,
  categories: Object.fromEntries(Object.keys(NOTIF_CATEGORIES).map((k) => [k, true])),
});
export const loadPrefs = (): NotifPrefs => {
  try {
    if (Platform.OS === "web" && typeof localStorage !== "undefined") {
      const raw = localStorage.getItem(PREFS_KEY);
      if (raw) return { ...defaultPrefs(), ...JSON.parse(raw) };
    }
  } catch { /* defaults */ }
  return defaultPrefs();
};
export const savePrefs = (p: NotifPrefs) => {
  try {
    if (Platform.OS === "web" && typeof localStorage !== "undefined") {
      localStorage.setItem(PREFS_KEY, JSON.stringify(p));
    }
  } catch { /* ignore */ }
};

/** Never toast the same notification twice (survives page navigation). */
const TOASTED_KEY = "sks.notif.toasted.v1";
export const alreadyToasted = (id: string): boolean => {
  try {
    const arr: string[] = JSON.parse(localStorage.getItem(TOASTED_KEY) || "[]");
    return arr.includes(id);
  } catch { return false; }
};
export const rememberToasted = (ids: string[]) => {
  try {
    const arr: string[] = JSON.parse(localStorage.getItem(TOASTED_KEY) || "[]");
    const next = [...arr, ...ids].slice(-300);
    localStorage.setItem(TOASTED_KEY, JSON.stringify(next));
  } catch { /* ignore */ }
};

/** Soft two-tone chime via WebAudio — no asset file needed. */
export const playNotifSound = () => {
  try {
    const Ctx = (window as any).AudioContext || (window as any).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const play = (freq: number, t0: number) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.type = "sine"; o.frequency.value = freq;
      g.gain.setValueAtTime(0.0001, ctx.currentTime + t0);
      g.gain.exponentialRampToValueAtTime(0.12, ctx.currentTime + t0 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + t0 + 0.25);
      o.connect(g); g.connect(ctx.destination);
      o.start(ctx.currentTime + t0); o.stop(ctx.currentTime + t0 + 0.3);
    };
    play(880, 0); play(1174, 0.12);
    setTimeout(() => ctx.close(), 800);
  } catch { /* silent */ }
};
