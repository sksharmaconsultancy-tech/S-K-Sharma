/**
 * Iter 592 — CENTRAL KEYBOARD SHORTCUT ENGINE (user spec §1/§9).
 * ONE global keydown listener (web only). Pages register scoped bindings;
 * duplicates are detected and rejected. Shortcuts never fire while the
 * user is typing in an input/textarea/contenteditable (unless the binding
 * sets allowInInput). Touch-only devices: listener simply never fires.
 *
 * Usage:
 *   const off = registerShortcuts("employee-master", [
 *     { combo: "ctrl+s", label: "Save Employee", handler: save },
 *   ]);
 *   useEffect(() => off, []);   // unregister on unmount
 */
import { Platform } from "react-native";

export type ShortcutBinding = {
  combo: string;          // e.g. "alt+1", "ctrl+shift+e", "?"
  label: string;
  category?: string;      // for the help overlay
  allowInInput?: boolean; // fire even while typing (rare)
  handler: () => void;
};

type Entry = ShortcutBinding & { scope: string; defaultCombo: string };

const registry = new Map<string, Entry>(); // combo -> entry
let started = false;

// Iter 619 (Phase 3, user spec §11) — user-customisable bindings, stored on
// this device. Map key: `${scope}|${defaultCombo}` → custom combo.
const OV_KEY = "sk_shortcut_overrides_v1";
let captureMode = false; // ShortcutHelp is recording a new key — engine pauses

export function setCaptureMode(on: boolean) { captureMode = on; }

function loadOverrides(): Record<string, string> {
  try {
    return JSON.parse(window.localStorage.getItem(OV_KEY) || "{}") || {};
  } catch { return {}; }
}

function saveOverrides(ov: Record<string, string>) {
  try { window.localStorage.setItem(OV_KEY, JSON.stringify(ov)); } catch { /* private mode */ }
}

export function comboOf(e: KeyboardEvent): string {
  const parts: string[] = [];
  if (e.ctrlKey || e.metaKey) parts.push("ctrl");
  if (e.altKey) parts.push("alt");
  if (e.shiftKey) parts.push("shift");
  let k = (e.key || "").toLowerCase();
  if (k === " ") k = "space";
  if (["control", "alt", "shift", "meta"].includes(k)) return "";
  // "?" already implies shift on most layouts — normalise it.
  if (k === "?") return "?";
  parts.push(k);
  return parts.join("+");
}

function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  if (!t) return false;
  const tag = (t.tagName || "").toLowerCase();
  return tag === "input" || tag === "textarea" || tag === "select"
    || !!t.isContentEditable;
}

function onKeyDown(e: KeyboardEvent) {
  if (captureMode) return; // ShortcutHelp is recording a new binding
  const combo = comboOf(e);
  if (!combo) return;
  const entry = registry.get(combo);
  if (!entry) return;
  if (isTyping(e) && !entry.allowInInput) {
    // While typing, only allow chords that can't be normal text entry
    // (ctrl/alt combos are safe; bare letters like "p" are not).
    if (!combo.includes("ctrl+") && !combo.includes("alt+")) return;
  }
  e.preventDefault();
  e.stopPropagation();
  try { entry.handler(); } catch { /* handler errors must not crash */ }
}

export function registerShortcuts(scope: string, bindings: ShortcutBinding[]): () => void {
  if (Platform.OS !== "web" || typeof window === "undefined") return () => {};
  if (!started) {
    window.addEventListener("keydown", onKeyDown, true);
    started = true;
  }
  const overrides = loadOverrides();
  const addedDefaults: string[] = [];
  for (const b of bindings) {
    const defaultCombo = b.combo.toLowerCase();
    // Iter 619 — a user-customised key wins over the built-in default.
    const combo = (overrides[`${scope}|${defaultCombo}`] || defaultCombo).toLowerCase();
    const existing = registry.get(combo);
    if (existing && existing.scope !== scope) {
      // conflict — page-scoped bindings override globals while mounted,
      // anything else is rejected loudly in dev.
      if (existing.scope !== "global") {
        console.warn(`[shortcuts] conflict: ${combo} already registered by ${existing.scope}`);
        continue;
      }
    }
    registry.set(combo, { ...b, combo, defaultCombo, scope });
    addedDefaults.push(defaultCombo);
  }
  return () => {
    // remove by scope+default (the live combo may have been re-mapped)
    registry.forEach((e, k) => {
      if (e.scope === scope && addedDefaults.includes(e.defaultCombo)) registry.delete(k);
    });
  };
}

/** Iter 619 — remap one shortcut. Returns an error message or null on success. */
export function applyOverride(scope: string, defaultCombo: string, newComboRaw: string): string | null {
  const newCombo = (newComboRaw || "").toLowerCase();
  if (!newCombo) return "Invalid key";
  let currentKey = "";
  let entry: Entry | undefined;
  registry.forEach((e, k) => {
    if (e.scope === scope && e.defaultCombo === defaultCombo) { currentKey = k; entry = e; }
  });
  const clash = registry.get(newCombo);
  if (clash && clash !== entry) return `Already used by "${clash.label}"`;
  const ov = loadOverrides();
  if (newCombo === defaultCombo) delete ov[`${scope}|${defaultCombo}`];
  else ov[`${scope}|${defaultCombo}`] = newCombo;
  saveOverrides(ov);
  if (entry && currentKey && currentKey !== newCombo) {
    registry.delete(currentKey);
    registry.set(newCombo, { ...entry, combo: newCombo });
  }
  return null;
}

/** Iter 619 — wipe ALL custom keys and restore built-in defaults. */
export function resetOverrides(): void {
  saveOverrides({});
  const moves: [string, Entry][] = [];
  registry.forEach((e, k) => { if (k !== e.defaultCombo) moves.push([k, e]); });
  moves.forEach(([k, e]) => {
    registry.delete(k);
    if (!registry.get(e.defaultCombo)) {
      registry.set(e.defaultCombo, { ...e, combo: e.defaultCombo });
    }
  });
}

export function listShortcuts(): Entry[] {
  return Array.from(registry.values());
}
