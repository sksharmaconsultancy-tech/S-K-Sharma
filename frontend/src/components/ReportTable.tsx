/**
 * Iter 496 — UNIVERSAL REPORT LAYOUT ENGINE (user spec).
 *
 * One common table renderer for every payroll/attendance report:
 *   • Auto column width from content (clamped to min/max per column type)
 *   • Sticky header (vertical) + frozen leading columns (horizontal, web)
 *   • Ellipsis + hover/press tooltip — text NEVER overlaps
 *   • Right-aligned numbers, centered dates, left-aligned text
 *   • Responsive font (14 desktop / 13 laptop / 12 tablet, never < 11)
 *   • Consistent row height; virtual scrolling for 100k+ rows
 *   • Column resize (drag, web) + show/hide columns + reset layout
 *   • Preferences persisted per user per report (localStorage + server)
 *
 * Reports must NOT override the layout engine — they only declare columns
 * (key/label/type and optional min/max/sticky) and provide rows.
 */
import React from "react";
import {
  ActivityIndicator,
  Platform,
  Pressable,
  ScrollView,
  Text,
  View,
  useWindowDimensions,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors } from "@/src/theme";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
export type ReportColType = "text" | "num" | "date" | "center";

export type ReportCol<T = any> = {
  key: string;
  label: string;
  /** text (left) | num (right) | date/center (centered). Default: text. */
  type?: ReportColType;
  min?: number;
  max?: number;
  /** Freeze this column while scrolling horizontally (leading cols only). */
  sticky?: boolean;
  /** Banded (grouped) header segment above the column — e.g. Earnings. */
  band?: { key: string; label: string; color?: string };
  /** Display string for the cell (default: String(row[key])). */
  value?: (row: T) => string;
  /** Fully custom cell renderer (photo thumbs etc.). */
  render?: (row: T, width: number) => React.ReactNode;
  /** Extra text style per row (colors / bold). */
  textStyle?: (row: T) => any;
};

type FooterSpec = { label: string; values: Record<string, string> };

type Props<T = any> = {
  /** Unique key for saved layout prefs, e.g. "punch_log". */
  reportKey: string;
  columns: ReportCol<T>[];
  rows: T[];
  loading?: boolean;
  emptyText?: string;
  /** Per-row extra style (e.g. flag background colors). */
  rowStyle?: (row: T, index: number) => any;
  /** Totals row pinned at the bottom. */
  footer?: FooterSpec;
  /** Height cap for the scroll area (default: fills parent flex). */
  maxHeight?: number;
  /** Sorting hooks — engine renders the indicators, parent sorts rows. */
  sortBy?: string;
  sortDir?: "asc" | "desc";
  onHeaderPress?: (colKey: string) => void;
  /** Hide the Columns/Reset toolbar (rarely needed). */
  hideToolbar?: boolean;
  /** When set, a PDF button appears — exports the CURRENT on-screen layout
   *  (visible columns, widths, order) via the shared landscape PDF engine
   *  so PDF/print always match the screen. */
  pdfTitle?: string;
  pdfSubtitle?: string;
};

// ---------------------------------------------------------------------------
// Layout constants
// ---------------------------------------------------------------------------
const TYPE_DEFAULTS: Record<ReportColType, { min: number; max: number }> = {
  text: { min: 90, max: 280 },
  num: { min: 100, max: 150 },
  date: { min: 96, max: 130 },
  center: { min: 64, max: 160 },
};
const CELL_PAD = 18; // horizontal padding inside a cell
const SAMPLE_ROWS = 300;
const VIRTUAL_THRESHOLD = 120; // virtualize above this row count
const OVERSCAN = 12;

function responsiveFont(w: number): number {
  if (w >= 1440) return 14;
  if (w >= 1024) return 13;
  if (w >= 720) return 12;
  return 11;
}

function alignFor(t: ReportColType | undefined): "left" | "right" | "center" {
  if (t === "num") return "right";
  if (t === "date" || t === "center") return "center";
  return "left";
}

