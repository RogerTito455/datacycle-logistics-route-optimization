"""The baseline route plan: how Llobregat Express plans a delivery wave today, before any optimizer.

The company's planners make one fixed plan per wave before the vans leave, and nobody changes it
during the day. This module reproduces that practice with simple rules, so that the optimizer
(issue #16) has a realistic plan to be compared with. For a service date and a wave:

1. Every van of the wave goes out: the whole fleet in the morning, the vans the fleet register
   marks for the afternoon after (30 and 10 on a weekday, as in the company profile).
2. Routes per zone. A zone needs its stops divided by its stops per route (company profile), its
   estimated minutes (step 4) divided by a route's, or its parcels divided by the mean van
   capacity, whichever is more. Every zone with orders gets one
   route, and the others go one at a time to the zone with the highest need per route (the
   D'Hondt method). With fewer vans than zones (the afternoon), the smallest zone joins its nearest
   neighbour until there are as many areas as vans.
3. Vans to routes. A zone takes its own vans first (their home zone in the fleet register),
   preferred types and larger vans first. Routes still without a van, the busiest first, take a
   free van of a type the zone prefers, from the nearest home zone.
4. Orders to routes. The zone's orders are swept by angle around their centre and cut into
   consecutive slices, one per van, in proportion to capacity. A slice never exceeds the van's
   parcel capacity or the company's 390-minute maximum route, as estimated before the stops are
   ordered (the estimate is rough, and a planned route can end up longer). What does not fit goes
   to the route with room nearest to the order; if no route has room, the order stays at the hub
   and is reported (held).
5. Stop order. From the hub, each next stop is the nearest by OSRM travel time among the stops
   whose window is open at the van's arrival, or opens within EARLY_MIN minutes: drivers do not
   deliver a 12:00-14:00 slot at 09:00. When no window is open the van goes to the one that opens
   first and waits. The durations are OSRM's, without traffic: the plan is optimistic, and
   comparing it with what the vans do gives the KPI's delay against plan.
6. Times. Vans leave the docks from FIRST_DEPARTURE, one every DEPARTURE_INTERVAL_S; each stop
   takes its zone's minutes per stop; the 30-minute break comes after the first stop that ends
   BREAK_AFTER_MIN minutes after departure, unless it was the last.
7. The promise. A consumer who accepted any time in the wave (window_type 'wave') gets a 120-minute
   window when the routes are planned (demand model, prompt 004): it starts on the half hour at or
   before the planned arrival minus an hour, inside the wave. Other orders keep their own window.
8. Drivers. Each route gets a driver of the wave's shift cleared for its van type, one who knows
   the route's zone if possible; the route with the fewest candidates is served first.

Nothing is random: the same orders and the same road network give the same plan.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from llobregat_generator.rules import Wave, WindowType, minutes

from llobregat_simulator.company import Company, Order, Point, Vehicle, Zone, local

SOURCE_ID = "planner/baseline"
PLANNER = "baseline"
PLAN_VERSION = 0
REPLAN_REASON = "initial"

# Rules of the baseline planner where the company profile says nothing (README, "Baseline plan").
PLANNED_AT = {Wave.MORNING: "06:00", Wave.AFTERNOON: "13:45"}  # when the planners make the wave's plan
FIRST_DEPARTURE = {Wave.MORNING: "07:30", Wave.AFTERNOON: "14:35"}  # hub timetable: departures 07:30-14:45
DEPARTURE_INTERVAL_S = 40  # one van leaves the docks every 40 seconds
EARLY_MIN = 15  # a driver delivers at most 15 minutes before a window opens, and waits otherwise
BREAK_AFTER_MIN = 180  # the break comes after the first stop that ends three hours after departure
WINDOW_STEP_MIN = 30  # promised windows start on the half hour
# Estimates of a route's length before its stops are ordered, against the 390-minute maximum. The
# company profile's baseline has 22 minutes from the hub to the first stop; between stops it has
# 1.1 minutes of driving, but OSRM on the real streets gives these plans about 2 on 28 September
# 2026. 1.8 plans every morning order of that heavy Monday and keeps most routes near the maximum.
EST_FIRST_LEG_MIN = 25.0
EST_LEG_MIN = 1.8

# Durations in seconds and distances in metres between every pair of points, as OSRM /table gives them.
Matrix = Callable[[Sequence[Point]], tuple[list[list[float]], list[list[float]]]]


@dataclass(frozen=True)
class Stop:
    order: Order
    sequence: int
    arrival: datetime
    leg_distance_m: float  # from the previous stop, or the hub
    leg_duration_s: float
    window_start: datetime  # the promised window
    window_end: datetime


@dataclass
class Route:
    route_id: str
    wave: Wave
    zone_id: str
    vehicle: Vehicle
    departure: datetime
    stops: list[Stop]
    completion: datetime  # when the last stop ends
    driver_id: str | None = None

    @property
    def parcels(self) -> int:
        return sum(s.order.parcels for s in self.stops)

    @property
    def distance_m(self) -> float:
        return sum(s.leg_distance_m for s in self.stops)

    @property
    def zones(self) -> set[str]:
        return {s.order.zone_id for s in self.stops}


@dataclass
class WavePlan:
    service_date: date
    wave: Wave
    planned_at: datetime
    routes: list[Route]
    held: list[Order] = field(default_factory=list)  # orders no route had room for


def haversine_m(a: Point, b: Point) -> float:
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(math.radians(b.lon - a.lon) / 2) ** 2
    )
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


def centre(points: Sequence[Point]) -> Point:
    return Point(sum(p.lat for p in points) / len(points), sum(p.lon for p in points) / len(points))


# 2 · Routes per zone ------------------------------------------------------------------------


def group_zones(by_zone: dict[str, list[Order]], zones: dict[str, Zone], vans: int) -> list[list[str]]:
    """Zones with orders, the smallest joined to its nearest neighbour until there are no more groups than vans."""
    areas = [[z] for z in sorted(by_zone)]
    while len(areas) > vans:
        smallest = min(areas, key=lambda a: (sum(len(by_zone[z]) for z in a), a))
        others = [a for a in areas if a is not smallest]
        nearest = min(others, key=lambda a: (min(haversine_m(zones[x], zones[y]) for x in smallest for y in a), a))
        nearest.extend(smallest)
        areas = others
    return areas


def routes_per_area(
    areas: list[list[str]], by_zone: dict[str, list[Order]], need: Callable[[list[Order]], float], vans: int
) -> list[int]:
    """One route per area, then the rest one at a time to the area with the highest need per route."""
    needs = [need([o for z in area for o in by_zone[z]]) for area in areas]
    routes = [1] * len(areas)
    for _ in range(vans - len(areas)):
        best = max(range(len(areas)), key=lambda i: (needs[i] / routes[i], -i))
        routes[best] += 1
    return routes


# 3 · Vans to routes -------------------------------------------------------------------------


def assign_vans(
    areas: list[list[str]], routes: list[int], fleet: list[Vehicle], zones: dict[str, Zone], loads: list[int]
) -> list[list[Vehicle]]:
    """The vans of each area: its own first, then free vans of a preferred type from the nearest home zone."""
    free = sorted(fleet, key=lambda v: v.vehicle_id)
    vans: list[list[Vehicle]] = [[] for _ in areas]
    for i, area in enumerate(areas):
        preferred = zones[area[0]].preferred_types
        own = sorted(
            (v for v in free if v.home_zone_id in area),
            key=lambda v: (v.type.type_id not in preferred, -v.capacity, v.vehicle_id),
        )
        vans[i] = own[: routes[i]]
        free = [v for v in free if v not in vans[i]]
    open_routes = sorted(
        (i for i in range(len(areas)) for _ in range(routes[i] - len(vans[i]))),
        key=lambda i: (-loads[i] / routes[i], i),
    )
    for i in open_routes:
        preferred, here = zones[areas[i][0]].preferred_types, centre([zones[z] for z in areas[i]])
        van = min(
            free,
            key=lambda v: (v.type.type_id not in preferred, haversine_m(zones[v.home_zone_id], here), v.vehicle_id),
        )
        vans[i].append(van)
        free.remove(van)
    return vans


# 4 · Orders to routes -----------------------------------------------------------------------


@dataclass
class _Load:
    """A van's orders while the wave is cut into routes, with its estimated length."""

    van: Vehicle
    area: int
    orders: list[Order] = field(default_factory=list)
    parcels: int = 0
    minutes: float = 0.0

    def fits(self, order: Order, stop_min: float, max_min: float) -> bool:
        return self.parcels + order.parcels <= self.van.capacity and self.minutes + stop_min <= max_min

    def add(self, order: Order, stop_min: float) -> None:
        self.orders.append(order)
        self.parcels += order.parcels
        self.minutes += stop_min


