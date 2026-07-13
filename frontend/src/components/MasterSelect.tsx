/**
 * MasterSelect — Iter 91.
 *
 * Compact dropdown backed by the Masters registry
 * (GET /admin/masters?type=X&company_id=Y). Options stay COLLAPSED until
 * the field is tapped — no more full chip lists crowding the form.
 * A "custom" text row lets the admin type a one-off value that is not
 * in the master yet.
 *
 * Used for Designation, Department and the unified Employee Type/Group
 * fields on both the Add-Employee form and the Employee Master screen.
 */
import React, { useEffect, useRef, useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, ScrollView, Platform,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";

import { api } from "@/src/api/client";
import { colors, radius } from "@/src/theme";

type Props = {
  label: string;
  masterType: "designation" | "department" | "group";
  companyId?: string | null;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  /** Uppercase both typed and picked values (designations). */
  uppercase?: boolean;
  testID?: string;
};

export default function MasterSelect({
  label, masterType, companyId, value, onChange,
  placeholder = "Tap to select", uppercase = false, testID,
}: Props) {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const wrapRef = useRef<View | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const qs = companyId
          ? `?type=${masterType}&company_id=${encodeURIComponent(companyId)}`
          : `?type=${masterType}`;
        const r = await api<{ items: { name: string }[] }>(`/admin/masters${qs}`);
        let names = (r.items || [])
          .map((i) => (i.name || "").trim())
          .filter(Boolean);
        // Iter 114 — FULL MERGE: the Employee Type / Group dropdown also
        // lists the firm's Employee Group policy templates, so picking a
        // template name auto-applies its policy to the employee.
        if (masterType === "group") {
          try {
            const gq = companyId ? `?company_id=${encodeURIComponent(companyId)}` : "";
            const g = await api<{ groups: { name: string }[] }>(`/admin/employee-groups${gq}`);
            names = names.concat((g.groups || []).map((x) => (x.name || "").trim()).filter(Boolean));
          } catch { /* groups endpoint unavailable — masters list still shown */ }
        }
        const seen = new Set<string>();
        const uniq: string[] = [];
        for (const n0 of names) {
          const n = uppercase ? n0.toUpperCase() : n0;
          const k = n.toLowerCase();
          if (!seen.has(k)) { seen.add(k); uniq.push(n); }
        }
        setOptions(uniq.sort());
      } catch {
        setOptions([]);
      }
    })();
  }, [companyId, masterType, uppercase]);

  // Close when clicking outside (web)
  useEffect(() => {
    if (Platform.OS !== "web" || !open) return;
    const onDocClick = (e: MouseEvent) => {
      const el = wrapRef.current as unknown as HTMLElement | null;
      if (!el || typeof (el as any).contains !== "function") return;
      if (!el.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [open]);

  const pick = (v: string) => {
    const val = uppercase ? v.toUpperCase() : v;
    onChange(val);
    setOpen(false);
    setCustom("");
    // Iter 113 — a manually typed value is SAVED into the master registry
    // so it appears in this dropdown permanently (user rule).
    const trimmed = val.trim();
    if (trimmed && !options.some((o) => o.toLowerCase() === trimmed.toLowerCase())) {
      setOptions((prev) => Array.from(new Set([...prev, trimmed])).sort());
      api(`/admin/masters`, {
        method: "POST",
        body: { type: masterType, name: trimmed, company_id: companyId || "__global__" },
      }).catch(() => { /* duplicate (409) or offline — value still usable */ });
    }
  };

  // Iter 108 — typing a NEW custom value auto-registers it in the
  // Masters registry so it appears as an option for every next employee.
  const pickCustom = (raw: string) => {
    const v = (uppercase ? raw.toUpperCase() : raw).trim();
    if (!v) return;
    const exists = options.some((o) => o.toLowerCase() === v.toLowerCase());
    if (!exists) {
      setOptions((prev) => [...prev, v].sort());
      api("/admin/masters", {
        method: "POST",
        body: { type: masterType, name: v, company_id: companyId || "__global__" },
      }).catch(() => {}); // 409 duplicate / permission issues are non-fatal
    }
    pick(v);
  };

  return (
    <View ref={wrapRef} style={{ position: "relative", zIndex: open ? 60 : 1 }}>
      <Text style={styles.lbl}>{label}</Text>
      <Pressable
        onPress={() => setOpen((o) => !o)}
        style={styles.trigger}
        testID={testID || `master-select-${masterType}`}
      >
        <Text style={[styles.triggerTxt, !value && { color: colors.onSurfaceTertiary }]}>
          {value || placeholder}
        </Text>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          {value ? (
            <Pressable onPress={() => pick("")} hitSlop={8}>
              <Ionicons name="close-circle" size={15} color={colors.onSurfaceTertiary} />
            </Pressable>
          ) : null}
          <Ionicons
            name={open ? "chevron-up" : "chevron-down"}
            size={15}
            color={colors.onSurfaceSecondary}
          />
        </View>
      </Pressable>

      {open ? (
        <View style={styles.menu}>
          <View style={styles.customRow}>
            <TextInput
              value={custom}
              onChangeText={(v) => setCustom(uppercase ? v.toUpperCase() : v)}
              placeholder="Type a custom value…"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={styles.customInput}
              autoCapitalize={uppercase ? "characters" : "words"}
              onSubmitEditing={() => custom.trim() && pickCustom(custom)}
              testID={`${testID || `master-select-${masterType}`}-custom`}
            />
            <Pressable
              onPress={() => custom.trim() && pickCustom(custom)}
              style={styles.customBtn}
            >
              <Ionicons name="checkmark" size={15} color="#fff" />
            </Pressable>
          </View>
          <ScrollView style={{ maxHeight: 220 }} keyboardShouldPersistTaps="handled">
            {options.length === 0 ? (
              <Text style={styles.emptyTxt}>
                Nothing in this master yet — type a custom value above, or add
                entries on the Masters screen.
              </Text>
            ) : options.map((name) => {
              const active = value.trim().toLowerCase() === name.toLowerCase();
              return (
                <Pressable
                  key={name}
                  onPress={() => pick(name)}
                  style={[styles.opt, active && styles.optActive]}
                  testID={`${testID || `master-select-${masterType}`}-opt-${name.replace(/\W+/g, "_")}`}
                >
                  <Text style={[styles.optTxt, active && styles.optTxtActive]}>{name}</Text>
                  {active ? (
                    <Ionicons name="checkmark" size={14} color={colors.brandPrimary} />
                  ) : null}
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  lbl: {
    fontSize: 12, color: colors.onSurfaceSecondary,
    fontWeight: "700", marginBottom: 4,
  },
  trigger: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between",
    borderWidth: 1, borderColor: colors.borderStrong || colors.border,
    borderRadius: radius.md,
    paddingHorizontal: 12, paddingVertical: 10,
    backgroundColor: colors.surface,
    minHeight: 44,
  },
  triggerTxt: { fontSize: 13, color: colors.onSurface, flex: 1 },
  menu: {
    // In-flow (not absolute) so the list always opens fully on web —
    // absolute menus get clipped by parent cards/ScrollViews.
    marginTop: 4,
    backgroundColor: colors.surface,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.md,
    elevation: 10,
    shadowColor: "#000", shadowOpacity: 0.16,
    shadowRadius: 10, shadowOffset: { width: 0, height: 4 },
    overflow: "hidden",
  },
  customRow: {
    flexDirection: "row", gap: 6, padding: 8,
    borderBottomWidth: 1, borderBottomColor: colors.divider,
  },
  customInput: {
    flex: 1,
    borderWidth: 1, borderColor: colors.border,
    borderRadius: radius.sm,
    paddingHorizontal: 10, paddingVertical: 6,
    fontSize: 12, color: colors.onSurface,
    backgroundColor: colors.background,
  },
  customBtn: {
    backgroundColor: colors.brandPrimary,
    borderRadius: radius.sm,
    paddingHorizontal: 10,
    alignItems: "center", justifyContent: "center",
  },
  opt: {
    flexDirection: "row", alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: 12, paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.divider,
  },
  optActive: { backgroundColor: colors.brandTertiary },
  optTxt: { fontSize: 13, color: colors.onSurface },
  optTxtActive: { color: colors.brandPrimary, fontWeight: "800" },
  emptyTxt: {
    fontSize: 11, color: colors.onSurfaceTertiary,
    padding: 12, fontStyle: "italic",
  },
});
