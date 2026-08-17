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

type Entry = ShortcutBinding & { scope: string };

const registry = new Map<string, Entry>(); // combo -> entry
let started = false;

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
  const added: string[] = [];
  for (const b of bindings) {
    const combo = b.combo.toLowerCase();
    const existing = registry.get(combo);
    if (existing && existing.scope !== scope) {
      // conflict — page-scoped bindings override globals while mounted,
      // anything else is rejected loudly in dev.
      if (existing.scope !== "global") {
        console.warn(`[shortcuts] conflict: ${combo} already registered by ${existing.scope}`);
        continue;
      }
    }
    registry.set(combo, { ...b, combo, scope });
    added.push(combo);
  }
  return () => { added.forEach((c) => { if (registry.get(c)?.scope === scope) registry.delete(c); }); };
}

export function listShortcuts(): Entry[] {
  return Array.from(registry.values());
}
