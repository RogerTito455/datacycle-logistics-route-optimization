"""Reference data for the bronze tables: the company profile, fleet, drivers, shippers and addresses.

Each table's rows are built from one seed or one open-data file, and every row names it in
`source`. Loading is write-once and idempotent: a row whose key is already in the table is left
untouched, so running the load twice writes nothing the second time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NamedTuple

import pyarrow as pa

from llobregat_generator import addresses, db
from llobregat_generator.config import Settings
from llobregat_generator.rules import RELIEF_POOL, clock, span
from llobregat_generator.seeds import Seeds
from llobregat_generator.storage import Bucket
from llobregat_generator.zones import ZoneMap

COMPANY = "generator/company-profile"
FLEET = "generator/fleet"
DRIVERS = "generator/drivers"
DEMAND = "generator/demand-model"
# The seeds with one record per row are also stored in the bronze bucket, one Parquet file per
# table, and their rows keep its key. The company profile is one document spread over four tables.
SEED_FILES = {
    "bronze.vehicles": "reference/generator/fleet/vehicles.parquet",
    "bronze.drivers": "reference/generator/drivers/drivers.parquet",
    "bronze.shippers": "reference/generator/demand-model/shippers.parquet",
}


@dataclass
class Table:
    """Rows for one bronze table, all from one source."""

    name: str
    rows: list[dict]
    source: str
    raw_object_key: str | None = None
    skipped: int = 0  # rows of the file that could not be loaded

    @property
    def columns(self) -> list[str]:
        columns = list(self.rows[0]) + ["source"]
        return columns + ["raw_object_key"] if self.raw_object_key else columns

    def rows_with_metadata(self):
        """Each row's values followed by source (and raw_object_key), in the order of `columns`."""
        extra = [self.source, self.raw_object_key] if self.raw_object_key else [self.source]
        for row in self.rows:
            yield [*row.values(), *extra]


class Loaded(NamedTuple):
    """What loading one table did."""

    rows: int  # rows offered from the seed or file
    skipped: int  # rows of the file left out (ICGC addresses without coordinates)
    inserted: int  # rows whose key was new
    in_table: int  # rows in the table afterwards


def hub_id(hub: dict) -> str:
    """The code in brackets at the end of the hub's name: "... Zona Franca (BCN-ZF)" gives BCN-ZF."""
    match = re.search(r"\(([^)]+)\)\s*$", hub["name"])
    if not match:
        raise ValueError(f"no hub code in brackets in {hub['name']!r}")
    return match.group(1)


def shift_id(name: str) -> str:
    """ "Morning wave" gives morning and "Afternoon-evening wave" afternoon, the wave names of route plans."""
    return re.split(r"[\s-]", name, maxsplit=1)[0].lower()


def hubs(company: dict) -> list[dict]:
    hub, timetable = company["hub"], company["hub"]["timetable"]
    inbound = [clock(t) for t in span(timetable["inbound_trucks_arrive"])]
    sorting = [clock(t) for t in span(timetable["sorting"])]
    # geofence_radius_m is left out, so the table default of migration 007 applies (400 m).
    return [
        {
            "hub_id": hub_id(hub),
            "name": hub["name"],
            "address": hub["address"],
            "municipality": hub["municipality"],
            "lat": hub["lat"],
            "lon": hub["lon"],
            "floor_area_m2": hub["floor_area_m2"],
            "loading_docks": hub["loading_docks"],
            "sorting_capacity_parcels_per_hour": hub["sorting_capacity_parcels_per_hour"],
            "inbound_from": inbound[0],
            "inbound_to": inbound[1],
            "sorting_from": sorting[0],
            "sorting_to": sorting[1],
            "first_departure": clock(timetable["first_departure"]),
            "last_departure": clock(timetable["last_departure"]),
            "same_day_cutoff": clock(timetable["same_day_cutoff"]),
        }
    ]


