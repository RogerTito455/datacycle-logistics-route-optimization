"""Reference rows from the seeds, zone assignment and address formatting."""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime

import jsonschema
import pytest
from llobregat_generator import addresses, reference
from llobregat_generator.config import GENERATOR_DIR
from llobregat_generator.metadata import FileMetadata, content_checksum, parquet_table
from llobregat_generator.zones import in_polygons


def test_seed_tables_match_the_seeds(seeds):
    tables = {t.name: t for t in reference.seed_tables(seeds)}
    assert {name: len(t.rows) for name, t in tables.items()} == {
        "bronze.zones": 14,
        "bronze.vehicle_types": 6,
        "bronze.shifts": 2,
        "bronze.hubs": 1,
        "bronze.vehicles": 30,
        "bronze.drivers": 48,
        "bronze.shippers": 40,
        "bronze.delivery_notes": 300,
    }
    assert {t.source for t in tables.values()} == {
        "generator/company-profile",
        "generator/fleet",
        "generator/drivers",
        "generator/demand-model",
        "generator/delivery-notes",
    }
    for table in tables.values():  # every row has the same columns, then source and raw_object_key
        assert all(list(row) == list(table.rows[0]) for row in table.rows)
        from_file = table.name in reference.SEED_FILES
        assert table.columns[-2:] == (["source", "raw_object_key"] if from_file else [table.columns[-2], "source"])
        assert table.raw_object_key == reference.SEED_FILES.get(table.name)
        assert (table.raw_object_key or "").endswith(".parquet") == from_file


def test_seed_files_carry_source_ingested_at_owner_and_schema_version(seeds):
    ingested_at = datetime(2026, 9, 29, 6, 30, tzinfo=UTC)
    rows = reference.vehicles(seeds.fleet)
    table = parquet_table(rows, FileMetadata("generator/fleet", "fleet", 4, ingested_at))
    assert table.column_names == [*rows[0], "source", "ingested_at"]
    assert set(table.column("source").to_pylist()) == {"generator/fleet"}
    assert set(table.column("ingested_at").to_pylist()) == {ingested_at}
    assert {k.decode(): v.decode() for k, v in table.schema.metadata.items()} == {
        "source": "generator/fleet",
        "owner": "fleet",
        "schema_version": "4",
        "ingested_at": "2026-09-29T06:30:00+00:00",
    }


def test_a_seed_file_is_written_again_only_when_its_content_changes(seeds):
    rows = reference.shippers(seeds.demand)
    first = FileMetadata("generator/demand-model", "operations", 2, datetime(2026, 9, 29, 6, 30, tzinfo=UTC))
    later = FileMetadata("generator/demand-model", "operations", 2, datetime(2026, 9, 30, 7, 0, tzinfo=UTC))
    assert content_checksum(rows, first) == content_checksum(rows, later)  # ingested_at left out
    changed = [{**rows[0], "share_of_daily_parcels": 0.5}, *rows[1:]]
    assert content_checksum(changed, later) != content_checksum(rows, later)
    new_version = FileMetadata("generator/demand-model", "operations", 3, later.ingested_at)
    assert content_checksum(rows, new_version) != content_checksum(rows, later)


def test_delivery_note_rows_are_the_corpus(seeds):
    rows = reference.delivery_notes(seeds.delivery_notes)
    assert rows == seeds.delivery_notes["notes"]  # every field, as generated, in the corpus order
    table = next(t for t in reference.seed_tables(seeds) if t.name == "bronze.delivery_notes")
    assert table.raw_object_key == "reference/generator/delivery-notes/delivery_notes.parquet"


def test_hub_and_shift_ids(seeds):
    hub = reference.hubs(seeds.company)[0]
    assert hub["hub_id"] == "BCN-ZF"
    assert "geofence_radius_m" not in hub  # the table default of migration 007 applies
    assert [s["shift_id"] for s in reference.shifts(seeds.company)] == ["morning", "afternoon"]


def test_driver_rows(seeds):
    rows = {d["driver_id"]: d for d in reference.drivers(seeds.drivers, seeds.company)}
    relief = [d for d in rows.values() if d["roster_group"] == "Relief pool"]
    assert len(relief) == 8
    assert all(d["shift_id"] is None and d["status"] == "reserve" for d in relief)
    assert rows["D-001"]["full_name"] == "Manuel Cano Serrano"
    assert rows["D-001"]["shift_id"] == "morning"


def test_zone_map(zone_map):
    assert zone_map.for_district("01") == "Z01"
    assert zone_map.for_district("08") == zone_map.for_district("09") == "Z08"  # Nou Barris i Sant Andreu
    assert zone_map.for_district("10") == "Z09"
    assert zone_map.for_municipality("l'Hospitalet de Llobregat") == "Z10"  # ICGC spelling
    assert zone_map.for_municipality("el Prat de Llobregat") == "Z11"
    assert zone_map.for_municipality("Sant Boi de Lluçanès") is None
    assert zone_map.municipality("Z10") == "L'Hospitalet de Llobregat"


def test_barcelona_address(zone_map):
    row = {
        "street_code": "011200",
        "street_number": "0044",
        "number_letter": "B",
        "district_code": "10",
        "postal_district": "05",
        "lat": "41.3950000",
        "lon": "2.1850000",
    }
    address = addresses.barcelona_address(row, "Carrer dels Almogàvers", zone_map)
    assert address.address_ref == "011200-0044B"
    assert address.street_address == "Carrer dels Almogàvers, 44B"
    assert (address.zone_id, address.postcode, address.municipality) == ("Z09", "08005", "Barcelona")
    assert addresses.barcelona_address(row, None, zone_map) is None  # no street name, no delivery


