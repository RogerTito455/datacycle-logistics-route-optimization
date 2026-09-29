"""A van's day on the road: the track it drives, and what its GPS, telemetry unit and handheld send.

drive_day() takes the routes of one van on a service date, in order, with the OSRM road of each,
and builds its day:

- The van is at its dock LOADING_MIN minutes before the planned departure: door open, ignition off.
- It leaves at the planned departure, or, for its afternoon route, TURNAROUND_MIN minutes after it
  came back from the morning if that is later. Every parcel of the route is scanned
  `out_for_delivery` as it leaves.
- It follows the OSRM geometry segment by segment. A segment takes OSRM's duration times the traffic
  factor where and when it starts (traffic.py), times a random factor per leg (LEG_NOISE): a lorry
  in the loading bay, a slow junction.
- At a stop the handheld scans `arrived`. If that is more than EARLY_MIN minutes before the promised
  window, the driver waits. Then the stop (behaviour.py): the cargo door opens, the `delivered` or
  `failed` scan comes three quarters into it, the door closes and the van leaves. A delivered parcel
  gets its proof-of-delivery photo.
- The 30-minute break comes after the first stop that ends three hours after departure, unless it
  was the last, as in the plan.
- After the last stop the van drives back to the hub. Between waves an electric van charges there.

Its messages: a GPS ping every GPS_INTERVAL_S seconds from its first minute at the dock to its last
at the hub, telemetry every TELEMETRY_INTERVAL_S seconds, and the handheld's scans when they happen.
Pings and telemetry carry the route from departure until the van is back at the hub, and none while
it waits there. Everything random comes from generators seeded with the seed, the date and the van
or route, so a date and a seed always give the same messages.
"""

from __future__ import annotations

import hashlib
import math
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from heapq import merge

import numpy as np
from llobregat_generator import pod

from llobregat_simulator import behaviour
from llobregat_simulator.company import Company, Vehicle, local
from llobregat_simulator.osrm import Leg
from llobregat_simulator.osrm import Route as Road
from llobregat_simulator.planner import BREAK_AFTER_MIN, EARLY_MIN, Route
from llobregat_simulator.traffic import Traffic

GPS_TOPIC, TELEMETRY_TOPIC, EVENTS_TOPIC = "gps.pings", "vehicle.telemetry", "delivery.events"
GPS_SOURCE, TELEMETRY_SOURCE, HANDHELD_SOURCE = "simulator/gps", "simulator/telemetry", "simulator/handheld"
SCHEMA_VERSION = 1  # of the three messages
GPS_INTERVAL_S = 5
TELEMETRY_INTERVAL_S = 30

# Rules of the simulator, where the seeds say nothing (README, "Simulation").
LOADING_MIN = 15  # at the dock with the door open before leaving
TURNAROUND_MIN = 20  # back from the morning, unloading and loading before the afternoon
CHARGER_KW = 50  # DC chargers at the hub, used between waves
LEG_NOISE = 0.12  # sigma of the lognormal factor of each leg
SCAN_AT = 0.75  # the delivered or failed scan, as a share of the stop
DOOR_S = 15  # the cargo door opens this long after the stop starts and closes this long before it ends
IGNITION_S = 5  # the driver switches off this long after arriving and on this long before leaving
MAX_SEGMENT_SPEED_MS = 30.0  # a segment OSRM times at zero is driven at this speed at most
GPS_ACCURACY_M = (3.0, 8.0)
SPEED_NOISE = 0.03
START_LEVEL = {"electric": (0.88, 1.0), "diesel": (0.35, 0.95), "CNG": (0.40, 0.95)}  # of the tank, at dawn
ADBLUE_PCT = (30.0, 90.0)
ADBLUE_PCT_PER_KM = 0.02
CNG_FULL_BAR = 200.0
TYRE_BAR = (4.6, 5.2)
EVENT_NAMESPACE = uuid.UUID("5b1c5a52-58c8-4a4e-9a55-6c6c0b7a0e07")  # event ids: uuid5 of route, order, status
STREAM = 7  # third entropy word of the simulator's random streams (issue #7)


@dataclass(frozen=True, slots=True)
class Message:
    t: int  # seconds after local midnight of the service date
    topic: str
    key: str
    value: dict
    photo: pod.Delivery | None = None  # a delivered event: the photo to store before it is sent