def zones(company: dict) -> list[dict]:
    return [
        {
            "zone_id": z["zone_id"],
            "name": z["name"],
            "municipality": z["municipality"],
            "districts": z["districts"],
            "centroid_lat": z["centroid"]["lat"],
            "centroid_lon": z["centroid"]["lon"],
            "distance_from_hub_km": z["distance_from_hub_km"],
            "share_of_daily_parcels": z["share_of_daily_parcels"],
            "stops_per_route": z["stops_per_route"],
            "minutes_per_stop": z["minutes_per_stop"],
            "delivery_difficulty": z["delivery_difficulty"],
            "difficulty_factors": z["difficulty_factors"],
            "preferred_vehicle_type_ids": z["preferred_vehicle_type_ids"],
        }
        for z in company["zones"]
    ]


def shifts(company: dict) -> list[dict]:
    return [
        {
            "shift_id": shift_id(s["name"]),
            "name": s["name"],
            "start_time": clock(s["start"]),
            "end_time": clock(s["end"]),
            "break_minutes": s["break_minutes"],
            "drivers": s["drivers"],
        }
        for s in company["drivers"]["shifts"]
    ]


def vehicle_types(company: dict) -> list[dict]:
    return [
        {
            "type_id": t["type_id"],
            "description": t["description"],
            "planned_count": t["count"],
            "energy": t["energy"],
            "dgt_label": t["dgt_label"],
            "payload_kg": t["payload_kg"],
            "cargo_volume_m3": t["cargo_volume_m3"],
            "parcel_capacity": t["parcel_capacity"],
            "consumption_value": t["consumption"]["value"],
            "consumption_unit": t["consumption"]["unit"],
            "range_km": t["range_km"],
            "urban_average_speed_kmh": t["urban_average_speed_kmh"],
            "telemetry_sensors": t["telemetry_sensors"],
        }
        for t in company["fleet"]["vehicle_types"]
    ]


def vehicles(fleet: dict) -> list[dict]:
    return [
        {
            "vehicle_id": v["vehicle_id"],
            "plate": v["plate"],
            "type_id": v["type_id"],
            "home_zone_id": v["home_zone_id"],
            "registration_year": v["registration_year"],
            "odometer_km": v["odometer_km"],
            "battery_state_of_health_pct": v["battery_state_of_health_pct"],
            "runs_afternoon_wave": v["runs_afternoon_wave"],
            "telematics_unit_id": v["telematics_unit_id"],
            "maintenance_note": v["maintenance_note"],
        }
        for v in fleet["vehicles"]
    ]


def drivers(roster: dict, company: dict) -> list[dict]:
    shift_ids = {s["name"]: shift_id(s["name"]) for s in company["drivers"]["shifts"]}
    return [
        {
            "driver_id": d["driver_id"],
            "full_name": f"{d['first_name']} {d['last_names']}",
            "shift_id": shift_ids.get(d["shift"]),  # NULL for the relief pool
            "status": "reserve" if d["shift"] == RELIEF_POOL else "active",
            "first_name": d["first_name"],
            "last_names": d["last_names"],
            "roster_group": d["shift"],
            "contract": d["contract"],
            "hired_year": d["hired_year"],
            "years_driving_professionally": d["years_driving_professionally"],
            "home_municipality": d["home_municipality"],
            "languages": d["languages"],
            "zone_knowledge": d["zone_knowledge"],
            "qualified_vehicle_types": d["qualified_vehicle_types"],
            "planning_note": d["planning_note"],
        }
        for d in roster["drivers"]
    ]


def shippers(demand: dict) -> list[dict]:
    return [
        {
            "shipper_id": s["shipper_id"],
            "name": s["name"],
            "segment": s["segment"],
            "description": s["description"],
            "share_of_daily_parcels": s["share_of_daily_parcels"],
            "parcel_mix_small": s["parcel_mix"]["small"],
            "parcel_mix_medium": s["parcel_mix"]["medium"],
            "parcel_mix_large": s["parcel_mix"]["large"],
            "same_day_share": s["same_day_share"],
            "recipient_type": s["recipient_type"],
            "business_share": s["business_share"],
            "arrives_at_hub": s["arrives_at_hub"],
            "business_recipient_zones": s["business_recipient_zones"],
        }
        for s in demand["shippers"]
    ]


