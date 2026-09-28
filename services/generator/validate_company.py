"""Validate the AI-generated company profile (prompt 001).

Three layers of checks, so a plausible-looking but wrong generation cannot slip in:

1. Structure: the JSON matches company.schema.json.
2. Consistency: the numbers agree with each other (shares, counts, capacity, shifts, KPIs).
3. Geography (needs network, skipped with --offline):
   - each centroid lies in the district or municipality it claims (Nominatim reverse geocoding),
   - each point is close to a drivable road, and the claimed road distance from the hub
     matches a real route (OSRM from the running stack).

Usage:
    uv run --with jsonschema python services/generator/validate_company.py [--offline]
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

import jsonschema

SEED_DIR = Path(__file__).parent / "seed"
OSRM_URL = os.environ.get("OSRM_URL", "http://localhost:5000")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
REPO_URL = "https://github.com/RogerTito455/datacycle-logistics-route-optimization"
USER_AGENT = f"llobregat-express-datacycle/1.0 (student project; {REPO_URL})"

errors: list[str] = []
warnings: list[str] = []


def error(msg: str) -> None:
    errors.append(msg)
    print(f"  ERROR  {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  WARN   {msg}")


def ok(msg: str) -> None:
    print(f"  ok     {msg}")


def minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def norm(text: str) -> str:
    """Keep only lowercase letters and digits, so "Sarrià - Sant Gervasi" matches "Sarrià-Sant Gervasi"."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(c for c in text.lower() if c.isalnum())


