/**
 * Rectified Punches Audit — Iter 277 (user request).
 *
 * Shows which biometric scans were AUTO-IGNORED by the attendance engine
 * (double-scans within 30s, same-direction duplicates within 15 min,
 * OUT→IN device bounces) — per employee per day, with the reason.
 * Useful when workers dispute their attendance.
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import CompanyPicker from "@/src/components/CompanyPicker";

const C = {
  bg: "#F4F7F9",
  card: "#FFFFFF",
  border: "#DCE4EA",
  ink: "#12262F",
  sub: "#5B707B",
  brand: "#0F2E3D",
  accent: "#1B7A67",
  danger: "#B3261E",
  amber: "#B45309",
};

type Firm = { company_id: string; name: string };
type DroppedPunch = { time: string; kind: string; source: string; reason: string };
type Row = {
  user_id: string;
  name: string;
  employee_code: string;
  date: string;
  raw_count: number;
  kept_count: number;
  kept: { time: string; kind: string }[];
  dropped: DroppedPunch[];
};

function defaultMonth(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

export default function RectifiedPunchesScreen() {
  const router = useRouter();
  const [firms, setFirms] = useState<Firm[]>([]);
  const [firmId, setFirmId] = useState<string>("");
  const [month, setMonth] = useState<string>(defaultMonth());
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState<Row[]>([]);
  const [summary, setSummary] = useState<{ days: number; ignored: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await api<{ companies: any[] }>("/companies?lite=1");
        const list = (r.companies || []).map((c: any) => ({
          company_id: c.company_id, name: c.name || c.company_id,
        }));
        setFirms(list);
        if (list.length) setFirmId(list[0].company_id);
      } catch { /* firm list optional */ }
    })();
  }, []);

  const load = useCallback(async (cid: string, m: string) => {
    if (!cid || !/^\d{4}-\d{2}$/.test(m)) return;
    setLoading(true);
    setErr(null);
    try {
      const r = await api<{ days_affected: number; punches_ignored: number; rows: Row[] }>(
        `/admin/attendance/rectified-punches/${cid}/${m}`,
      );
      setRows(r.rows || []);
      setSummary({ days: r.days_affected || 0, ignored: r.punches_ignored || 0 });
    } catch (e: any) {
      setErr(e?.message || "Failed to load");
      setRows([]);
      setSummary(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (firmId) void load(firmId, month);
  }, [firmId, month, load]);

  const shiftMonth = (delta: number) => {
    const [y, m] = month.split("-").map(Number);
    const d = new Date(y, m - 1 + delta, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`);
  };

  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.header}>
        <Pressable onPress={() => router.back()} hitSlop={10} testID="back-btn">
          <Ionicons name="arrow-back" size={22} color="#fff" />
        </Pressable>
        <Text style={styles.headerTitle}>Rectified Punches Audit</Text>
      </View>
      <ScrollView contentContainerStyle={styles.body}>
        <Text style={styles.note}>
          Scans that were automatically ignored by the attendance engine —
          double-scans within 30 seconds, duplicate same-direction punches
          within 15 minutes, and OUT→IN device bounces — with the reason.
        </Text>

        <Text style={styles.label}>Firm</Text>
        {/* Iter 520 (user request) — firm list as searchable DROPDOWN */}
        <CompanyPicker
          value={firmId || "all"}
          onChange={(v) => setFirmId(v === "all" ? "" : (v as string))}
          companies={firms as any}
          allowAll={false}
          label="Firm"
          testID="rp-firm-dd"
        />

        <Text style={styles.label}>Month</Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 10 }}>
          <Pressable onPress={() => shiftMonth(-1)} style={styles.monthBtn} testID="rp-prev">
            <Ionicons name="chevron-back" size={16} color={C.brand} />
          </Pressable>
          <Text style={styles.monthTxt}>{month}</Text>
          <Pressable onPress={() => shiftMonth(1)} style={styles.monthBtn} testID="rp-next">
            <Ionicons name="chevron-forward" size={16} color={C.brand} />
          </Pressable>
          {loading ? <ActivityIndicator size="small" color={C.accent} /> : null}
        </View>

        {err ? <Text style={{ color: C.danger, marginTop: 10 }}>{err}</Text> : null}

        {summary ? (
          <View style={styles.summaryCard}>
            <Ionicons name="shield-checkmark-outline" size={18} color={C.accent} />
            <Text style={styles.summaryTxt}>
              {summary.ignored} duplicate scan{summary.ignored === 1 ? "" : "s"} auto-ignored
              across {summary.days} employee-day{summary.days === 1 ? "" : "s"} in {month}.
            </Text>
          </View>
        ) : null}

        {!loading && summary && rows.length === 0 ? (
          <Text style={{ color: C.sub, marginTop: 14 }}>
            No duplicate scans were ignored this month — all punches were clean. ✓
          </Text>
        ) : null}

        {rows.map((r, i) => (
          <View key={`${r.user_id}-${r.date}-${i}`} style={styles.card} testID={`rp-row-${i}`}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", flexWrap: "wrap", gap: 4 }}>
              <Text style={styles.cardTitle}>
                {r.name} {r.employee_code ? `(${r.employee_code})` : ""}
              </Text>
              <Text style={styles.cardDate}>{r.date}</Text>
            </View>
            <Text style={styles.cardSub}>
              {r.raw_count} scans received → {r.kept_count} kept
              {r.kept.length ? `  ·  Kept: ${r.kept.map((k) => `${k.kind} ${k.time}`).join(", ")}` : ""}
            </Text>
            {r.dropped.map((d, j) => (
              <View key={j} style={styles.dropRow}>
                <Ionicons name="close-circle-outline" size={14} color={C.amber} />
                <Text style={styles.dropTxt}>
                  <Text style={{ fontWeight: "700" }}>{d.kind} {d.time}</Text>
                  {d.source ? `  (${d.source})` : ""} — {d.reason}
                </Text>
              </View>
            ))}
          </View>
        ))}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: C.bg },
  header: {
    flexDirection: "row", alignItems: "center", gap: 12,
    backgroundColor: C.brand, paddingHorizontal: 16, paddingVertical: 14,
  },
  headerTitle: { color: "#fff", fontSize: 17, fontWeight: "700" },
  body: { padding: 16, paddingBottom: 60, maxWidth: 900, width: "100%", alignSelf: "center" },
  note: { color: C.sub, fontSize: 12.5, lineHeight: 18, marginBottom: 12 },
  label: { color: C.ink, fontWeight: "700", fontSize: 13, marginTop: 10, marginBottom: 6 },
  chipsRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 7, borderRadius: 16,
    borderWidth: 1, borderColor: C.border, backgroundColor: C.card,
  },
  chipOn: { backgroundColor: C.accent, borderColor: C.accent },
  chipTxt: { fontSize: 12.5, color: C.ink, fontWeight: "600" },
  monthBtn: {
    width: 32, height: 32, borderRadius: 8, borderWidth: 1, borderColor: C.border,
    backgroundColor: C.card, alignItems: "center", justifyContent: "center",
  },
  monthTxt: { fontSize: 15, fontWeight: "700", color: C.ink, minWidth: 76, textAlign: "center" },
  summaryCard: {
    flexDirection: "row", alignItems: "center", gap: 8, marginTop: 14,
    backgroundColor: "#EAF5F1", borderWidth: 1, borderColor: "#CBE7DD",
    borderRadius: 10, padding: 12,
  },
  summaryTxt: { flex: 1, color: C.ink, fontSize: 13, fontWeight: "600" },
  card: {
    backgroundColor: C.card, borderWidth: 1, borderColor: C.border,
    borderRadius: 10, padding: 12, marginTop: 10,
  },
  cardTitle: { fontSize: 13.5, fontWeight: "700", color: C.ink },
  cardDate: { fontSize: 12.5, fontWeight: "700", color: C.accent },
  cardSub: { fontSize: 12, color: C.sub, marginTop: 3 },
  dropRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 6 },
  dropTxt: { flex: 1, fontSize: 12, color: C.ink },
});
