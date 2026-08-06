// Iter 504 (user bug — "Still Not Showing Task Management Option in PWA of
// Super Admin Login") — dedicated TASKS bottom tab for admin roles on the
// mobile PWA. Renders the same TasksPanel used by the Portal Dashboard so
// Super Admins / Sub Admins can create, assign and review tasks from the
// phone without hunting through menus.
import React from "react";
import { View, Text, ScrollView, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

import { useAuth } from "@/src/context/AuthContext";
import { useSelectedCompany } from "@/src/context/SelectedCompanyContext";
import { colors, spacing, type } from "@/src/theme";
import TasksPanel from "@/src/components/portal/TasksPanel";

export default function TasksTabScreen() {
  const { user } = useAuth();
  const { selectedCompanyId, companies } = useSelectedCompany();
  const canView =
    user?.role === "super_admin" || user?.role === "company_admin" || user?.role === "sub_admin";

  if (!canView) {
    return (
      <View style={st.center}>
        <Text style={st.dim}>Admins only.</Text>
      </View>
    );
  }
  return (
    <View style={st.root} testID="tasks-tab-screen">
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={st.head}>
          <Text style={st.title}>Task Management</Text>
        </View>
      </SafeAreaView>
      <ScrollView contentContainerStyle={{ padding: spacing.md, paddingBottom: 90 }}>
        <TasksPanel
          companyId={selectedCompanyId}
          companies={companies}
          canPickFirm={user?.role !== "company_admin"}
          canCreate={user?.role === "super_admin" || user?.role === "sub_admin"}
          role={user?.role || ""}
          myUserId={user?.user_id || ""}
        />
      </ScrollView>
    </View>
  );
}

const st = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.background },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  dim: { fontSize: 12.5, color: colors.onSurfaceSecondary },
  head: { paddingHorizontal: spacing.md, paddingVertical: 10 },
  title: { ...type.h3, color: colors.onSurface },
});
