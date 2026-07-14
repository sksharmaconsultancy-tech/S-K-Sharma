import * as Location from "expo-location";
import { Alert, Linking, Platform } from "react-native";

export type LatLng = { latitude: number; longitude: number };

/**
 * Reverse-geocode a coordinate to a human-readable address using
 * OpenStreetMap Nominatim. Returns null on any failure. Caller should
 * fall back to "lat, lng" text.
 *
 * Note: Nominatim's usage policy requests <= 1 req/sec and a UA header
 * with contact info. In-app we throttle by only calling on location
 * change and pass a UA header.
 */
export async function reverseGeocode(
  lat: number,
  lng: number,
): Promise<string | null> {
  const d = await reverseGeocodeDetailed(lat, lng);
  return d ? d.display_name : null;
}

export type ReverseGeocodeResult = {
  display_name: string;
  address?: string;
  city?: string;
  state?: string;
  postcode?: string;
  country?: string;
};

/**
 * Richer reverse-geocode that also returns structured pieces (city,
 * state, postcode) so callers can auto-fill multiple form fields.
 */
export async function reverseGeocodeDetailed(
  lat: number,
  lng: number,
): Promise<ReverseGeocodeResult | null> {
  try {
    const url =
      `https://nominatim.openstreetmap.org/reverse?format=json&zoom=17&addressdetails=1` +
      `&lat=${lat}&lon=${lng}`;
    const res = await fetch(url, {
      headers: {
        Accept: "application/json",
        "Accept-Language": "en",
        "User-Agent": "SKSharmaCo-App/1.0",
      },
    });
    if (!res.ok) return null;
    const j = await res.json();
    if (!j) return null;
    const a = j.address || {};
    const streetParts = [
      a.house_number,
      a.road,
      a.neighbourhood || a.suburb,
    ].filter(Boolean);
    const addressLine = streetParts.length
      ? streetParts.join(", ")
      : (j.display_name as string | undefined) || "";
    return {
      display_name: (j.display_name as string) || addressLine,
      address: addressLine || undefined,
      city: a.city || a.town || a.village || a.county,
      state: a.state,
      postcode: a.postcode,
      country: a.country,
    };
  } catch {
    return null;
  }
}

/**
 * Handle permission gates & fetch current GPS position with sensible
 * defaults. Returns null if permission was denied. Shows an actionable
 * dialog with an "Open settings" button when the OS says we can no
 * longer ask.
 */
export async function requestLocation(): Promise<LatLng | null> {
  try {
    const cur = await Location.getForegroundPermissionsAsync();
    let status = cur.status;
    let canAskAgain = cur.canAskAgain;
    if (status !== "granted") {
      if (canAskAgain) {
        const req = await Location.requestForegroundPermissionsAsync();
        status = req.status;
        canAskAgain = req.canAskAgain;
      }
    }
    if (status !== "granted") {
      if (!canAskAgain && Platform.OS !== "web") {
        Alert.alert(
          "Location permission needed",
          "Please enable location access in Settings so we can verify you're at the office when you punch in/out.",
          [
            { text: "Cancel", style: "cancel" },
            { text: "Open settings", onPress: () => Linking.openSettings() },
          ],
        );
      }
      return null;
    }
    const l = await Location.getCurrentPositionAsync({
      accuracy: Location.Accuracy.High,
    });
    return { latitude: l.coords.latitude, longitude: l.coords.longitude };
  } catch {
    return null;
  }
}

/**
 * Great-circle distance in metres between two coordinates.
 */
export function haversineMeters(a: LatLng, b: LatLng): number {
  const R = 6371000;
  const toRad = (n: number) => (n * Math.PI) / 180;
  const dLat = toRad(b.latitude - a.latitude);
  const dLng = toRad(b.longitude - a.longitude);
  const s =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a.latitude)) *
      Math.cos(toRad(b.latitude)) *
      Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(s));
}

/**
 * Format meters as "12 m", "1.2 km", "3.4 km".
 */
export function formatDistance(m: number | null | undefined): string {
  if (m === null || m === undefined || Number.isNaN(m)) return "—";
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}
