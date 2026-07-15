/**
 * Cross-platform Yes/No confirmation (Iter 129e).
 * Web → window.confirm; native → Alert with Yes/No buttons.
 */
import { Alert, Platform } from "react-native";

export function confirmYesNo(message: string, title = "Please confirm"): Promise<boolean> {
  if (Platform.OS === "web") {
    return Promise.resolve(typeof window !== "undefined" ? window.confirm(message) : true);
  }
  return new Promise((resolve) => {
    Alert.alert(title, message, [
      { text: "No", style: "cancel", onPress: () => resolve(false) },
      { text: "Yes", onPress: () => resolve(true) },
    ]);
  });
}
