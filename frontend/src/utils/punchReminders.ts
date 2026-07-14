/**
 * Local daily punch-reminder notification.
 *
 * Purpose: nudge employees who forget to open the app during a shift.
 * If they don't launch the app, the background auto-punch task never
 * fires — so a scheduled local notification is the cheapest way to
 * pull them back in.
 *
 * We intentionally use LOCAL notifications (expo-notifications with a
 * daily trigger) — no Firebase, no server infrastructure required.
 * They fire after the app has been opened at least once and
 * notification permission is granted.
 *
 * Design:
 *   • One "IN reminder" fires each morning at 09:00 local time.
 *   • One "OUT reminder" fires each evening at 18:00 local time.
 *   • Both are opt-in — user can toggle on the Profile screen. The
 *     preference is stored in AsyncStorage so it survives app restarts.
 *   • Tapping a reminder deep-links to the Attendance tab.
 *   • The scheduler runs on every app cold-start (idempotent — the OS
 *     dedupes by identifier, so scheduling twice is safe).
 */
import * as Notifications from "expo-notifications";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Platform } from "react-native";

const PREFS_KEY = "@punch_reminders_enabled_v1";
const IN_ID = "punch-reminder-in";
const OUT_ID = "punch-reminder-out";

const IN_HOUR = 9;
const OUT_HOUR = 18;

// Configure the foreground handler once at module import time so
// notifications that arrive while the app is in the foreground still
// show a banner + play a sound.
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

export async function areRemindersEnabled(): Promise<boolean> {
  try {
    const raw = await AsyncStorage.getItem(PREFS_KEY);
    // Default: OFF. User must opt in explicitly.
    return raw === "1";
  } catch {
    return false;
  }
}

async function saveEnabled(v: boolean) {
  try {
    await AsyncStorage.setItem(PREFS_KEY, v ? "1" : "0");
  } catch {}
}

async function ensurePermission(): Promise<boolean> {
  const cur = await Notifications.getPermissionsAsync();
  if (cur.granted) return true;
  if (cur.canAskAgain === false) return false;
  const req = await Notifications.requestPermissionsAsync({
    ios: {
      allowAlert: true,
      allowBadge: false,
      allowSound: true,
    },
  });
  return !!req.granted;
}

async function cancelAll() {
  try {
    await Notifications.cancelScheduledNotificationAsync(IN_ID);
  } catch {}
  try {
    await Notifications.cancelScheduledNotificationAsync(OUT_ID);
  } catch {}
}

async function scheduleDaily(
  id: string,
  hour: number,
  minute: number,
  title: string,
  body: string,
) {
  // On web the API is a no-op; skip cleanly.
  if (Platform.OS === "web") return;
  await Notifications.scheduleNotificationAsync({
    identifier: id,
    content: {
      title,
      body,
      sound: "default",
      data: { screen: "attendance" },
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DAILY,
      hour,
      minute,
    },
  });
}

/**
 * Enable reminders — requests permission (if needed), then schedules
 * the two daily notifications. Returns true if scheduling succeeded.
 */
export async function enableReminders(): Promise<boolean> {
  const granted = await ensurePermission();
  if (!granted) return false;
  await cancelAll();
  const firm = await readFirmName();
  await scheduleDaily(
    IN_ID,
    IN_HOUR,
    0,
    `Welcome to ${firm} \u2600\uFE0F`,
    `Please punch IN your attendance at ${firm} to start your duty.`,
  );
  await scheduleDaily(
    OUT_ID,
    OUT_HOUR,
    0,
    "End of duty \uD83D\uDD55",
    `You are not on duty at ${firm} — please punch OUT your attendance.`,
  );
  await saveEnabled(true);
  return true;
}

export async function disableReminders(): Promise<void> {
  await cancelAll();
  await saveEnabled(false);
}

/**
 * Idempotent re-schedule at app cold-start. Call from a top-level
 * effect (root layout or AuthContext). Skips gracefully when the OS
 * has revoked permission or the user opted out.
 */
export async function refreshRemindersOnBoot(): Promise<void> {
  try {
    if (Platform.OS === "web") return;
    const enabled = await areRemindersEnabled();
    if (!enabled) return;
    const perm = await Notifications.getPermissionsAsync();
    if (!perm.granted) {
      // Permission was revoked at the OS level — sync our flag.
      await saveEnabled(false);
      return;
    }
    // Cancel + reschedule to survive OS clears (e.g. after OS updates)
    await cancelAll();
    const firm = await readFirmName();
    await scheduleDaily(
      IN_ID,
      IN_HOUR,
      0,
      `Welcome to ${firm} \u2600\uFE0F`,
      `Please punch IN your attendance at ${firm} to start your duty.`,
    );
    await scheduleDaily(
      OUT_ID,
      OUT_HOUR,
      0,
      "End of duty \uD83D\uDD55",
      `You are not on duty at ${firm} — please punch OUT your attendance.`,
    );
  } catch {
    // Silent — never crash the app because of a scheduler blip.
  }
}
