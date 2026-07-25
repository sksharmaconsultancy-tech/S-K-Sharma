/**
 * Iter 294 — Lightweight i18n (English + Hindi) for the admin shell.
 *
 * Module-level store + useSyncExternalStore hook — no provider needed, so
 * any component can call useLang()/t() without touching _layout. Language
 * choice persists to localStorage (web) and defaults to English.
 */
import { useSyncExternalStore } from "react";
import { Platform } from "react-native";

export type Lang = "en" | "hi";

const KEY = "sksharma.lang";
let _lang: Lang = "en";
if (Platform.OS === "web" && typeof localStorage !== "undefined") {
  const saved = localStorage.getItem(KEY);
  if (saved === "hi" || saved === "en") _lang = saved;
}

const listeners = new Set<() => void>();

export function setLang(l: Lang) {
  _lang = l;
  if (Platform.OS === "web" && typeof localStorage !== "undefined") {
    localStorage.setItem(KEY, l);
  }
  listeners.forEach((fn) => fn());
}

export function getLang(): Lang {
  return _lang;
}

export function useLang(): Lang {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => listeners.delete(cb); },
    () => _lang,
    () => _lang,
  );
}

// Hindi translations for shell / navigation strings. Anything missing
// falls back to the English label unchanged.
const HI: Record<string, string> = {
  "Dashboard": "डैशबोर्ड",
  "Employees": "कर्मचारी",
  "Attendance & Shift": "उपस्थिति और शिफ्ट",
  "Payroll": "पेरोल",
  "Compliance": "अनुपालन",
  "Approvals & Workflow": "अनुमोदन और वर्कफ़्लो",
  "Reports": "रिपोर्ट",
  "Masters": "मास्टर्स",
  "Import / Export": "आयात / निर्यात",
  "Devices & Integration": "डिवाइस और इंटीग्रेशन",
  "Communication": "संचार",
  "Administration": "प्रशासन",
  "AI Insights": "AI इनसाइट्स",
  "Favourites": "पसंदीदा",
  "Recently Opened": "हाल ही में खोले गए",
  "Refresh": "रीफ्रेश",
  "Logout": "लॉगआउट",
  "Web portal": "वेब पोर्टल",
  "Switch firm": "फर्म बदलें",
  "ACTIVE FIRM": "सक्रिय फर्म",
  "Search menu… (clients, payroll, reports)": "मेनू खोजें… (क्लाइंट, पेरोल, रिपोर्ट)",
  "AI Assistant": "AI सहायक",
  "Ask AI — e.g. \"Process July payroll\"": "AI से पूछें — जैसे \"जुलाई पेरोल प्रोसेस करें\"",
  "Keyboard Shortcuts": "कीबोर्ड शॉर्टकट",
  "Add New Employee": "नया कर्मचारी जोड़ें",
  "Employee Master Data": "कर्मचारी मास्टर डेटा",
  "Attendance Report": "उपस्थिति रिपोर्ट",
  "Bank Transfer Files": "बैंक ट्रांसफर फ़ाइलें",
  "BI & Data Feed (Power BI / Excel)": "BI और डेटा फ़ीड (Power BI / Excel)",
  "Split View Compare": "स्प्लिट व्यू तुलना",
};

export function t(label: string): string {
  if (_lang === "hi") return HI[label] || label;
  return label;
}

/** Reactive translate — re-renders on language switch. */
export function useT(): (label: string) => string {
  const lang = useLang();
  return (label: string) => (lang === "hi" ? HI[label] || label : label);
}
