import { useEffect, useRef, useState } from "react";
import * as maptilersdk from "@maptiler/sdk";
import "@maptiler/sdk/dist/maptiler-sdk.css";
import { GeocodingControl } from "@maptiler/geocoding-control/maptilersdk";
import "@maptiler/geocoding-control/style.css";

// Default center — Texas
const DEFAULT_CENTER = [-99.17065, 31.391533];
const DEFAULT_ZOOM = 4.5;

export default function MapView({ apiKey, lat, lon, onCoordinateSelect  }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const markerRef = useRef(null);
  const [isHybrid, setIsHybrid] = useState(false);

  const onCoordinateSelectRef = useRef(onCoordinateSelect);
  useEffect(() => { onCoordinateSelectRef.current = onCoordinateSelect; }, [onCoordinateSelect]);

  // Initialize the map once, after the container div is in the DOM
  useEffect(() => {
    if (!containerRef.current) return;

    maptilersdk.config.apiKey = apiKey;

    mapRef.current = new maptilersdk.Map({
      container: containerRef.current,
      style: maptilersdk.MapStyle.STREETS,
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: false,
    });

    mapRef.current.addControl(
      new GeocodingControl(),
      'top-left'
    )

    // Wait for the map to finish loading before attaching interaction listeners
    mapRef.current.on("load", () => {
      // Pass clicked coordinates back to the parent
      mapRef.current.on("click", (e) => {
        if (onCoordinateSelectRef.current) {
          onCoordinateSelectRef.current({
            lat: e.lngLat.lat.toFixed(6),
            lon: e.lngLat.lng.toFixed(6),
          });
        }
      });

      // Show a crosshair cursor so the map feels clickable
      mapRef.current.getCanvas().style.cursor = "crosshair";
    });

    // Cleanup on unmount
    return () => {
      if (markerRef.current) markerRef.current.remove();
      if (mapRef.current) mapRef.current.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
  }, []); // intentionally empty — run once on mount

  useEffect(() => {
    if (!mapRef.current) return;
    mapRef.current.setStyle(
      isHybrid ? maptilersdk.MapStyle.HYBRID : maptilersdk.MapStyle.STREETS
    );
  }, [isHybrid]);

  // React to lat/lon changes: fly to coords and update marker
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const parsedLat = parseFloat(lat);
    const parsedLon = parseFloat(lon);
    const valid =
      !isNaN(parsedLat) &&
      !isNaN(parsedLon) &&
      parsedLat >= -90 && parsedLat <= 90 &&
      parsedLon >= -180 && parsedLon <= 180;

    if (!valid) {
      // Remove stale marker if coords are cleared/invalid
      if (markerRef.current) {
        markerRef.current.remove();
        markerRef.current = null;
      }
      return;
    }

    const lngLat = [parsedLon, parsedLat];

    // Place or move the marker
    if (markerRef.current) {
      markerRef.current.setLngLat(lngLat);
    } else {
      markerRef.current = new maptilersdk.Marker({ color: "#4fc3f7" })
        .setLngLat(lngLat)
        .addTo(map);
    }

    // Fly to the new location
    map.flyTo({ center: lngLat, zoom: 8, duration: 1200, essential: true });
  }, [lat, lon]);

return (
    <div style={{ position: "relative", width: "100%", flex: 1, minHeight: 0 }}>
      {/* Map canvas */}
      <div
        ref={containerRef}
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: "4px",
          overflow: "hidden",
        }}
      />

      {/* Style toggle — overlaid top-left, above the map canvas */}
      <button
        onClick={() => setIsHybrid((v) => !v)}
        style={{
          position: "absolute",
          top: 53,
          left: 10,
          zIndex: 10,
          padding: "4px 10px",
          fontSize: "0.7rem",
          fontFamily: '"IBM Plex Mono", monospace',
          fontWeight: 600,
          letterSpacing: "0.5px",
          textTransform: "uppercase",
          cursor: "pointer",
          border: "1px solid rgba(255,255,255,0.25)",
          borderRadius: "4px",
          background: "rgba(13, 17, 23, 0.75)",
          backdropFilter: "blur(4px)",
          color: "#4fc3f7",
          transition: "color 0.2s, border-color 0.2s",
        }}
        onMouseEnter={(e) => e.currentTarget.style.borderColor = "rgba(255,255,255,0.5)"}
        onMouseLeave={(e) => e.currentTarget.style.borderColor = "rgba(255,255,255,0.25)"}
      >
        {isHybrid ? "Hybrid" : "Street"}
      </button>
    </div>
  );
}