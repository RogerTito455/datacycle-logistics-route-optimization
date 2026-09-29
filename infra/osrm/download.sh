#!/bin/sh
# Download the OpenStreetMap extract that OSRM builds its road graph from.
# Skipped when the graph is already built or the file is already here.
set -eu

cd /data
if [ -f region.osrm.ready ]; then
  echo "road graph already built, skipping download"
  exit 0
fi
if [ -s region.osm.pbf ]; then
  echo "extract already downloaded ($(du -h region.osm.pbf | cut -f1))"
  exit 0
fi

echo "downloading $OSRM_PBF_URL"
curl -fL --retry 5 --retry-delay 5 -o region.osm.pbf.part "$OSRM_PBF_URL"
mv region.osm.pbf.part region.osm.pbf
echo "downloaded $(du -h region.osm.pbf | cut -f1)"