def icgc_row(**values) -> dict:
    row = {
        "address_id": "av1",
        "municipality": "el Prat de Llobregat",
        "street_type": "Carrer",
        "street_article": "de l'",
        "street_name": "Arquitecte Moragas",
        "address_type": "vianum",
        "number_from": "5",
        "number_from_suffix": " ",
        "number_to": "0",
        "number_to_suffix": " ",
        "postcode": "08820",
        "lat": 41.32,
        "lon": 2.09,
    }
    return {**row, **values}


@pytest.mark.parametrize(
    ("values", "street_address"),
    [
        ({}, "Carrer de l'Arquitecte Moragas, 5"),
        ({"number_to": "7"}, "Carrer de l'Arquitecte Moragas, 5-7"),
        (
            {"street_article": "del", "street_name": "Riu Llobregat", "number_from_suffix": "B"},
            "Carrer del Riu Llobregat, 5B",
        ),
        (
            {"street_article": " ", "street_type": "Avinguda", "street_name": "Onze de Setembre"},
            "Avinguda Onze de Setembre, 5",
        ),
        ({"number_from": "0"}, "Carrer de l'Arquitecte Moragas, s/n"),
    ],
)
def test_icgc_address(zone_map, values, street_address):
    address = addresses.icgc_address(icgc_row(**values), zone_map)
    assert address.street_address == street_address
    assert (address.zone_id, address.municipality) == ("Z11", "El Prat de Llobregat")


def test_icgc_blocks_and_other_towns_are_not_delivery_addresses(zone_map):
    assert addresses.icgc_address(icgc_row(address_type="viabloc"), zone_map) is None
    assert addresses.icgc_address(icgc_row(municipality="Viladecans"), zone_map) is None


def test_read_icgc_keeps_the_zone_towns_converts_coordinates_and_skips_rows_without_them(tmp_path, zone_map):
    """The loader's path: the zip, the subset of the five towns, the conversion to WGS84."""
    towns = ["l'Hospitalet de Llobregat", "el Prat de Llobregat", "Cornellà de Llobregat"]
    towns += ["Esplugues de Llobregat", "Sant Boi de Llobregat", "Viladecans"]
    municipi = ["codmuni;nommuni"] + [f"08{n:04d};{name}" for n, name in enumerate(towns)]
    header = list(addresses.ICGC_COLUMNS)

    def address(address_id: str, town: int, x: str, y: str) -> str:
        values = dict.fromkeys(header, " ")
        values |= {"idadrvia": address_id, "codmuni": f"08{town:04d}", "nommuni": towns[town]}
        values |= {"tipusadr": "vianum", "numini": "1", "coor_utmx": x, "coor_utmy": y}
        return ";".join(values[column] for column in header)

    # x and y of a taula-direle row, which publishes WGS84 too: 2.1535184, 41.3775667.
    adrecavia = [";".join(header), address("a1", 0, "429217.072", "4581017.569"), address("a2", 1, " ", " ")]
    adrecavia.append(address("a3", 5, "420000", "4570000"))  # Viladecans: not a zone
    zip_path = tmp_path / "adreces-simplificat-v1r0-20260410.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("adreces-simplificat-v1r0-municipi-20260410.csv", "\n".join(municipi) + "\n")
        archive.writestr("adreces-simplificat-v1r0-adrecavia-20260410.csv", "\n".join(adrecavia) + "\n")

    rows, skipped = addresses.read_icgc(zip_path, zone_map)
    assert [r["address_id"] for r in rows] == ["a1"]
    assert skipped == 1  # a2 has no coordinates
    assert rows[0]["lon"] == pytest.approx(2.1535184, abs=1e-6)  # about 8 cm
    assert rows[0]["lat"] == pytest.approx(41.3775667, abs=1e-6)
    assert (rows[0]["x_etrs89"], rows[0]["y_etrs89"]) == (429217.072, 4581017.569)


def test_the_registers_put_each_sample_address_inside_its_zone(pool, boundaries):
    """The loader's zone assignment, by district code or municipality matched to company.json, run on
    rows as the registers publish them, against the official boundaries, which come from other files.
    A wrong district-to-zone match or a wrong coordinate conversion puts addresses outside."""
    assert set(pool) == set(boundaries)
    sample = [a for zone in pool.values() for a in zone]
    outside = [(a.zone_id, a.address_ref) for a in sample if not in_polygons(boundaries[a.zone_id], a.lon, a.lat)]
    assert len(outside) <= len(sample) // 100, outside


@pytest.mark.parametrize("name", ["fleet", "drivers", "demand", "delivery_notes"])
def test_schemas_accept_the_seed_and_reject_a_broken_one(name):
    schema = json.loads((GENERATOR_DIR / "seed" / f"{name}.schema.json").read_text(encoding="utf-8"))
    seed = json.loads((GENERATOR_DIR / "seed" / f"{name}.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    assert not list(validator.iter_errors(seed))
    records = {"fleet": "vehicles", "drivers": "drivers", "demand": "shippers", "delivery_notes": "notes"}[name]
    seed[records][0]["unexpected"] = True
    assert list(validator.iter_errors(seed))
