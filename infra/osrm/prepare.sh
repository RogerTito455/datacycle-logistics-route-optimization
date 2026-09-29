#!/usr/bin/env bash
# Build the OSRM road graph (multi-level Dijkstra) from the downloaded extract.
# Runs once; the result stays in the osrm-data volume.
set -euo pipefail

cd /data
if [ -f region.osrm.ready ]; then
  echo "road graph already built"
  exit 0
fi

start=$(date +%s)
osrm-extract -p /opt/car.lua region.osm.pbf
osrm-partition region.osrm
osrm-customize region.osrm
touch region.osrm.ready
rm -f region.osm.pbf  # the source extract is no longer needed once the graph exists
echo "road graph built in $(( $(date +%s) - start )) s"
