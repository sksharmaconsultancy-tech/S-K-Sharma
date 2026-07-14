import React, { useMemo } from "react";
import { Platform, View, StyleSheet } from "react-native";
import { WebView } from "react-native-webview";

import { colors, radius } from "@/src/theme";

type Pin = { lat: number; lng: number; label: string; color: string };

interface MiniMapProps {
  office: Pin | null;
  me: Pin | null;
  height?: number;
}

/**
 * Small OpenStreetMap-powered map showing up to two markers (office +
 * employee) connected by a line. Renders as an inline Leaflet page inside
 * a WebView (which is an iframe on web).
 */
export function MiniMap({ office, me, height = 220 }: MiniMapProps) {
  const html = useMemo(() => buildHtml(office, me), [office, me]);
  if (!office && !me) return null;

  return (
    <View style={[styles.wrap, { height }]}> 
      <WebView
        originWhitelist={["*"]}
        source={{ html }}
        style={styles.web}
        containerStyle={styles.web}
        // Web needs pointer events; native picks these up automatically
        scrollEnabled={false}
        scalesPageToFit={Platform.OS !== "web"}
        javaScriptEnabled
      />
    </View>
  );
}

function buildHtml(office: Pin | null, me: Pin | null): string {
  const centerLat = office?.lat ?? me?.lat ?? 20.5937;
  const centerLng = office?.lng ?? me?.lng ?? 78.9629;
  const markers: string[] = [];
  if (office) {
    markers.push(
      `L.circleMarker([${office.lat},${office.lng}], {radius:9, color:'#fff', weight:2, fillColor:'${office.color}', fillOpacity:1}).addTo(map).bindTooltip('${escapeJs(office.label)}', {permanent:true, direction:'top', offset:[0,-8]});`,
    );
  }
  if (me) {
    markers.push(
      `L.circleMarker([${me.lat},${me.lng}], {radius:9, color:'#fff', weight:2, fillColor:'${me.color}', fillOpacity:1}).addTo(map).bindTooltip('${escapeJs(me.label)}', {permanent:true, direction:'top', offset:[0,-8]});`,
    );
  }
  const line =
    office && me
      ? `L.polyline([[${office.lat},${office.lng}],[${me.lat},${me.lng}]], {color:'#0F3D3E', weight:3, dashArray:'6,6'}).addTo(map);`
      : "";
  const fit =
    office && me
      ? `map.fitBounds([[${office.lat},${office.lng}],[${me.lat},${me.lng}]], {padding:[30,30]});`
      : `map.setView([${centerLat},${centerLng}], 16);`;

  return `<!doctype html>
<html>
  <head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0" />
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <style>
      html,body,#map { height:100%; margin:0; padding:0; background:#fff; }
      .leaflet-tooltip { font-size:11px; padding:3px 6px; border-radius:6px; }
    </style>
  </head>
  <body>
    <div id="map"></div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
    <script>
      var map = L.map('map', { zoomControl:false, attributionControl:false });
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19 }).addTo(map);
      ${markers.join("\n")}
      ${line}
      ${fit}
    </script>
  </body>
</html>`;
}

function escapeJs(s: string): string {
  return String(s).replace(/[\\'"<>]/g, (c) => `\\${c}`);
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: radius.md,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  web: { flex: 1, backgroundColor: "transparent" },
});
