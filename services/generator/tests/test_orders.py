"""The generated orders follow the company profile (prompt 001) and the demand model (prompt 004).

Single-day figures get a tolerance of a few standard errors of one day's sampling noise; figures
pooled over a week get a tighter one. The seeds are fixed, so the tests are deterministic; the
tolerances say how far the generator may drift before a test should fail.
"""

from __future__ import annotations

import io
from collections import Counter
from datetime import date, timedelta
from statistics import mean, stdev

import numpy as np
import pyarrow.parquet as pq
import pytest
from conftest import MONDAY, SATURDAY, SEED
from llobregat_generator.orders import LOCAL_TZ, SATURDAY_OPEN, SIZES, NoServiceError, day_total, generate_day
from llobregat_generator.publish import ORDER_SCHEMA, orders_table
from llobregat_generator.rules import (
    MIDDAY_INJECTION,
    business_parcels_by_zone,
    delivery_waves,
    hours_category,
    minutes,
    opening_ranges,
    weekday_business_share,
    weekday_same_day_share,
    zone_shares,
)
from llobregat_generator.zones import in_polygons

WINDOW = 120


def parcels(orders, predicate=lambda o: True) -> int:
    return sum(o["parcels"] for o in orders if predicate(o))


def parcel_share(orders, predicate) -> tuple[float, float]:
    """Share of parcels that meet predicate, and its standard error.

    Parcels come in stops of one to a dozen, all in the same zone and wave, so the error is that of
    a ratio of sums over stops, not of independent parcels.
    """
    sizes = np.array([o["parcels"] for o in orders], dtype=float)
    hits = np.array([predicate(o) for o in orders], dtype=float)
    share = (sizes * hits).sum() / sizes.sum()
    residuals = sizes * (hits - share)
    return share, float(np.sqrt((residuals**2).mean() / len(orders)) / sizes.mean())


def pooled(days) -> list[dict]:
    return [o for day in days for o in day.orders]


def local(ts):
    return ts.astimezone(LOCAL_TZ)


def minute_of_day(ts) -> int:
    ts = local(ts)
    return ts.hour * 60 + ts.minute


# Day total ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("service_date", "multiplier"),
    [
        (date(2026, 10, 6), 1.05),  # Tuesday, no peak
        (SATURDAY, 0.30),
        (date(2026, 11, 23), 1.15 * 1.55),  # Monday of the Black Friday week
        (date(2026, 9, 25), 0.87 * 1.1),  # Friday, back to school
    ],
)
def test_day_total_follows_mean_stddev_weekday_and_season(seeds, service_date, multiplier):
    volume = seeds.company["daily_volume"]
    totals = [
        day_total(np.random.default_rng([seed, service_date.toordinal()]), service_date, seeds) for seed in range(400)
    ]
    expected_mean = volume["weekday_parcels_mean"] * multiplier
    expected_sd = volume["weekday_parcels_stddev"] * multiplier
    assert mean(totals) == pytest.approx(expected_mean, abs=4 * expected_sd / 400**0.5)
    assert stdev(totals) == pytest.approx(expected_sd, rel=0.15)


def test_saturday_mean_matches_company_profile(seeds):
    volume = seeds.company["daily_volume"]
    assert volume["weekday_parcels_mean"] * seeds.demand["weekday_multipliers"]["Sat"] == pytest.approx(
        volume["saturday_parcels_mean"]
    )


def test_orders_add_up_to_the_day_total(week, saturday):
    for day in [*week, saturday]:
        assert parcels(day.orders) == day.parcels


def test_no_orders_on_sunday(seeds, pool):
    with pytest.raises(NoServiceError):
        generate_day(date(2026, 10, 11), SEED, seeds, pool)


# Zones and business share ---------------------------------------------------------------------


def shares_by_zone(orders) -> dict[str, float]:
    total = parcels(orders)
    counts = Counter()
    for o in orders:
        counts[o["destination_zone_id"]] += o["parcels"]
    return {zone: n / total for zone, n in counts.items()}


def test_zone_shares_single_day(seeds, weekday, saturday):
    for day in (weekday, saturday):
        shares = shares_by_zone(day.orders)
        for zone in seeds.company["zones"]:
            assert shares[zone["zone_id"]] == pytest.approx(zone["share_of_daily_parcels"], abs=0.03), zone["zone_id"]


def test_zone_shares_over_a_week(seeds, week):
    shares = shares_by_zone(pooled(week))
    for zone in seeds.company["zones"]:
        assert shares[zone["zone_id"]] == pytest.approx(zone["share_of_daily_parcels"], abs=0.012), zone["zone_id"]


