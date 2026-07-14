import React, { useEffect, useState } from "react";
import {
  View,
  Text,
  StyleSheet,
  Pressable,
  ActivityIndicator,
  Platform,
  Alert,
  ScrollView,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Ionicons } from "@expo/vector-icons";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import * as ImagePicker from "expo-image-picker";
import * as ImageManipulator from "expo-image-manipulator";
import * as FileSystem from "expo-file-system";

import { api } from "@/src/api/client";
import { useAuth } from "@/src/context/AuthContext";
import { colors, radius, spacing, type } from "@/src/theme";

/**
 * Compress + resize the picked image to keep base64 payloads small
 * (target ~1MB post-encoding). Returns a data URL string.
 */
async function compressImage(uri: string): Promise<string> {
  try {
    const manip = await ImageManipulator.manipulateAsync(
      uri,
      [{ resize: { width: 720 } }],
      { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true },
    );
    if (manip.base64) return `data:image/jpeg;base64,${manip.base64}`;
  } catch {
    // Fall through to raw base64 encode
  }
  // Fallback: read the file directly (older devices)
  const b64 = await FileSystem.readAsStringAsync(uri, {
    encoding: "base64" as any,
  });
  return `data:image/jpeg;base64,${b64}`;
}

export default function ProfilePhotoScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<string | null>(
    user?.profile_photo_base64 || null,
  );

  // Re-sync the preview whenever AuthContext hydrates the user record.
  // The useState initializer only runs once at first mount, so if
  // /auth/me hadn't returned yet we'd be stuck at null even after the
  // user hydrates. This effect keeps preview in step with the ground
  // truth from AuthContext.
  useEffect(() => {
    setPreview(user?.profile_photo_base64 || null);
  }, [user?.profile_photo_base64]);

  const showMsg = (msg: string) => {
    if (Platform.OS === "web") window.alert(msg);
    else Alert.alert("Profile photo", msg);
  };

  const pick = async (from: "camera" | "library") => {
    try {
      if (from === "camera") {
        const perm = await ImagePicker.requestCameraPermissionsAsync();
        if (perm.status !== "granted") {
          showMsg("Camera permission is required to take a photo.");
          return;
        }
        const r = await ImagePicker.launchCameraAsync({
          allowsEditing: true,
          aspect: [1, 1],
          quality: 0.7,
        });
        if (r.canceled || !r.assets?.[0]?.uri) return;
        await upload(r.assets[0].uri);
      } else {
        const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
        if (perm.status !== "granted") {
          showMsg("Photos permission is required.");
          return;
        }
        const r = await ImagePicker.launchImageLibraryAsync({
          allowsEditing: true,
          aspect: [1, 1],
          quality: 0.7,
        });
        if (r.canceled || !r.assets?.[0]?.uri) return;
        await upload(r.assets[0].uri);
      }
    } catch (e: any) {
      showMsg(e?.message || "Could not open picker");
    }
  };

  const upload = async (uri: string) => {
    setBusy(true);
    try {
      const b64 = await compressImage(uri);
      await api("/me/profile-photo", {
        method: "POST",
        body: { photo_base64: b64 },
      });
      setPreview(b64);
      await refresh();
      showMsg("Photo updated ✓");
    } catch (e: any) {
      showMsg(e?.message || "Upload failed");
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await api("/me/profile-photo", { method: "DELETE" });
      setPreview(null);
      await refresh();
      showMsg("Photo removed");
    } catch (e: any) {
      showMsg(e?.message || "Delete failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <View style={styles.root}>
      <SafeAreaView edges={["top"]} style={{ backgroundColor: colors.surface }}>
        <View style={styles.header}>
          <Pressable onPress={() => router.back()} hitSlop={8}>
            <Ionicons name="chevron-back" size={26} color={colors.onSurface} />
          </Pressable>
          <Text style={styles.h1}>Profile photo</Text>
          <View style={{ width: 26 }} />
        </View>
      </SafeAreaView>

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.previewWrap}>
          {preview ? (
            <Image
              source={{
                uri: preview.startsWith("data:")
                  ? preview
                  : `data:image/jpeg;base64,${preview}`,
              }}
              style={styles.preview}
              contentFit="cover"
              testID="profile-photo-preview"
            />
          ) : (
            <View style={[styles.preview, styles.previewFallback]}>
              <Text style={styles.previewInit}>{user?.name?.[0] || "U"}</Text>
            </View>
          )}
        </View>

        <Text style={styles.name}>{user?.name}</Text>
        <Text style={styles.hint}>
          Your profile photo appears on your profile card and in employer
          reports. Keep it clear and professional.
        </Text>

        <Pressable
          onPress={() => pick("camera")}
          disabled={busy}
          style={[styles.primaryBtn, busy && { opacity: 0.7 }]}
          testID="profile-photo-take"
        >
          {busy ? (
            <ActivityIndicator color="#fff" size="small" />
          ) : (
            <>
              <Ionicons name="camera-outline" size={18} color="#fff" />
              <Text style={styles.primaryTxt}>Take a photo</Text>
            </>
          )}
        </Pressable>
        <Pressable
          onPress={() => pick("library")}
          disabled={busy}
          style={[styles.secondaryBtn, busy && { opacity: 0.7 }]}
          testID="profile-photo-pick"
        >
          <Ionicons name="image-outline" size={18} color={colors.brandPrimary} />
          <Text style={styles.secondaryTxt}>Choose from library</Text>
        </Pressable>
        {preview && (
          <Pressable
            onPress={remove}
            disabled={busy}
            style={[styles.dangerBtn, busy && { opacity: 0.7 }]}
            testID="profile-photo-remove"
          >
            <Ionicons name="trash-outline" size={18} color="#B91C1C" />
            <Text style={styles.dangerTxt}>Remove photo</Text>
          </Pressable>
        )}
      </ScrollView>
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
  scroll: { padding: spacing.lg, paddingBottom: spacing.xl, alignItems: "center" },
  previewWrap: {
    marginTop: spacing.md,
    padding: 6,
    borderRadius: 999,
    backgroundColor: colors.brandTertiary,
  },
  preview: { width: 220, height: 220, borderRadius: 110 },
  previewFallback: {
    backgroundColor: colors.brandTertiary,
    alignItems: "center", justifyContent: "center",
  },
  previewInit: { color: colors.onBrandTertiary, fontSize: 72, fontWeight: "700" },
  name: { color: colors.onSurface, fontSize: type.lg, fontWeight: "700", marginTop: spacing.md },
  hint: { color: colors.onSurfaceTertiary, fontSize: type.sm, textAlign: "center", marginTop: 6, marginBottom: spacing.lg, paddingHorizontal: spacing.md },

  primaryBtn: {
    backgroundColor: colors.cta,
    borderRadius: radius.md,
    paddingVertical: 14, paddingHorizontal: 24,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    width: "100%",
  },
  primaryTxt: { color: "#fff", fontSize: type.base, fontWeight: "700" },
  secondaryBtn: {
    marginTop: 10,
    backgroundColor: colors.brandTertiary,
    borderRadius: radius.md,
    paddingVertical: 14, paddingHorizontal: 24,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    width: "100%",
  },
  secondaryTxt: { color: colors.brandPrimary, fontSize: type.base, fontWeight: "700" },
  dangerBtn: {
    marginTop: 10,
    borderRadius: radius.md,
    paddingVertical: 14, paddingHorizontal: 24,
    flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8,
    backgroundColor: "#FDECEC",
    width: "100%",
  },
  dangerTxt: { color: "#B91C1C", fontSize: type.base, fontWeight: "700" },
});