def _number(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


def rng_for(seed: int, service_date: date, *names: str) -> np.random.Generator:
    return np.random.default_rng([seed, service_date.toordinal(), STREAM, *map(_number, names)])


def bearing(lon1, lat1, lon2, lat2):
    """Initial bearing in degrees from north, 0-360; works on numpy arrays."""
    p1, p2, dl = np.radians(lat1), np.radians(lat2), np.radians(lon2 - lon1)
    y = np.sin(dl) * np.cos(p2)
    x = np.cos(p1) * np.sin(p2) - np.sin(p1) * np.cos(p2) * np.cos(dl)
    return np.degrees(np.arctan2(y, x)) % 360


@dataclass
class _Track:
    """Where the van is over the day: keyframes of time, position and distance, straight lines between."""

    t: list[float]
    lon: list[float]
    lat: list[float]
    dist: list[float]
    off: list[tuple[float, float]] = field(default_factory=list)  # ignition off
    door: list[tuple[float, float]] = field(default_factory=list)  # cargo door open
    charge: list[tuple[float, float, float]] = field(default_factory=list)  # start, end, energy added
    routes: list[tuple[float, float, str]] = field(default_factory=list)  # departure, back at the hub, route

    @property
    def now(self) -> float:
        return self.t[-1]

    def stand(self, until: float) -> None:
        if until > self.t[-1]:
            self.t.append(until)
            self.lon.append(self.lon[-1])
            self.lat.append(self.lat[-1])
            self.dist.append(self.dist[-1])

    def drive(self, leg: Leg, traffic: Traffic, noise: float, midnight: datetime) -> None:
        for (lon, lat), metres, seconds in zip(leg.coordinates[1:], leg.distances_m, leg.durations_s, strict=True):
            if metres <= 0:
                continue
            when = midnight + timedelta(seconds=self.t[-1])
            dt = max(seconds * traffic.factor(when, self.lon[-1], self.lat[-1]) * noise, metres / MAX_SEGMENT_SPEED_MS)
            self.t.append(self.t[-1] + dt)
            self.lon.append(lon)
            self.lat.append(lat)
            self.dist.append(self.dist[-1] + metres)


def _inside(ts: np.ndarray, intervals: Sequence[tuple[float, float]]) -> np.ndarray:
    mask = np.zeros(ts.shape, dtype=bool)
    for start, end in intervals:
        mask |= (ts >= start) & (ts < end)
    return mask


@dataclass
class VanDay:
    """A van's simulated day: its track, its handheld scans and what it needs to report its sensors."""

    service_date: date
    van: Vehicle
    track: _Track
    events: list[Message]
    seed: int
    energy0: float  # in the tank or battery at dawn, in the type's energy unit
    usable: float  # usable tank or battery
    counter0: float  # the energy counter at dawn
    adblue0: float
    tyres: list[float]

    @property
    def start(self) -> int:
        return int(self.track.t[0])

    @property
    def end(self) -> int:
        return int(self.track.t[-1])

    def _at(self, ts: np.ndarray) -> dict[str, np.ndarray]:
        """The van's state at the given moments: position, speed, heading, distance, route."""
        t = np.asarray(self.track.t)
        lon, lat, dist = (np.asarray(a) for a in (self.track.lon, self.track.lat, self.track.dist))
        k = np.clip(np.searchsorted(t, ts, side="right") - 1, 0, len(t) - 2)
        speed = (dist[k + 1] - dist[k]) / (t[k + 1] - t[k])
        heading = np.where(np.diff(dist) > 0, bearing(lon[:-1], lat[:-1], lon[1:], lat[1:]), np.nan)
        last = np.maximum.accumulate(np.where(np.isnan(heading), -1, np.arange(len(heading))))
        heading = np.where(last >= 0, heading[np.maximum(last, 0)], 0.0)
        route = np.full(ts.shape, None, dtype=object)
        for start, end, route_id in self.track.routes:
            route[(ts >= start) & (ts < end)] = route_id
        return {
            "lon": np.interp(ts, t, lon),
            "lat": np.interp(ts, t, lat),
            "dist": np.interp(ts, t, dist),
            "speed": np.where(ts < t[-1], speed, 0.0),
            "heading": heading[k],
            "route": route,
        }

    def _ticks(self, interval: int) -> np.ndarray:
        first = math.ceil(self.start / interval) * interval
        return np.arange(first, self.end + 1, interval, dtype=float)

    def pings(self) -> Iterator[Message]:
        ts = self._ticks(GPS_INTERVAL_S)
        state = self._at(ts)
        rng = rng_for(self.seed, self.service_date, self.van.vehicle_id, "gps")
        accuracy = rng.uniform(*GPS_ACCURACY_M, len(ts))
        north, east = rng.normal(0, accuracy / 2), rng.normal(0, accuracy / 2)
        lat = state["lat"] + north / 111_320
        lon = state["lon"] + east / (111_320 * np.cos(np.radians(state["lat"])))
        speed = np.maximum(state["speed"] * 3.6 * (1 + rng.normal(0, SPEED_NOISE, len(ts))), 0)
        speed = np.where(state["speed"] > 0, speed, 0.0)
        times = _Clock(self.service_date).isos(ts)
        for i, t in enumerate(ts.astype(int)):
            value = {
                "vehicle_id": self.van.vehicle_id,
                "event_time": times[i],
                "lat": round(float(lat[i]), 6),
                "lon": round(float(lon[i]), 6),
                "speed_kmh": round(float(speed[i]), 1),
                "heading_deg": int(state["heading"][i]) % 360,
                "accuracy_m": round(float(accuracy[i]), 1),
                "source": GPS_SOURCE,
                "schema_version": SCHEMA_VERSION,
            }
            if state["route"][i] is not None:
                value["route_id"] = state["route"][i]
            yield Message(int(t), GPS_TOPIC, self.van.vehicle_id, value)

    def energy(self, ts: np.ndarray, dist: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Energy left, the energy counter and whether the van is charging, at the given moments."""
        used = dist / 1000 * self.van.type.consumption / 100
        added = np.zeros(ts.shape)
        for start, end, amount in self.track.charge:
            added += amount * np.clip((ts - start) / (end - start), 0, 1)
        charging = np.zeros(ts.shape, dtype=bool)
        for start, end, _ in self.track.charge:  # a reading says charging when energy came in since the last
            charging |= (ts > start) & (ts < end + TELEMETRY_INTERVAL_S)
        return self.energy0 - used + added, self.counter0 + used, charging

    def telemetry(self) -> Iterator[Message]:
        ts = self._ticks(TELEMETRY_INTERVAL_S)
        state = self._at(ts)
        left, counter, charging = self.energy(ts, state["dist"])
        ignition = ~_inside(ts, self.track.off)
        door = _inside(ts, self.track.door)
        kind, sensors = self.van.type.energy, " ".join(self.van.type.sensors)
        times = _Clock(self.service_date).isos(ts)
        for i, t in enumerate(ts.astype(int)):
            speed = round(float(state["speed"][i]) * 3.6, 1)
            value = {
                "vehicle_id": self.van.vehicle_id,
                "event_time": times[i],
                "speed_kmh": speed,
                "odometer_km": round(self.van.odometer_km + float(state["dist"][i]) / 1000, 1),
                "ignition_on": bool(ignition[i]),
                "energy_level_pct": round(100 * float(left[i]) / self.usable, 1),
                "energy_used_total": round(float(counter[i]), 3),
                "energy_unit": self.van.type.energy_unit,
                "cargo_door_open": bool(door[i]),
                "source": TELEMETRY_SOURCE,
                "schema_version": SCHEMA_VERSION,
            }
            if state["route"][i] is not None:
                value["route_id"] = state["route"][i]
            if kind == "electric":
                value["charging"] = bool(charging[i])
            if "Tyre pressure" in sensors:
                value["tyre_pressure_bar"] = self.tyres
            if kind == "diesel":
                value["engine_rpm"] = 0 if not ignition[i] else (750 if speed == 0 else int(1100 + 22 * speed))
                value["adblue_level_pct"] = round(self.adblue0 - ADBLUE_PCT_PER_KM * float(state["dist"][i]) / 1000, 1)
            if kind == "CNG":
                value["cng_tank_pressure_bar"] = round(CNG_FULL_BAR * float(left[i]) / self.usable, 1)
            yield Message(int(t), TELEMETRY_TOPIC, self.van.vehicle_id, value)

    def messages(self) -> Iterator[Message]:
        """Everything the van sends, in time order."""
        return merge(self.pings(), self.telemetry(), iter(self.events), key=lambda m: m.t)


class _Clock:
    """ISO 8601 UTC times of seconds after local midnight of the service date."""

    def __init__(self, service_date: date):
        self.epoch = local(service_date, 0).timestamp()

    def iso(self, t: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.epoch + t))

    def isos(self, ts: np.ndarray) -> list[str]:
        seconds = (np.round(self.epoch + ts)).astype("datetime64[s]")
        return [f"{text}Z" for text in np.datetime_as_string(seconds, unit="s")]

    def moment(self, t: float) -> datetime:
        return datetime.fromtimestamp(self.epoch + t, UTC)


def drive_day(
    service_date: date,
    van: Vehicle,
    routes: Sequence[Route],
    roads: dict[str, Road],
    company: Company,
    demand: dict,
    notes: dict[str, behaviour.NoteLabels],
    traffic: Traffic,
    seed: int = 0,
) -> VanDay:
    """The van's day over its routes, in order of departure. roads[route_id] runs hub, stops, hub."""
    midnight = local(service_date, 0)
    clock = _Clock(service_date)
    rng = rng_for(seed, service_date, van.vehicle_id)
    usable = van.type.tank * (van.battery_health_pct or 100) / 100
    energy0 = usable * rng.uniform(*START_LEVEL[van.type.energy])
    adblue0 = rng.uniform(*ADBLUE_PCT)
    tyres = [round(float(p), 2) for p in rng.uniform(*TYRE_BAR, 4)]
    counter0 = van.odometer_km * van.type.consumption / 100
    track: _Track | None = None
    events: list[Message] = []
    back = 0.0

    def scan(route: Route, i: int, status: str, t: float, lat: float, lon: float, **extra) -> None:
        t = round(t)
        stop = route.stops[i]
        order = stop.order
        value = {
            "event_id": str(uuid.uuid5(EVENT_NAMESPACE, f"{route.route_id}/{order.order_id}/{status}")),
            "order_id": order.order_id,
            "route_id": route.route_id,
            "stop_sequence": stop.sequence,
            "vehicle_id": van.vehicle_id,
            "driver_id": route.driver_id,
            "status": status,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            **extra,
            "event_time": clock.iso(t),
            "source": HANDHELD_SOURCE,
            "schema_version": SCHEMA_VERSION,
        }
        photo = None
        if status == "delivered":
            photo = pod.Delivery(
                order.order_id, service_date, clock.moment(t), order.lat, order.lon, order.parcels, order.parcel_size
            )
            value["pod_object_key"] = pod.object_key(photo)
        events.append(Message(t, EVENTS_TOPIC, van.vehicle_id, value, photo))

    for route in sorted(routes, key=lambda r: r.departure):
        road = roads[route.route_id]
        route_rng = rng_for(seed, service_date, route.route_id)
        orders = [s.order for s in route.stops]
        outcomes = behaviour.outcomes(orders, company, demand, notes, route_rng)
        noise = route_rng.lognormal(0, LEG_NOISE, len(road.legs))
        planned = (route.departure - midnight).total_seconds()
        if track is None:
            start = math.floor((planned - LOADING_MIN * 60) / GPS_INTERVAL_S) * GPS_INTERVAL_S
            lon, lat = road.legs[0].coordinates[0]
            track = _Track([start], [lon], [lat], [0.0])
            departure = planned
        else:
            departure = max(planned, back + TURNAROUND_MIN * 60)
            if van.type.energy == "electric" and departure - back > 180:
                used = track.dist[-1] / 1000 * van.type.consumption / 100
                level = energy0 - used + sum(c[2] for c in track.charge)
                hours = (departure - 120 - (back + 60)) / 3600
                track.charge.append((back + 60, departure - 120, max(0.0, min(usable - level, CHARGER_KW * hours))))
        track.door.append((max(track.now, departure - LOADING_MIN * 60), departure - 180))
        track.off.append((track.now, departure - 60))
        track.stand(departure)
        for i in range(len(orders)):
            scan(route, i, "out_for_delivery", departure, company.hub.lat, company.hub.lon)
        rested = False
        for i, (stop, outcome) in enumerate(zip(route.stops, outcomes, strict=True)):
            track.drive(road.legs[i], traffic, float(noise[i]), midnight)
            arrival = track.now
            scan(route, i, "arrived", arrival, track.lat[-1], track.lon[-1])
            begin = max(arrival, (stop.window_start - midnight).total_seconds() - EARLY_MIN * 60)
            leave = begin + outcome.stop_s
            at = begin + SCAN_AT * outcome.stop_s
            track.off.append((arrival + IGNITION_S, leave - IGNITION_S))
            track.door.append((begin + DOOR_S, leave - DOOR_S))
            track.stand(leave)
            if outcome.failed:
                scan(route, i, "failed", at, stop.order.lat, stop.order.lon, failure_reason=outcome.reason)
            else:
                scan(route, i, "delivered", at, stop.order.lat, stop.order.lon)
            last = i == len(route.stops) - 1
            if not rested and not last and leave - departure >= BREAK_AFTER_MIN * 60:
                rest = company.break_min[route.wave] * 60
                track.off.append((leave, leave + rest))
                track.stand(leave + rest)
                rested = True
        track.drive(road.legs[-1], traffic, float(noise[-1]), midnight)
        back = track.now
        track.routes.append((departure, back, route.route_id))
    if track is None:
        raise ValueError(f"{van.vehicle_id} has no route on {service_date}")
    track.off.append((back + 30, back + 120))
    track.stand(back + 120)
    events.sort(key=lambda m: m.t)
    return VanDay(service_date, van, track, events, seed, energy0, usable, counter0, adblue0, tyres)
