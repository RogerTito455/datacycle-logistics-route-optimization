"""Shared fixtures: the committed seeds, a sample of real addresses and a few generated days.

Everything here is offline: the address sample (tests/fixtures/addresses_sample.csv, 40 real
addresses per zone) stands in for the database, so the tests run in CI.
"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

import pytest
from llobregat_generator.addresses import Address
from llobregat_generator.config import GENERATOR_DIR
from llobregat_generator.orders import Day, generate_day
from llobregat_generator.seeds import Seeds
from llobregat_generator.zones import load_boundaries

FIXTURES = Path(__file__).parent / "fixtures"
MONDAY = date(2026, 10, 5)  # a week without a seasonal peak
SATURDAY = date(2026, 10, 10)
SEED = 0


@pytest.fixture(scope="session")
def seeds() -> Seeds:
    return Seeds.load(GENERATOR_DIR / "seed")


@pytest.fixture(scope="session")
def pool() -> dict[str, list[Address]]:
    pool: dict[str, list[Address]] = {}
    with (FIXTURES / "addresses_sample.csv").open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            address = Address(**{**row, "lat": float(row["lat"]), "lon": float(row["lon"])})
            pool.setdefault(address.zone_id, []).append(address)
    return pool


@pytest.fixture(scope="session")
def boundaries():
    return load_boundaries()


@pytest.fixture(scope="session")
def week(seeds, pool) -> list[Day]:
    """Monday to Friday of one week."""
    return [generate_day(MONDAY + timedelta(days=i), SEED, seeds.company, seeds.demand, pool) for i in range(5)]


@pytest.fixture(scope="session")
def weekday(week) -> Day:
    return week[0]


@pytest.fixture(scope="session")
def saturday(seeds, pool) -> Day:
    return generate_day(SATURDAY, SEED, seeds.company, seeds.demand, pool)


@pytest.fixture(scope="session")
def shippers(seeds) -> dict[str, dict]:
    return {s["shipper_id"]: s for s in seeds.demand["shippers"]}
