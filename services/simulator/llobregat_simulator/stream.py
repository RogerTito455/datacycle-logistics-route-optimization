"""Publishing a simulated day to Redpanda at a chosen speed, with the proof-of-delivery photos.

Messages go out in the order of their event_time. With a speed of 60 a simulated minute takes a
second of wall-clock time; with 1 the vans move in real time; with 0 everything goes out as fast
as the broker takes it. The event_time in a message is always the simulated moment, so the speed
changes when the messages arrive, never what they say.

A `delivered` event names its photo (pod/<service date>/<order id>.jpg), so the photo is drawn and
stored in the RustFS bronze bucket before the event is sent. Photos are drawn by a few worker
threads while the rest of the stream goes on; the delivered events wait for theirs, in order.
"""

from __future__ import annotations

import json
import time
from collections import Counter, deque
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date

from llobregat_generator import pod

from llobregat_simulator.company import Hub, local
from llobregat_simulator.planner import Route, haversine_m
from llobregat_simulator.van import EVENTS_TOPIC, GPS_TOPIC, Message

PHOTO_WORKERS = 4


class Pacer:
    """Holds each message until its simulated moment, divided by the speed, has come."""

    def __init__(self, speed: float, clock: Callable[[], float] = time.monotonic, sleep=time.sleep):
        self.speed, self.clock, self.sleep = speed, clock, sleep
        self.origin: tuple[float, float] | None = None  # (simulated second, wall clock) of the first message
        self.behind = 0.0  # how far the last message was sent after its moment, in seconds

    def wait(self, t: float) -> None:
        if self.speed <= 0:
            return
        if self.origin is None:
            self.origin = (t, self.clock())
        due = self.origin[1] + (t - self.origin[0]) / self.speed
        ahead = due - self.clock()
        if ahead > 0:
            self.sleep(ahead)
        self.behind = max(0.0, -ahead)


@dataclass
class _RouteTally:
    departed: int | None = None  # first ping outside the hub geofence
    completed: int | None = None  # last delivered or failed scan
    delivered: int = 0
    failed: int = 0
    on_time: int = 0


@dataclass
class Tally:
    """What went out: messages per topic, and each route's KPI measured from them as silver will."""

    hub: Hub
    windows: dict[str, tuple[int, int]]  # order id: promised window, seconds after local midnight
    counts: Counter = field(default_factory=Counter)
    routes: dict[str, _RouteTally] = field(default_factory=dict)
    photos: int = 0

    @classmethod
    def of(cls, routes: Iterable[Route], hub: Hub, service_date: date) -> Tally:
        midnight = local(service_date, 0)
        windows = {}
        for route in routes:
            for s in route.stops:
                windows[s.order.order_id] = (
                    int((s.window_start - midnight).total_seconds()),
                    int((s.window_end - midnight).total_seconds()),
                )
        return cls(hub, windows)

    def add(self, m: Message) -> None:
        self.counts[m.topic] += 1
        route_id = m.value.get("route_id")
        if route_id is None:
            return
        route = self.routes.setdefault(route_id, _RouteTally())
        if m.topic == GPS_TOPIC and route.departed is None:
            if haversine_m(self.hub, _Point(m.value["lat"], m.value["lon"])) > self.hub.geofence_radius_m:
                route.departed = m.t
        elif m.topic == EVENTS_TOPIC and m.value["status"] in ("delivered", "failed"):
            route.completed = m.t
            if m.value["status"] == "delivered":
                route.delivered += 1
                self.photos += "pod_object_key" in m.value
                start, end = self.windows.get(m.value["order_id"], (0, 0))
                route.on_time += start <= m.t <= end
            else:
                route.failed += 1

    def report(self) -> str:
        done = [r for r in self.routes.values() if r.departed is not None and r.completed is not None]
        stops = sum(r.delivered + r.failed for r in self.routes.values())
        failed = sum(r.failed for r in self.routes.values())
        delivered = stops - failed
        lines = ["Sent: " + ", ".join(f"{topic} {n:,}" for topic, n in sorted(self.counts.items()))]
        if done and stops:
            minutes = [(r.completed - r.departed) / 60 for r in done]
            lines += [
                f"Stops: {stops:,}, {failed:,} failed at the first attempt ({failed / stops:.1%}); "
                f"{sum(r.on_time for r in self.routes.values()) / max(delivered, 1):.1%} of the deliveries inside "
                "the promised window; "
                f"{self.photos:,} proof-of-delivery photos",
                "Average delivery time per route, geofence exit to the last scan: "
                f"{sum(minutes) / len(minutes):.0f} min over {len(done)} routes "
                f"(from {min(minutes):.0f} to {max(minutes):.0f})",
            ]
        return "\n".join(lines)


@dataclass(frozen=True)
class _Point:
    lat: float
    lon: float


class KafkaSink:
    """Sends messages to Redpanda: JSON values, keyed by vehicle, in the topic of each message."""

    def __init__(self, bootstrap: str):
        from confluent_kafka import Producer  # imported here so the tests need no broker library

        self.producer = Producer(
            {
                "bootstrap.servers": bootstrap,
                "client.id": "llobregat-simulator",
                "enable.idempotence": True,
                "linger.ms": 20,
                "compression.type": "lz4",
            }
        )
        self.errors: list[str] = []

    def _delivered(self, error, _message) -> None:
        if error is not None:
            self.errors.append(str(error))

    def __call__(self, m: Message) -> None:
        value = json.dumps(m.value, separators=(",", ":"), ensure_ascii=False).encode()
        while True:
            try:
                self.producer.produce(m.topic, key=m.key.encode(), value=value, on_delivery=self._delivered)
                break
            except BufferError:  # the local queue is full: let it drain
                self.producer.poll(0.5)
        self.producer.poll(0)

    def close(self) -> None:
        left = self.producer.flush(60)
        if left or self.errors:
            raise RuntimeError(f"{left} messages not delivered; errors: {self.errors[:3]}")


def publish(
    messages: Iterable[Message],
    send: Callable[[Message], None],
    store_photo: Callable[[pod.Delivery], str],
    pacer: Pacer,
    tally: Tally,
    progress: Callable[[int], None] | None = None,
    workers: int = PHOTO_WORKERS,
) -> None:
    """Send the messages in order, at the pacer's speed; a delivered event after its photo is stored."""
    waiting: deque[tuple[Future, Message]] = deque()

    def release(limit: int) -> None:
        """Send the delivered events whose photo is stored, and wait for photos beyond the limit."""
        while waiting and (waiting[0][0].done() or len(waiting) > limit):
            photo, m = waiting.popleft()
            key = photo.result()
            if key != m.value["pod_object_key"]:
                raise RuntimeError(f"photo stored at {key}, event names {m.value['pod_object_key']}")
            send(m)
            tally.add(m)

    with ThreadPoolExecutor(workers, thread_name_prefix="pod") as pool:
        for m in messages:
            pacer.wait(m.t)
            release(limit=50 * workers)
            if progress:
                progress(m.t)
            if m.photo is not None:
                waiting.append((pool.submit(store_photo, m.photo), m))
                continue
            send(m)
            tally.add(m)
        release(limit=0)
