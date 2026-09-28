"""Validate the AI-generated company profile (prompt 001).

Three layers of checks, so a plausible-looking but wrong generation cannot slip in:

1. Structure: the JSON matches company.schema.json.
2. Consistency: the numbers agree with each other (shares, counts, capacity, shifts, KPIs).
3. Geography (needs network, skipped with --offline):
   - each centroid lies in the district or municipality it claims (Nominatim reverse geocoding),
   - each point is close to a drivable road, and the claimed road distance from the hub
     matches a real route (OSRM from the running stack).

Usage:
    uv run --project services/generator --frozen python services/generator/validate_company.py [--offline]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple

import jsonschema
from llobregat_generator.rules import minutes

SEED_DIR = Path(__file__).parent / "seed"
OSRM_URL = os.environ.get("OSRM_URL", "http://localhost:5000")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
REPO_URL = "https://github.com/RogerTito455/datacycle-logistics-route-optimization"
USER_AGENT = f"llobregat-express-datacycle/1.0 (student project; {REPO_URL})"
HTTP_TIMEOUT_S = 15
NOMINATIM_PAUSE_S = 1.1  # Nominatim usage policy: at most one request per second

# Fixed by the prompt.
EXPECTED_VEHICLES = 30
MIN_ZERO_EMISSION_SHARE = 0.5  # "mostly electric"

# Tolerances for figures the model computes by hand.
SHARE_SUM_TOLERANCE = 0.005  # zone shares must sum to 1 within this
PARCEL_MIX_TOLERANCE_PCT = 0.5  # parcel mix must sum to 100% within this

# Plausibility ranges: outside them the simulation looks odd, but the data is not wrong.
ROUTES_PER_VEHICLE_MIN, ROUTES_PER_VEHICLE_MAX = 0.8, 2.5
FALLBACK_SPEED_KMH = 20  # used when a zone names no known vehicle type
MAX_ROAD_SNAP_M = 300  # a point farther than this from a drivable road is suspicious
MAX_ROAD_DISTANCE_DEVIATION = 0.35  # claimed road distance against OSRM, as a share of OSRM's

errors: list[str] = []
warnings: list[str] = []


class Point(NamedTuple):
    """A place the profile locates: the hub or a zone centroid."""

    point_id: str
    name: str
    lat: float
    lon: float
    expected_places: list[str]

    @property
    def label(self) -> str:
        return f"{self.point_id} {self.name}"

    @property
    def lon_lat(self) -> str:
        return f"{self.lon},{self.lat}"


def error(msg: str) -> None:
    errors.append(msg)
    print(f"  ERROR  {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  WARN   {msg}")


def ok(msg: str) -> None:
    print(f"  ok     {msg}")


def check(passed: bool, msg: str, *, warn_only: bool = False) -> bool:
    """Print msg as ok when the check passed, otherwise record it as an error (or a warning)."""
    if passed:
        ok(msg)
    elif warn_only:
        warn(msg)
    else:
        error(msg)
    return passed


def norm(text: str) -> str:
    """Keep only lowercase letters and digits, so "Sarrià - Sant Gervasi" matches "Sarrià-Sant Gervasi"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in text.lower() if ch.isalnum())


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
        return json.load(resp)


def osrm(path: str) -> dict | None:
    """Call the OSRM API. On a network error or a reply that is not Ok, warn and return None."""
    try:
        reply = get_json(f"{OSRM_URL}/{path}")
    except (OSError, ValueError) as exc:  # URLError, HTTPError and timeouts are OSErrors; bad JSON is a ValueError
        warn(f"OSRM request {path} failed: {exc}")
        return None
    if reply.get("code") != "Ok":
        warn(f"OSRM request {path} replied {reply.get('code')}: {reply.get('message', '')}")
        return None
    return reply