def sweep(orders: list[Order], hub: Point) -> list[Order]:
    """Orders by angle around their centre, starting from the direction of the hub."""
    c = centre(orders)
    scale = math.cos(math.radians(c.lat))

    def angle(p: Point) -> float:
        return math.atan2(p.lat - c.lat, (p.lon - c.lon) * scale)

    start = angle(hub)
    return sorted(orders, key=lambda o: ((angle(o) - start) % (2 * math.pi), o.order_id))


def cut(
    orders: list[Order], loads: list[_Load], stop_min: Callable[[Order], float], max_min: float, hub: Point
) -> list[Order]:
    """Fill the vans with consecutive slices of the swept orders; return the orders that did not fit."""
    total = sum(o.parcels for o in orders)
    capacity = sum(load.van.capacity for load in loads)
    targets = [total * load.van.capacity / capacity for load in loads]
    left, k = [], 0
    for order in sweep(orders, hub):
        while k < len(loads):
            last = k == len(loads) - 1
            if loads[k].fits(order, stop_min(order), max_min) and (loads[k].parcels < targets[k] or last):
                loads[k].add(order, stop_min(order))
                break
            k += 1
        else:
            left.append(order)
    return left


def place_leftovers(
    left: list[Order], loads: list[_Load], stop_min: Callable[[Order], float], max_min: float, anchors: list[Point]
) -> list[Order]:
    """Each order that did not fit goes to the route with room nearest to it; return those none can take."""
    held = []
    for order in left:
        room = [load for load in loads if load.fits(order, stop_min(order), max_min)]
        if not room:
            held.append(order)
            continue

        nearest = min(
            room,
            key=lambda load, o=order: (
                haversine_m(o, centre(load.orders) if load.orders else anchors[load.area]),
                load.van.vehicle_id,
            ),
        )
        nearest.add(order, stop_min(order))
    return held


