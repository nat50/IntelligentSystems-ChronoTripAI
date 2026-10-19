import type { Map as MLMap, StyleSpecification } from "maplibre-gl";

/** OpenStreetMap vector tiles (OpenFreeMap), restyled to the Figma map palette. */
export const BASE_STYLE = process.env.NEXT_PUBLIC_MAP_STYLE ?? "https://tiles.openfreemap.org/styles/positron";

export const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#e6e4df" } }],
};

const LAND = "#e6e4df";
const WARD = ["#f7f5f0", "#f4f1eb", "#eeeae2", "#ebe6dc"];

/** Recolour the base style: beige land, white roads/boundaries, quiet labels. */
export function applyPalette(map: MLMap) {
  const style = map.getStyle();
  for (const layer of style.layers ?? []) {
    const id = layer.id.toLowerCase();
    const set = (prop: string, value: unknown) => {
      try {
        map.setPaintProperty(layer.id, prop, value);
      } catch {
        /* property not valid for this layer */
      }
    };
    if (layer.type === "background") set("background-color", LAND);
    else if (layer.type === "fill") {
      if (id.includes("water")) set("fill-color", "#d9e0e3");
      else if (id.includes("park") || id.includes("wood") || id.includes("grass") || id.includes("landcover"))
        set("fill-color", WARD[2]);
      else if (id.includes("building")) set("fill-color", WARD[3]);
      else set("fill-color", WARD[1]);
    } else if (layer.type === "line") {
      if (id.includes("water") || id.includes("river")) set("line-color", "#d9e0e3");
      else if (id.includes("boundary") || id.includes("admin")) {
        set("line-color", "#ffffff");
        set("line-opacity", 0.9);
      } else if (id.includes("rail")) set("line-color", "#ddd8cf");
      else set("line-color", "#ffffff");
    } else if (layer.type === "symbol") {
      set("text-color", "#8f8a92");
      set("text-halo-color", "rgba(255,255,255,0.85)");
      if (id.includes("poi")) map.setLayoutProperty(layer.id, "visibility", "none");
    }
  }
}
