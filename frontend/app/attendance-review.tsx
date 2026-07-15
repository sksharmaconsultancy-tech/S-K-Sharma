/**
 * Attendance review — consolidated Super Admin / Company Admin screen.
 *
 * Merges the three previously-separate options into one tabbed workspace:
 *   • Daily roster        — bulk mark IN / OUT / Absent per employee
 *   • Open shifts         — close a missed-OUT punch manually
 *   • Flagged punches     — clear a face-mismatch flag after review
 *
 * All three panels are strict about optimistic clearing: after admin
 * approves / rejects / applies a manual time on a row, that row is removed
 * from the visible list immediately so the queue shrinks in real-time.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ScrollView,
  ActivityIndicator,
  RefreshControl,
  Image,
  Alert,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { useOnRefresh } from "@/src/context/RefreshBusContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import CompanyPicker from "@/src/components/CompanyPicker";
import { colors, radius, spacing, type } from "@/src/theme";

type Tab = "roster" | "open" | "flagged";

const TAB_LABELS: { key: Tab; label: string; icon: keyof typeof Ionicons.glyphMap }[] = [
  { key: "roster", label: "Daily roster", icon: "clipboard-outline" },
  { key: "open", label: "Open shifts", icon: "hourglass-outline" },
  { key: "flagged", label: "Flagged", icon: "alert-circle-outline" },
];

const showMsg = (title: string, msg: string) => {
  if (Platform.OS === "web") window.alert(msg);
  else Alert.alert(title, msg);
};

export default function AttendanceReviewScreen() {
  const router = useRouter();
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";
  const { selectedCompanyId: globalCid } = useSelectedCompany();

  const [tab, setTab] = useState<Tab>("roster");
  const [companyFilter, setCompanyFilter] = useState<string | "all">(globalCid || "all");
  // Iter 67 — Sub-Admin firm impersonation: sync filter with global selection
  useEffect(() => {
    if (globalCid) setCompanyFilter(globalCid);
  }, [globalCid]);

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8} testID="ar-back">
            <Ionicons name="arrow-back" size={22} color={colors.onSurface} />
          </Pressable>
          <View style={{ flex: 1 }}>
            <Text style={styles.title}>Attendance review</Text>
            <Text style={styles.subtitle}>
              Roster · Open shifts · Flagged punches — all in one place
            </Text>
          </View>
        </View>

        {/* Segmented tabs */}
        <View style={styles.tabsRow}>
          {TAB_LABELS.map((t) => {
            const on = tab === t.key;
            return (
              <Pressable
                key={t.key}
                onPress={() => setTab(t.key)}
                style={[styles.tabBtn, on && styles.tabBtnOn]}
                testID={`ar-tab-${t.key}`}
              >
                <Ionicons
                  name={t.icon}
                  size={14}
                  color={on ? colors.onCta : colors.onSurfaceSecondary}
                />
                <Text style={[styles.tabTxt, on && styles.tabTxtOn]}>
                  {t.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </SafeAreaView>

      {isSuper && (
        <View style={styles.filterBar}>
          <CompanyPicker
            testID="ar-company-picker"
            value={companyFilter}
            onChange={setCompanyFilter}
            label=""
            compact={false}
          />
        </View>
      )}

      {tab === "roster" && (
        <RosterPanel key={`roster-${companyFilter}`} companyId={companyFilter} isSuper={isSuper} />
      )}
      {tab === "open" && (
        <OpenShiftsPanel key={`open-${companyFilter}`} companyId={companyFilter} isSuper={isSuper} />
      )}
      {tab === "flagged" && (
        <FlaggedPanel key={`flagged-${companyFilter}`} companyId={companyFilter} isSuper={isSuper} />
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Panel 1 · Daily roster
// ---------------------------------------------------------------------------
type RosterRow = {
  user_id: string;
  name: string;
  employee_code?: string | null;
  is_live_in: boolean;
  shift_start?: string | null;
  shift_end?: string | null;
  first_in?: string | null;
  last_out?: string | null;
  punch_count: number;
  state: "in" | "done" | "absent";
};

function fmtTime(iso?: string | null) {
  if (!iso) return "—";
  // Punch times are stored as wall-clock (machine/IST time) — show verbatim.
  const m = /T(\d{2}):(\d{2})/.exec(iso);
  return m ? `${m[1]}:${m[2]}` : iso;
}

function RosterPanel({ companyId, isSuper }: { companyId: string | "all"; isSuper: boolean }) {
  const [rows, setRows] = useState<RosterRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"all" | "live_in" | "commute">("all");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = isSuper && companyId !== "all" ? `?company_id=${companyId}` : "";
      const r = await api<{ roster: RosterRow[] }>(`/admin/attendance/roster${q}`);
      setRows(r.roster || []);
      setSelected(new Set());
    } catch (e: any) {
      showMsg("Roster", e?.message || "Could not load roster.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyId, isSuper]);

  useEffect(() => {
    load();
  }, [load]);
  useOnRefresh(load);

  const filtered = useMemo(() => {
    if (filter === "all") return rows;
    if (filter === "live_in") return rows.filter((r) => r.is_live_in);
    return rows.filter((r) => !r.is_live_in);
  }, [rows, filter]);

  const toggle = (uid: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(uid)) next.delete(uid);
      else next.add(uid);
      return next;
    });

  const selectAllShown = () => setSelected(new Set(filtered.map((r) => r.user_id)));
  const clearAll = () => setSelected(new Set());

  const doBatch = async (action: "in" | "out" | "absent") => {
    if (selected.size === 0) {
      showMsg("Roster", "Select at least one employee first.");
      return;
    }
    setBusy(true);
    try {
      const marks = Array.from(selected).map((user_id) => ({ user_id, action }));
      const r = await api<{
        results: { user_id: string; ok: boolean; detail?: string }[];
      }>("/admin/attendance/roster/mark", {
        method: "POST",
        body: { marks },
      });
      const okIds = new Set(r.results.filter((x) => x.ok).map((x) => x.user_id));
      const failed = r.results.filter((x) => !x.ok);
      // OPTIMISTIC CLEAR: remove successfully-actioned employees from the list.
      setRows((prev) => prev.filter((row) => !okIds.has(row.user_id)));
      setSelected(new Set());
      let msg = `Recorded ${action.toUpperCase()} for ${okIds.size} employees.`;
      if (failed.length > 0) {
        msg += ` ${failed.length} skipped (${failed
          .slice(0, 3)
          .map((f) => f.detail || "unknown")
          .join(", ")}).`;
      }
      showMsg("Roster", msg);
    } catch (e: any) {
      showMsg("Roster", e?.message || "Could not update roster.");
    } finally {
      setBusy(false);
    }
  };

  const stateBadge = (s: RosterRow["state"]) => {
    if (s === "in") return { bg: "#E7F5EA", fg: "#0F5B22", label: "IN" };
    if (s === "done") return { bg: "#EEF2F7", fg: "#334155", label: "Done" };
    return { bg: "#FDECE2", fg: "#7A1B00", label: "Absent" };
  };

  return (
    <View style={{ flex: 1 }}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => {
              setRefreshing(true);
              load();
            }}
            tintColor={colors.brandPrimary}
          />
        }
      >
        <Text style={styles.panelHint}>
          {filtered.length} shown · {selected.size} selected
        </Text>
        <View style={styles.chipRow}>
          {(["all", "live_in", "commute"] as const).map((f) => (
            <Pressable
              key={f}
              onPress={() => setFilter(f)}
              style={[styles.chip, filter === f && styles.chipOn]}
              testID={`ar-ros-filter-${f}`}
            >
              <Text style={[styles.chipTxt, filter === f && styles.chipTxtOn]}>
                {f === "all" ? "All" : f === "live_in" ? "Live-in" : "Commute"}
              </Text>
            </Pressable>
          ))}
        </View>

        <View style={styles.selectBar}>
          <Pressable onPress={selectAllShown} testID="ar-ros-select-all">
            <Text style={styles.linkTxt}>Select all shown</Text>
          </Pressable>
          <View style={{ flex: 1 }} />
          {selected.size > 0 ? (
            <Pressable onPress={clearAll} testID="ar-ros-clear-selection">
              <Text style={styles.linkTxtMuted}>Clear</Text>
            </Pressable>
          ) : null}
        </View>

        {loading ? (
          <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
        ) : filtered.length === 0 ? (
          <EmptyBlock
            icon="checkmark-done-circle-outline"
            title="No employees pending"
            body="The roster queue is empty for this filter."
          />
        ) : (
          filtered.map((r) => {
            const on = selected.has(r.user_id);
            const b = stateBadge(r.state);
            return (
              <Pressable
                key={r.user_id}
                onPress={() => toggle(r.user_id)}
                style={[styles.row, on && styles.rowOn]}
                testID={`ar-ros-row-${r.user_id}`}
              >
                <View style={[styles.check, on && styles.checkOn]}>
                  {on ? <Ionicons name="checkmark" size={12} color="#fff" /> : null}
                </View>
                <View style={{ flex: 1 }}>
                  <View style={styles.rowTop}>
                    <Text style={styles.name} numberOfLines={1}>
                      {r.name}
                    </Text>
                    {r.is_live_in ? (
                      <View style={styles.livePill}>
                        <Ionicons name="home" size={10} color={colors.onBrandTertiary} />
                        <Text style={styles.livePillTxt}>Live-in</Text>
                      </View>
                    ) : null}
                  </View>
                  <Text style={styles.meta} numberOfLines={1}>
                    {r.employee_code ? `${r.employee_code} · ` : ""}
                    {r.shift_start && r.shift_end
                      ? `Shift ${r.shift_start}–${r.shift_end}`
                      : "No shift"}
                  </Text>
                  <View style={styles.timesRow}>
                    <Text style={styles.timeTxt}>IN {fmtTime(r.first_in)}</Text>
                    <Text style={styles.timeTxt}>OUT {fmtTime(r.last_out)}</Text>
                    <Text style={styles.timeTxt}>
                      {r.punch_count} punch{r.punch_count === 1 ? "" : "es"}
                    </Text>
                  </View>
                </View>
                <View style={[styles.badge, { backgroundColor: b.bg }]}>
                  <Text style={[styles.badgeTxt, { color: b.fg }]}>{b.label}</Text>
                </View>
              </Pressable>
            );
          })
        )}
        <View style={{ height: 120 }} />
      </ScrollView>

      {selected.size > 0 ? (
        <View style={styles.actionBar}>
          <Pressable
            onPress={() => doBatch("in")}
            disabled={busy}
            style={[styles.actBtnFilled, { backgroundColor: colors.success }]}
            testID="ar-ros-mark-in"
          >
            {busy ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Ionicons name="log-in-outline" size={15} color="#fff" />
                <Text style={styles.actBtnFilledTxt}>Mark IN</Text>
              </>
            )}
          </Pressable>
          <Pressable
            onPress={() => doBatch("out")}
            disabled={busy}
            style={[styles.actBtnFilled, { backgroundColor: colors.brandPrimary }]}
            testID="ar-ros-mark-out"
          >
            <Ionicons name="log-out-outline" size={15} color="#fff" />
            <Text style={styles.actBtnFilledTxt}>Mark OUT</Text>
          </Pressable>
          <Pressable
            onPress={() => doBatch("absent")}
            disabled={busy}
            style={[styles.actBtnFilled, { backgroundColor: colors.error }]}
            testID="ar-ros-mark-absent"
          >
            <Ionicons name="close-outline" size={15} color="#fff" />
            <Text style={styles.actBtnFilledTxt}>Mark Absent</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Panel 2 · Open shifts (missed OUT)
// ---------------------------------------------------------------------------
type OpenShift = {
  user_id: string;
  name?: string | null;
  employee_code?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  last_in_at: string;
  elapsed_hours: number;
  punch_count: number;
  will_auto_close: boolean;
  last_location_lat?: number | null;
  last_location_lng?: number | null;
  last_location_at?: string | null;
};

function fmtWhen(iso?: string | null) {
  if (!iso) return "—";
  // Wall-clock timestamps — show verbatim (dd Mon HH:MM), no tz shift.
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso);
  if (!m) return iso;
  const MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${m[3]} ${MON[Number(m[2]) - 1]}, ${m[4]}:${m[5]}`;
}

function fmtElapsed(hours: number): string {
  const h = Math.floor(hours);
  const m = Math.round((hours - h) * 60);
  if (h === 0) return `${m} min`;
  if (m === 0) return `${h} hr`;
  return `${h}h ${m}m`;
}

function OpenShiftsPanel({ companyId, isSuper }: { companyId: string | "all"; isSuper: boolean }) {
  const [items, setItems] = useState<OpenShift[]>([]);
  const [autoCloseAfter, setAutoCloseAfter] = useState(12);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [runningJob, setRunningJob] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = isSuper && companyId !== "all" ? `?company_id=${companyId}` : "";
      const r = await api<{
        open_shifts: OpenShift[];
        count: number;
        auto_close_after_hours: number;
      }>(`/admin/attendance/open-shifts${q}`);
      setItems(r.open_shifts || []);
      setAutoCloseAfter(r.auto_close_after_hours || 12);
    } catch (e: any) {
      showMsg("Open shifts", e?.message || "Could not load open shifts.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyId, isSuper]);

  useEffect(() => {
    load();
  }, [load]);

  const approveOut = async (userId: string, name?: string | null) => {
    setBusy(userId);
    try {
      await api("/admin/attendance/approve-punch", {
        method: "POST",
        body: { user_id: userId, kind: "out", note: "Admin manual close" },
      });
      // OPTIMISTIC CLEAR: this row is done.
      setItems((prev) => prev.filter((r) => r.user_id !== userId));
      showMsg("Open shifts", `OUT punch recorded for ${name || "employee"}.`);
    } catch (e: any) {
      showMsg("Open shifts", e?.message || "Could not approve punch.");
    } finally {
      setBusy(null);
    }
  };

  const triggerAutoClose = async () => {
    setRunningJob(true);
    try {
      const r = await api<{ closed: number; scanned: number }>(
        "/admin/attendance/auto-close",
        { method: "POST" },
      );
      showMsg(
        "Open shifts",
        `Auto-close complete. Closed ${r.closed} of ${r.scanned} open shift${
          r.scanned === 1 ? "" : "s"
        }.`,
      );
      await load();
    } catch (e: any) {
      showMsg("Open shifts", e?.message || "Could not run auto-close.");
    } finally {
      setRunningJob(false);
    }
  };

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            load();
          }}
          tintColor={colors.brandPrimary}
        />
      }
    >
      <View style={styles.infoCard}>
        <Ionicons name="information-circle-outline" size={16} color={colors.brandPrimary} />
        <Text style={styles.infoTxt}>
          Punched IN today but no OUT. Server auto-closes after{" "}
          <Text style={{ fontWeight: "800" }}>{autoCloseAfter}h</Text> or when
          the last known location leaves the geofence for 30+ min. You can
          also close manually below.
        </Text>
      </View>

      <Pressable
        style={[styles.runBtn, runningJob && { opacity: 0.6 }]}
        onPress={triggerAutoClose}
        disabled={runningJob}
        testID="ar-os-run-auto-close"
      >
        {runningJob ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <>
            <Ionicons name="flash-outline" size={16} color="#fff" />
            <Text style={styles.runBtnTxt}>Run auto-close now</Text>
          </>
        )}
      </Pressable>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
      ) : items.length === 0 ? (
        <EmptyBlock
          icon="checkmark-done-circle-outline"
          title="All shifts closed"
          body="No employees are currently on an open shift."
        />
      ) : (
        items.map((r) => {
          const isBusy = busy === r.user_id;
          return (
            <View
              key={r.user_id}
              style={styles.card}
              testID={`ar-os-row-${r.user_id}`}
            >
              <View style={styles.cardHead}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name} numberOfLines={1}>
                    {r.name || "Unknown"}
                  </Text>
                  <Text style={styles.meta} numberOfLines={1}>
                    {r.employee_code ? `${r.employee_code} · ` : ""}
                    {r.company_name || ""}
                  </Text>
                </View>
                <View
                  style={[
                    styles.pill,
                    r.will_auto_close ? styles.pillWarn : styles.pillOk,
                  ]}
                >
                  <Text
                    style={[
                      styles.pillTxt,
                      { color: r.will_auto_close ? "#7A1B00" : "#0F5B22" },
                    ]}
                  >
                    {fmtElapsed(r.elapsed_hours)}
                  </Text>
                </View>
              </View>

              <View style={styles.lineRow}>
                <Ionicons name="log-in-outline" size={13} color={colors.onSurfaceTertiary} />
                <Text style={styles.lineTxt}>IN at {fmtWhen(r.last_in_at)}</Text>
              </View>
              {r.last_location_at ? (
                <View style={styles.lineRow}>
                  <Ionicons name="location-outline" size={13} color={colors.onSurfaceTertiary} />
                  <Text style={styles.lineTxt} numberOfLines={1}>
                    Last ping {fmtWhen(r.last_location_at)}
                    {typeof r.last_location_lat === "number"
                      ? ` · ${r.last_location_lat.toFixed(4)}, ${(r.last_location_lng || 0).toFixed(4)}`
                      : ""}
                  </Text>
                </View>
              ) : (
                <View style={styles.lineRow}>
                  <Ionicons name="alert-circle-outline" size={13} color={colors.warning} />
                  <Text style={[styles.lineTxt, { color: colors.warning }]}>
                    No location shared — app may be force-quit.
                  </Text>
                </View>
              )}

              <View style={styles.actionsRow}>
                <Pressable
                  onPress={() => approveOut(r.user_id, r.name)}
                  disabled={isBusy}
                  style={[styles.actBtn, isBusy && { opacity: 0.6 }]}
                  testID={`ar-os-close-${r.user_id}`}
                >
                  {isBusy ? (
                    <ActivityIndicator color={colors.brandPrimary} />
                  ) : (
                    <>
                      <Ionicons name="log-out-outline" size={15} color={colors.brandPrimary} />
                      <Text style={styles.actBtnTxt}>Punch OUT now</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          );
        })
      )}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Panel 3 · Flagged punches (face-mismatch review)
// ---------------------------------------------------------------------------
type Flagged = {
  record_id: string;
  user_id: string;
  user_name?: string | null;
  employee_code?: string | null;
  company_id?: string | null;
  company_name?: string | null;
  date: string;
  at: string;
  kind: "in" | "out";
  identity_confidence?: number;
  identity_reason?: string;
  latitude?: number | null;
  longitude?: number | null;
  branch_name?: string | null;
};

type PhotoBundle = { profile?: string | null; punch?: string | null };

function FlaggedPanel({ companyId, isSuper }: { companyId: string | "all"; isSuper: boolean }) {
  const [items, setItems] = useState<Flagged[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [photos, setPhotos] = useState<Record<string, PhotoBundle>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = isSuper && companyId !== "all" ? `?company_id=${companyId}` : "";
      const r = await api<{ flagged: Flagged[]; count: number }>(
        `/admin/attendance/flagged${q}`,
      );
      setItems(r.flagged || []);
    } catch (e: any) {
      showMsg("Flagged", e?.message || "Could not load flagged punches.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [companyId, isSuper]);

  useEffect(() => {
    load();
  }, [load]);

  const clear = async (record_id: string) => {
    setBusy(record_id);
    try {
      await api(`/admin/attendance/${record_id}/clear-flag`, { method: "PATCH" });
      // OPTIMISTIC CLEAR: remove the row once admin has reviewed it.
      setItems((prev) => prev.filter((r) => r.record_id !== record_id));
    } catch (e: any) {
      showMsg("Flagged", e?.message || "Could not clear the flag.");
    } finally {
      setBusy(null);
    }
  };

  const loadPhotos = async (rec: Flagged) => {
    if (photos[rec.record_id]) return;
    try {
      const punch = await api<{ selfie_base64?: string | null }>(
        `/admin/attendance/${rec.record_id}/selfie`,
      ).catch(() => null);
      const profile = await api<{ photo_base64?: string | null }>(
        `/admin/users/${rec.user_id}/photo`,
      ).catch(() => null);
      setPhotos((p) => ({
        ...p,
        [rec.record_id]: {
          punch: punch?.selfie_base64 || null,
          profile: profile?.photo_base64 || null,
        },
      }));
    } catch {}
  };

  const renderPhoto = (b64?: string | null): string | null => {
    if (!b64) return null;
    return b64.startsWith("data:") ? b64 : `data:image/jpeg;base64,${b64}`;
  };

  return (
    <ScrollView
      contentContainerStyle={styles.scroll}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => {
            setRefreshing(true);
            load();
          }}
          tintColor={colors.brandPrimary}
        />
      }
    >
      <Text style={styles.panelHint}>
        {items.length} {items.length === 1 ? "record" : "records"} awaiting review
      </Text>

      {loading ? (
        <ActivityIndicator style={{ marginTop: 60 }} color={colors.brandPrimary} />
      ) : items.length === 0 ? (
        <EmptyBlock
          icon="shield-checkmark-outline"
          title="All clear"
          body="No punches are currently flagged. Face-match verification is working normally."
        />
      ) : (
        items.map((rec) => {
          const photoBundle = photos[rec.record_id];
          const conf = Math.round((rec.identity_confidence || 0) * 100);
          const isBusy = busy === rec.record_id;
          return (
            <View
              key={rec.record_id}
              style={styles.card}
              testID={`ar-fp-row-${rec.record_id}`}
            >
              <View style={styles.cardHead}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.name} numberOfLines={1}>
                    {rec.user_name || "Unknown"}
                  </Text>
                  <Text style={styles.meta} numberOfLines={1}>
                    {rec.employee_code ? `${rec.employee_code} · ` : ""}
                    {rec.company_name || ""}
                  </Text>
                </View>
                <View
                  style={[
                    styles.kindPill,
                    rec.kind === "in" ? styles.kindPillIn : styles.kindPillOut,
                  ]}
                >
                  <Text
                    style={[
                      styles.kindPillTxt,
                      { color: rec.kind === "in" ? "#0F5B22" : "#7A1B00" },
                    ]}
                  >
                    {rec.kind === "in" ? "IN" : "OUT"}
                  </Text>
                </View>
              </View>
              <Text style={styles.when}>{fmtWhen(rec.at)}</Text>

              <View style={styles.confRow}>
                <Ionicons name="alert-circle" size={14} color={colors.warning} />
                <Text style={styles.confTxt}>
                  Model confidence:{" "}
                  <Text style={{ fontWeight: "800" }}>{conf}%</Text>
                </Text>
              </View>
              {rec.identity_reason ? (
                <Text style={styles.reason} numberOfLines={3}>
                  {`"${rec.identity_reason}"`}
                </Text>
              ) : null}

              {photoBundle ? (
                <View style={styles.photosRow}>
                  <View style={styles.photoBox}>
                    <Text style={styles.photoLabel}>ENROLLED</Text>
                    {renderPhoto(photoBundle.profile) ? (
                      <Image
                        source={{ uri: renderPhoto(photoBundle.profile)! }}
                        style={styles.photo}
                        resizeMode="cover"
                      />
                    ) : (
                      <View style={[styles.photo, styles.photoEmpty]}>
                        <Ionicons
                          name="person-outline"
                          size={20}
                          color={colors.onSurfaceTertiary}
                        />
                      </View>
                    )}
                  </View>
                  <View style={styles.photoBox}>
                    <Text style={styles.photoLabel}>PUNCH SELFIE</Text>
                    {renderPhoto(photoBundle.punch) ? (
                      <Image
                        source={{ uri: renderPhoto(photoBundle.punch)! }}
                        style={styles.photo}
                        resizeMode="cover"
                      />
                    ) : (
                      <View style={[styles.photo, styles.photoEmpty]}>
                        <Ionicons
                          name="camera-outline"
                          size={20}
                          color={colors.onSurfaceTertiary}
                        />
                      </View>
                    )}
                  </View>
                </View>
              ) : (
                <Pressable
                  style={styles.loadBtn}
                  onPress={() => loadPhotos(rec)}
                  testID={`ar-fp-load-${rec.record_id}`}
                >
                  <Ionicons name="images-outline" size={14} color={colors.brandPrimary} />
                  <Text style={styles.loadBtnTxt}>Load photos</Text>
                </Pressable>
              )}

              <View style={styles.actionsRow}>
                <Pressable
                  onPress={() => clear(rec.record_id)}
                  disabled={isBusy}
                  style={[styles.actBtn, isBusy && { opacity: 0.6 }]}
                  testID={`ar-fp-clear-${rec.record_id}`}
                >
                  {isBusy ? (
                    <ActivityIndicator color={colors.brandPrimary} />
                  ) : (
                    <>
                      <Ionicons
                        name="checkmark-circle-outline"
                        size={16}
                        color={colors.brandPrimary}
                      />
                      <Text style={styles.actBtnTxt}>Clear flag (looks OK)</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          );
        })
      )}
      <View style={{ height: 40 }} />
    </ScrollView>
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------
function EmptyBlock({
  icon,
  title,
  body,
}: {
  icon: keyof typeof Ionicons.glyphMap;
  title: string;
  body: string;
}) {
  return (
    <View style={styles.empty}>
      <Ionicons name={icon} size={42} color={colors.onSurfaceTertiary} />
      <Text style={styles.emptyT}>{title}</Text>
      <Text style={styles.emptyS}>{body}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    backgroundColor: colors.surface,
  },
  title: { color: colors.onSurface, fontSize: type.xl, fontWeight: "800" },
  subtitle: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 2 },

  tabsRow: {
    flexDirection: "row",
    gap: 6,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  tabBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.pill,
    backgroundColor: colors.background,
  },
  tabBtnOn: { backgroundColor: colors.brandPrimary },
  tabTxt: { color: colors.onSurfaceSecondary, fontSize: 12, fontWeight: "700" },
  tabTxtOn: { color: colors.onCta },

  filterBar: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    backgroundColor: colors.surface,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },

  scroll: { padding: spacing.lg },
  panelHint: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginBottom: spacing.sm,
    fontWeight: "600",
  },
  chipRow: { flexDirection: "row", gap: 8, marginBottom: spacing.md },
  chip: {
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  chipOn: { backgroundColor: colors.brandPrimary },
  chipTxt: { color: colors.brandPrimary, fontSize: 12, fontWeight: "700" },
  chipTxtOn: { color: "#fff" },

  selectBar: { flexDirection: "row", alignItems: "center", marginBottom: spacing.sm },
  linkTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "700" },
  linkTxtMuted: { color: colors.onSurfaceTertiary, fontSize: type.sm, fontWeight: "700" },

  empty: { alignItems: "center", padding: spacing.xl, marginTop: spacing.md },
  emptyT: {
    color: colors.onSurface,
    fontSize: type.lg,
    fontWeight: "800",
    marginTop: 12,
  },
  emptyS: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    marginTop: 6,
    textAlign: "center",
    lineHeight: 20,
  },

  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
    padding: spacing.md,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "transparent",
  },
  rowOn: { borderColor: colors.brandPrimary },
  check: {
    width: 22,
    height: 22,
    borderRadius: 5,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: "center",
    justifyContent: "center",
  },
  checkOn: { backgroundColor: colors.brandPrimary, borderColor: colors.brandPrimary },
  rowTop: { flexDirection: "row", alignItems: "center", gap: 8 },
  name: { color: colors.onSurface, fontSize: type.base, fontWeight: "700" },
  meta: { color: colors.onSurfaceTertiary, fontSize: 11, marginTop: 2 },
  timesRow: { flexDirection: "row", gap: 10, marginTop: 6, flexWrap: "wrap" },
  timeTxt: { color: colors.onSurfaceSecondary, fontSize: 11, fontWeight: "600" },
  livePill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 3,
    paddingHorizontal: 6,
    paddingVertical: 2,
    backgroundColor: colors.brandTertiary,
    borderRadius: 4,
  },
  livePillTxt: {
    color: colors.onBrandTertiary,
    fontSize: 9,
    fontWeight: "800",
    letterSpacing: 0.4,
  },
  badge: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  badgeTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },

  actionBar: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    flexDirection: "row",
    gap: 8,
    padding: spacing.md,
    paddingBottom: spacing.lg,
    backgroundColor: colors.surface,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.divider,
  },
  actBtnFilled: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 12,
    borderRadius: radius.md,
  },
  actBtnFilledTxt: { color: "#fff", fontSize: type.sm, fontWeight: "800" },

  infoCard: {
    flexDirection: "row",
    gap: 10,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  infoTxt: { flex: 1, color: colors.onBrandTertiary, fontSize: type.sm, lineHeight: 20 },
  runBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.md,
    paddingVertical: 12,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 8,
    marginBottom: spacing.lg,
  },
  runBtnTxt: { color: "#fff", fontSize: type.base, fontWeight: "800" },

  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.md,
  },
  cardHead: { flexDirection: "row", alignItems: "center", gap: 10 },
  pill: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  pillOk: { backgroundColor: "#E7F5EA" },
  pillWarn: { backgroundColor: "#FDECE2" },
  pillTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  lineRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 4 },
  lineTxt: { flex: 1, color: colors.onSurfaceSecondary, fontSize: 12 },
  actionsRow: { flexDirection: "row", gap: 8, marginTop: 10 },
  actBtn: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    paddingVertical: 10,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.brandPrimary,
    backgroundColor: colors.surface,
  },
  actBtnTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "800" },

  when: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: 6 },
  kindPill: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 4 },
  kindPillIn: { backgroundColor: "#E7F5EA" },
  kindPillOut: { backgroundColor: "#FDECE2" },
  kindPillTxt: { fontSize: 10, fontWeight: "800", letterSpacing: 0.5 },
  confRow: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10 },
  confTxt: { color: colors.onSurface, fontSize: type.sm },
  reason: {
    color: colors.onSurfaceSecondary,
    fontSize: type.sm,
    fontStyle: "italic",
    marginTop: 4,
    lineHeight: 18,
  },
  photosRow: { flexDirection: "row", gap: 10, marginTop: 12 },
  photoBox: { flex: 1 },
  photoLabel: {
    color: colors.onSurfaceTertiary,
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
    marginBottom: 4,
  },
  photo: {
    width: "100%",
    aspectRatio: 1,
    borderRadius: 8,
    backgroundColor: colors.background,
  },
  photoEmpty: { alignItems: "center", justifyContent: "center" },
  loadBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    marginTop: 10,
    paddingVertical: 8,
    borderRadius: 8,
    backgroundColor: colors.background,
  },
  loadBtnTxt: { color: colors.brandPrimary, fontSize: type.sm, fontWeight: "700" },
});
