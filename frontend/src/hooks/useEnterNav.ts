/**
 * Iter 108 — Enter-key form navigation (web).
 * Pressing Enter inside a form input moves focus to the NEXT visible
 * input/select (spreadsheet-style data entry). Pressing Enter on the
 * LAST field triggers the screen's save handler.
 */
import { useEffect, useRef } from "react";
import { Platform } from "react-native";

export default function useEnterNav(onLast?: () => void) {
  const cb = useRef(onLast);
  cb.current = onLast;

  useEffect(() => {
    if (Platform.OS !== "web") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.shiftKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (!t) return;
      const tag = t.tagName;
      if (tag === "TEXTAREA") return; // multiline keeps newline behaviour
      if (tag !== "INPUT" && tag !== "SELECT") return;
      const asInput = t as HTMLInputElement;
      const type = (asInput.getAttribute("type") || "text").toLowerCase();
      if (["checkbox", "radio", "button", "submit", "file", "hidden"].includes(type)) return;

      const fields = Array.from(
        document.querySelectorAll<HTMLElement>("input, select"),
      ).filter((el) => {
        const i = el as HTMLInputElement;
        if (i.disabled || i.readOnly) return false;
        const ty = (i.getAttribute("type") || "text").toLowerCase();
        if (["checkbox", "radio", "button", "submit", "file", "hidden"].includes(ty)) return false;
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      const idx = fields.indexOf(t);
      if (idx === -1) return;
      e.preventDefault();
      e.stopPropagation();
      if (idx < fields.length - 1) {
        const next = fields[idx + 1];
        next.focus();
        if (next.tagName === "INPUT") {
          try { (next as HTMLInputElement).select(); } catch {}
        }
        next.scrollIntoView({ block: "center", behavior: "smooth" });
      } else {
        cb.current?.();
      }
    };
    document.addEventListener("keydown", handler, true);
    return () => document.removeEventListener("keydown", handler, true);
  }, []);
}
