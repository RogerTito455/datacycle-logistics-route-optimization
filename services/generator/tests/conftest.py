"""Shared fixtures: the committed seeds, a sample of real addresses and a few generated days.

Everything here is offline: 40 real addresses per zone, as the registers publish them
(tests/fixtures, written by scripts/build_fixtures.py), stand in for the database, so the tests
run in CI. They go through the loader's own reading and zone assignment.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from llobregat_generator import addresses
from llobregat_generator.addresses import Address
from llobregat_generator.config import GENERATOR_DIR
from llobregat_generator.orders import Day, generate_day
from llobregat_generator.seeds import Seeds
from llobregat_generator.zones import ZoneMap, load_boundaries

FIXTURES = Path(__file__).parent / "fixtures"
MONDAY = date(2026, 10, 5)  # a week without a seasonal peak
SATURDAY = date(2026, 10, 10)
SEED = 0


@pytest.fixture(scope="session")
def seeds() -> Seeds:
    return Seeds.load(GENERATOR_DIR / "seed")


@pytest.fixture(scope="session")
def zone_map(seeds) -> ZoneMap:
    return ZoneMap.from_company(seeds.company)


@pytest.fixture(scope="session")
def pool(zone_map) -> dict[str, list[Address]]:
    """The address pool of the sample, built as read_pool builds it from bronze."""
    streets = addresses.read_carrerer(FIXTURES / "carrerer_sample.csv")
    towns, _ = addresses.read_icgc_subset(FIXTURES / "icgc_sample.csv")
    return addresses.build_pool(
        addresses.read_taula_direle(FIXTURES / "taula_direle_sample.csv"),
        {s["street_code"]: s["official_name"] for s in streets},
        towns,
        zone_map,
    )


@pytest.fixture(scope="session")
def boundaries():
    return load_boundaries()


@pytest.fixture(scope="session")
def week(seeds, pool) -> list[Day]:
    """Monday to Friday of one week."""
    return [generate_day(MONDAY + timedelta(days=i), SEED, seeds, pool) for i in range(5)]


@pytest.fixture(scope="session")
def weekday(week) -> Day:
    return week[0]


@pytest.fixture(scope="session")
def saturday(seeds, pool) -> Day:
    return generate_day(SATURDAY, SEED, seeds, pool)


@pytest.fixture(scope="session")
def shippers(seeds) -> dict[str, dict]:
    return {s["shipper_id"]: s for s in seeds.demand["shippers"]}
