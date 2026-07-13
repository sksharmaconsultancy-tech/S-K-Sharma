import React, { useState } from "react";
import {
  View, Text, StyleSheet, Pressable, TextInput, KeyboardAvoidingView, Platform, ActivityIndicator,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Redirect, useRouter } from "expo-router";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, shadow, spacing, type } from "@/src/theme";
import { KeyboardAwareScrollView } from "react-native-keyboard-controller";

export default function RegisterCompany() {
  const { user } = useAuth();
  const router = useRouter();

  const [contactName, setContactName] = useState(user?.name || "");
  const [contactMobile, setContactMobile] = useState("");
  const [contactEmail, setContactEmail] = useState(
    user?.email && !user.email.endsWith("@otp.local") ? user.email : ""
  );
  const [companyName, setCompanyName] = useState("");
  const [address, setAddress] = useState("");
  const [employeeCount, setEmployeeCount] = useState("");
  const [servicesNeeded, setServicesNeeded] = useState("");
  const [notes, setNotes] = useState("");

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<{
    email_delivered: boolean;
    admin_emails: string[];
  } | null>(null);

  if (!user) return <Redirect href="/" />;
  if (user.role === "super_admin") return <Redirect href="/(tabs)" />;

  const submit = async () => {
    setError(null);
    if (!contactName.trim() || !contactMobile.trim() || !companyName.trim()) {
      setError("Please fill your name, mobile and company name");
      return;
    }
    setSubmitting(true);
    try {
      const r = await api<{
        email_delivered: boolean;
        admin_emails: string[];
      }>("/company-requests", {
        method: "POST",
        body: {
          contact_name: contactName.trim(),
          contact_mobile: contactMobile.trim(),
          contact_email: contactEmail.trim() || null,
          company_name: companyName.trim(),
          address: address.trim() || null,
          employee_count: employeeCount ? parseInt(employeeCount, 10) : null,
          services_needed: servicesNeeded.trim() || null,
          notes: notes.trim() || null,
        },
      });
      setSuccess(r);
    } catch (e: any) {
      setError(e.message || "Failed to send request");
    } finally {
      setSubmitting(false);
    }
  };

  if (success) {
    return (
      <View style={styles.root}>
        <SafeAreaView edges={["top", "bottom"]} style={{ flex: 1 }}>
          <View style={styles.header}>
            <Text style={styles.h1}>Request submitted</Text>
          </View>
          <View style={styles.successBox} testID="request-success">
            <View style={styles.successIcon}>
              <Ionicons name="checkmark" size={36} color={colors.onSuccess} />
            </View>
            <Text style={styles.successTitle}>Details shared with admin</Text>
            <Text style={styles.successBody}>
              We&apos;ve delivered your company details {success.email_delivered
                ? `to ${success.admin_emails.join(", ")}.`
                : `to the S.K. Sharma & Co. admin queue at ${success.admin_emails.join(", ")}. They will reach out on ${contactMobile} within 24 hours.`}
            </Text>
            {!success.email_delivered && (
              <Text style={styles.successHint}>
                (Email delivery is queued in-app. Ask the admin to connect SendGrid
                or a mail provider for automatic emails.)
              </Text>
            )}
            <Pressable
              testID="request-done"
              style={styles.cta}
              onPress={() => router.replace("/")}
            >
              <Text style={styles.ctaTxt}>Done</Text>
            </Pressable>
          </View>
        </SafeAreaView>
      </View>
    );
  }

  return (
    <View style={styles.root} testID="register-company-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Register your company</Text>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        style={{ flex: 1 }}
      >
        <KeyboardAwareScrollView bottomOffset={62}
          contentContainerStyle={styles.scroll}
          keyboardShouldPersistTaps="handled"
        >
          <Text style={styles.section}>Contact person</Text>

          <Field
            testID="contact-name-input"
            label="Full name *"
            value={contactName}
            onChangeText={setContactName}
            placeholder="Ramesh Kumar"
          />
          <Field
            testID="contact-mobile-input"
            label="Mobile number *"
            value={contactMobile}
            onChangeText={setContactMobile}
            placeholder="+91 98765 43210"
            keyboardType="phone-pad"
          />
          <Field
            testID="contact-email-input"
            label="Email (optional)"
            value={contactEmail}
            onChangeText={setContactEmail}
            placeholder="ramesh@company.com"
            keyboardType="email-address"
          />

          <Text style={styles.section}>Company details</Text>

          <Field
            testID="company-name-input"
            label="Company name *"
            value={companyName}
            onChangeText={setCompanyName}
            placeholder="Acme Textiles Pvt Ltd"
          />
          <Field
            testID="company-address-input"
            label="Address"
            value={address}
            onChangeText={setAddress}
            placeholder="Sector 5, Noida, UP"
          />
          <Field
            testID="employee-count-input"
            label="Approx number of employees"
            value={employeeCount}
            onChangeText={setEmployeeCount}
            placeholder="50"
            keyboardType="numeric"
          />
          <Field
            testID="services-input"
            label="Services needed"
            value={servicesNeeded}
            onChangeText={setServicesNeeded}
            placeholder="Compliance · Payroll · Attendance"
          />
          <View>
            <Text style={styles.label}>Additional notes</Text>
            <TextInput
              testID="notes-input"
              value={notes}
              onChangeText={setNotes}
              placeholder="Anything else the admin should know?"
              placeholderTextColor={colors.onSurfaceTertiary}
              style={[styles.input, { height: 90 }]}
              multiline
            />
          </View>

          {error && <Text style={styles.err}>{error}</Text>}

          <Pressable
            testID="submit-company-request"
            style={[styles.cta, submitting && { opacity: 0.7 }]}
            onPress={submit}
            disabled={submitting}
          >
            {submitting ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <>
                <Text style={styles.ctaTxt}>Send to admin</Text>
                <Ionicons name="paper-plane-outline" size={16} color="#fff" />
              </>
            )}
          </Pressable>

          <Text style={styles.legal}>
            Your details are sent to the S.K. Sharma & Co. super admin. They
            will call you on the number above.
          </Text>
          <View style={{ height: 40 }} />
        </KeyboardAwareScrollView>
      </KeyboardAvoidingView>
    </View>
  );
}

