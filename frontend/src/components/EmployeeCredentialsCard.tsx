import React, { useState } from "react";
import { View, Text, StyleSheet, Pressable, TextInput, ActivityIndicator, Platform, Alert } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { api } from "@/src/api/client";
import { colors, radius, spacing, type } from "@/src/theme";

type Props = {
  userId: string;
  employeeName?: string;
  loginId?: string | null;
  hasPin?: boolean;
  hasPassword?: boolean;
  onSaved?: (info: { login_id?: string | null; has_pin: boolean; has_password: boolean }) => void;
};

/**
 * Iter 96l — Employer sets an employee's login credentials (username + PIN +
 * password). The employee then signs in on the Employee login screen using
 * username + PIN or username + password.
 */
export default function EmployeeCredentialsCard({
  userId, employeeName, loginId, hasPin, hasPassword, onSaved,
}: Props) {
  const [username, setUsername] = useState(loginId || "");
  const [pin, setPin] = useState("");
  const [password, setPassword] = useState("");
  const [mustChange, setMustChange] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [showPw, setShowPw] = useState(false);

  const notify = (title: string, body: string) => {
    if (Platform.OS === "web") window.alert(`${title}\n\n${body}`);
    else Alert.alert(title, body);
  };

  const save = async () => {
    setErr(null); setMsg(null);
    const u = username.trim();
    const p = pin.trim();
    const pw = password;
    if (!u && !p && !pw) { setErr("Enter a username, PIN and/or password to set."); return; }
    if (u && (u.length < 3 || /\s/.test(u))) { setErr("Username must be 3+ characters with no spaces."); return; }
    if (p && !/^\d{6}$/.test(p)) { setErr("PIN must be exactly 6 digits."); return; }
    if (pw && (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw))) {
      setErr("Password must be 8+ characters with a letter and a number."); return;
    }
    setBusy(true);
    try {
      const body: any = { user_id: userId, must_change: mustChange };
      if (u) body.login_id = u;
      if (p) body.pin = p;
      if (pw) body.password = pw;
      const r = await api<{ ok: boolean; login_id?: string | null; has_pin: boolean; has_password: boolean }>(
        "/admin/employee-credentials",
        { method: "POST", body },
      );
      setPin(""); setPassword("");
      const parts: string[] = [];
      if (u) parts.push(`Username: ${u}`);
      if (p) parts.push(`PIN: ${p}`);
      if (pw) parts.push("Password: (set)");
      setMsg("Saved. " + parts.join("  ·  "));
      notify(
        "Credentials saved",
        `${employeeName || "Employee"} can now sign in on the Employee login using:\n\n` +
        parts.join("\n") +
        "\n\nShare these securely with the employee.",
      );
      onSaved?.({ login_id: r.login_id, has_pin: r.has_pin, has_password: r.has_password });
    } catch (e: any) {
      setErr(e?.message || "Could not save credentials");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.card} testID="employee-credentials-card">
      <View style={styles.headRow}>
        <Ionicons name="key-outline" size={18} color={colors.brand} />
        <Text style={styles.title}>Login Credentials</Text>
      </View>
      <Text style={styles.sub}>
        Set a username, PIN and/or password so this employee can sign in on the
        Employee login. Leave a field blank to keep it unchanged.
      </Text>

      <View style={styles.statusRow}>
        <View style={[styles.pill, loginId ? styles.pillOn : styles.pillOff]}>
          <Text style={[styles.pillTxt, loginId ? styles.pillTxtOn : styles.pillTxtOff]}>
            {loginId ? `Username: ${loginId}` : "No username"}
          </Text>
        </View>
        <View style={[styles.pill, hasPin ? styles.pillOn : styles.pillOff]}>
          <Text style={[styles.pillTxt, hasPin ? styles.pillTxtOn : styles.pillTxtOff]}>
            {hasPin ? "PIN set" : "No PIN"}
          </Text>
        </View>
        <View style={[styles.pill, hasPassword ? styles.pillOn : styles.pillOff]}>
          <Text style={[styles.pillTxt, hasPassword ? styles.pillTxtOn : styles.pillTxtOff]}>
            {hasPassword ? "Password set" : "No password"}
          </Text>
        </View>
      </View>

      <Text style={styles.label}>Username</Text>
      <TextInput
        testID="cred-username"
        value={username}
        onChangeText={setUsername}
        placeholder="e.g. ravi.kumar"
        placeholderTextColor={colors.onSurfaceTertiary}
        autoCapitalize="none"
        autoCorrect={false}
        style={styles.input}
      />

      <Text style={styles.label}>New PIN (6 digits)</Text>
      <TextInput
        testID="cred-pin"
        value={pin}
        onChangeText={(t) => setPin(t.replace(/\D/g, "").slice(0, 6))}
        placeholder="Leave blank to keep current"
        placeholderTextColor={colors.onSurfaceTertiary}
        keyboardType="number-pad"
        maxLength={6}
        style={styles.input}
      />

      <Text style={styles.label}>New Password</Text>
      <View style={styles.pwRow}>
        <TextInput
          testID="cred-password"
          value={password}
          onChangeText={setPassword}
          placeholder="Min 8 chars, letter + number"
          placeholderTextColor={colors.onSurfaceTertiary}
          autoCapitalize="none"
          autoCorrect={false}
          secureTextEntry={!showPw}
          style={[styles.input, { flex: 1, marginTop: 0 }]}
        />
        <Pressable onPress={() => setShowPw((v) => !v)} hitSlop={8} style={styles.eyeBtn}>
          <Ionicons name={showPw ? "eye-off-outline" : "eye-outline"} size={20} color={colors.onSurfaceSecondary} />
        </Pressable>
      </View>

      <Pressable onPress={() => setMustChange((v) => !v)} style={styles.checkRow} testID="cred-mustchange">
        <Ionicons
          name={mustChange ? "checkbox" : "square-outline"}
          size={20}
          color={mustChange ? colors.brand : colors.onSurfaceSecondary}
        />
        <Text style={styles.checkTxt}>Force change on first login</Text>
      </Pressable>

      {err ? <Text style={styles.err}>{err}</Text> : null}
      {msg ? <Text style={styles.ok}>{msg}</Text> : null}

      <Pressable style={[styles.saveBtn, busy && { opacity: 0.7 }]} onPress={save} disabled={busy} testID="cred-save">
        {busy ? <ActivityIndicator color="#fff" /> : (
          <>
            <Ionicons name="save-outline" size={16} color="#fff" />
            <Text style={styles.saveTxt}>Save Credentials</Text>
          </>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface, borderRadius: radius.lg, padding: spacing.md,
    borderWidth: 1, borderColor: colors.border, marginBottom: spacing.md,
  },
  headRow: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 4 },
  title: { ...type.h3, color: colors.onSurface, fontWeight: "800" },
  sub: { fontSize: 12.5, color: colors.onSurfaceSecondary, marginBottom: spacing.sm },
  statusRow: { flexDirection: "row", flexWrap: "wrap", gap: 6, marginBottom: spacing.sm },
  pill: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999 },
  pillOn: { backgroundColor: "#DCFCE7" },
  pillOff: { backgroundColor: "#FEE2E2" },
  pillTxt: { fontSize: 11.5, fontWeight: "700" },
  pillTxtOn: { color: "#166534" },
  pillTxtOff: { color: "#991B1B" },
  label: { fontSize: 12.5, fontWeight: "700", color: colors.onSurfaceSecondary, marginTop: 8, marginBottom: 4 },
  input: {
    backgroundColor: colors.surfaceSecondary, borderRadius: radius.md, borderWidth: 1,
    borderColor: colors.border, paddingHorizontal: 12, paddingVertical: 11, fontSize: 15,
    color: colors.onSurface,
  },
  pwRow: { flexDirection: "row", alignItems: "center", gap: 8 },
  eyeBtn: { padding: 6 },
  checkRow: { flexDirection: "row", alignItems: "center", gap: 8, marginTop: 12 },
  checkTxt: { fontSize: 13.5, color: colors.onSurface },
  err: { color: "#B91C1C", fontSize: 13, marginTop: 10 },
  ok: { color: "#166534", fontSize: 13, marginTop: 10, fontWeight: "600" },
  saveBtn: {
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: colors.brand, paddingVertical: 14, borderRadius: radius.lg, marginTop: 14,
  },
  saveTxt: { color: "#fff", fontWeight: "800", fontSize: 14.5 },
});
