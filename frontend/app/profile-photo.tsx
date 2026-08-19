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
  Modal,
  PanResponder,
  Image as RNImage,
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

/**
 * Iter 617 (user request) — square crop step before upload: drag the photo
 * to position it inside the frame and zoom with the − / + controls. Used on
 * web (native platforms get the OS crop UI via allowsEditing).
 */
function CropModal({ uri, busy, onCancel, onDone }: {
  uri: string;
  busy: boolean;
  onCancel: () => void;
  onDone: (rect: { originX: number; originY: number; width: number; height: number }) => void;
}) {
  const V = 280; // crop viewport (square)
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [, force] = useState(0);
  const off = React.useRef({ x: 0, y: 0 });
  const start = React.useRef({ x: 0, y: 0 });
  const clampRef = React.useRef<(x: number, y: number) => { x: number; y: number }>(
    (x, y) => ({ x, y }),
  );

  useEffect(() => {
    RNImage.getSize(uri, (w, h) => setNat({ w, h }), () => setNat({ w: 720, h: 720 }));
  }, [uri]);

  const k = nat ? (V / Math.min(nat.w, nat.h)) * zoom : 1;
  const dw = nat ? nat.w * k : V;
  const dh = nat ? nat.h * k : V;
  clampRef.current = (x: number, y: number) => ({
    x: Math.min(0, Math.max(V - dw, x)),
    y: Math.min(0, Math.max(V - dh, y)),
  });
  off.current = clampRef.current(off.current.x, off.current.y);

  const pan = React.useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => true,
      onMoveShouldSetPanResponder: () => true,
      onPanResponderGrant: () => { start.current = { ...off.current }; },
      onPanResponderMove: (_e, g) => {
        off.current = clampRef.current(start.current.x + g.dx, start.current.y + g.dy);
        force((n) => n + 1);
      },
    }),
  ).current;

  const stepZoom = (d: number) => {
    setZoom((z) => Math.min(3, Math.max(1, Math.round((z + d) * 100) / 100)));
  };

  const doCrop = () => {
    if (!nat) return;
    const originX = Math.max(0, Math.round(-off.current.x / k));
    const originY = Math.max(0, Math.round(-off.current.y / k));
    const size = Math.round(V / k);
    onDone({
      originX,
      originY,
      width: Math.max(1, Math.min(size, nat.w - originX)),
      height: Math.max(1, Math.min(size, nat.h - originY)),
    });
  };

  return (
    <Modal visible transparent animationType="fade" onRequestClose={onCancel}>
      <View style={cropStyles.backdrop}>
        <View style={cropStyles.sheet}>
          <Text style={cropStyles.title}>Position &amp; crop your photo</Text>
          <Text style={cropStyles.sub}>Drag to position · use − / + to zoom</Text>
          <View style={[cropStyles.viewport, { width: V, height: V }]} {...pan.panHandlers}>
            {nat ? (
              <RNImage
                source={{ uri }}
                style={{
                  position: "absolute",
                  left: off.current.x,
                  top: off.current.y,
                  width: dw,
                  height: dh,
                }}
                resizeMode="stretch"
              />
            ) : (
              <ActivityIndicator color={colors.brandPrimary} />
            )}
            <View pointerEvents="none" style={cropStyles.frame} />
          </View>
          <View style={cropStyles.zoomRow}>
            <Pressable onPress={() => stepZoom(-0.25)} style={cropStyles.zoomBtn} testID="crop-zoom-out">
              <Ionicons name="remove" size={20} color={colors.onSurface} />
            </Pressable>
            <Text style={cropStyles.zoomTxt}>{Math.round(zoom * 100)}%</Text>
            <Pressable onPress={() => stepZoom(0.25)} style={cropStyles.zoomBtn} testID="crop-zoom-in">
              <Ionicons name="add" size={20} color={colors.onSurface} />
            </Pressable>
          </View>
          <View style={cropStyles.btnRow}>
            <Pressable onPress={onCancel} disabled={busy} style={cropStyles.cancelBtn} testID="crop-cancel">
              <Text style={cropStyles.cancelTxt}>Cancel</Text>
            </Pressable>
            <Pressable
              onPress={doCrop}
              disabled={busy || !nat}
              style={[cropStyles.okBtn, (busy || !nat) && { opacity: 0.6 }]}
              testID="crop-upload"
            >
              {busy ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Ionicons name="crop-outline" size={16} color="#fff" />
              )}
              <Text style={cropStyles.okTxt}>Crop &amp; Upload</Text>
            </Pressable>
          </View>
        </View>
      </View>
    </Modal>
  );
}