def check_structure(company: dict) -> None:
    print("Structure")
    schema = read_json(SEED_DIR / "company.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    problems = sorted(validator.iter_errors(company), key=lambda e: list(e.path))
    for problem in problems:
        error(f"{'/'.join(map(str, problem.path)) or '(root)'}: {problem.message}")
    if not problems:
        ok("schema violations against company.schema.json: 0")


def check_consistency(company: dict) -> None:
    print("Consistency")
    zones, fleet, volume = company["zones"], company["fleet"], company["daily_volume"]
    types = {t["type_id"]: t for t in fleet["vehicle_types"]}

    share = sum(z["share_of_daily_parcels"] for z in zones)
    check(abs(share - 1) <= SHARE_SUM_TOLERANCE, f"zone shares sum to {share:.3f} (expected 1.000)")

    ids = [z["zone_id"] for z in zones]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    check(not duplicates, f"{len(ids)} zone ids, duplicated: {', '.join(duplicates) or 'none'}")

    unknown = sorted({v for z in zones for v in z["preferred_vehicle_type_ids"] if v not in types})
    check(not unknown, f"preferred vehicle types missing from the fleet: {', '.join(unknown) or 'none'}")

    count = sum(t["count"] for t in types.values())
    check(
        count == fleet["total_vehicles"] == EXPECTED_VEHICLES,
        f"vehicle counts sum to {count}, total_vehicles is {fleet['total_vehicles']} (expected {EXPECTED_VEHICLES})",
    )

    capacity = sum(t["count"] * t["parcel_capacity"] for t in types.values())
    mean = volume["weekday_parcels_mean"]
    check(capacity >= mean, f"full-fleet load {capacity} parcels, weekday mean {mean} parcels")

    mix = sum(volume["parcel_mix"].values())
    check(abs(mix - 100) <= PARCEL_MIX_TOLERANCE_PCT, f"parcel mix sums to {mix}% (expected 100%)")

    labelled = sum(t["count"] for t in types.values() if t["dgt_label"] != "0")
    zero_share = 1 - labelled / count
    check(
        zero_share > MIN_ZERO_EMISSION_SHARE,
        f"zero-emission share of the fleet {zero_share:.0%} (the prompt asks for mostly electric)",
    )

    # A route must fit inside every shift, so the shortest one is the limit.
    shortest_shift = min(
        minutes(s["end"]) - minutes(s["start"]) - s["break_minutes"] for s in company["drivers"]["shifts"]
    )
    max_route = company["drivers"]["max_route_duration_minutes"]
    check(
        max_route <= shortest_shift,
        f"max route {max_route} min, shortest shift {shortest_shift} min of work",
    )

    drivers = company["drivers"]["headcount"]
    check(drivers >= fleet["total_vehicles"], f"{drivers} drivers for {fleet['total_vehicles']} vehicles")

    kpi = company["kpi_targets"]["avg_delivery_time_per_route_minutes"]
    baseline, target = kpi["current_baseline"], kpi["target_with_optimization"]
    check(
        target < baseline <= max_route,
        f"KPI target {target} min, baseline {baseline} min, max route {max_route} min",
    )
    on_time = company["kpi_targets"]["on_time_share_pct"]
    check(
        on_time["target"] >= on_time["current_baseline"],
        f"on-time share baseline {on_time['current_baseline']}%, target {on_time['target']}%",
    )

    # Upper bound: a stop often takes more than one parcel (B2B, buildings with a concierge).
    routes = sum(z["share_of_daily_parcels"] * mean / z["stops_per_route"] for z in zones)
    print(
        f"  info   at one parcel per stop, weekday demand needs about {routes:.0f} routes for {count} vehicles "
        f"({routes / count:.1f} routes per vehicle per day)"
    )
    check(
        ROUTES_PER_VEHICLE_MIN <= routes / count <= ROUTES_PER_VEHICLE_MAX,
        f"routes per vehicle per day {routes / count:.1f} "
        f"(plausible range {ROUTES_PER_VEHICLE_MIN}-{ROUTES_PER_VEHICLE_MAX})",
        warn_only=True,
    )

    # A route ends at its last stop (the KPI), so it has one hub leg, out to the zone.
    # Driving between stops and the break are not modelled: the estimate is a lower bound.
    too_long = []
    for zone in zones:
        zone_types = [types[t] for t in zone["preferred_vehicle_type_ids"] if t in types]
        speed = min(t["urban_average_speed_kmh"] for t in zone_types) if zone_types else FALLBACK_SPEED_KMH
        hub_leg = zone["distance_from_hub_km"] / speed * 60
        stops = zone["stops_per_route"] * zone["minutes_per_stop"]
        if hub_leg + stops > max_route:
            too_long.append(zone["zone_id"])
            warn(
                f"{zone['zone_id']} {zone['name']}: stops ({stops:.0f} min) + hub leg ({hub_leg:.0f} min) "
                f"= {hub_leg + stops:.0f} min > max route {max_route}"
            )
    check(
        not too_long,
        f"zones whose stops plus hub leg (no driving between stops) exceed the max route: {len(too_long)}",
        warn_only=True,
    )


def expected_places(zone: dict) -> list[str]:
    """Inside Barcelona city the municipality always matches, so check the district instead."""
    return zone["districts"] if norm(zone["municipality"]) == "barcelona" else [zone["municipality"]]


def check_place(point: Point) -> None:
    """Reverse-geocode a point and compare with the district or municipality it claims."""
    query = urllib.parse.urlencode(
        {"lat": point.lat, "lon": point.lon, "format": "jsonv2", "zoom": 14, "addressdetails": 1}
    )
    try:
        address = get_json(f"{NOMINATIM_URL}?{query}", {"Accept-Language": "ca"}).get("address", {})
    except (OSError, ValueError) as exc:
        warn(f"{point.label}: reverse geocoding failed: {exc}")
        return
    finally:
        time.sleep(NOMINATIM_PAUSE_S)
    keys = ("city_district", "borough", "suburb", "city", "town", "municipality", "village")
    found = [address[k] for k in keys if address.get(k)]
    found_norm = {norm(place) for place in found}
    hit = any(
        norm(want) in found_norm
        or any(norm(want) in place or place in norm(want) for place in found_norm if len(place) > 3)
        for want in point.expected_places
    )
    check(hit, f"{point.label}: claims {', '.join(point.expected_places)}; OpenStreetMap says {', '.join(found)}")


def check_geography(company: dict) -> None:
    print("Geography (Nominatim reverse geocoding, OSRM on the running stack)")
    hub = company["hub"]
    hub_point = Point("hub", hub["name"], hub["lat"], hub["lon"], [hub["municipality"]])
    zone_points = {
        z["zone_id"]: Point(z["zone_id"], z["name"], z["centroid"]["lat"], z["centroid"]["lon"], expected_places(z))
        for z in company["zones"]
    }
    points = [hub_point, *zone_points.values()]

    for point in points:
        check_place(point)

    if osrm(f"nearest/v1/driving/{hub_point.lon_lat}") is None:
        warn(f"OSRM not usable at {OSRM_URL}; skipping road checks (run `make up` first)")
        return
    for point in points:
        nearest = osrm(f"nearest/v1/driving/{point.lon_lat}")
        if nearest is None:
            continue
        snap_m = nearest["waypoints"][0]["distance"]
        check(
            snap_m <= MAX_ROAD_SNAP_M,
            f"{point.label}: {snap_m:.0f} m from the nearest drivable road (limit {MAX_ROAD_SNAP_M} m)",
            warn_only=True,
        )
    for zone in company["zones"]:
        point = zone_points[zone["zone_id"]]
        route = osrm(f"route/v1/driving/{hub_point.lon_lat};{point.lon_lat}?overview=false")
        if route is None:
            continue
        real_km = route["routes"][0]["distance"] / 1000
        claimed_km = zone["distance_from_hub_km"]
        if real_km == 0:
            warn(f"{point.label}: OSRM route from the hub has zero length; cannot compare {claimed_km} km")
            continue
        deviation = abs(claimed_km - real_km) / real_km
        check(
            deviation <= MAX_ROAD_DISTANCE_DEVIATION,
            f"{point.label}: claims {claimed_km} km by road, OSRM says {real_km:.1f} km "
            f"(off by {deviation:.0%}, tolerance {MAX_ROAD_DISTANCE_DEVIATION:.0%})",
            warn_only=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip the geography checks that need network access",
    )
    args = parser.parse_args()

    company = read_json(SEED_DIR / "company.json")
    check_structure(company)
    if errors:
        print(f"\n{len(errors)} structural errors; fix those first.")
        return 1
    check_consistency(company)
    if not args.offline:
        check_geography(company)
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