def blank_to_none(rows: list[dict], columns: tuple[str, ...]) -> list[dict]:
    """Numeric columns cannot take an empty string; an empty published value becomes NULL."""
    for row in rows:
        for column in columns:
            if not str(row[column]).strip():
                row[column] = None
    return rows


def raw_key(download_source: str, path: Path) -> str:
    """Key of a downloaded file in the bronze bucket: source, day it was downloaded, file name."""
    fetched = date.fromtimestamp(path.stat().st_mtime).isoformat()
    return f"reference/{download_source}/{fetched}/{path.name}"


def seed_tables(seeds: Seeds) -> list[Table]:
    """Tables from the AI-generated seeds, in foreign-key order."""
    company = seeds.company
    return [
        Table("bronze.zones", zones(company), COMPANY),
        Table("bronze.vehicle_types", vehicle_types(company), COMPANY),
        Table("bronze.shifts", shifts(company), COMPANY),
        Table("bronze.hubs", hubs(company), COMPANY),
        Table("bronze.vehicles", vehicles(seeds.fleet), FLEET, SEED_FILES["bronze.vehicles"]),
        Table("bronze.drivers", drivers(seeds.drivers, company), DRIVERS, SEED_FILES["bronze.drivers"]),
        Table("bronze.shippers", shippers(seeds.demand), DEMAND, SEED_FILES["bronze.shippers"]),
    ]


def address_tables(settings: Settings, zone_map: ZoneMap, bucket: Bucket) -> list[Table]:
    """Streets and addresses from the open-data files, each file stored in the bucket as it arrived."""
    cache = settings.cache_dir
    direle = addresses.fetch_download(addresses.TAULA_DIRELE, cache)
    carrerer = addresses.fetch_download(addresses.CARRERER, cache)
    icgc = addresses.fetch_icgc(cache)
    keys = {
        path: bucket.put_file(raw_key(source, path), path)
        for source, path in (
            (addresses.TAULA_DIRELE.source_id, direle),
            (addresses.CARRERER.source_id, carrerer),
            (addresses.ICGC_SOURCE_ID, icgc),
        )
    }
    numeric = ("x_ed50", "y_ed50", "x_etrs89", "y_etrs89", "lon", "lat")
    icgc_rows, icgc_skipped = addresses.read_icgc(icgc, zone_map)
    return [
        Table("bronze.streets", addresses.read_carrerer(carrerer), addresses.CARRERER.source_id, keys[carrerer]),
        Table(
            "bronze.addresses",
            blank_to_none(addresses.read_taula_direle(direle), numeric),
            addresses.TAULA_DIRELE.source_id,
            keys[direle],
        ),
        Table("bronze.icgc_addresses", icgc_rows, addresses.ICGC_SOURCE_ID, keys[icgc], icgc_skipped),
    ]


def seed_parquet(tables: list[Table], bucket: Bucket) -> list[str]:
    """The fleet register, driver roster and shipper list as Parquet files in the bronze bucket."""
    return [
        bucket.put_parquet(table.raw_object_key, pa.Table.from_pylist(table.rows))
        for table in tables
        if table.name in SEED_FILES
    ]


def load_reference(settings: Settings) -> dict[str, Loaded]:
    """Load every reference table; return what loading did, per table."""
    seeds = Seeds.load(settings.seed_dir)
    zone_map = ZoneMap.from_company(seeds.company)
    bucket = Bucket(settings)
    print("Reference files in the bronze bucket")
    tables = seed_tables(seeds)
    seed_parquet(tables, bucket)
    tables += address_tables(settings, zone_map, bucket)
    for table in tables:
        if table.raw_object_key:
            print(f"  {bucket.name}/{table.raw_object_key}")
    results = {}
    with db.connect(settings) as conn, conn.transaction():
        for table in tables:
            inserted = db.insert_new(conn, table.name, table.columns, table.rows_with_metadata())
            results[table.name] = Loaded(len(table.rows), table.skipped, inserted, db.count(conn, table.name))
    return results