# 5-7 · Stop order, times and the promise ------------------------------------------------------


def _seconds(moment: datetime, midnight: datetime) -> float:
    return (moment - midnight).total_seconds()


def promised_window(
    order: Order, arrival: datetime, wave: tuple[int, int], window_min: int, midnight: datetime
) -> tuple[datetime, datetime]:
    """The 120 minutes promised to the customer: the order's own window, or one set from the plan for 'wave' orders."""
    if order.window_type != WindowType.WAVE:
        return order.window_start, order.window_end
    start = math.floor((_seconds(arrival, midnight) / 60 - 60) / WINDOW_STEP_MIN) * WINDOW_STEP_MIN
    start = min(max(start, wave[0]), wave[1] - window_min)
    return midnight + timedelta(minutes=start), midnight + timedelta(minutes=start + window_min)


def sequence(
    orders: list[Order],
    departure: datetime,
    company: Company,
    wave: Wave,
    matrix: Matrix,
) -> tuple[list[Stop], datetime]:
    """Order the stops by nearest neighbour on OSRM travel times; return them with the route's end."""
    midnight = local(departure.date(), 0)
    durations, distances = matrix([company.hub, *orders])
    t, here, left = _seconds(departure, midnight), 0, list(range(1, len(orders) + 1))
    opens = {j: _seconds(orders[j - 1].window_start, midnight) - EARLY_MIN * 60 for j in left}
    start, rested, stops = t, False, []
    while left:
        if not rested and t - start >= BREAK_AFTER_MIN * 60:  # the break, before the next stop
            t += company.break_min[wave] * 60
            rested = True
        ready = [j for j in left if opens[j] <= t + durations[here][j]]
        if not ready:  # nothing open yet: the window that opens first
            first = min(opens[j] for j in left)
            ready = [j for j in left if opens[j] == first]
        j = min(ready, key=lambda j: (durations[here][j], orders[j - 1].order_id))
        order = orders[j - 1]
        arrival = t + durations[here][j]
        t = max(arrival, opens[j]) + company.zones[order.zone_id].minutes_per_stop * 60
        arrived = midnight + timedelta(seconds=arrival)
        promise = promised_window(order, arrived, company.waves[wave], company.promised_window_min, midnight)
        stops.append(Stop(order, len(stops) + 1, arrived, distances[here][j], durations[here][j], *promise))
        here = j
        left.remove(j)
    return stops, midnight + timedelta(seconds=t)


