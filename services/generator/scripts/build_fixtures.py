"""Rebuild the two small open-data extracts committed with the generator.

1. llobregat_generator/zone_boundaries.geojson: the official boundary of every zone, from the
   Barcelona district boundaries (Open Data BCN, CC BY 4.0) and the municipal boundaries at
   1:50,000 (ICGC, CC BY 4.0), simplified to about 5 m. The tests and `llobregat-generator summary`
   use it to check that orders lie inside their zone.
2. tests/fixtures/: 40 real addresses per zone drawn from the full address pool, written as their
   registers publish them, so the tests run the loader's own reading and zone assignment on them
   and generate orders without the database or the downloads: taula_direle_sample.csv and
   carrerer_sample.csv (Open Data BCN) for Barcelona, icgc_sample.csv (ICGC Adreces simplificat,
   the columns the loader reads) for the five towns.

Usage, from services/generator:
    uv run python scripts/build_fixtures.py
"""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

import numpy as np
from llobregat_generator import addresses
from llobregat_generator.config import Settings
from llobregat_generator.seeds import Seeds
from llobregat_generator.zones import BARCELONA_DISTRICTS, BOUNDARIES_PATH, ZoneMap, in_polygons, norm

DISTRICTS = addresses.Download(
    "opendata-bcn/20170706-districtes-barris",
    "https://opendata-ajuntament.barcelona.cat/data/dataset/808daafa-d9ce-48c0-925a-fa5afdb1ed41"
    "/resource/576bc645-9481-4bc4-b8bf-f5972c20df3f/download",
    "BarcelonaCiutat_Districtes.csv",
    ("Codi_Districte", "nom_districte", "geometria_wgs84"),
)
MUNICIPALITIES = addresses.Download(
    "icgc/divisions-administratives",
    "https://datacloud.icgc.cat/datacloud/divisions-administratives/json_unzip/"
    "divisions-administratives-v2r2-municipis-50000-20260120.json",
    "divisions-administratives-v2r2-municipis-50000-20260120.json",
)
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
SAMPLE_PER_ZONE = 40
SIMPLIFY_M = 5.0
M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(41.38))


def simplify(ring: list[tuple[float, float]], tolerance_m: float) -> list[tuple[float, float]]:
    """Douglas-Peucker on a closed ring, in metres of a local projection."""

    def distance(p, a, b) -> float:
        (px, py), (ax, ay), (bx, by) = ((x * M_PER_DEG_LON, y * M_PER_DEG_LAT) for x, y in (p, a, b))
        dx, dy = bx - ax, by - ay
        if dx == dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)

    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        far, index = max((distance(ring[i], ring[first], ring[last]), i) for i in range(first + 1, last))
        if far > tolerance_m:
            keep[index] = True
            stack += [(first, index), (index, last)]
    points = [p for p, kept in zip(ring, keep, strict=True) if kept]
    return points if len(points) >= 4 else ring