def test_business_share(seeds, weekday):
    expected = weekday_business_share(seeds.demand)
    assert parcels(weekday.orders, lambda o: o["customer_type"] == "B2B") / weekday.parcels == pytest.approx(
        expected, abs=0.005
    )
    assert expected == pytest.approx(seeds.company["daily_volume"]["b2b_share_pct"] / 100, abs=0.005)


def test_business_and_consumer_parcels_by_zone_over_a_week(seeds, week):
    """As the demand model says: a shipper's business parcels spread over its zones in proportion
    to the zone shares, and consumer parcels fill each zone up to its share."""
    zone_share = zone_shares(seeds.company)
    business = business_parcels_by_zone(seeds)
    consumer = {zone: zone_share[zone] - business[zone] for zone in zone_share}
    orders = pooled(week)
    for kind, expected in (("B2B", business), ("B2C", consumer)):
        of_kind = [o for o in orders if o["customer_type"] == kind]
        for zone in zone_share:
            got, error = parcel_share(of_kind, lambda o, z=zone: o["destination_zone_id"] == z)
            assert got == pytest.approx(expected[zone] / sum(expected.values()), abs=4 * error), (kind, zone)


def test_business_recipients_are_in_their_shippers_zones(week, shippers):
    for o in pooled(week):
        if o["customer_type"] == "B2B":
            assert o["destination_zone_id"] in shippers[o["shipper_id"]]["business_recipient_zones"]
        else:
            assert shippers[o["shipper_id"]]["business_share"] < 1


def test_saturday_business_parcels_only_for_shops_and_healthcare(saturday, shippers):
    b2b = [o for o in saturday.orders if o["customer_type"] == "B2B"]
    assert b2b
    assert {hours_category(shippers[o["shipper_id"]]) for o in b2b} <= SATURDAY_OPEN


# Same day -------------------------------------------------------------------------------------


def test_same_day_only_midday_shippers_before_the_cutoff(seeds, week, saturday, shippers):
    cutoff = minutes(seeds.company["hub"]["timetable"]["same_day_cutoff"])
    for day in [*week, saturday]:
        for o in day.orders:
            registered = local(o["event_time"])
            if o["service_level"] == "same_day":
                assert shippers[o["shipper_id"]]["arrives_at_hub"] == MIDDAY_INJECTION
                assert registered.date() == day.service_date
                assert minute_of_day(o["event_time"]) < cutoff
                assert o["priority"] == "high"
            else:
                assert registered.date() < day.service_date
                assert o["priority"] == "normal"


def test_same_day_share_matches_the_demand_model(seeds, weekday, week, shippers):
    expected = weekday_same_day_share(seeds.demand)
    same_day = lambda o: o["service_level"] == "same_day"  # noqa: E731
    assert parcels(weekday.orders, same_day) / weekday.parcels == pytest.approx(expected, abs=0.015)
    orders = pooled(week)
    midday = [o for o in orders if shippers[o["shipper_id"]]["arrives_at_hub"] == MIDDAY_INJECTION]
    midday_expected = sum(
        s["share_of_daily_parcels"] * s["same_day_share"]
        for s in shippers.values()
        if s["arrives_at_hub"] == MIDDAY_INJECTION
    ) / sum(s["share_of_daily_parcels"] for s in shippers.values() if s["arrives_at_hub"] == MIDDAY_INJECTION)
    assert parcels(midday, same_day) / parcels(midday) == pytest.approx(midday_expected, abs=0.03)


def test_next_day_orders_of_a_monday_were_registered_at_the_weekend(weekday):
    assert weekday.service_date.weekday() == 0
    days = Counter(local(o["event_time"]).date() for o in weekday.orders if o["service_level"] == "next_day")
    assert set(days) == {MONDAY - timedelta(days=2), MONDAY - timedelta(days=1)}


def test_registration_follows_the_hourly_curve(seeds, week):
    hourly = seeds.demand["hourly_registration_share"]
    orders = pooled(week)
    hours = Counter(local(o["event_time"]).hour for o in orders)
    for hour in range(24):
        assert hours[hour] / len(orders) == pytest.approx(hourly[f"{hour:02d}"], abs=0.01), hour


# Waves and windows ----------------------------------------------------------------------------


def test_windows(seeds, week, saturday, shippers):
    waves = delivery_waves(seeds.company)
    hours = seeds.demand["business_opening_hours"]
    for day in [*week, saturday]:
        for o in day.orders:
            start, end = minute_of_day(o["window_start"]), minute_of_day(o["window_end"])
            assert local(o["window_start"]).date() == day.service_date
            wave_start, wave_end = waves[o["wave"]]
            assert wave_start <= start < end <= wave_end
            shipper = shippers[o["shipper_id"]]
            if o["service_level"] == "same_day" or shipper["arrives_at_hub"] == MIDDAY_INJECTION:
                assert o["wave"] == "afternoon"
            if o["window_type"] == "slot":
                assert o["customer_type"] == "B2C"
                assert end - start == WINDOW and (start - wave_start) % WINDOW == 0
            elif o["window_type"] == "wave":
                assert o["customer_type"] == "B2C"
                assert (start, end) == (wave_start, wave_end)
            else:
                assert o["window_type"] == "opening_hours" and o["customer_type"] == "B2B"
                assert end - start == WINDOW
                category = hours_category(shipper)
                assert any(a <= start and end <= b for a, b in opening_ranges(hours[category])), o["order_id"]
                if shipper["arrives_at_hub"] != MIDDAY_INJECTION:
                    assert o["wave"] == "morning"


