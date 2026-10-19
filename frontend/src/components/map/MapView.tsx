"use client";

import maplibregl, { type GeoJSONSource, type LngLatLike, type Map as MLMap } from "maplibre-gl";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { clock, duration, timeRange } from "@/lib/time";
import type { Place, Point } from "@/lib/types";
import { applyPalette, BASE_STYLE, FALLBACK_STYLE } from "./style";
import s from "./map.module.css";

export interface RouteDay {
  day: number;
  color: string;
  stops: { place: Place; start: number }[];
}

export interface MapViewProps {
  center: { lat: number; lon: number };
  /** candidate places (grey) — selected ones are drawn pink */
  places?: Place[];
  selectedIds?: Set<number>;
  hoveredId?: number | null;
  onHover?: (id: number | null) => void;
  onPlaceClick?: (place: Place) => void;
  stay?: Point | null;
  onStayChange?: (p: Point) => void;
  routes?: RouteDay[];
  activeDay?: number;
  onBoundsChange?: (bbox: string) => void;
  fitKey?: string;
}

const PLACES = "ct-places";
const ROUTE = "ct-route";
const ROUTE_ACTIVE = "ct-route-active";

function cardContent(p: Place, hint?: string): HTMLElement {
  const conf = { high: "#137333", medium: "#b06000", low: "#9aa0a6" }[p.confidence] ?? "#9aa0a6";
  const card = document.createElement("div");
  const score = document.createElement("span");
  score.className = "ct-card-score";
  score.textContent = String(p.score);
  card.append(score);

  const title = document.createElement("div");
  title.className = "ct-card-title";
  title.textContent = `${p.label} · ${p.ward}`;
  card.append(title);

  for (const text of [`~${duration(p.duration)} · best ${timeRange(p.golden_start, p.golden_end)}`, `Open ${timeRange(p.open_min, p.close_min)} (from check-ins)`]) {
    const meta = document.createElement("div");
    meta.className = "ct-card-meta";
    meta.textContent = text;
    card.append(meta);
  }

  const estimate = document.createElement("div");
  estimate.className = "ct-card-est";
  const dot = document.createElement("span");
  dot.style.width = "6px";
  dot.style.height = "6px";
  dot.style.borderRadius = "50%";
  dot.style.background = conf;
  estimate.append(dot, document.createTextNode(`Estimated · ${p.confidence} confidence`));
  card.append(estimate);

  if (hint) {
    const hintElement = document.createElement("div");
    hintElement.className = "ct-card-hint";
    hintElement.textContent = hint;
    card.append(hintElement);
  }
  return card;
}

