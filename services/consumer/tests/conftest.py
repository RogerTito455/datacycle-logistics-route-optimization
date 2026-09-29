"""Messages as the simulator sends them (services/simulator/README.md, "Messages"), and a fake broker."""

from __future__ import annotations

import json

import pytest
from confluent_kafka import TIMESTAMP_CREATE_TIME, TopicPartition
from llobregat_consumer.messages import Envelope

SOURCES = frozenset({"simulator/gps", "simulator/telemetry", "simulator/handheld"})

PING = {
    "vehicle_id": "V-08",
    "route_id": "R-20260928-Z02-M1",
    "event_time": "2026-09-28T06:15:05Z",
    "lat": 41.378359,
    "lon": 2.159104,
    "speed_kmh": 14.6,
    "heading_deg": 134,
    "accuracy_m": 6.0,
    "source": "simulator/gps",
    "schema_version": 1,
}
TELEMETRY = {  # an electric van with tyre pressure sensors
    "vehicle_id": "V-08",
    "route_id": "R-20260928-Z02-M1",
    "event_time": "2026-09-28T06:15:00Z",
    "speed_kmh": 14.2,
    "odometer_km": 48213.4,
    "ignition_on": True,
    "energy_level_pct": 81.5,
    "energy_used_total": 9642.681,
    "energy_unit": "kWh",
    "cargo_door_open": False,
    "source": "simulator/telemetry",
    "schema_version": 1,
    "charging": False,
    "tyre_pressure_bar": [4.81, 4.9, 5.02, 4.77],
}
DELIVERED = {
    "event_id": "e6097e9f-baee-5004-b099-a39d71e9a2e1",
    "order_id": "O-20260928-01152",
    "route_id": "R-20260928-Z02-M1",
    "stop_sequence": 1,
    "vehicle_id": "V-08",
    "driver_id": "D-008",
    "status": "delivered",
    "lat": 41.380303,
    "lon": 2.161758,
    "event_time": "2026-09-28T05:57:13Z",
    "pod_object_key": "pod/2026-09-28/O-20260928-01152.jpg",
    "source": "simulator/handheld",
    "schema_version": 1,
}
FAILED = {
    "event_id": "46895084-c32a-55e9-94d3-f14e87634ecc",
    "order_id": "O-20260928-01507",
    "route_id": "R-20260928-Z05-M2",
    "stop_sequence": 1,
    "vehicle_id": "V-23",
    "driver_id": "D-032",
    "status": "failed",
    "lat": 41.39331,
    "lon": 2.124281,
    "event_time": "2026-09-28T06:06:24Z",
    "failure_reason": "recipient_absent",
    "source": "simulator/handheld",
    "schema_version": 1,
}


def envelope(topic: str, value, partition: int = 0, offset: int = 0, key: bytes | None = b"V-08") -> Envelope:
    """A message on a topic; a dict is sent as JSON, bytes and None as they are."""
    raw = json.dumps(value).encode() if isinstance(value, dict) else value
    return Envelope(topic, partition, offset, key, raw)


class FakeMessage:
    def __init__(self, e: Envelope, error=None):
        self.e, self._error = e, error

    def error(self):
        return self._error

    def topic(self):
        return self.e.topic

    def partition(self):
        return self.e.partition

    def offset(self):
        return self.e.offset

    def key(self):
        return self.e.key

    def value(self):
        return self.e.value

    def timestamp(self):
        return TIMESTAMP_CREATE_TIME, 1_790_644_849_724


class FakeConsumer:
    """A broker with messages queued per call of consume(), and the commits it received."""

    def __init__(self, partitions: list[tuple[str, int]] | None = None):
        self.queue: list[FakeMessage] = []
        self.commits: list[list[TopicPartition]] = []
        self.committed_offsets: dict[tuple[str, int], int] = {}
        self.ends: dict[tuple[str, int], int] = {}
        self.partitions = partitions or [("gps.pings", 0)]
        self.callbacks = {}
        self.closed = False
        self.on_consume = None  # called before each consume(), to run a rebalance for instance

    def subscribe(self, topics, **callbacks):
        self.topics = topics
        self.callbacks = callbacks

    def send(self, *envelopes: Envelope) -> None:
        self.queue.extend(FakeMessage(e) for e in envelopes)
        for e in envelopes:
            key = (e.topic, e.partition)
            self.ends[key] = max(self.ends.get(key, 0), e.offset + 1)

    def consume(self, num_messages: int, timeout: float):
        if self.on_consume:
            self.on_consume()
        out, self.queue = self.queue[:num_messages], self.queue[num_messages:]
        return out

    def commit(self, offsets, asynchronous):
        assert asynchronous is False
        self.commits.append(offsets)
        for tp in offsets:
            self.committed_offsets[(tp.topic, tp.partition)] = tp.offset
        return offsets

    def assignment(self):
        return [TopicPartition(t, p) for t, p in self.partitions]

    def committed(self, partitions, timeout):
        return [
            TopicPartition(tp.topic, tp.partition, self.committed_offsets.get((tp.topic, tp.partition), -1001))
            for tp in partitions
        ]

    def get_watermark_offsets(self, tp, timeout, cached):
        return 0, self.ends.get((tp.topic, tp.partition), 0)

    def close(self):
        self.closed = True


@pytest.fixture
def fake_consumer() -> FakeConsumer:
    return FakeConsumer()