def test_consumer_window_choice(seeds, week, shippers):
    choice = seeds.demand["consumer_window_choice"]
    early = [
        o
        for o in pooled(week)
        if o["customer_type"] == "B2C" and shippers[o["shipper_id"]]["arrives_at_hub"] != MIDDAY_INJECTION
    ]
    morning = sum(o["wave"] == "morning" for o in early) / len(early)
    assert morning == pytest.approx(choice["morning_wave"], abs=0.02)
    consumers = [o for o in pooled(week) if o["customer_type"] == "B2C"]
    slot = sum(o["window_type"] == "slot" for o in consumers) / len(consumers)
    assert slot == pytest.approx(choice["specific_slot_share"], abs=0.02)


# Parcels ------------------------------------------------------------------------------------


def test_parcels_per_stop(week):
    orders = pooled(week)
    for kind, expected in (("B2C", 1.19), ("B2B", 2.30)):  # demand.json assumptions
        stops = [o for o in orders if o["customer_type"] == kind]
        assert parcels(stops) / len(stops) == pytest.approx(expected, abs=0.08), kind
    assert parcels(orders) / len(orders) == pytest.approx(1.41, abs=0.05)


def test_parcel_mix(seeds, week):
    shippers = seeds.demand["shippers"]
    orders = pooled(week)
    for size in SIZES:
        expected = sum(s["share_of_daily_parcels"] * s["parcel_mix"][size] for s in shippers)
        assert parcels(orders, lambda o, s=size: o["parcel_size"] == s) / parcels(orders) == pytest.approx(
            expected, abs=0.015
        ), size


# Addresses ----------------------------------------------------------------------------------


def test_addresses_are_real_and_inside_their_zone(pool, boundaries, week, saturday):
    by_ref = {a.address_ref: a for addresses in pool.values() for a in addresses}
    orders = [*pooled(week), *saturday.orders]
    for o in orders:
        address = by_ref[o["address_ref"]]
        assert address.zone_id == o["destination_zone_id"]
        assert (address.lat, address.lon) == (o["destination_lat"], o["destination_lon"])
        assert address.street_address == o["destination_address"]
    inside = sum(
        in_polygons(boundaries[o["destination_zone_id"]], o["destination_lon"], o["destination_lat"]) for o in orders
    )
    assert inside / len(orders) >= 0.99


def test_the_sample_addresses_lie_in_their_official_boundary(pool, boundaries):
    addresses = [a for zone in pool.values() for a in zone]
    assert len(pool) == 14
    assert sum(in_polygons(boundaries[a.zone_id], a.lon, a.lat) for a in addresses) / len(addresses) >= 0.99


# Identity and determinism -------------------------------------------------------------------


def test_order_ids_follow_registration_time(weekday):
    ids = [o["order_id"] for o in weekday.orders]
    assert ids == [f"O-{MONDAY:%Y%m%d}-{n:05d}" for n in range(1, len(ids) + 1)]
    times = [o["event_time"] for o in weekday.orders]
    assert times == sorted(times)


def test_same_date_and_seed_give_the_same_orders(seeds, pool, weekday):
    again = generate_day(MONDAY, SEED, seeds, pool)
    assert again.orders == weekday.orders

    def parquet_bytes(day) -> bytes:
        buffer = io.BytesIO()
        pq.write_table(orders_table(day), buffer)
        return buffer.getvalue()

    assert parquet_bytes(again) == parquet_bytes(weekday)


def test_another_seed_or_date_gives_other_orders(seeds, pool, weekday):
    other_seed = generate_day(MONDAY, SEED + 1, seeds, pool)
    assert other_seed.orders != weekday.orders
    next_monday = generate_day(MONDAY + timedelta(days=7), SEED, seeds, pool)
    assert [o["address_ref"] for o in next_monday.orders[:50]] != [o["address_ref"] for o in weekday.orders[:50]]


def test_parquet_file_has_the_bronze_columns(weekday):
    table = orders_table(weekday)
    assert table.schema.names == ORDER_SCHEMA.names
    assert table.num_rows == len(weekday.orders)
    assert table.schema.metadata[b"seed"] == str(SEED).encode()
    assert table.column("notes").null_count == table.num_rows  # filled by issue #25