function Field({
  label, value, onChangeText, placeholder, testID, keyboardType,
}: {
  label: string; value: string; onChangeText: (v: string) => void;
  placeholder?: string; testID?: string; keyboardType?: any;
}) {
  return (
    <View>
      <Text style={styles.label}>{label}</Text>
      <TextInput
        testID={testID}
        value={value}
        onChangeText={onChangeText}
        placeholder={placeholder}
        placeholderTextColor={colors.onSurfaceTertiary}
        style={styles.input}
        keyboardType={keyboardType}
        autoCapitalize={keyboardType === "email-address" ? "none" : "sentences"}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.surface },
  header: {
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
    paddingHorizontal: spacing.lg, paddingVertical: spacing.md,
  },
  h1: { fontSize: type.lg, color: colors.onSurface, fontWeight: "700" },
  scroll: { padding: spacing.lg },
  section: {
    color: colors.onSurface, fontSize: type.base, fontWeight: "700",
    marginTop: spacing.md, marginBottom: 4,
    letterSpacing: 0.3, textTransform: "uppercase",
  },
  label: { color: colors.onSurfaceSecondary, fontSize: type.sm, marginTop: spacing.md },
  input: {
    borderWidth: 1, borderColor: colors.border, borderRadius: radius.md,
    padding: spacing.md, color: colors.onSurface, fontSize: type.base,
    marginTop: 6, backgroundColor: colors.surfaceSecondary,
  },
  err: { color: colors.error, fontSize: type.sm, marginTop: spacing.md },
  cta: {
    marginTop: spacing.lg, backgroundColor: colors.cta,
    paddingVertical: 16, borderRadius: radius.pill,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    ...shadow.cta,
  },
  ctaTxt: { color: colors.onCta, fontSize: type.lg, fontWeight: "700" },
  legal: {
    color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center",
    marginTop: spacing.md, lineHeight: 18,
  },
  successBox: {
    flex: 1, padding: spacing.xl, alignItems: "center", justifyContent: "center", gap: 16,
  },
  successIcon: {
    width: 84, height: 84, borderRadius: 42,
    backgroundColor: colors.success,
    alignItems: "center", justifyContent: "center",
  },
  successTitle: { color: colors.onSurface, fontSize: type.xl, fontWeight: "700", textAlign: "center" },
  successBody: {
    color: colors.onSurfaceSecondary, fontSize: type.base,
    textAlign: "center", lineHeight: 22, paddingHorizontal: spacing.md,
  },
  successHint: {
    color: colors.onSurfaceTertiary, fontSize: type.sm,
    textAlign: "center", lineHeight: 18, paddingHorizontal: spacing.md,
  },
});