const cropStyles = StyleSheet.create({
  backdrop: {
    flex: 1, backgroundColor: "rgba(15,23,42,0.75)",
    alignItems: "center", justifyContent: "center", padding: 20,
  },
  sheet: {
    backgroundColor: colors.surface, borderRadius: radius.lg,
    padding: spacing.md, alignItems: "center", gap: 10, width: 328, maxWidth: "100%",
  },
  title: { fontSize: 15, fontWeight: "800", color: colors.onSurface },
  sub: { fontSize: 11.5, color: colors.onSurfaceTertiary },
  viewport: {
    overflow: "hidden", borderRadius: 12, backgroundColor: "#0F172A",
    alignItems: "center", justifyContent: "center",
  },
  frame: {
    position: "absolute", left: 0, top: 0, right: 0, bottom: 0,
    borderWidth: 2, borderColor: "rgba(255,255,255,0.85)", borderRadius: 12,
  },
  zoomRow: { flexDirection: "row", alignItems: "center", gap: 14 },
  zoomBtn: {
    width: 40, height: 40, borderRadius: 20, borderWidth: 1,
    borderColor: colors.borderLight, alignItems: "center", justifyContent: "center",
    backgroundColor: colors.background,
  },
  zoomTxt: { fontSize: 13, fontWeight: "700", color: colors.onSurface, minWidth: 46, textAlign: "center" },
  btnRow: { flexDirection: "row", gap: 10, alignSelf: "stretch" },
  cancelBtn: {
    flex: 1, minHeight: 44, borderRadius: 10, borderWidth: 1,
    borderColor: colors.borderLight, alignItems: "center", justifyContent: "center",
  },
  cancelTxt: { fontSize: 13.5, fontWeight: "700", color: colors.onSurfaceSecondary },
  okBtn: {
    flex: 1.4, minHeight: 44, borderRadius: 10, backgroundColor: colors.brandPrimary,
    alignItems: "center", justifyContent: "center", flexDirection: "row", gap: 6,
  },
  okTxt: { fontSize: 13.5, fontWeight: "700", color: "#fff" },
});

export default function ProfilePhotoScreen() {
  const router = useRouter();
  const { user, refresh } = useAuth();
  const [busy, setBusy] = useState(false);
  // Iter 617 — pending image awaiting the crop step (web).
  const [cropUri, setCropUri] = useState<string | null>(null);
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
        // Iter 617 (user request) — on web the OS crop UI doesn't exist:
        // open our own crop step (drag to position + zoom) before upload.
        if (Platform.OS === "web") setCropUri(r.assets[0].uri);
        else await upload(r.assets[0].uri);
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
        if (Platform.OS === "web") setCropUri(r.assets[0].uri);
        else await upload(r.assets[0].uri);
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

  // Iter 617 — apply the chosen crop, then compress + upload.
  const onCropDone = async (rect: {
    originX: number; originY: number; width: number; height: number;
  }) => {
    if (!cropUri) return;
    setBusy(true);
    try {
      const manip = await ImageManipulator.manipulateAsync(
        cropUri,
        [{ crop: rect }, { resize: { width: 720 } }],
        { compress: 0.7, format: ImageManipulator.SaveFormat.JPEG, base64: true },
      );
      const b64 = `data:image/jpeg;base64,${manip.base64}`;
      await api("/me/profile-photo", {
        method: "POST",
        body: { photo_base64: b64 },
      });
      setPreview(b64);
      setCropUri(null);
      await refresh();
      showMsg("Photo updated ✓");
    } catch (e: any) {
      showMsg(e?.message || "Crop failed — try another photo");
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
      {cropUri ? (
        <CropModal
          uri={cropUri}
          busy={busy}
          onCancel={() => setCropUri(null)}
          onDone={onCropDone}
        />
      ) : null}
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
