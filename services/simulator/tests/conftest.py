"""Shared fixtures: the committed seeds, a generated Monday of orders and a road network without OSRM.

Everything is offline. The orders come from the order generator at the sample addresses it tests
with (services/generator/tests/fixtures), and a straight-line "road network" stands in for OSRM:
distances are the great-circle distance times a detour factor, driven at a constant speed.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

import pytest
from llobregat_generator import addresses
from llobregat_generator.config import GENERATOR_DIR
from llobregat_generator.orders import generate_day
from llobregat_generator.seeds import Seeds
from llobregat_generator.zones import ZoneMap
from llobregat_simulator.company import Company, Order, Point
from llobregat_simulator.planner import haversine_m

FIXTURES = GENERATOR_DIR / "tests" / "fixtures"
MONDAY = date(2026, 10, 5)  # a week without a seasonal peak
DETOUR = 1.3
SPEED_MS = 20 / 3.6


def straight_matrix(points: Sequence[Point]) -> tuple[list[list[float]], list[list[float]]]:
    """Durations and distances as OSRM /table gives them, from straight lines."""
    distances = [[haversine_m(a, b) * DETOUR for b in points] for a in points]
    return [[d / SPEED_MS for d in row] for row in distances], distances


@pytest.fixture(scope="session")
def seeds() -> Seeds:
    return Seeds.load(GENERATOR_DIR / "seed")


@pytest.fixture(scope="session")
def company(seeds) -> Company:
    return Company.from_seeds(seeds)


@pytest.fixture(scope="session")
def monday(seeds) -> list[Order]:
    """The orders of a Monday at the sample addresses, 40 per zone."""
    streets = addresses.read_carrerer(FIXTURES / "carrerer_sample.csv")
    towns, _ = addresses.read_icgc_subset(FIXTURES / "icgc_sample.csv")
    pool = addresses.build_pool(
        addresses.read_taula_direle(FIXTURES / "taula_direle_sample.csv"),
        {s["street_code"]: s["official_name"] for s in streets},
        towns,
        ZoneMap.from_company(seeds.company),
    )
    return [Order.from_row(row) for row in generate_day(MONDAY, 0, seeds, pool).orders]
