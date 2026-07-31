/**
 * Shared register-style table + export buttons for statistics/returns
 * modules (Iter 357). Generic columns/rows/totals renderer with horizontal
 * scroll, plus PDF/Excel download buttons.
 */
import React, { useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  Pressable,
  ActivityIndicator,
  Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { apiBinary } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

export type RegCol = { key: string; label: string };

export function fmtVal(v: any): string {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number")
    return v.toLocaleString("en-IN", { maximumFractionDigits: 2 });
  return String(v);
}

export function ExportButtons({
  basePath,
  fileBase,
}: {
  basePath: string; // e.g. /admin/labour-stats/department?company_id=..&month=..
  fileBase: string;
}) {
  const [busy, setBusy] = useState("");
  const dl = async (ext: "pdf" | "xlsx") => {
    setBusy(ext);
    try {
      const [p, q] = basePath.split("?");
      const res = await apiBinary(`${p}.${ext}${q ? `?${q}` : ""}`);
      if (Platform.OS === "web" && res.webBlobUrl) {
        const a = document.createElement("a");
        a.href = res.webBlobUrl;
        a.download = `${fileBase}.${ext}`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(res.webBlobUrl!), 30000);
      }
    } catch (e: any) {
      if (Platform.OS === "web") globalThis.alert(e?.message || "Export failed");
    } finally {
      setBusy("");
    }
  };
  return (
    <View style={{ flexDirection: "row", gap: 12 }}>
      <Pressable onPress={() => dl("pdf")} disabled={!!busy} hitSlop={8}>
        {busy === "pdf" ? (
          <ActivityIndicator size="small" />
        ) : (
          <Ionicons name="document-outline" size={20} color="#C0392B" />
        )}
      </Pressable>
      <Pressable onPress={() => dl("xlsx")} disabled={!!busy} hitSlop={8}>
        {busy === "xlsx" ? (
          <ActivityIndicator size="small" />
        ) : (
          <Ionicons name="download-outline" size={20} color={colors.brandPrimary} />
        )}
      </Pressable>
    </View>
  );
}

export default function RegisterTable({
  columns,
  rows,
  totals,
}: {
  columns: RegCol[];
  rows: any[];
  totals?: Record<string, any> | null;
}) {
  if (!columns?.length) return null;
  return (
    <ScrollView horizontal showsHorizontalScrollIndicator>
      <View>
        <View style={st.tr}>
          {columns.map((c, j) => (
            <Text key={c.key} style={[st.cell, st.th, j === 0 && st.thFirst]}>
              {c.label}
            </Text>
          ))}
        </View>
        {rows.map((r, i) => (
          <View key={i} style={st.tr}>
            {columns.map((c, j) => (
              <Text
                key={c.key}
                style={[
                  st.cell,
                  typeof r[c.key] === "number" && st.num,
                  j === 0 && st.first,
                ]}
              >
                {fmtVal(r[c.key])}
              </Text>
            ))}
          </View>
        ))}
        {totals && (
          <View style={st.tr}>
            {columns.map((c, j) => (
              <Text
                key={c.key}
                style={[
                  st.cell,
                  st.tot,
                  typeof totals[c.key] === "number" && st.num,
                  j === 0 && st.first,
                ]}
              >
                {fmtVal(totals[c.key])}
              </Text>
            ))}
          </View>
        )}
        {rows.length === 0 && (
          <Text style={st.empty}>No data for the selected period.</Text>
        )}
      </View>
    </ScrollView>
  );
}

const st = StyleSheet.create({
  tr: { flexDirection: "row" },
  cell: {
    width: 108,
    padding: 6,
    fontSize: 11.5,
    borderWidth: 0.5,
    borderColor: "#E2E8F0",
    color: colors.onSurface,
  },
  first: { width: 170, fontWeight: "600" },
  th: {
    backgroundColor: "#DDEBF7",
    fontWeight: "800",
    textAlign: "center",
    width: 108,
  },
  // Iter 400 — the FIRST data column is 170px wide (st.first) but its
  // heading stayed 108px, shifting every heading off its column. Match it.
  thFirst: { width: 170 },
  num: { textAlign: "right" },
  tot: { backgroundColor: "#FFF2CC", fontWeight: "800" },
  empty: {
    padding: 14,
    fontSize: 12.5,
    color: colors.onSurfaceSecondary,
  },
});

export const shared = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    backgroundColor: colors.surface,
  },
  headerTitle: { fontSize: 16, fontWeight: "700", color: colors.onSurface },
  tabs: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: 10 },
  tab: {
    paddingHorizontal: 12,
    paddingVertical: 7,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  tabActive: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  tabTxt: { fontSize: 12.5, color: colors.onSurface, fontWeight: "600" },
  tabTxtActive: { color: "#fff" },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    marginBottom: 12,
  },
  cardTitle: {
    fontSize: 14,
    fontWeight: "800",
    color: colors.onSurface,
    marginBottom: 8,
  },
  meta: { fontSize: 12, color: colors.onSurfaceSecondary, marginBottom: 8 },
  input: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    paddingVertical: 7,
    fontSize: 13,
    minWidth: 120,
    backgroundColor: colors.surface,
    color: colors.onSurface,
  },
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
});