export default function MapView(props: MapViewProps) {
  const { center, places = [], selectedIds, hoveredId, stay, routes, activeDay = 0, fitKey } = props;
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MLMap | null>(null);
  const [ready, setReady] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const cb = useRef(props);
  useLayoutEffect(() => {
    cb.current = props;
  });
  const popup = useRef<maplibregl.Popup | null>(null);
  const stayMarker = useRef<maplibregl.Marker | null>(null);
  const stopMarkers = useRef<maplibregl.Marker[]>([]);
  const placeIndex = useRef<Map<number, Place>>(new Map());

  // create / destroy the map (routes stay mounted while hidden, so always clean up)
  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current,
      style: BASE_STYLE,
      center: [center.lon, center.lat],
      zoom: 12.3,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    let fellBack = false;
    map.on("error", (e) => {
      const msg = String(e?.error?.message ?? "");
      if (!fellBack && !map.isStyleLoaded() && /style|fetch|Failed/i.test(msg)) {
        fellBack = true;
        setNotice("Map tiles are unavailable offline — showing places only.");
        map.setStyle(FALLBACK_STYLE);
      }
    });
    const setup = () => {
      applyPalette(map);
      if (!map.getSource(ROUTE)) {
        const empty = { type: "FeatureCollection" as const, features: [] };
        map.addSource(ROUTE, { type: "geojson", data: empty });
        map.addSource(ROUTE_ACTIVE, { type: "geojson", data: empty, lineMetrics: true });
        const layout = { "line-cap": "round" as const, "line-join": "round" as const };
        // other days: thin and faded; active day: Figma route, #D6336C 4px
        map.addLayer({ id: ROUTE, type: "line", source: ROUTE, layout, paint: { "line-color": "#8ab4f8", "line-width": 2.5, "line-opacity": 0.6 } });
        map.addLayer({ id: ROUTE_ACTIVE, type: "line", source: ROUTE_ACTIVE, layout, paint: { "line-color": "#d6336c", "line-width": 4 } });
      }
      if (!map.getSource(PLACES)) {
        map.addSource(PLACES, { type: "geojson", data: { type: "FeatureCollection", features: [] }, promoteId: "id" });
        map.addLayer({
          id: PLACES,
          type: "circle",
          source: PLACES,
          layout: { "circle-sort-key": ["case", ["get", "selected"], 1, 0] },
          paint: {
            // Figma: candidate 14px grey, selected 20px pink, both with a 3px white ring
            "circle-radius": ["case", ["get", "selected"], 7, 4],
            "circle-color": ["case", ["get", "selected"], "#d6336c", "#9aa0a6"],
            "circle-stroke-color": "#ffffff",
            "circle-stroke-width": ["case", ["boolean", ["feature-state", "hover"], false], 4, 3],
            "circle-radius-transition": { duration: 250 },
          },
        });
      }
      setReady(true);
    };
    map.on("load", setup);
    map.on("style.load", () => map.isStyleLoaded() && setup());

    map.on("mousemove", PLACES, (e) => {
      map.getCanvas().style.cursor = "pointer";
      const id = Number(e.features?.[0]?.id);
      if (!Number.isNaN(id)) cb.current.onHover?.(id);
    });
    map.on("mouseleave", PLACES, () => {
      map.getCanvas().style.cursor = "";
      cb.current.onHover?.(null);
    });
    map.on("click", PLACES, (e) => {
      const id = Number(e.features?.[0]?.id);
      const p = placeIndex.current.get(id);
      if (p) cb.current.onPlaceClick?.(p);
    });
    const emitBounds = () => {
      const b = map.getBounds();
      cb.current.onBoundsChange?.([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(4)).join(","));
    };
    map.on("moveend", emitBounds);
    map.once("load", emitBounds);

    return () => {
      popup.current?.remove();
      stopMarkers.current.forEach((m) => m.remove());
      stopMarkers.current = [];
      stayMarker.current?.remove();
      stayMarker.current = null;
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // the map is created once per mount; later centre changes use flyTo below
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // recentre when the city changes
  useEffect(() => {
    mapRef.current?.flyTo({ center: [center.lon, center.lat], zoom: 12.3, duration: 900 });
  }, [center.lat, center.lon]);

  // candidate / selected pins
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    placeIndex.current = new Map(places.map((p) => [p.id, p]));
    const src = map.getSource(PLACES) as GeoJSONSource | undefined;
    src?.setData({
      type: "FeatureCollection",
      features: places.map((p) => ({
        type: "Feature",
        id: p.id,
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: { id: p.id, selected: selectedIds?.has(p.id) ?? false },
      })),
    });
  }, [places, selectedIds, ready]);

  // hover state + place card
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.removeFeatureState({ source: PLACES });
    popup.current?.remove();
    stopMarkers.current.forEach((m) => {
      const wrap = m.getElement();
      const pin = wrap.firstElementChild as HTMLElement | null;
      if (pin) pin.dataset.hover = String(Number(wrap.dataset.id) === hoveredId);
    });
    if (hoveredId == null) return;
    if (placeIndex.current.has(hoveredId)) map.setFeatureState({ source: PLACES, id: hoveredId }, { hover: true });
    const p =
      placeIndex.current.get(hoveredId) ??
      routes?.flatMap((r) => r.stops).find((x) => x.place.id === hoveredId)?.place;
    if (!p) return;
    const hint = cb.current.onPlaceClick ? (selectedIds?.has(p.id) ? "Click to remove" : "Click to add") : undefined;
    popup.current = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 16, className: "ct-popup", maxWidth: "260px" })
      .setLngLat([p.lon, p.lat])
      .setDOMContent(cardContent(p, hint))
      .addTo(map);
  }, [hoveredId, ready, selectedIds, routes]);

  // stay marker "H"
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !stay) return;
    if (!stayMarker.current) {
      const el = document.createElement("div");
      el.className = "ct-stay";
      el.textContent = "H";
      el.title = cb.current.onStayChange ? "Your stay — drag to move" : "Your stay";
      const m = new maplibregl.Marker({ element: el, draggable: Boolean(cb.current.onStayChange) })
        .setLngLat([stay.lon, stay.lat])
        .addTo(map);
      m.on("dragend", () => {
        const ll = m.getLngLat();
        cb.current.onStayChange?.({ lat: ll.lat, lon: ll.lng, label: "Stay" });
      });
      stayMarker.current = m;
    } else {
      stayMarker.current.setLngLat([stay.lon, stay.lat]);
    }
  }, [stay, ready]);

  // itinerary: route lines + numbered pins
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    stopMarkers.current.forEach((m) => m.remove());
    stopMarkers.current = [];
    const others = map.getSource(ROUTE) as GeoJSONSource | undefined;
    const active = map.getSource(ROUTE_ACTIVE) as GeoJSONSource | undefined;
    if (!routes || !stay) {
      others?.setData({ type: "FeatureCollection", features: [] });
      active?.setData({ type: "FeatureCollection", features: [] });
      return;
    }
    const home: [number, number] = [stay.lon, stay.lat];
    const line = (r: RouteDay) => ({
      type: "Feature" as const,
      properties: {},
      geometry: {
        type: "LineString" as const,
        coordinates: [home, ...r.stops.map((x) => [x.place.lon, x.place.lat] as [number, number]), home],
      },
    });
    const withStops = routes.filter((r) => r.stops.length);
    others?.setData({ type: "FeatureCollection", features: withStops.filter((r) => r.day !== activeDay).map(line) });
    active?.setData({ type: "FeatureCollection", features: withStops.filter((r) => r.day === activeDay).map(line) });
    routes.forEach((r) =>
      r.stops.forEach((x, i) => {
        // MapLibre positions the outer element with a transform; animate the inner one
        const wrap = document.createElement("div");
        const el = document.createElement("div");
        wrap.appendChild(el);
        wrap.dataset.id = String(x.place.id);
        el.className = "ct-pin";
        el.textContent = String(i + 1);
        el.dataset.dim = String(r.day !== activeDay);
        el.style.setProperty("--pin-color", r.day === activeDay ? r.color : "#8ab4f8");
        el.style.setProperty("--delay", `${r.day === activeDay ? 120 + i * 90 : 0}ms`);
        wrap.title = `${clock(x.start)} · ${x.place.label} · ${x.place.ward}`;
        wrap.addEventListener("mouseenter", () => cb.current.onHover?.(x.place.id));
        wrap.addEventListener("mouseleave", () => cb.current.onHover?.(null));
        stopMarkers.current.push(
          new maplibregl.Marker({ element: wrap }).setLngLat([x.place.lon, x.place.lat]).addTo(map),
        );
      }),
    );
    // draw the active day's route progressively
    let raf = 0;
    const t0 = performance.now();
    const color = routes.find((r) => r.day === activeDay)?.color ?? "#d6336c";
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / 900);
      const eased = 1 - Math.pow(1 - k, 3);
      try {
        map.setPaintProperty(ROUTE_ACTIVE, "line-gradient", [
          "step", ["line-progress"], color, Math.max(0.0001, eased), "rgba(0,0,0,0)",
        ]);
      } catch {
        return;
      }
      if (k < 1) raf = requestAnimationFrame(tick);
      else map.setPaintProperty(ROUTE_ACTIVE, "line-gradient", ["step", ["line-progress"], color, 1, color]);
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      map.setPaintProperty(ROUTE_ACTIVE, "line-gradient", ["step", ["line-progress"], color, 1, color]);
    } else raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [routes, stay, ready, activeDay]);

  // fit the view to what matters (selected places / the route)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !fitKey) return;
    const pts: LngLatLike[] = [];
    if (routes) routes.forEach((r) => r.stops.forEach((x) => pts.push([x.place.lon, x.place.lat])));
    else places.filter((p) => selectedIds?.has(p.id)).forEach((p) => pts.push([p.lon, p.lat]));
    if (stay) pts.push([stay.lon, stay.lat]);
    if (pts.length < 2) return;
    const b = new maplibregl.LngLatBounds(pts[0], pts[0]);
    pts.forEach((p) => b.extend(p));
    map.fitBounds(b, { padding: 80, maxZoom: 14.5, duration: 800 });
    // only when the key changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey, ready]);

  return (
    <div className={s.wrap}>
      <div ref={container} className={s.map} data-lenis-prevent />
      {notice && <div className={s.notice}>{notice}</div>}
    </div>
  );
}
