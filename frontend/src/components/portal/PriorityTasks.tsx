/**
 * Iter 499 (user request) — compact "Priority Tasks" highlight strip shown
 * at the TOP of the existing Portal Dashboard overview. Does NOT change the
 * existing dashboard layout — it only prepends a small card.
 *
 *   🔴 Overdue   🟠 High priority   ⚠ Due today   📅 Today's schedule
 *
 * Tapping a task opens the existing Tasks tab; tapping a schedule item
 * opens the existing Calendar tab. Completed / low-priority tasks are
 * never shown here.
 */
import React from "react";
import { View, Text, StyleSheet, Pressable } from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius, spacing } from "@/src/theme";

type PriorityItem = {
  task_id: string;
  title: string;
  company_name?: string | null;
  assignee_name?: string | null;
  due_date?: string | null;
  priority: string;
  status: string;
  bucket: "overdue" | "high" | "due_today";
};

type ScheduleItem = { key: string; title: string; kind?: string; date: string };

const BUCKET: Record<string, { icon: string; color: string; label: string }> = {
  overdue: { icon: "🔴", color: "#B91C1C", label: "OVERDUE" },
  high: { icon: "🟠", color: "#C2410C", label: "HIGH" },
  due_today: { icon: "⚠️", color: "#B45309", label: "DUE TODAY" },
};

function fmtDue(due: string | null | undefined, today: string): string {
  if (!due) return "No due date";
  if (due === today) return "Due Today";
  const [y, m, d] = due.split("-");
  const lbl = `${d}-${m}-${y}`;
  return due < today ? `Was due ${lbl}` : `Due ${lbl}`;
}

export default function PriorityTasks({
  companyId,
  refreshKey,
  onOpenTasks,
  onOpenCalendar,
}: {
  companyId: string | null;
  /** bump to force a refetch (e.g. when returning to the Overview tab) */
  refreshKey?: number;
  onOpenTasks: () => void;
  onOpenCalendar: () => void;
}) {
  const [items, setItems] = React.useState<PriorityItem[]>([]);
  const [schedule, setSchedule] = React.useState<ScheduleItem[]>([]);
  const [today, setToday] = React.useState("");
  const [loaded, setLoaded] = React.useState(false);

  React.useEffect(() => {
    let alive = true;
    const q = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
    api<{ items: PriorityItem[]; schedule: ScheduleItem[]; today: string }>(
      `/admin/portal-tasks/priority${q}`,
    )
      .then((r) => {
        if (!alive) return;
        setItems(r.items || []);
        setSchedule(r.schedule || []);
        setToday(r.today || "");
        setLoaded(true);
      })
      .catch(() => alive && setLoaded(true));
    return () => {
      alive = false;
    };
  }, [companyId, refreshKey]);

  if (!loaded) return null;
  const total = items.length + schedule.length;
  if (total === 0) {
    return (
      <View style={st.clearRow} testID="priority-tasks-clear">
        <Ionicons name="checkmark-circle" size={14} color="#15803D" />
        <Text style={st.clearTxt}>All clear — no overdue or priority tasks today.</Text>
      </View>
    );
  }

  return (
    <View style={st.card} testID="priority-tasks">
      <View style={st.head}>
        <Text style={st.headTxt}>⚡ Priority Tasks</Text>
        <Pressable onPress={onOpenTasks} hitSlop={8} testID="priority-tasks-all">
          <Text style={st.allTxt}>View all →</Text>
        </Pressable>
      </View>
      {items.map((t) => {
        const b = BUCKET[t.bucket] || BUCKET.high;
        return (
          <Pressable
            key={t.task_id}
            style={st.row}
            onPress={onOpenTasks}
            testID={`priority-task-${t.task_id}`}
          >
            <Text style={st.icon}>{b.icon}</Text>
            <View style={{ flex: 1, minWidth: 0 }}>
              <Text numberOfLines={1} style={st.title}>{t.title}</Text>
              <Text numberOfLines={1} style={st.sub}>
                {[
                  t.company_name || "All firms",
                  fmtDue(t.due_date, today),
                  t.assignee_name ? `Assigned: ${t.assignee_name}` : null,
                ].filter(Boolean).join(" • ")}
              </Text>
            </View>
            <Text style={[st.badge, { color: b.color, borderColor: b.color }]}>
              {b.label}
            </Text>
          </Pressable>
        );
      })}
      {schedule.map((s) => (
        <Pressable
          key={s.key}
          style={st.row}
          onPress={onOpenCalendar}
          testID={`priority-sched-${s.key}`}
        >
          <Text style={st.icon}>📅</Text>
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text numberOfLines={1} style={st.title}>{s.title}</Text>
            <Text numberOfLines={1} style={st.sub}>
              {(s.kind || "Statutory")} • Today&apos;s schedule
            </Text>
          </View>
          <Text style={[st.badge, { color: "#1D4ED8", borderColor: "#1D4ED8" }]}>TODAY</Text>
        </Pressable>
      ))}
    </View>
  );
}

const st = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: "#FCA5A5",
    marginBottom: spacing.md,
    paddingVertical: 4,
    paddingHorizontal: 10,
  },
  head: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  headTxt: { fontSize: 12.5, fontWeight: "800", color: "#B91C1C" },
  allTxt: { fontSize: 11, fontWeight: "700", color: colors.brandPrimary },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  icon: { fontSize: 13 },
  title: { fontSize: 12, fontWeight: "700", color: colors.onSurface },
  sub: { fontSize: 10.5, color: colors.onSurfaceSecondary, marginTop: 1 },
  badge: {
    fontSize: 8.5,
    fontWeight: "800",
    borderWidth: 1,
    borderRadius: 6,
    paddingHorizontal: 6,
    paddingVertical: 2,
    overflow: "hidden",
  },
  clearRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    marginBottom: spacing.sm,
    paddingHorizontal: 4,
  },
  clearTxt: { fontSize: 11, fontWeight: "600", color: "#15803D" },
});
