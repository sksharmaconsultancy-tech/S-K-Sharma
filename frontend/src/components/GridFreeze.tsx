import React from "react";
import { Platform, ScrollView, View } from "react-native";

/** Iter 140 (user request) — shared grid-freeze helpers.
 *  On web the grid lives in ONE both-axis scroll container so CSS
 *  position:sticky can freeze the header rows on top and the identity
 *  columns (Name / Father Name / Designation) on the left. Native falls
 *  back to the classic horizontal ScrollView. */
export function GridScroller({
  children,
  maxHeight = 640,
}: {
  children: React.ReactNode;
  // Iter 635 — string values (e.g. "calc(100vh - 170px)") let big grids use
  // the full available viewport height on web.
  maxHeight?: number | string;
}) {
  if (Platform.OS === "web") {
    return (
      <View style={{ overflow: "auto", maxHeight, marginTop: 8 } as any}>
        <View style={{ minWidth: "max-content" } as any}>{children}</View>
      </View>
    );
  }
  return (
    <ScrollView horizontal style={{ marginTop: 8 }}>
      <View>{children}</View>
    </ScrollView>
  );
}

/** Freeze a cell at `left` px while scrolling right (web only). */
export const stickyCol = (left: number, bg: string): any =>
  Platform.OS === "web"
    ? ({ position: "sticky", left, zIndex: 2, backgroundColor: bg } as any)
    : null;

/** Iter 657 (user request) — freeze a cell at the RIGHT edge (web only). */
export const stickyColRight = (bg: string): any =>
  Platform.OS === "web"
    ? ({ position: "sticky", right: 0, zIndex: 2, backgroundColor: bg } as any)
    : null;

/** Freeze the header block on top while scrolling down (web only). */
export const stickyHeader = (bg: string): any =>
  Platform.OS === "web"
    ? ({ position: "sticky", top: 0, zIndex: 10, backgroundColor: bg } as any)
    : undefined;