# 8 · Drivers --------------------------------------------------------------------------------


def assign_drivers(routes: list[Route], company: Company, wave: Wave) -> None:
    """A driver of the shift, cleared for the van, who knows the zone if possible; hardest routes first."""
    free = sorted(company.crew(wave), key=lambda d: d.driver_id)
    pending = list(routes)
    while pending:
        options = {r.route_id: [d for d in free if r.vehicle.type.type_id in d.vehicle_types] for r in pending}
        route = min(pending, key=lambda r: (len(options[r.route_id]), r.route_id))
        candidates = options[route.route_id]
        if candidates:
            driver = min(
                candidates,
                key=lambda d: (route.zone_id not in d.zones, not d.zones & route.zones, d.driver_id),
            )
            route.driver_id = driver.driver_id
            free.remove(driver)
        pending.remove(route)


# The plan -----------------------------------------------------------------------------------


def plan_wave(service_date: date, wave: Wave, orders: list[Order], company: Company, matrix: Matrix) -> WavePlan:
    """The baseline plan of one wave: its routes, and the orders no route had room for."""
    orders = sorted((o for o in orders if o.wave == wave), key=lambda o: o.order_id)
    planned_at = local(service_date, minutes(PLANNED_AT[wave]))
    fleet = company.fleet(wave)
    if not orders:
        return WavePlan(service_date, wave, planned_at, [])
    fleet = fleet[: len(orders)]
    by_zone: dict[str, list[Order]] = defaultdict(list)
    for order in orders:
        by_zone[order.zone_id].append(order)
    zones = company.zones
    areas = group_zones(by_zone, zones, len(fleet))
    for area in areas:  # the zone with the most orders names the area
        area.sort(key=lambda z: (-len(by_zone[z]), z))
    parcels = [sum(o.parcels for z in area for o in by_zone[z]) for area in areas]
    mean_capacity = sum(v.capacity for v in fleet) / len(fleet)
    max_min = company.max_route_min - EST_FIRST_LEG_MIN - company.break_min[wave]

    def stop_min(order: Order) -> float:
        return zones[order.zone_id].minutes_per_stop + EST_LEG_MIN

    def need(area_orders: list[Order]) -> float:
        """Routes the orders need: by the zones' stops per route, their minutes, or their parcels."""
        stops = Counter(o.zone_id for o in area_orders)
        return max(
            sum(n / zones[z].stops_per_route for z, n in stops.items()),
            sum(stop_min(o) for o in area_orders) / max_min,
            sum(o.parcels for o in area_orders) / mean_capacity,
        )

    counts = routes_per_area(areas, by_zone, need, len(fleet))
    vans = assign_vans(areas, counts, fleet, zones, parcels)
    loads = [_Load(van, i) for i, area_vans in enumerate(vans) for van in area_vans]
    left = []
    for i, area in enumerate(areas):
        area_orders = [o for z in area for o in by_zone[z]]
        left += cut(area_orders, [load for load in loads if load.area == i], stop_min, max_min, company.hub)
    anchors = [centre([zones[z] for z in area]) for area in areas]
    held = place_leftovers(left, loads, stop_min, max_min, anchors)

    routes, numbers = [], Counter()
    first = local(service_date, minutes(FIRST_DEPARTURE[wave]))
    named = []
    for load in loads:
        if not load.orders:
            continue
        counts_by_zone = Counter(o.zone_id for o in load.orders)
        zone_id = min(counts_by_zone, key=lambda z: (-counts_by_zone[z], z))
        numbers[zone_id] += 1
        named.append((f"R-{service_date:%Y%m%d}-{zone_id}-{wave.value[0].upper()}{numbers[zone_id]}", zone_id, load))
    for k, (route_id, zone_id, load) in enumerate(sorted(named, key=lambda n: n[0])):
        departure = first + timedelta(seconds=k * DEPARTURE_INTERVAL_S)
        stops, completion = sequence(load.orders, departure, company, wave, matrix)
        routes.append(Route(route_id, wave, zone_id, load.van, departure, stops, completion))
    assign_drivers(routes, company, wave)
    return WavePlan(service_date, wave, planned_at, routes, sorted(held, key=lambda o: o.order_id))
