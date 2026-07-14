/**
 * Iter 110 — Ctrl+S / Cmd+S saves the current screen's data (web).
 * Screens with a save action register it via this hook; the browser's
 * "Save page" dialog is suppressed portal-wide (see AdminWebShell).
 */
import { useEffect, useRef } from "react";
import { Platform } from "react-native";

export default function useSaveShortcut(onSave?: () => void) {
  const cb = useRef(onSave);
  cb.current = onSave;

  useEffect(() => {
    if (Platform.OS !== "web") return;
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && (e.key === "s" || e.key === "S")) {
        e.preventDefault();
        e.stopPropagation();
        cb.current?.();
      }
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, []);
}