def check_feature_collection(path: Path) -> str | None:
    """Why the file is not a complete GeoJSON FeatureCollection; None when it is (addresses.fetch)."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return f"not a complete JSON document ({exc})"
    if not isinstance(document, dict) or not document.get("features"):
        return "not a GeoJSON FeatureCollection with features"
    return None


def parse_wkt(wkt: str) -> list[list[list[tuple[float, float]]]]:
    """POLYGON or MULTIPOLYGON in WKT to GeoJSON-like nested lists."""
    body = wkt[wkt.index("(") :]
    polygons = re.findall(r"\(\s*(\([^()]*\)(?:\s*,\s*\([^()]*\))*)\s*\)", body)
    return [
        [[tuple(map(float, point.split())) for point in ring.split(",")] for ring in re.findall(r"\(([^()]*)\)", poly)]
        for poly in polygons
    ]


def build_boundaries(seeds: Seeds, cache_dir: Path) -> dict:
    zone_map = ZoneMap.from_company(seeds.company)
    polygons: dict[str, list] = {z["zone_id"]: [] for z in seeds.company["zones"]}
    with addresses.fetch_download(DISTRICTS, cache_dir).open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            assert norm(row["nom_districte"]) == norm(BARCELONA_DISTRICTS[row["Codi_Districte"]])
            polygons[zone_map.for_district(row["Codi_Districte"])] += parse_wkt(row["geometria_wgs84"])
    towns_path = addresses.fetch(MUNICIPALITIES.url, cache_dir / MUNICIPALITIES.filename, check_feature_collection)
    towns = json.loads(towns_path.read_text(encoding="utf-8"))
    for feature in towns["features"]:
        zone_id = zone_map.for_municipality(feature["properties"]["NOMMUNI"])
        if zone_id:
            polygons[zone_id] += feature["geometry"]["coordinates"]
    features = []
    for zone in seeds.company["zones"]:
        rings = [
            [[[round(x, 6), round(y, 6)] for x, y in simplify([tuple(p) for p in ring], SIMPLIFY_M)] for ring in poly]
            for poly in polygons[zone["zone_id"]]
        ]
        features.append(
            {
                "type": "Feature",
                "properties": {"zone_id": zone["zone_id"], "name": zone["name"]},
                "geometry": {"type": "MultiPolygon", "coordinates": rings},
            }
        )
    return {
        "type": "FeatureCollection",
        "name": "Llobregat Express zone boundaries",
        "attribution": (
            "Barcelona districts: Ajuntament de Barcelona, Open Data BCN, 20170706-districtes-barris, CC BY 4.0. "
            "Municipalities: Institut Cartogràfic i Geològic de Catalunya, divisions administratives 1:50,000, "
            f"CC BY 4.0. Simplified to about {SIMPLIFY_M:.0f} m."
        ),
        "features": features,
    }


def published(path: Path, columns: dict[str, str]) -> list[dict]:
    """The rows of a register as published, with the columns the loader reads."""
    with path.open(encoding="utf-8", newline="") as f:
        return [{field: row[field] for field in columns} for row in csv.DictReader(f)]


def build_sample(seeds: Seeds, cache_dir: Path, boundaries: dict) -> dict[str, list[dict]]:
    """40 addresses per zone of the generator's pool, as rows of the files they come from."""
    zone_map = ZoneMap.from_company(seeds.company)
    direle = addresses.fetch_download(addresses.TAULA_DIRELE, cache_dir)
    carrerer = addresses.fetch_download(addresses.CARRERER, cache_dir)
    subset = addresses.icgc_subset(addresses.fetch_icgc(cache_dir), zone_map)
    names = {s["street_code"]: s["official_name"] for s in addresses.read_carrerer(carrerer)}
    pool = addresses.build_pool(
        addresses.read_taula_direle(direle), names, addresses.read_icgc_subset(subset)[0], zone_map
    )
    shapes = {f["properties"]["zone_id"]: f["geometry"]["coordinates"] for f in boundaries["features"]}
    rng = np.random.default_rng(0)
    picked = set()
    for zone_id, zone_pool in pool.items():
        inside = sum(in_polygons(shapes[zone_id], a.lon, a.lat) for a in zone_pool)
        print(f"  {zone_id}: {len(zone_pool)} addresses, {inside / len(zone_pool):.2%} inside the simplified boundary")
        picked |= {zone_pool[i].address_ref for i in rng.choice(len(zone_pool), SAMPLE_PER_ZONE, replace=False)}

    def direle_ref(row: dict) -> str:
        return addresses.barcelona_ref({addresses.TAULA_DIRELE_COLUMNS[k]: v for k, v in row.items()})

    direle_rows = [r for r in published(direle, addresses.TAULA_DIRELE_COLUMNS) if direle_ref(r) in picked]
    codes = {r["codi_carrer"] for r in direle_rows}
    return {
        "taula_direle_sample.csv": direle_rows,
        "carrerer_sample.csv": [r for r in published(carrerer, addresses.CARRERER_COLUMNS) if r["codi_via"] in codes],
        "icgc_sample.csv": [r for r in published(subset, addresses.ICGC_COLUMNS) if r["idadrvia"] in picked],
    }


def main() -> None:
    settings = Settings.from_env()
    seeds = Seeds.load(settings.seed_dir)
    boundaries = build_boundaries(seeds, settings.cache_dir)
    BOUNDARIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BOUNDARIES_PATH.write_text(json.dumps(boundaries, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {BOUNDARIES_PATH} ({BOUNDARIES_PATH.stat().st_size / 1e3:.0f} kB)")
    for name, rows in build_sample(seeds, settings.cache_dir, boundaries).items():
        with (FIXTURES / name).open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, list(rows[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {FIXTURES / name} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
