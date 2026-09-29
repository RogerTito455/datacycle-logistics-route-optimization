"""The simulated vans: pings every 5 s along the road, telemetry that only falls between charges,
the demand model's failures, a photo for every delivery, and the same messages for the same seed."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from heapq import merge

import numpy as np
import pytest
from conftest import MONDAY, straight_matrix, straight_road
from llobregat_generator import pod
from llobregat_generator.orders import LOCAL_TZ
from llobregat_generator.rules import Wave
from llobregat_simulator import behaviour, planner, van
from llobregat_simulator.company import local
from llobregat_simulator.stream import Pacer, Tally, publish
from llobregat_simulator.traffic import TimeOfDayProfile

REASONS = {"recipient_absent", "address_not_found", "refused", "access_restricted", "damaged", "other"}


@pytest.fixture(scope="module")
def routes(monday, company) -> list[planner.Route]:
    return [r for wave in Wave for r in planner.plan_wave(MONDAY, wave, monday, company, straight_matrix).routes]


@pytest.fixture(scope="module")
def roads(routes, company):
    return {r.route_id: straight_road([company.hub, *(s.order for s in r.stops), company.hub]) for r in routes}


def simulate(routes, roads, company, seeds, seed=0) -> list[van.VanDay]:
    by_van = defaultdict(list)
    for route in routes:
        by_van[route.vehicle.vehicle_id].append(route)
    notes = behaviour.note_labels(seeds.delivery_notes)
    return [
        van.drive_day(MONDAY, rs[0].vehicle, rs, roads, company, seeds.demand, notes, TimeOfDayProfile(), seed)
        for _, rs in sorted(by_van.items())
    ]


@pytest.fixture(scope="module")
def days(routes, roads, company, seeds) -> list[van.VanDay]:
    return simulate(routes, roads, company, seeds)


@pytest.fixture(scope="module")
def messages(days) -> list[van.Message]:
    return list(merge(*(d.messages() for d in days), key=lambda m: m.t))


def by_vehicle(messages, topic):
    grouped = defaultdict(list)
    for m in messages:
        if m.topic == topic:
            grouped[m.key].append(m)
    return grouped


def metres(lat1, lon1, lat2, lon2):
    """Equirectangular distance in metres, fine at a few hundred metres."""
    x = np.radians(np.asarray(lon2) - lon1) * np.cos(np.radians(lat1)) * 6_371_000
    y = np.radians(np.asarray(lat2) - lat1) * 6_371_000
    return np.hypot(x, y)


def test_every_van_pings_every_5_seconds_from_the_dock_to_the_hub(messages, days):
    pings = by_vehicle(messages, van.GPS_TOPIC)
    assert sorted(pings) == sorted(d.van.vehicle_id for d in days)
    for day in days:
        times = [m.t for m in pings[day.van.vehicle_id]]
        assert set(np.diff(times)) == {van.GPS_INTERVAL_S}
        assert times[0] <= day.start + van.GPS_INTERVAL_S and times[-1] >= day.end - van.GPS_INTERVAL_S


def test_telemetry_every_30_seconds(messages):
    for readings in by_vehicle(messages, van.TELEMETRY_TOPIC).values():
        assert set(np.diff([m.t for m in readings])) == {van.TELEMETRY_INTERVAL_S}


def test_pings_follow_the_road(messages, routes, roads):
    for route in (routes[0], routes[-1]):  # a morning route and an afternoon one
        points = np.array([c for leg in roads[route.route_id].legs for c in leg.coordinates])
        a, b = points[:-1], points[1:]
        pings = [m.value for m in messages if m.topic == van.GPS_TOPIC and m.value.get("route_id") == route.route_id]
        assert len(pings) > 100
        lat0 = points[0, 1]
        scale = np.array([math.cos(math.radians(lat0)), 1.0]) * 111_320
        p = np.array([[v["lon"], v["lat"]] for v in pings])[:, None, :] * scale
        a, b = a[None, :, :] * scale, b[None, :, :] * scale
        ab = b - a
        along = np.clip(((p - a) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-9), 0, 1)
        off_road = np.linalg.norm(p - (a + along[..., None] * ab), axis=-1).min(axis=1)
        assert off_road.max() < 25  # metres: GNSS noise of 3-8 m accuracy


def test_the_van_leaves_the_hub_geofence_on_its_route(messages, routes, company):
    hub, radius = company.hub, company.hub.geofence_radius_m
    pings = by_vehicle(messages, van.GPS_TOPIC)
    for route in routes:
        own = pings[route.vehicle.vehicle_id]
        on_route = [m for m in own if m.value.get("route_id") == route.route_id]
        outside = [m for m in on_route if metres(hub.lat, hub.lon, m.value["lat"], m.value["lon"]) > radius]
        departure = outside[0].t
        # Before the route starts, the van waits at the hub without a route: inside the geofence.
        before = [m for m in own if m.t < on_route[0].t and m.t > on_route[0].t - 600]
        assert before and all("route_id" not in m.value for m in before)
        assert all(metres(hub.lat, hub.lon, m.value["lat"], m.value["lon"]) < radius for m in before)
        assert departure >= (route.departure - local(MONDAY, 0)).total_seconds()


def test_levels_only_fall_between_charges(messages, days):
    telemetry = by_vehicle(messages, van.TELEMETRY_TOPIC)
    charged = 0
    for day in days:
        readings = [m.value for m in telemetry[day.van.vehicle_id]]
        for before, after in zip(readings, readings[1:], strict=False):
            assert after["odometer_km"] >= before["odometer_km"]
            assert after["energy_used_total"] >= before["energy_used_total"]
            if after.get("charging"):
                charged += after["energy_level_pct"] > before["energy_level_pct"]
            else:
                assert after["energy_level_pct"] <= before["energy_level_pct"]
        assert 0 < readings[-1]["energy_level_pct"] < readings[0]["energy_level_pct"] + 100
    assert charged  # the afternoon vans charge between waves


def test_every_order_is_scanned_out_arrived_then_delivered_or_failed(messages, routes):
    scans = defaultdict(list)
    for m in messages:
        if m.topic == van.EVENTS_TOPIC:
            scans[m.value["order_id"]].append(m)
    assert sorted(scans) == sorted(s.order.order_id for r in routes for s in r.stops)
    for events in scans.values():
        statuses = [m.value["status"] for m in events]
        assert statuses[:2] == ["out_for_delivery", "arrived"] and statuses[2] in ("delivered", "failed")
        assert len(statuses) == 3 and [m.t for m in events] == sorted(m.t for m in events)


def test_every_delivery_has_its_photo_and_every_failure_a_reason(messages):
    events = [m for m in messages if m.topic == van.EVENTS_TOPIC]
    delivered = [m for m in events if m.value["status"] == "delivered"]
    failed = [m for m in events if m.value["status"] == "failed"]
    assert delivered and failed
    for m in delivered:
        assert m.value["pod_object_key"] == f"pod/{MONDAY}/{m.value['order_id']}.jpg" == pod.object_key(m.photo)
        assert m.photo.delivered_at == datetime.fromisoformat(m.value["event_time"])
        assert (m.photo.lat, m.photo.lon) == pytest.approx((m.value["lat"], m.value["lon"]), abs=1e-6)
    for m in failed:
        assert m.value["failure_reason"] in REASONS and "pod_object_key" not in m.value and m.photo is None
    assert all(m.photo is None for m in events if m.value["status"] not in ("delivered",))


def test_the_failure_rate_is_the_demand_models(messages, routes, company, seeds):
    odds = [behaviour.failure_probability(s.order, company, seeds.demand) for r in routes for s in r.stops]
    failed = sum(1 for m in messages if m.topic == van.EVENTS_TOPIC and m.value["status"] == "failed")
    expected, n = sum(odds), len(odds)
    spread = math.sqrt(sum(p * (1 - p) for p in odds))
    assert abs(failed - expected) <= 4 * spread, f"{failed} failed, {expected:.0f} expected of {n}"


def test_stops_take_the_zones_minutes_on_average(company, seeds, monday):
    notes = behaviour.note_labels(seeds.delivery_notes)
    outcomes = behaviour.outcomes(monday, company, seeds.demand, notes, np.random.default_rng(1))
    expected = sum(company.zones[o.zone_id].minutes_per_stop * 60 for o in monday)
    assert sum(o.stop_s for o in outcomes) == pytest.approx(expected, rel=0.03)


def test_the_notes_move_the_odds_but_keep_the_total():
    rescaled = behaviour._rescale([0.1, 0.1, 0.1, 0.1], [True, False, False, False], behaviour.NOTE_FAIL)
    assert sum(rescaled) == pytest.approx(0.4) and rescaled[0] == pytest.approx(0.25)


def test_every_message_carries_its_metadata(messages):
    sources = {
        van.GPS_TOPIC: van.GPS_SOURCE,
        van.TELEMETRY_TOPIC: van.TELEMETRY_SOURCE,
        van.EVENTS_TOPIC: van.HANDHELD_SOURCE,
    }
    for m in messages[::97]:
        assert m.value["source"] == sources[m.topic] and m.value["schema_version"] == van.SCHEMA_VERSION
        assert m.key == m.value["vehicle_id"]
        moment = datetime.fromisoformat(m.value["event_time"]).astimezone(LOCAL_TZ)
        assert (moment - local(MONDAY, 0)).total_seconds() == m.t


def test_the_same_date_and_seed_give_the_same_messages(routes, roads, company, seeds, days):
    some = [r for r in routes if r.vehicle.vehicle_id in ("V-05", "V-24")]  # an afternoon van and a quadricycle
    again = simulate(some, roads, company, seeds)
    other = simulate(some, roads, company, seeds, seed=1)
    first = {d.van.vehicle_id: list(d.messages()) for d in days}
    for a, b in zip(again, other, strict=True):
        assert list(a.messages()) == first[a.van.vehicle_id]
        assert list(b.messages()) != first[b.van.vehicle_id]


def test_traffic_slows_the_peak_hours():
    profile = TimeOfDayProfile()
    monday_peak, monday_night = local(MONDAY, 8 * 60), local(MONDAY, 3 * 60)
    saturday_peak = local(MONDAY.replace(day=10), 8 * 60)
    assert profile.factor(monday_peak, 2.17, 41.39) > profile.factor(saturday_peak, 2.17, 41.39) > 1
    assert profile.factor(monday_night, 2.17, 41.39) == 1


def test_the_stream_paces_and_sends_a_delivery_after_its_photo(messages, routes, company):
    head = [m for m in messages if m.t < messages[0].t + 3 * 3600]
    stored, sent = set(), []

    def store(delivery):
        stored.add(delivery.order_id)
        return pod.object_key(delivery)

    def send(m):
        if m.value.get("status") == "delivered":
            assert m.value["order_id"] in stored
        sent.append(m)

    slept = []
    now = [0.0]

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    tally = Tally.of(routes, company.hub, MONDAY)
    publish(head, send, store, Pacer(60, clock=lambda: now[0], sleep=sleep), tally)
    assert len(sent) == len(head) and sum(tally.counts.values()) == len(head)
    assert sum(slept) == pytest.approx((head[-1].t - head[0].t) / 60, abs=1)
    assert tally.photos == len(stored) > 0