// ---------------------------------------------------------------------------
// Preferences (localStorage + server sync)
// ---------------------------------------------------------------------------
type Prefs = { w: Record<string, number>; hide: string[]; t: number };

const EMPTY_PREFS: Prefs = { w: {}, hide: [], t: 0 };

function loadLocalPrefs(key: string): Prefs {
  if (Platform.OS !== "web") return EMPTY_PREFS;
  try {
    const raw = globalThis.localStorage?.getItem(`rt:${key}`);
    if (!raw) return EMPTY_PREFS;
    const p = JSON.parse(raw);
    return { w: p.w || {}, hide: p.hide || [], t: p.t || 0 };
  } catch {
    return EMPTY_PREFS;
  }
}

function saveLocalPrefs(key: string, p: Prefs) {
  if (Platform.OS !== "web") return;
  try {
    globalThis.localStorage?.setItem(`rt:${key}`, JSON.stringify(p));
  } catch {
    /* storage full/blocked — ignore */
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------
export default function ReportTable<T = any>({
  reportKey,
  columns,
  rows,
  loading,
  emptyText = "No records found.",
  rowStyle,
  footer,
  maxHeight,
  sortBy,
  sortDir,
  onHeaderPress,
  hideToolbar,
  pdfTitle,
  pdfSubtitle,
}: Props<T>) {
  const { width: winW } = useWindowDimensions();
  const fontSize = responsiveFont(winW);
  const ROW_H = fontSize + 22; // consistent row height
  const HEAD_H = fontSize + 24;

  const [prefs, setPrefs] = React.useState<Prefs>(() => loadLocalPrefs(reportKey));
  const [colsOpen, setColsOpen] = React.useState(false);
  const [scrollY, setScrollY] = React.useState(0);
  const [viewH, setViewH] = React.useState(480);
  const [tip, setTip] = React.useState<{ text: string } | null>(null);
  const tipTimer = React.useRef<any>(null);
  const putTimer = React.useRef<any>(null);
  const dragRef = React.useRef<{ key: string; startX: number; startW: number } | null>(null);

  // ---- server prefs sync (per user per report) --------------------------
  React.useEffect(() => {
    let alive = true;
    api<{ prefs?: Prefs | null }>(`/report-prefs/${encodeURIComponent(reportKey)}`)
      .then((r) => {
        if (!alive || !r?.prefs) return;
        const sp = { w: r.prefs.w || {}, hide: r.prefs.hide || [], t: r.prefs.t || 0 };
        setPrefs((cur) => {
          if (sp.t > (cur.t || 0)) {
            saveLocalPrefs(reportKey, sp);
            return sp;
          }
          return cur;
        });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [reportKey]);

  const persistPrefs = React.useCallback(
    (p: Prefs) => {
      saveLocalPrefs(reportKey, p);
      if (putTimer.current) clearTimeout(putTimer.current);
      putTimer.current = setTimeout(() => {
        api(`/report-prefs/${encodeURIComponent(reportKey)}`, {
          method: "PUT",
          body: p,
        }).catch(() => {});
      }, 1200);
    },
    [reportKey],
  );

  const updatePrefs = React.useCallback(
    (fn: (p: Prefs) => Prefs) => {
      setPrefs((cur) => {
        const next = { ...fn(cur), t: Date.now() };
        persistPrefs(next);
        return next;
      });
    },
    [persistPrefs],
  );

  // ---- visible columns ---------------------------------------------------
  const visCols = React.useMemo(
    () => columns.filter((c) => !prefs.hide.includes(c.key)),
    [columns, prefs.hide],
  );

  // ---- auto column widths (content-measured, clamped) --------------------
  const widths = React.useMemo(() => {
    const charW = fontSize * 0.62;
    const out: Record<string, number> = {};
    const sample = rows.length > SAMPLE_ROWS ? rows.slice(0, SAMPLE_ROWS) : rows;
    for (const c of visCols) {
      if (prefs.w[c.key]) {
        out[c.key] = prefs.w[c.key];
        continue;
      }
      const def = TYPE_DEFAULTS[c.type || "text"];
      const cMin = c.min ?? def.min;
      const cMax = Math.max(c.max ?? def.max, cMin);
      let longest = c.label.length;
      for (const r of sample) {
        const v = c.value ? c.value(r) : String((r as any)[c.key] ?? "");
        if (v.length > longest) longest = v.length;
      }
      out[c.key] = Math.round(
        Math.min(cMax, Math.max(cMin, longest * charW + CELL_PAD)),
      );
    }
    return out;
  }, [visCols, rows, prefs.w, fontSize]);

  // sticky offsets — only LEADING sticky columns freeze
  const stickyLefts = React.useMemo(() => {
    const lefts: Record<string, number> = {};
    let acc = 0;
    for (const c of visCols) {
      if (!c.sticky) break;
      lefts[c.key] = acc;
      acc += widths[c.key] || 0;
    }
    return lefts;
  }, [visCols, widths]);

  const totalW = React.useMemo(
    () => visCols.reduce((s, c) => s + (widths[c.key] || 0), 0),
    [visCols, widths],
  );

  // ---- banded (grouped) header segments -----------------------------------
  const BAND_H = fontSize + 12;
  const hasBands = visCols.some((c) => !!c.band);
  const bandSegs = React.useMemo(() => {
    if (!hasBands) return [];
    const segs: { key: string; label: string; color: string; width: number; stickyLeft: number | null }[] = [];
    visCols.forEach((c, i) => {
      const bKey = c.band?.key ?? `__solo_${i}`;
      const last = segs[segs.length - 1];
      const w = widths[c.key] || 0;
      if (last && last.key === bKey && c.band) {
        last.width += w;
      } else {
        segs.push({
          key: bKey,
          label: c.band?.label ?? "",
          color: c.band?.color ?? "#1E3A8A",
          width: w,
          stickyLeft: c.key in stickyLefts ? stickyLefts[c.key] : null,
        });
      }
    });
    return segs;
  }, [hasBands, visCols, widths, stickyLefts]);

  // ---- column resize (web drag) ------------------------------------------
  const onResizeStart = React.useCallback(
    (colKey: string, e: any) => {
      if (Platform.OS !== "web") return;
      e.preventDefault?.();
      dragRef.current = {
        key: colKey,
        startX: e.pageX ?? e.nativeEvent?.pageX ?? 0,
        startW: widths[colKey] || 100,
      };
      const move = (ev: MouseEvent) => {
        const d = dragRef.current;
        if (!d) return;
        const w = Math.max(48, Math.round(d.startW + (ev.pageX - d.startX)));
        setPrefs((cur) => ({ ...cur, w: { ...cur.w, [d.key]: w } }));
      };
      const up = () => {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
        const d = dragRef.current;
        dragRef.current = null;
        if (d) {
          setPrefs((cur) => {
            const next = { ...cur, t: Date.now() };
            persistPrefs(next);
            return next;
          });
        }
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    },
    [widths, persistPrefs],
  );

  // ---- tooltip -----------------------------------------------------------
  const showTip = React.useCallback((text: string) => {
    if (tipTimer.current) clearTimeout(tipTimer.current);
    setTip({ text });
    tipTimer.current = setTimeout(() => setTip(null), 3500);
  }, []);
  const hideTip = React.useCallback(() => {
    if (tipTimer.current) clearTimeout(tipTimer.current);
    setTip(null);
  }, []);

  // ---- virtual window ----------------------------------------------------
  const virtual = rows.length > VIRTUAL_THRESHOLD;
  let startIdx = 0;
  let endIdx = rows.length;
  if (virtual) {
    startIdx = Math.max(0, Math.floor(scrollY / ROW_H) - OVERSCAN);
    endIdx = Math.min(rows.length, startIdx + Math.ceil(viewH / ROW_H) + OVERSCAN * 2);
  }
  const slice = virtual ? rows.slice(startIdx, endIdx) : rows;

  // ---- cell renderers ----------------------------------------------------
  const headerBg = "#1E3A8A";
  const altBg = colors.surfaceSecondary || "#F8FAFC";
  const baseBg = colors.surface || "#FFFFFF";

  const renderHeadCell = (c: ReportCol<T>) => {
    const w = widths[c.key] || 100;
    const align = alignFor(c.type);
    const sortable = !!onHeaderPress;
    const active = sortBy === c.key;
    const cell = (
      <View
        key={c.key}
        style={[
          {
            width: w,
            height: HEAD_H,
            justifyContent: "center",
            paddingHorizontal: 8,
            backgroundColor: headerBg,
            borderRightWidth: 1,
            borderRightColor: "rgba(255,255,255,0.15)",
          },
          c.key in stickyLefts && Platform.OS === "web"
            ? ({ position: "sticky", left: stickyLefts[c.key], zIndex: 12 } as any)
            : null,
        ]}
      >
        <Pressable
          disabled={!sortable}
          onPress={() => onHeaderPress?.(c.key)}
          style={{ flexDirection: "row", alignItems: "center", justifyContent: align === "right" ? "flex-end" : align === "center" ? "center" : "flex-start" }}
        >
          <Text
            numberOfLines={1}
            style={{ color: "#fff", fontWeight: "800", fontSize: Math.max(11, fontSize - 1), textAlign: align }}
          >
            {c.label}
            {active ? (sortDir === "desc" ? " ↓" : " ↑") : ""}
          </Text>
        </Pressable>
        {Platform.OS === "web" ? (
          <View
            {...({
              onMouseDown: (e: any) => onResizeStart(c.key, e),
            } as any)}
            style={
              {
                position: "absolute",
                right: -4,
                top: 0,
                bottom: 0,
                width: 9,
                cursor: "col-resize",
                zIndex: 15,
              } as any
            }
          />
        ) : null}
      </View>
    );
    return cell;
  };

  const renderCell = (c: ReportCol<T>, row: T, rowBg: string) => {
    const w = widths[c.key] || 100;
    const align = alignFor(c.type);
    const sticky = c.key in stickyLefts && Platform.OS === "web";
    const boxStyle = [
      {
        width: w,
        height: ROW_H,
        justifyContent: "center" as const,
        paddingHorizontal: 8,
        backgroundColor: rowBg,
        borderRightWidth: 1,
        borderRightColor: colors.border || "#E2E8F0",
      },
      sticky
        ? ({ position: "sticky", left: stickyLefts[c.key], zIndex: 2 } as any)
        : null,
    ];
    if (c.render) {
      return (
        <View key={c.key} style={boxStyle}>
          {c.render(row, w)}
        </View>
      );
    }
    const v = c.value ? c.value(row) : String((row as any)[c.key] ?? "");
    const display = v === "" || v === "null" || v === "undefined" ? "—" : v;
    const overflows = display.length * fontSize * 0.62 > w - CELL_PAD + 4;
    const extra = c.textStyle ? c.textStyle(row) : null;
    const txt = (
      <Text
        numberOfLines={1}
        style={[
          { fontSize, color: colors.onSurface || "#0F172A", textAlign: align },
          extra,
        ]}
      >
        {display}
      </Text>
    );
    if (!overflows) {
      return (
        <View key={c.key} style={boxStyle}>
          {txt}
        </View>
      );
    }
    // Truncated → hover (web) or tap shows the full value. Never overlap.
    return (
      <Pressable
        key={c.key}
        style={boxStyle}
        onPress={() => showTip(display)}
        {...(Platform.OS === "web"
          ? ({ onHoverIn: () => showTip(display), onHoverOut: hideTip } as any)
          : null)}
      >
        {txt}
      </Pressable>
    );
  };

  // ---- footer (totals) row -----------------------------------------------
  const renderFooter = () => {
    if (!footer) return null;
    let labelDone = false;
    return (
      <View
        style={[
          { flexDirection: "row", borderTopWidth: 2, borderTopColor: headerBg },
          Platform.OS === "web"
            ? ({ position: "sticky", bottom: 0, zIndex: 11 } as any)
            : null,
        ]}
      >
        {visCols.map((c) => {
          const w = widths[c.key] || 100;
          const val = footer.values[c.key];
          const sticky = c.key in stickyLefts && Platform.OS === "web";
          let content = val ?? "";
          if (!val && !labelDone) {
            content = footer.label;
            labelDone = true;
          }
          return (
            <View
              key={c.key}
              style={[
                {
                  width: w,
                  height: ROW_H,
                  justifyContent: "center",
                  paddingHorizontal: 8,
                  backgroundColor: "#FEF9C3",
                  borderRightWidth: 1,
                  borderRightColor: colors.border || "#E2E8F0",
                },
                sticky
                  ? ({ position: "sticky", left: stickyLefts[c.key], zIndex: 12 } as any)
                  : null,
              ]}
            >
              <Text
                numberOfLines={1}
                style={{
                  fontSize,
                  fontWeight: "800",
                  color: "#78350F",
                  textAlign: val ? alignFor(c.type) : "left",
                }}
              >
                {content}
              </Text>
            </View>
          );
        })}
      </View>
    );
  };

  // ---- universal PDF export (matches the on-screen layout exactly) --------
  const [pdfBusy, setPdfBusy] = React.useState(false);
  const exportPdf = React.useCallback(async () => {
    if (Platform.OS !== "web" || pdfBusy) return;
    setPdfBusy(true);
    try {
      const cols = visCols.map((c) => ({
        label: c.label,
        align: alignFor(c.type),
        width: widths[c.key] || 100,
        band: c.band ? { label: c.band.label, color: c.band.color || "#1E3A8A" } : null,
      }));
      const dataRows = rows.slice(0, 20000).map((r) =>
        visCols.map((c) => {
          if (c.render && !c.value) return "";
          const v = c.value ? c.value(r) : String((r as any)[c.key] ?? "");
          return v === "null" || v === "undefined" ? "" : v;
        }),
      );
      let footRow: string[] | null = null;
      if (footer) {
        let labelDone = false;
        footRow = visCols.map((c) => {
          const val = footer.values[c.key];
          if (val) return val;
          if (!labelDone) {
            labelDone = true;
            return footer.label;
          }
          return "";
        });
      }
      const token = globalThis.localStorage?.getItem("llc_session_token") || "";
      const base = (process.env.EXPO_PUBLIC_BACKEND_URL as string) || "";
      const res = await fetch(`${base}/api/report-export/pdf`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        credentials: "include",
        body: JSON.stringify({
          title: pdfTitle || reportKey,
          subtitle: pdfSubtitle || "",
          columns: cols,
          rows: dataRows,
          footer: footRow,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${(pdfTitle || reportKey).replace(/\s+/g, "_")}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 30000);
    } catch (e: any) {
      globalThis.alert?.(e?.message || "PDF export failed");
    } finally {
      setPdfBusy(false);
    }
  }, [visCols, widths, rows, footer, pdfTitle, pdfSubtitle, reportKey, pdfBusy]);

  // ---- toolbar (columns / reset) -----------------------------------------
  const toolbar = hideToolbar ? null : (
    <View style={{ flexDirection: "row", justifyContent: "flex-end", alignItems: "center", gap: 10, paddingHorizontal: 8, paddingVertical: 4 }}>
      <Text style={{ fontSize: 11, color: colors.onSurfaceTertiary || "#94A3B8" }}>
        {rows.length.toLocaleString("en-IN")} row{rows.length === 1 ? "" : "s"}
      </Text>
      {pdfTitle && Platform.OS === "web" && rows.length > 0 ? (
        <Pressable
          onPress={exportPdf}
          disabled={pdfBusy}
          style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, borderWidth: 1, borderColor: colors.border || "#E2E8F0", opacity: pdfBusy ? 0.5 : 1 }}
          testID={`rt-pdf-${reportKey}`}
        >
          {pdfBusy ? (
            <ActivityIndicator size={12} color="#B91C1C" />
          ) : (
            <Ionicons name="document-text-outline" size={13} color="#B91C1C" />
          )}
          <Text style={{ fontSize: 11, fontWeight: "700", color: "#B91C1C" }}>PDF</Text>
        </Pressable>
      ) : null}
      <Pressable
        onPress={() => setColsOpen((o) => !o)}
        style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, borderWidth: 1, borderColor: colors.border || "#E2E8F0" }}
        testID={`rt-cols-${reportKey}`}
      >
        <Ionicons name="options-outline" size={13} color={colors.onSurfaceSecondary || "#475569"} />
        <Text style={{ fontSize: 11, fontWeight: "700", color: colors.onSurfaceSecondary || "#475569" }}>Columns</Text>
      </Pressable>
      {prefs.hide.length > 0 || Object.keys(prefs.w).length > 0 ? (
        <Pressable
          onPress={() => updatePrefs(() => ({ ...EMPTY_PREFS }))}
          style={{ paddingHorizontal: 8, paddingVertical: 4 }}
          testID={`rt-reset-${reportKey}`}
        >
          <Text style={{ fontSize: 11, fontWeight: "700", color: "#B91C1C" }}>Reset layout</Text>
        </Pressable>
      ) : null}
    </View>
  );

  const colsPanel = colsOpen ? (
    <View
      style={[
        {
          position: "absolute",
          top: 30,
          right: 8,
          zIndex: 50,
          backgroundColor: baseBg,
          borderWidth: 1,
          borderColor: colors.border || "#E2E8F0",
          borderRadius: 8,
          padding: 8,
          maxHeight: 340,
          minWidth: 200,
          shadowColor: "#000",
          shadowOpacity: 0.15,
          shadowRadius: 12,
          elevation: 8,
        } as any,
      ]}
    >
      <ScrollView style={{ maxHeight: 300 }}>
        {columns.map((c) => {
          const hidden = prefs.hide.includes(c.key);
          return (
            <Pressable
              key={c.key}
              onPress={() =>
                updatePrefs((p) => ({
                  ...p,
                  hide: hidden
                    ? p.hide.filter((k) => k !== c.key)
                    : [...p.hide, c.key],
                }))
              }
              style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6, paddingHorizontal: 4 }}
            >
              <Ionicons
                name={hidden ? "square-outline" : "checkbox"}
                size={16}
                color={hidden ? "#94A3B8" : "#1E3A8A"}
              />
              <Text style={{ fontSize: 12, color: colors.onSurface || "#0F172A" }}>
                {c.label || c.key}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
      <Pressable
        onPress={() => setColsOpen(false)}
        style={{ marginTop: 6, alignSelf: "flex-end", paddingHorizontal: 8, paddingVertical: 4 }}
      >
        <Text style={{ fontSize: 11, fontWeight: "700", color: "#1E3A8A" }}>Close</Text>
      </Pressable>
    </View>
  ) : null;

  // ---- body --------------------------------------------------------------
  if (loading) {
    return <ActivityIndicator style={{ marginTop: 40 }} color={colors.brandPrimary || "#1E3A8A"} />;
  }

  const headerRow = (
    <>
      {hasBands ? (        <View
          style={[
            { flexDirection: "row", width: totalW },
            Platform.OS === "web"
              ? ({ position: "sticky", top: 0, zIndex: 11 } as any)
              : null,
          ]}
        >
          {bandSegs.map((b, i) => (
            <View
              key={`${b.key}-${i}`}
              style={[
                {
                  width: b.width,
                  height: BAND_H,
                  justifyContent: "center",
                  alignItems: "center",
                  backgroundColor: b.color,
                  borderRightWidth: 1,
                  borderRightColor: "rgba(255,255,255,0.2)",
                },
                b.stickyLeft !== null && Platform.OS === "web"
                  ? ({ position: "sticky", left: b.stickyLeft, zIndex: 13 } as any)
                  : null,
              ]}
            >
              <Text numberOfLines={1} style={{ color: "#fff", fontWeight: "800", fontSize: Math.max(10, fontSize - 2) }}>
                {b.label}
              </Text>
            </View>
          ))}
        </View>
      ) : null}
      <View
        style={[
          { flexDirection: "row", width: totalW },
          Platform.OS === "web"
            ? ({ position: "sticky", top: hasBands ? BAND_H : 0, zIndex: 10 } as any)
            : null,
        ]}
      >
        {visCols.map(renderHeadCell)}
      </View>
    </>
  );

  const bodyRows = (
    <>
      {virtual ? <View style={{ height: startIdx * ROW_H, width: totalW }} /> : null}
      {slice.map((row, i) => {
        const idx = virtual ? startIdx + i : i;
        const extra = rowStyle ? rowStyle(row, idx) : null;
        const rowBg = extra?.backgroundColor || (idx % 2 === 1 ? altBg : baseBg);
        return (
          <View key={idx} style={[{ flexDirection: "row", width: totalW, borderBottomWidth: 1, borderBottomColor: colors.border || "#E2E8F0" }, extra]}>
            {visCols.map((c) => renderCell(c, row, rowBg))}
          </View>
        );
      })}
      {virtual ? (
        <View style={{ height: Math.max(0, (rows.length - endIdx) * ROW_H), width: totalW }} />
      ) : null}
      {rows.length === 0 ? (
        <Text style={{ textAlign: "center", marginTop: 40, marginBottom: 40, color: colors.onSurfaceTertiary || "#94A3B8", fontSize: 13, width: "100%" }}>
          {emptyText}
        </Text>
      ) : null}
    </>
  );

  const onScroll = (e: any) => {
    if (virtual) setScrollY(e.nativeEvent.contentOffset?.y ?? e.nativeEvent?.target?.scrollTop ?? 0);
  };
  const onLayout = (e: any) => setViewH(e.nativeEvent.layout.height || 480);

  return (
    <View style={{ flex: 1, position: "relative" }}>
      {toolbar}
      {colsPanel}
      {tip ? (
        <View
          pointerEvents="none"
          style={
            {
              position: "absolute",
              top: 2,
              alignSelf: "center",
              zIndex: 60,
              backgroundColor: "#0F172A",
              borderRadius: 6,
              paddingHorizontal: 10,
              paddingVertical: 5,
              maxWidth: "86%",
            } as any
          }
        >
          <Text style={{ color: "#fff", fontSize: 12 }}>{tip.text}</Text>
        </View>
      ) : null}
      {Platform.OS === "web" ? (
        // ONE both-axis scroll container so position:sticky freezes the
        // header on top AND the leading columns on the left simultaneously.
        <ScrollView
          style={[{ flex: 1 }, maxHeight ? { maxHeight } : null, { overflow: "auto" } as any]}
          onScroll={onScroll}
          scrollEventThrottle={16}
          onLayout={onLayout}
          contentContainerStyle={{ minWidth: "100%" } as any}
        >
          <View style={{ minWidth: totalW }}>
            {headerRow}
            {bodyRows}
            {renderFooter()}
          </View>
        </ScrollView>
      ) : (
        <ScrollView horizontal contentContainerStyle={{ minWidth: "100%" }}>
          <ScrollView
            style={maxHeight ? { maxHeight } : { flex: 1 }}
            stickyHeaderIndices={hasBands ? [0, 1] : [0]}
            onScroll={onScroll}
            scrollEventThrottle={16}
            onLayout={onLayout}
          >
            {headerRow}
            {bodyRows}
            {renderFooter()}
          </ScrollView>
        </ScrollView>
      )}
    </View>
  );
}
