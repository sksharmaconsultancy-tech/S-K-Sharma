/**
 * PunchRepairModal — Iter 233 (user request).
 *
 * Opened by tapping ANY day cell on the Attendance Grid (IN/OUT report).
 * Lets the admin repair that exact employee-day directly:
 *   • see every recorded punch (time, IN/OUT, source),
 *   • add the missing IN or OUT punch,
 *   • edit a wrong punch time/kind,
 *   • delete a stray punch.
 * Backend: existing manual-punch endpoints (full audit trail preserved).
 */
import React, { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Modal,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import WebDateField from "@/src/components/WebDateField";
import { colors, radius, spacing } from "@/src/theme";

type Punch = {
  record_id: string;
  kind: "in" | "out";
  at: string;
  source?: string;
  status?: string;
  manual_reason?: string;
};

const fmtDateDmy = (iso: string): string => {
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
};

const srcLabel = (s?: string): string => {
  const v = (s || "").toLowerCase();
  if (v.startsWith("zkteco") || v.startsWith("import") || v.includes("bio")) return "Machine";
  if (v.startsWith("manual")) return "Manual";
  return "App";
};

export default function PunchRepairModal({
  userId,
  empName,
  dateIso,
  onClose,
  onSaved,
}: {
  userId: string;
  empName: string;
  dateIso: string; // YYYY-MM-DD
  onClose: (changed: boolean) => void;
  onSaved?: () => void; // live grid refresh after every save/delete
}) {
  const [punches, setPunches] = useState<Punch[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [changed, setChanged] = useState(false);

  // Add / edit form
  const [formOpen, setFormOpen] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [kind, setKind] = useState<"in" | "out">("in");
  const [time, setTime] = useState("");
  // Iter 498 (user request) — repair the FULL day in ONE go: IN time +
  // OUT time entered together, saved with a single button.
  const [bothOpen, setBothOpen] = useState(false);
  const [inTime, setInTime] = useState("");
  const [outTime, setOutTime] = useState("");
  // Iter 498b (user request) — OT punches (2nd IN→OUT pair) repairable in
  // the SAME one-shot save, when applicable.
  const [otOpen, setOtOpen] = useState(false);
  const [otInTime, setOtInTime] = useState("");
  const [otOutTime, setOtOutTime] = useState("");
  // Iter 295 (user request) — punch DATE is editable too (ISO, edited via
  // the WebDateField calendar picker), so night-shift/wrong-day punches
  // can be placed on the correct date.
  const [pDate, setPDate] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await api<{ records: Punch[] }>(
        `/admin/attendance/history?user_id=${userId}&date_from=${dateIso}&date_to=${dateIso}&limit=100`,
      );
      // Show real punches only (hide rejected / auto-ignored / duplicate noise).
      const visible = (r.records || []).filter(
        (p) => !["rejected", "auto_ignored", "duplicate"].includes(String(p.status || "")),
      );
      setPunches(visible.sort((a, b) => (a.at || "").localeCompare(b.at || "")));
    } catch {
      setPunches([]);
    } finally {
      setLoading(false);
    }
  }, [userId, dateIso]);

  useEffect(() => {
    load();
  }, [load]);

  const hasIn = punches.some((p) => p.kind === "in");
  const hasOut = punches.some((p) => p.kind === "out");
  // Iter 498 — pair mapping for the one-shot repair:
  //   duty pair = 1st IN + last OUT before the OT IN (or last OUT overall)
  //   OT pair (Iter 419 convention) = 2nd IN + the OUT after it.
  const ins = punches.filter((p) => p.kind === "in");
  const outs = punches.filter((p) => p.kind === "out");
  const firstIn = ins[0] || null;
  const otInPunch = ins[1] || null;
  const dutyOut = otInPunch
    ? [...outs].reverse().find((p) => (p.at || "") < (otInPunch.at || "")) || null
    : (outs.length ? outs[outs.length - 1] : null);
  const otOutPunch = otInPunch
    ? [...outs].reverse().find((p) => (p.at || "") > (otInPunch.at || "")) || null
    : null;

  const openBoth = () => {
    setInTime(firstIn ? (firstIn.at || "").slice(11, 16) : "");
    setOutTime(dutyOut ? (dutyOut.at || "").slice(11, 16) : "");
    setOtInTime(otInPunch ? (otInPunch.at || "").slice(11, 16) : "");
    setOtOutTime(otOutPunch ? (otOutPunch.at || "").slice(11, 16) : "");
    setOtOpen(!!otInPunch || !!otOutPunch);
    setPDate(dateIso);
    setReason("Full day punch repair");
    setErr("");
    setFormOpen(false);
    setBothOpen(true);
  };

  const openAdd = (k: "in" | "out") => {
    setEditId(null);
    setKind(k);
    setTime("");
    setPDate(dateIso);
    setReason("Missing punch repair");
    setErr("");
    setFormOpen(true);
  };
  const openEdit = (p: Punch) => {
    setEditId(p.record_id);
    setKind(p.kind);
    setTime((p.at || "").slice(11, 16));
    setPDate((p.at || "").slice(0, 10));
    setReason("Punch correction");
    setErr("");
    setFormOpen(true);
  };

  const fmtTimeInput = (raw: string) => {
    const digits = raw.replace(/\D/g, "").slice(0, 4);
    setTime(digits.length > 2 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits);
  };
  const fmtTimeRaw = (raw: string): string => {
    const digits = raw.replace(/\D/g, "").slice(0, 4);
    return digits.length > 2 ? `${digits.slice(0, 2)}:${digits.slice(2)}` : digits;
  };

  const validTime = (t: string) => {
    if (!/^\d{2}:\d{2}$/.test(t)) return false;
    const [hh, mm] = t.split(":").map(Number);
    return hh <= 23 && mm <= 59;
  };

  const nextDay = (iso: string): string => {
    const d = new Date(`${iso}T12:00:00Z`);
    d.setUTCDate(d.getUTCDate() + 1);
    return d.toISOString().slice(0, 10);
  };

  // Night shift helper — OUT earlier than IN means the OUT lands next day.
  const outIsNextDay =
    validTime(inTime) && validTime(outTime) && outTime < inTime;
  // OT pair lands after the duty OUT; roll to next day when the shift or
  // the OT pair crosses midnight.
  const otInIsNextDay =
    validTime(otInTime) && validTime(outTime) &&
    (outIsNextDay || otInTime < outTime);
  // Iter 544 — when OT In is blank, the OT Out rolls over based on the
  // duty OUT instead (OT starts right after duty ends).
  const otBase = otInTime || outTime;
  const otOutIsNextDay =
    validTime(otOutTime) && validTime(otBase) &&
    ((otInTime ? otInIsNextDay : outIsNextDay) || otOutTime < otBase);

  // Iter 498 — ONE save that repairs BOTH punches (updates existing IN/OUT
  // or creates the missing ones). Iter 498b — OT pair too, if provided.
  const saveBoth = async () => {
    if (!inTime && !outTime && !otInTime && !otOutTime) {
      setErr("Enter at least one time to repair");
      return;
    }
    for (const [lbl, t] of [["IN", inTime], ["OUT", outTime], ["OT IN", otInTime], ["OT OUT", otOutTime]] as const) {
      if (t && !validTime(t)) {
        setErr(`${lbl} time must be HH:MM (24-hour), e.g. 09:05`);
        return;
      }
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(pDate)) {
      setErr("Please pick the punch date");
      return;
    }
    if (!reason.trim()) {
      setErr("Reason is required for audit");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const why = reason.trim();
      const upsert = async (t: string, k: "in" | "out", existing: Punch | null, date: string) => {
        const at = `${date}T${t}:00`;
        if (existing) {
          await api(`/admin/attendance/${existing.record_id}`, {
            method: "PATCH",
            body: { at, kind: k, reason: why },
          });
        } else {
          await api(`/admin/attendance/manual-punch`, {
            method: "POST",
            body: { user_id: userId, kind: k, at, reason: why },
          });
        }
      };
      if (inTime) await upsert(inTime, "in", firstIn, pDate);
      if (outTime) await upsert(outTime, "out", dutyOut, outIsNextDay ? nextDay(pDate) : pDate);
      if (otInTime) {
        await upsert(otInTime, "in", otInPunch, otInIsNextDay ? nextDay(pDate) : pDate);
      } else if (otOutTime && !otInPunch) {
        // Iter 544 (user bug) — an OT OUT without an OT IN never forms a
        // pair, so duty/OT reports silently dropped it AND flagged the
        // day unpaired. Auto-add the OT IN 1 minute after the duty OUT
        // (OT starts when duty ends).
        const dutyOutDate = outIsNextDay ? nextDay(pDate) : pDate;
        const dutyOutHHMM = outTime || (dutyOut ? (dutyOut.at || "").slice(11, 16) : "");
        if (!dutyOutHHMM) {
          setErr("OT Out needs an OT In time (or a duty OUT) to pair with — enter OT In.");
          setBusy(false);
          return;
        }
        const d = new Date(`${dutyOutDate}T${dutyOutHHMM}:00Z`);
        d.setUTCMinutes(d.getUTCMinutes() + 1);
        await upsert(d.toISOString().slice(11, 16), "in", null, d.toISOString().slice(0, 10));
      }
      if (otOutTime) await upsert(otOutTime, "out", otOutPunch, otOutIsNextDay ? nextDay(pDate) : pDate);
      setChanged(true);
      setBothOpen(false);
      await load();
      onSaved?.(); // refresh the grid behind the modal immediately
    } catch (e: any) {
      setErr(e?.message || "Failed to save punches");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!/^\d{2}:\d{2}$/.test(time)) {
      setErr("Enter time as HH:MM (24-hour), e.g. 09:05");
      return;
    }
    const [hh, mm] = time.split(":").map(Number);
    if (hh > 23 || mm > 59) {
      setErr("Invalid time");
      return;
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(pDate)) {
      setErr("Please pick the punch date");
      return;
    }
    if (!reason.trim()) {
      setErr("Reason is required for audit");
      return;
    }
    setBusy(true);
    setErr("");
    try {
      const at = `${pDate}T${time}:00`;
      if (editId) {
        await api(`/admin/attendance/${editId}`, {
          method: "PATCH",
          body: { at, kind, reason: reason.trim() },
        });
      } else {
        await api(`/admin/attendance/manual-punch`, {
          method: "POST",
          body: { user_id: userId, kind, at, reason: reason.trim() },
        });
      }
      setChanged(true);
      setFormOpen(false);
      await load();
      onSaved?.(); // refresh the grid behind the modal immediately
    } catch (e: any) {
      setErr(e?.message || "Failed to save punch");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: Punch) => {
    const doDelete = async () => {
      setBusy(true);
      try {
        await api(
          `/admin/attendance/${p.record_id}?reason=${encodeURIComponent("Deleted via grid repair")}`,
          { method: "DELETE" },
        );
        setChanged(true);
        await load();
        onSaved?.(); // refresh the grid behind the modal immediately
      } catch (e: any) {
        const msg = e?.message || "Failed to delete";
        if (Platform.OS === "web") window.alert(msg);
        else Alert.alert("Error", msg);
      } finally {
        setBusy(false);
      }
    };
    const q = `Delete ${p.kind.toUpperCase()} punch at ${(p.at || "").slice(11, 16)} on ${(p.at || "").slice(0, 10).split("-").reverse().join("-")}?`;
    if (Platform.OS === "web") {
      if (window.confirm(q)) doDelete();
    } else {
      Alert.alert("Delete punch", q, [
        { text: "Cancel", style: "cancel" },
        { text: "Delete", style: "destructive", onPress: doDelete },
      ]);
    }
  };

  return (
    <Modal transparent animationType="fade" onRequestClose={() => onClose(changed)}>
      <View style={st.backdrop}>
        <View style={st.card}>
          {/* Header */}
          <View style={st.header}>
            <View style={{ flex: 1 }}>
              <Text style={st.title} numberOfLines={1}>🩺 Repair Punches</Text>
              <Text style={st.subtitle} numberOfLines={1}>
                {empName} · {fmtDateDmy(dateIso)}
              </Text>
            </View>
            <Pressable onPress={() => onClose(changed)} hitSlop={10} style={st.closeBtn}>
              <Ionicons name="close" size={20} color={colors.onSurfaceSecondary} />
            </Pressable>
          </View>

          <ScrollView
            style={st.body}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator
          >
          {/* Missing-punch banner */}
          {!loading && punches.length > 0 && hasIn !== hasOut && (
            <View style={st.warnBanner}>
              <Text style={st.warnTxt}>
                ⚠ Missing {hasIn ? "OUT" : "IN"} punch — add it below to fix the duty hours.
              </Text>
            </View>
          )}
          {!loading && punches.length === 0 && (
            <View style={st.warnBanner}>
              <Text style={st.warnTxt}>No punches recorded this day. Add IN and OUT below.</Text>
            </View>
          )}

          {/* Punch list */}
          {loading ? (
            <ActivityIndicator style={{ marginVertical: 24 }} color={colors.primary} />
          ) : (
            <View>
              {punches.map((p) => (
                <View key={p.record_id} style={st.punchRow}>
                  <View style={[st.kindBadge, p.kind === "in" ? st.kindIn : st.kindOut]}>
                    <Text style={st.kindTxt}>{p.kind.toUpperCase()}</Text>
                  </View>
                  <View style={{ minWidth: 78 }}>
                    <Text style={st.timeTxt}>{(p.at || "").slice(11, 16)}</Text>
                    {/* Iter 295 (user request) — show the punch DATE too so
                        wrong-day punches (e.g. night-shift OUT on the next
                        date) are obvious while rectifying. Amber = the punch
                        date differs from the day being repaired. */}
                    <Text
                      style={[
                        st.dateTxt,
                        (p.at || "").slice(0, 10) !== dateIso && st.dateTxtDiff,
                      ]}
                    >
                      {(p.at || "").slice(0, 10).split("-").reverse().join("-")}
                    </Text>
                  </View>
                  <Text style={st.srcTxt}>{srcLabel(p.source)}</Text>
                  {/* Iter 482 (user bug — "both punches available but
                      showing missing"): PENDING punches don't count in
                      the grid until approved. Tag them + 1-tap Approve. */}
                  {String(p.status || "") === "pending" ? (
                    <Pressable
                      onPress={async () => {
                        setBusy(true);
                        try {
                          await api(`/attendance/punches/${p.record_id}/decision`, {
                            method: "POST",
                            body: { action: "approve", reason: "Approved via grid repair" },
                          });
                          setChanged(true);
                          await load();
                          onSaved?.(); // Iter 486 — refresh the grid instantly
                        } catch (e: any) {
                          setErr(e?.message || "Approve failed");
                        } finally {
                          setBusy(false);
                        }
                      }}
                      disabled={busy}
                      style={st.pendingBtn}
                      testID={`approve-${p.record_id}`}
                    >
                      <Ionicons name="checkmark-circle" size={13} color="#B45309" />
                      <Text style={st.pendingTxt}>PENDING — tap to approve</Text>
                    </Pressable>
                  ) : null}
                  <View style={{ flex: 1 }} />
                  <Pressable onPress={() => openEdit(p)} hitSlop={8} style={st.iconBtn} disabled={busy}>
                    <Ionicons name="pencil" size={16} color={colors.primary} />
                  </Pressable>
                  <Pressable onPress={() => remove(p)} hitSlop={8} style={st.iconBtn} disabled={busy}>
                    <Ionicons name="trash-outline" size={16} color="#DC2626" />
                  </Pressable>
                </View>
              ))}
            </View>
          )}

          {/* Add buttons */}
          {!formOpen && !bothOpen && (
            <>
              {/* Iter 498 (user request) — repair the whole day in ONE go */}
              <Pressable
                style={st.bothBtn}
                onPress={openBoth}
                testID="repair-both-btn"
              >
                <Ionicons name="flash" size={16} color="#fff" />
                <Text style={st.bothBtnTxt}>
                  Fix IN + OUT Together (one save)
                </Text>
              </Pressable>
              <View style={st.addRow}>
                <Pressable style={[st.addBtn, { backgroundColor: "#DCFCE7" }]} onPress={() => openAdd("in")}>
                  <Ionicons name="add" size={16} color="#15803D" />
                  <Text style={[st.addBtnTxt, { color: "#15803D" }]}>Add IN</Text>
                </Pressable>
                <Pressable style={[st.addBtn, { backgroundColor: "#FEE2E2" }]} onPress={() => openAdd("out")}>
                  <Ionicons name="add" size={16} color="#B91C1C" />
                  <Text style={[st.addBtnTxt, { color: "#B91C1C" }]}>Add OUT</Text>
                </Pressable>
              </View>
            </>
          )}

          {/* Iter 498 — one-shot IN + OUT repair form */}
          {bothOpen && (
            <View style={st.form}>
              <Text style={st.formTitle}>
                Fix full attendance — {firstIn ? "update" : "add"} IN · {dutyOut ? "update" : "add"} OUT
              </Text>
              <View style={st.formRow}>
                <View style={{ flex: 1 }}>
                  <Text style={st.bothLbl}>IN time</Text>
                  <TextInput
                    style={[st.timeInput, { borderColor: "#86EFAC" }]}
                    value={inTime}
                    onChangeText={(v) => setInTime(fmtTimeRaw(v))}
                    placeholder="HH:MM"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    keyboardType="number-pad"
                    maxLength={5}
                    autoFocus
                    testID="repair-in-time"
                  />
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={st.bothLbl}>OUT time</Text>
                  <TextInput
                    style={[st.timeInput, { borderColor: "#FCA5A5" }]}
                    value={outTime}
                    onChangeText={(v) => setOutTime(fmtTimeRaw(v))}
                    placeholder="HH:MM"
                    placeholderTextColor={colors.onSurfaceTertiary}
                    keyboardType="number-pad"
                    maxLength={5}
                    testID="repair-out-time"
                  />
                </View>
              </View>
              {outIsNextDay ? (
                <Text style={st.nightHint}>
                  🌙 OUT is earlier than IN — it will be saved on the NEXT day
                  ({nextDay(pDate).split("-").reverse().join("-")}) as a night shift.
                </Text>
              ) : null}
              {/* Iter 498b — OT pair (2nd IN→OUT), repairable in the same save */}
              {!otOpen ? (
                <Pressable
                  style={st.otToggle}
                  onPress={() => setOtOpen(true)}
                  testID="repair-ot-toggle"
                >
                  <Ionicons name="add-circle-outline" size={14} color="#B45309" />
                  <Text style={st.otToggleTxt}>Also repair OT punch (OT In / OT Out)</Text>
                </Pressable>
              ) : (
                <View style={st.otBox}>
                  <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
                    <Text style={st.otTitle}>⏱ OT punches (2nd IN → OUT pair)</Text>
                    <Pressable
                      onPress={() => { setOtOpen(false); setOtInTime(""); setOtOutTime(""); }}
                      hitSlop={8}
                    >
                      <Ionicons name="close-circle-outline" size={16} color={colors.onSurfaceTertiary} />
                    </Pressable>
                  </View>
                  <View style={[st.formRow, { marginTop: 6 }]}>
                    <View style={{ flex: 1 }}>
                      <Text style={st.bothLbl}>OT In</Text>
                      <TextInput
                        style={[st.timeInput, { borderColor: "#FCD34D" }]}
                        value={otInTime}
                        onChangeText={(v) => setOtInTime(fmtTimeRaw(v))}
                        placeholder="HH:MM"
                        placeholderTextColor={colors.onSurfaceTertiary}
                        keyboardType="number-pad"
                        maxLength={5}
                        testID="repair-otin-time"
                      />
                    </View>
                    <View style={{ flex: 1 }}>
                      <Text style={st.bothLbl}>OT Out</Text>
                      <TextInput
                        style={[st.timeInput, { borderColor: "#FCD34D" }]}
                        value={otOutTime}
                        onChangeText={(v) => setOtOutTime(fmtTimeRaw(v))}
                        placeholder="HH:MM"
                        placeholderTextColor={colors.onSurfaceTertiary}
                        keyboardType="number-pad"
                        maxLength={5}
                        testID="repair-otout-time"
                      />
                    </View>
                  </View>
                  {otInIsNextDay || otOutIsNextDay ? (
                    <Text style={st.nightHint}>
                      🌙 {otInIsNextDay ? "OT In and OT Out" : "OT Out"} will be saved on the
                      next day ({nextDay(pDate).split("-").reverse().join("-")}).
                    </Text>
                  ) : null}
                </View>
              )}
              <View style={{ marginTop: 8 }}>
                <WebDateField
                  value={pDate}
                  onChange={setPDate}
                  testID="repair-both-date"
                />
              </View>
              <TextInput
                style={st.reasonInput}
                value={reason}
                onChangeText={setReason}
                placeholder="Reason (audit)"
                placeholderTextColor={colors.onSurfaceTertiary}
              />
              {err ? <Text style={st.errTxt}>{err}</Text> : null}
              <View style={st.formActions}>
                <Pressable style={st.cancelBtn} onPress={() => setBothOpen(false)} disabled={busy}>
                  <Text style={st.cancelTxt}>Cancel</Text>
                </Pressable>
                <Pressable
                  style={[st.saveBtn, busy && { opacity: 0.6 }]}
                  onPress={saveBoth}
                  disabled={busy}
                  testID="repair-both-save"
                >
                  {busy ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="checkmark-done" size={16} color="#fff" />
                      <Text style={st.saveTxt}>Save IN + OUT</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          )}

          {/* Add / edit form */}
          {formOpen && (
            <View style={st.form}>
              <Text style={st.formTitle}>{editId ? "Edit punch" : `Add ${kind.toUpperCase()} punch`}</Text>
              <View style={st.formRow}>
                <View style={st.kindToggle}>
                  {(["in", "out"] as const).map((k) => (
                    <Pressable
                      key={k}
                      onPress={() => setKind(k)}
                      style={[st.kindOpt, kind === k && (k === "in" ? st.kindOptInActive : st.kindOptOutActive)]}
                    >
                      <Text style={[st.kindOptTxt, kind === k && { color: "#fff" }]}>{k.toUpperCase()}</Text>
                    </Pressable>
                  ))}
                </View>
                <TextInput
                  style={st.timeInput}
                  value={time}
                  onChangeText={fmtTimeInput}
                  placeholder="HH:MM"
                  placeholderTextColor={colors.onSurfaceTertiary}
                  keyboardType="number-pad"
                  maxLength={5}
                  autoFocus
                />
              </View>
              {/* Iter 295 — punch date (calendar picker; DD-MM-YYYY shown) */}
              <View style={{ marginTop: 8 }}>
                <WebDateField
                  value={pDate}
                  onChange={setPDate}
                  testID="repair-date-input"
                />
              </View>
              <TextInput
                style={st.reasonInput}
                value={reason}
                onChangeText={setReason}
                placeholder="Reason (audit)"
                placeholderTextColor={colors.onSurfaceTertiary}
              />
              {err ? <Text style={st.errTxt}>{err}</Text> : null}
              <View style={st.formActions}>
                <Pressable style={st.cancelBtn} onPress={() => setFormOpen(false)} disabled={busy}>
                  <Text style={st.cancelTxt}>Cancel</Text>
                </Pressable>
                <Pressable style={[st.saveBtn, busy && { opacity: 0.6 }]} onPress={save} disabled={busy}>
                  {busy ? (
                    <ActivityIndicator size="small" color="#fff" />
                  ) : (
                    <>
                      <Ionicons name="checkmark" size={16} color="#fff" />
                      <Text style={st.saveTxt}>Save Punch</Text>
                    </>
                  )}
                </Pressable>
              </View>
            </View>
          )}

          {/* Footer — Save & Close (applies changes + refreshes the grid) */}
          {!formOpen && !bothOpen && (
            <Pressable
              style={[st.doneBtn, busy && { opacity: 0.6 }]}
              onPress={() => onClose(changed)}
              disabled={busy}
            >
              <Ionicons name="checkmark" size={18} color="#fff" />
              <Text style={st.doneTxt}>{changed ? "Save & Close" : "Close"}</Text>
            </Pressable>
          )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

const st = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "center",
    alignItems: "center",
    padding: spacing.lg,
  },
  card: {
    width: "100%",
    maxWidth: 420,
    maxHeight: "88%",
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.lg,
  },
  header: { flexDirection: "row", alignItems: "center", marginBottom: spacing.sm },
  body: { flexGrow: 0 },
  title: { fontSize: 16, fontWeight: "800", color: colors.onSurface },
  subtitle: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginTop: 2 },
  closeBtn: { padding: 4 },
  warnBanner: {
    backgroundColor: "rgba(245,158,11,0.12)",
    borderRadius: radius.md,
    padding: spacing.sm,
    marginBottom: spacing.sm,
  },
  warnTxt: { fontSize: 12, color: "#B45309", fontWeight: "700" },
  punchRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.border,
    gap: 10,
  },
  kindBadge: { borderRadius: 6, paddingHorizontal: 8, paddingVertical: 2 },
  kindIn: { backgroundColor: "#DCFCE7" },
  kindOut: { backgroundColor: "#FEE2E2" },
  kindTxt: { fontSize: 11, fontWeight: "800", color: colors.onSurface },
  timeTxt: { fontSize: 14, fontWeight: "800", color: colors.onSurface, minWidth: 46 },
  dateTxt: { fontSize: 10, color: colors.onSurfaceTertiary, marginTop: 1 },
  dateTxtDiff: { color: "#B45309", fontWeight: "800" },
  srcTxt: { fontSize: 11, color: colors.onSurfaceTertiary },
  pendingBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    backgroundColor: "#FEF3C7",
    borderWidth: 1,
    borderColor: "#FDE68A",
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 4,
    marginLeft: 6,
  },
  pendingTxt: { fontSize: 10, fontWeight: "800", color: "#92400E" },
  iconBtn: { padding: 6 },
  addRow: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.sm },
  bothBtn: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
    backgroundColor: "#1E3A8A",
    borderRadius: radius.md,
    paddingVertical: 11,
    marginTop: spacing.md,
  },
  bothBtnTxt: { fontSize: 13.5, fontWeight: "800", color: "#fff" },
  bothLbl: { fontSize: 11, fontWeight: "800", color: colors.onSurfaceSecondary, marginBottom: 4 },
  nightHint: { fontSize: 11.5, color: "#B45309", fontWeight: "700", marginTop: 8 },
  otToggle: {
    flexDirection: "row",
    alignItems: "center",
    gap: 5,
    marginTop: 10,
    alignSelf: "flex-start",
  },
  otToggleTxt: { fontSize: 12, fontWeight: "800", color: "#B45309" },
  otBox: {
    marginTop: 10,
    borderWidth: 1,
    borderColor: "#FDE68A",
    backgroundColor: "rgba(253,230,138,0.15)",
    borderRadius: radius.md,
    padding: spacing.sm,
  },
  otTitle: { fontSize: 12, fontWeight: "800", color: "#92400E" },
  addBtn: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: 9,
  },
  addBtnTxt: { fontSize: 13, fontWeight: "800" },
  form: {
    marginTop: spacing.md,
    backgroundColor: colors.surfaceSecondary,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  formTitle: { fontSize: 13, fontWeight: "800", color: colors.onSurface, marginBottom: spacing.sm },
  formRow: { flexDirection: "row", alignItems: "center", gap: spacing.sm },
  kindToggle: {
    flexDirection: "row",
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    overflow: "hidden",
  },
  kindOpt: { paddingHorizontal: 14, paddingVertical: 8, backgroundColor: colors.surface },
  kindOptInActive: { backgroundColor: "#15803D" },
  kindOptOutActive: { backgroundColor: "#B91C1C" },
  kindOptTxt: { fontSize: 12, fontWeight: "800", color: colors.onSurfaceSecondary },
  timeInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 15,
    fontWeight: "700",
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  reasonInput: {
    marginTop: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12,
    paddingVertical: 8,
    fontSize: 13,
    color: colors.onSurface,
    backgroundColor: colors.surface,
  },
  errTxt: { color: "#DC2626", fontSize: 12, fontWeight: "700", marginTop: 6 },
  formActions: { flexDirection: "row", gap: spacing.sm, marginTop: spacing.md },
  cancelBtn: {
    flex: 1,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelTxt: { fontSize: 14, fontWeight: "800", color: colors.onSurfaceSecondary },
  saveBtn: {
    flex: 1,
    flexDirection: "row",
    gap: 6,
    backgroundColor: "#15803D",
    borderRadius: radius.md,
    paddingVertical: 11,
    alignItems: "center",
    justifyContent: "center",
  },
  saveTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
  doneBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
    marginTop: spacing.lg, backgroundColor: "#15803D", borderRadius: radius.md,
    paddingVertical: 12,
  },
  doneTxt: { fontSize: 14, fontWeight: "800", color: "#fff" },
});
