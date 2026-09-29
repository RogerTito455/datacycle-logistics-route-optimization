"""The baseline plan: every order once, vans within capacity, nearest open stop first, the promise."""

from __future__ import annotations

import dataclasses
from collections import Counter
from datetime import timedelta

import pytest
from conftest import MONDAY, straight_matrix
from llobregat_generator.rules import Wave, WindowType
from llobregat_simulator import planner
from llobregat_simulator.company import Order, local


@pytest.fixture(scope="module")
def plans(monday, company) -> dict[Wave, planner.WavePlan]:
    return {wave: planner.plan_wave(MONDAY, wave, monday, company, straight_matrix) for wave in Wave}


@pytest.mark.parametrize("wave", list(Wave))
def test_every_order_of_the_wave_is_planned_once_or_held(plans, monday, wave):
    plan = plans[wave]
    planned = [s.order.order_id for r in plan.routes for s in r.stops]
    held = [o.order_id for o in plan.held]
    assert not [o for o, n in Counter(planned + held).items() if n > 1]
    assert set(planned) | set(held) == {o.order_id for o in monday if o.wave == wave}


def test_the_morning_plans_every_order(plans):
    # A mean weekday's morning fits in the 30 vans; only the afternoon's 10 can run out of room.
    assert plans[Wave.MORNING].held == []


@pytest.mark.parametrize("wave", list(Wave))
def test_a_route_never_carries_more_parcels_than_its_van(plans, wave):
    for route in plans[wave].routes:
        assert route.parcels <= route.vehicle.capacity, route.route_id


def test_the_morning_sends_the_whole_fleet_and_the_afternoon_its_own_vans(plans, company):
    morning = [r.vehicle.vehicle_id for r in plans[Wave.MORNING].routes]
    afternoon = [r.vehicle.vehicle_id for r in plans[Wave.AFTERNOON].routes]
    assert sorted(morning) == sorted(v.vehicle_id for v in company.vehicles)  # 30 routes, one per van
    assert sorted(afternoon) == sorted(v.vehicle_id for v in company.vehicles if v.runs_afternoon_wave)  # 10


def test_most_stops_are_served_by_a_van_of_their_zone(plans):
    stops = [(s.order.zone_id, r.vehicle.home_zone_id) for r in plans[Wave.MORNING].routes for s in r.stops]
    assert sum(zone == home for zone, home in stops) / len(stops) > 0.7


@pytest.mark.parametrize("wave", list(Wave))
def test_drivers_are_of_the_shift_and_cleared_for_their_van(plans, company, wave):
    drivers = {d.driver_id: d for d in company.drivers}
    assigned = [r.driver_id for r in plans[wave].routes]
    assert None not in assigned and len(set(assigned)) == len(assigned)
    for route in plans[wave].routes:
        driver = drivers[route.driver_id]
        assert driver.shift == wave and route.vehicle.type.type_id in driver.vehicle_types


@pytest.mark.parametrize("wave", list(Wave))
def test_vans_leave_one_after_another_and_times_follow_the_road(plans, wave):
    routes = plans[wave].routes
    first = local(MONDAY, 0) + timedelta(minutes=int(planner.FIRST_DEPARTURE[wave][:2]) * 60)
    first += timedelta(minutes=int(planner.FIRST_DEPARTURE[wave][3:]))
    assert [r.departure for r in routes] == [
        first + timedelta(seconds=k * planner.DEPARTURE_INTERVAL_S) for k in range(len(routes))
    ]
    for route in routes:
        first_stop = route.stops[0]
        assert first_stop.arrival == route.departure + timedelta(seconds=first_stop.leg_duration_s)
        arrivals = [s.arrival for s in route.stops]
        assert arrivals == sorted(arrivals) and route.completion > arrivals[-1]
        assert [s.sequence for s in route.stops] == list(range(1, len(route.stops) + 1))


@pytest.mark.parametrize("wave", list(Wave))
def test_the_promise_is_120_minutes_set_from_the_plan_for_wave_orders(plans, company, wave):
    wave_start, wave_end = (local(MONDAY, m) for m in company.waves[wave])
    for route in plans[wave].routes:
        for stop in route.stops:
            order = stop.order
            if order.window_type != WindowType.WAVE:
                assert (stop.window_start, stop.window_end) == (order.window_start, order.window_end)
                continue
            assert stop.window_end - stop.window_start == timedelta(minutes=company.promised_window_min)
            assert wave_start <= stop.window_start and stop.window_end <= wave_end
            assert stop.window_start.minute in (0, 30)
            if stop.arrival <= wave_end:  # inside it, or within the minutes a driver may be early
                early = timedelta(minutes=planner.EARLY_MIN)
                assert stop.window_start - early <= stop.arrival <= stop.window_end


def test_each_stop_is_the_nearest_open_one(company):
    """On a line east of the hub: the nearest stop waits for its window, the others go by distance."""
    hub = company.hub

    def order(order_id: str, km: float, start: int, end: int) -> Order:
        return Order(
            lat=hub.lat,
            lon=hub.lon + km / 83.4,  # a degree of longitude is about 83.4 km here
            order_id=order_id,
            zone_id="Z03",
            parcels=1,
            parcel_size="small",
            customer_type="B2C",
            wave="morning",
            window_type="slot",
            window_start=local(MONDAY, start * 60),
            window_end=local(MONDAY, end * 60),
        )

    orders = [
        order("O-near-late", 1, 12, 14),
        order("O-middle", 3, 8, 14),
        order("O-far", 6, 8, 14),
        order("O-farther", 7, 8, 10),
    ]
    stops, completion = planner.sequence(orders, local(MONDAY, 7 * 60 + 45), company, Wave.MORNING, straight_matrix)
    assert [s.order.order_id for s in stops] == ["O-middle", "O-far", "O-farther", "O-near-late"]
    # The van reaches the last stop long before noon and waits until 15 minutes before its window.
    assert stops[-1].arrival < local(MONDAY, 11 * 60)
    minutes_per_stop = company.zones["Z03"].minutes_per_stop
    assert completion == local(MONDAY, 11 * 60 + 45 + minutes_per_stop)


def test_a_fleet_too_small_holds_the_orders_it_cannot_carry(monday, company):
    small = dataclasses.replace(company, vehicles=company.vehicles[:2])
    plan = planner.plan_wave(MONDAY, Wave.MORNING, monday, small, straight_matrix)
    wave = [o for o in monday if o.wave == Wave.MORNING]
    assert len(plan.routes) == 2 and plan.held
    assert sum(len(r.stops) for r in plan.routes) + len(plan.held) == len(wave)
    for route in plan.routes:
        assert route.parcels <= route.vehicle.capacity


def test_zones_are_grouped_when_there_are_fewer_vans_than_zones(monday, company):
    by_zone: dict[str, list[Order]] = {}
    for o in monday:
        by_zone.setdefault(o.zone_id, []).append(o)
    areas = planner.group_zones(by_zone, company.zones, 10)
    assert len(areas) == 10
    assert sorted(z for area in areas for z in area) == sorted(by_zone)


def test_the_plan_is_the_same_every_time(plans, monday, company):
    again = planner.plan_wave(MONDAY, Wave.MORNING, monday, company, straight_matrix)
    assert again == plans[Wave.MORNING]
