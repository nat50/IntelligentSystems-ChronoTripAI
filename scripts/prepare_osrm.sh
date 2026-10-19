#!/usr/bin/env sh
# Build the OSRM routing graph for Vietnam (OpenStreetMap, Geofabrik extract).
# Run once before `docker compose up`; re-run to refresh the map data.
#   sh scripts/prepare_osrm.sh [car|bicycle|foot]
set -eu

PROFILE="${1:-car}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/osrm"
IMAGE="ghcr.io/project-osrm/osrm-backend:v6.0.0"
mkdir -p "$DIR"

if [ ! -f "$DIR/vietnam-latest.osm.pbf" ]; then
  echo "Downloading Vietnam OSM extract from Geofabrik..."
  curl -L --fail -o "$DIR/vietnam-latest.osm.pbf" https://download.geofabrik.de/asia/vietnam-latest.osm.pbf
fi

docker run --rm -t -v "$DIR:/data" "$IMAGE" osrm-extract -p "/opt/$PROFILE.lua" /data/vietnam-latest.osm.pbf
docker run --rm -t -v "$DIR:/data" "$IMAGE" osrm-partition /data/vietnam-latest.osrm
docker run --rm -t -v "$DIR:/data" "$IMAGE" osrm-customize /data/vietnam-latest.osrm
echo "OSRM data ready in $DIR"