def get_json(url: str, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def check_structure(company: dict) -> None:
    print("Structure")
    schema = json.loads((SEED_DIR / "company.schema.json").read_text())
    validator = jsonschema.Draft202012Validator(schema)
    problems = sorted(validator.iter_errors(company), key=lambda e: list(e.path))
    for p in problems:
        error(f"{'/'.join(map(str, p.path)) or '(root)'}: {p.message}")
    if not problems:
        ok("matches company.schema.json")


def check_consistency(c: dict) -> None:
    print("Consistency")
    zones, fleet, vol = c["zones"], c["fleet"], c["daily_volume"]
    types = {t["type_id"]: t for t in fleet["vehicle_types"]}

    share = sum(z["share_of_daily_parcels"] for z in zones)
    (ok if abs(share - 1) <= 0.005 else error)(f"zone shares sum to {share:.3f}")

    ids = [z["zone_id"] for z in zones]
    (ok if len(ids) == len(set(ids)) else error)(f"{len(ids)} zone ids, unique: {len(ids) == len(set(ids))}")

    unknown = {v for z in zones for v in z["preferred_vehicle_type_ids"] if v not in types}
    (error if unknown else ok)(
        f"preferred vehicle types exist in the fleet{': unknown ' + str(unknown) if unknown else ''}"
    )

    count = sum(t["count"] for t in types.values())
    (ok if count == fleet["total_vehicles"] == 30 else error)(f"vehicle counts sum to {count}")

    capacity = sum(t["count"] * t["parcel_capacity"] for t in types.values())
    mean = vol["weekday_parcels_mean"]
    (ok if capacity >= mean else error)(f"fleet capacity {capacity} parcels per wave vs weekday mean {mean}")

    mix = sum(vol["parcel_mix"].values())
    (ok if abs(mix - 100) <= 0.5 else error)(f"parcel mix sums to {mix}%")

    non_zero = [t for t in types.values() if t["dgt_label"] != "0"]
    zero_share = 1 - sum(t["count"] for t in non_zero) / count
    (ok if zero_share > 0.5 else error)(
        f"{zero_share:.0%} of the fleet is zero-emission (prompt asks for mostly electric)"
    )

    longest_shift = max(minutes(s["end"]) - minutes(s["start"]) - s["break_minutes"] for s in c["drivers"]["shifts"])
    max_route = c["drivers"]["max_route_duration_minutes"]
    (ok if max_route <= longest_shift else error)(
        f"max route {max_route} min fits the longest shift ({longest_shift} min of work)"
    )

    drivers = c["drivers"]["headcount"]
    (ok if drivers >= fleet["total_vehicles"] else error)(f"{drivers} drivers for {fleet['total_vehicles']} vehicles")

    kpi = c["kpi_targets"]["avg_delivery_time_per_route_minutes"]
    baseline, target = kpi["current_baseline"], kpi["target_with_optimization"]
    (ok if target < baseline <= max_route else error)(
        f"KPI baseline {baseline} min, target {target} min, max route {max_route} min"
    )
    ot = c["kpi_targets"]["on_time_share_pct"]
    (ok if ot["target"] >= ot["current_baseline"] else error)(
        f"on-time share {ot['current_baseline']}% to {ot['target']}%"
    )

    # Upper bound: a stop often takes more than one parcel (B2B, buildings with a concierge).
    routes = sum(z["share_of_daily_parcels"] * mean / z["stops_per_route"] for z in zones)
    print(
        f"  info   at one parcel per stop, weekday demand needs about {routes:.0f} routes for {count} vehicles "
        f"({routes / count:.1f} routes per vehicle per day)"
    )
    if not 0.8 <= routes / count <= 2.5:
        warn("routes per vehicle per day outside 0.8-2.5, the simulation will look odd")

    for z in zones:
        types_for_zone = [types[t] for t in z["preferred_vehicle_type_ids"] if t in types]
        speed = min(t["urban_average_speed_kmh"] for t in types_for_zone) if types_for_zone else 20
        drive = 2 * z["distance_from_hub_km"] / speed * 60
        stops = z["stops_per_route"] * z["minutes_per_stop"]
        total = drive + stops
        if total > max_route:
            warn(
                f"{z['zone_id']} {z['name']}: stops ({stops:.0f} min) + hub round trip ({drive:.0f} min) "
                f"= {total:.0f} min > max route {max_route}"
            )
    ok("per-zone route length estimates computed")


def check_geography(c: dict) -> None:
    print("Geography (Nominatim reverse geocoding, OSRM on the running stack)")
    hub = c["hub"]

    # Inside Barcelona city the municipality always matches, so check the district instead.
    def expected_places(z: dict) -> list[str]:
        return z["districts"] if norm(z["municipality"]) == "barcelona" else [z["municipality"]]

    points = [("hub", hub["name"], hub["lat"], hub["lon"], [hub["municipality"]])]
    points += [
        (
            z["zone_id"],
            z["name"],
            z["centroid"]["lat"],
            z["centroid"]["lon"],
            expected_places(z),
        )
        for z in c["zones"]
    ]

    for pid, name, lat, lon, expected in points:
        query = urllib.parse.urlencode(
            {
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": 14,
                "addressdetails": 1,
            }
        )
        try:
            addr = get_json(f"{NOMINATIM_URL}?{query}", {"Accept-Language": "ca"}).get("address", {})
        except Exception as exc:  # noqa: BLE001
            warn(f"{pid} reverse geocoding failed: {exc}")
            continue
        finally:
            time.sleep(1.1)  # Nominatim usage policy: at most one request per second
        found = [
            addr.get(k, "")
            for k in (
                "city_district",
                "borough",
                "suburb",
                "city",
                "town",
                "municipality",
                "village",
            )
        ]
        found_norm = {norm(f) for f in found if f}
        hit = any(
            norm(e) in found_norm or any(norm(e) in f or f in norm(e) for f in found_norm if len(f) > 3)
            for e in expected
        )
        where = ", ".join(f for f in found if f)
        (ok if hit else error)(f"{pid} {name}: lies in {where}")

    hub_ll = f"{hub['lon']},{hub['lat']}"
    try:
        get_json(f"{OSRM_URL}/nearest/v1/driving/{hub_ll}")
    except Exception:  # noqa: BLE001
        warn(f"OSRM not reachable at {OSRM_URL}; skipping road checks (run `make up` first)")
        return
    for pid, name, lat, lon, _ in points:
        snap = get_json(f"{OSRM_URL}/nearest/v1/driving/{lon},{lat}")["waypoints"][0]["distance"]
        (ok if snap <= 300 else warn)(f"{pid} {name}: {snap:.0f} m from the nearest drivable road")
    for z in c["zones"]:
        route = get_json(
            f"{OSRM_URL}/route/v1/driving/{hub_ll};{z['centroid']['lon']},{z['centroid']['lat']}?overview=false"
        )
        real_km = route["routes"][0]["distance"] / 1000
        claimed = z["distance_from_hub_km"]
        diff = abs(claimed - real_km) / real_km
        (ok if diff <= 0.35 else warn)(
            f"{z['zone_id']} {z['name']}: claims {claimed} km by road, OSRM says {real_km:.1f} km"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip the geography checks that need network access",
    )
    args = parser.parse_args()

    company = json.loads((SEED_DIR / "company.json").read_text())
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
