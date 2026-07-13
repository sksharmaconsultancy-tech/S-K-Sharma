import React, { useRef, useState } from "react";
import {
  View,
  Text,
  Image,
  StyleSheet,
  Pressable,
  Modal,
  ActivityIndicator,
  Platform,
} from "react-native";
import {
  CameraView,
  useCameraPermissions,
  type CameraCapturedPicture,
} from "expo-camera";
import { Ionicons } from "@expo/vector-icons";

import { colors, radius, spacing, type } from "@/src/theme";

type Props = {
  visible: boolean;
  title?: string;
  subtitle?: string;
  onCancel: () => void;
  /** Called with a base64 JPEG (no data URI prefix). */
  onCapture: (base64: string) => Promise<void> | void;
};

/**
 * Front-camera face capture sheet used during a manual punch. Provides a
 * simple viewfinder with an oval guide, a capture button, and a preview
 * where the user can retake or confirm. Returns a small (~640px) JPEG
 * base64 payload — no external service, works offline.
 */
export default function FaceCaptureModal({
  visible,
  title = "Face scan",
  subtitle = "Position your face inside the oval and hold still",
  onCancel,
  onCapture,
}: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const cameraRef = useRef<CameraView | null>(null);
  const [preview, setPreview] = useState<CameraCapturedPicture | null>(null);
  const [capturing, setCapturing] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const grant = async () => {
    await requestPermission();
  };

  const snap = async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);
    try {
      const pic = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.4,
        skipProcessing: true,
        // No shutter sound for a more discreet experience.
        shutterSound: false,
      } as any);
      setPreview(pic ?? null);
    } catch {
      // Ignore — user can tap capture again.
    } finally {
      setCapturing(false);
    }
  };

  const confirm = async () => {
    if (!preview?.base64) return;
    setSubmitting(true);
    try {
      await onCapture(preview.base64);
    } finally {
      setSubmitting(false);
      setPreview(null);
    }
  };

  const retake = () => setPreview(null);

  return (
    <Modal
      visible={visible}
      animationType="slide"
      transparent
      onRequestClose={onCancel}
    >
      <View style={styles.root}>
        <View style={styles.header}>
          <Pressable onPress={onCancel} hitSlop={12} testID="face-cancel">
            <Ionicons name="close" size={24} color="#fff" />
          </Pressable>
          <View style={{ flex: 1, marginLeft: 12 }}>
            <Text style={styles.title}>{title}</Text>
            <Text style={styles.subtitle}>{subtitle}</Text>
          </View>
        </View>

        {!permission ? (
          <View style={styles.placeholder} testID="face-loading">
            <ActivityIndicator color="#fff" />
          </View>
        ) : !permission.granted ? (
          <View style={styles.placeholder} testID="face-permission">
            <Ionicons name="camera-outline" size={40} color="#fff" />
            <Text style={styles.permTitle}>Allow camera access</Text>
            <Text style={styles.permBody}>
              We need the camera to take a quick selfie for attendance.
            </Text>
            <Pressable style={styles.permBtn} onPress={grant}>
              <Text style={styles.permBtnTxt}>Grant permission</Text>
            </Pressable>
          </View>
        ) : preview ? (
          <View style={styles.previewWrap} testID="face-preview">
            <View style={styles.previewImgWrap}>
              <PreviewImage uri={preview.uri} />
            </View>
            <View style={styles.actionRow}>
              <Pressable
                onPress={retake}
                style={[styles.actionBtn, styles.actionSecondary]}
                testID="face-retake"
                disabled={submitting}
              >
                <Ionicons name="refresh" size={16} color="#fff" />
                <Text style={styles.actionSecondaryTxt}>Retake</Text>
              </Pressable>
              <Pressable
                onPress={confirm}
                style={[styles.actionBtn, styles.actionPrimary]}
                testID="face-confirm"
                disabled={submitting}
              >
                {submitting ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <>
                    <Ionicons name="checkmark" size={16} color="#fff" />
                    <Text style={styles.actionPrimaryTxt}>Use this photo</Text>
                  </>
                )}
              </Pressable>
            </View>
          </View>
        ) : (
          <View style={styles.previewWrap}>
            <CameraView
              ref={cameraRef}
              style={styles.camera}
              facing="front"
              // On web `expo-camera` uses <video>; ok for smoke, image quality
              // will be low. Only ask for base64 on native (see snap()).
            />
            {/* Oval face guide overlay */}
            <View pointerEvents="none" style={styles.overlay}>
              <View style={styles.ovalGuide} />
            </View>
            <View style={styles.shutterRow}>
              <Pressable
                onPress={snap}
                style={styles.shutter}
                testID="face-shutter"
                disabled={capturing}
              >
                {capturing ? (
                  <ActivityIndicator color="#fff" />
                ) : (
                  <View style={styles.shutterInner} />
                )}
              </Pressable>
            </View>
          </View>
        )}
      </View>
    </Modal>
  );
}

function PreviewImage({ uri }: { uri: string }) {
  return (
    <Image
      source={{ uri }}
      style={{ width: "100%", height: "100%", borderRadius: radius.lg }}
      resizeMode="cover"
    />
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#000" },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingTop: Platform.OS === "ios" ? 60 : 40,
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.md,
  },
  title: { color: "#fff", fontSize: type.xl, fontWeight: "800" },
  subtitle: { color: "#ddd", fontSize: type.sm, marginTop: 2 },
  placeholder: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    padding: spacing.xl,
    gap: 8,
  },
  permTitle: { color: "#fff", fontSize: type.lg, fontWeight: "800" },
  permBody: {
    color: "#ddd",
    fontSize: type.sm,
    textAlign: "center",
    marginTop: 4,
  },
  permBtn: {
    marginTop: 16,
    backgroundColor: colors.brandPrimary,
    paddingHorizontal: 20,
    paddingVertical: 12,
    borderRadius: radius.pill,
  },
  permBtnTxt: { color: "#fff", fontWeight: "800" },
  previewWrap: { flex: 1, backgroundColor: "#000" },
  camera: { flex: 1 },
  overlay: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
  },
  ovalGuide: {
    width: 240,
    height: 300,
    borderRadius: 150,
    borderWidth: 3,
    borderColor: "rgba(255,255,255,0.8)",
  },
  shutterRow: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: Platform.OS === "ios" ? 60 : 40,
    alignItems: "center",
  },
  shutter: {
    width: 72,
    height: 72,
    borderRadius: 36,
    borderWidth: 4,
    borderColor: "#fff",
    alignItems: "center",
    justifyContent: "center",
  },
  shutterInner: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: "#fff",
  },
  previewImgWrap: { flex: 1, backgroundColor: "#000" },
  actionRow: {
    flexDirection: "row",
    gap: 12,
    padding: spacing.lg,
    paddingBottom: Platform.OS === "ios" ? 40 : spacing.lg,
  },
  actionBtn: {
    flex: 1,
    borderRadius: radius.pill,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 6,
  },
  actionPrimary: { backgroundColor: colors.brandPrimary },
  actionPrimaryTxt: { color: "#fff", fontWeight: "800" },
  actionSecondary: {
    backgroundColor: "transparent",
    borderWidth: 1,
    borderColor: "#fff",
  },
  actionSecondaryTxt: { color: "#fff", fontWeight: "700" },
});
