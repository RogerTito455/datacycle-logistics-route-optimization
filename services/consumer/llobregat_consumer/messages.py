"""What the three topics carry, and how a message becomes a bronze row or a dead letter.

Bronze is raw: a message is only turned away when it cannot be stored as a row at all. That is
when it is not a JSON object, lacks a key field (the table's primary key, `source`, `event_time`
or `schema_version`), has a `schema_version` this consumer does not know, names a source that is
not registered in `ops.data_sources`, or holds a value of a type its column cannot take (text
where a number goes, 134.5 where an integer goes). A value that only looks wrong (a ping outside
Catalonia, an unknown status) is stored as it arrived; silver judges it.

Every field of the message is kept: the fields with a column go to that column, the others to a
JSON column, `readings` for telemetry (the sensors of each vehicle type) and `extra_fields` for
pings and scans.
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Callable, Container, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

# The reason of a dead letter: a short code for dashboards; the error text says the rest.
EMPTY_MESSAGE = "empty_message"
INVALID_JSON = "invalid_json"
NOT_AN_OBJECT = "not_an_object"
MISSING_FIELD = "missing_field"
UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
INVALID_FIELD = "invalid_field"
UNKNOWN_SOURCE = "unknown_source"
UNKNOWN_TOPIC = "unknown_topic"
REJECTED_BY_DATABASE = "rejected_by_database"


class Invalid(Exception):
    """A message that cannot become a row."""

    def __init__(self, reason: str, error: str):
        super().__init__(error)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Envelope:
    """A message as the consumer read it: where it was in the topic, and its bytes."""

    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None
    timestamp: datetime | None = None  # the broker's timestamp of the message


@dataclass(frozen=True, slots=True)
class Row:
    envelope: Envelope
    table: str
    values: dict[str, Any]  # column: value, in the order of Table.columns
    event_time: datetime


@dataclass(frozen=True, slots=True)
class DeadLetter:
    envelope: Envelope
    reason: str
    error: str


# Converters from a JSON value (never None) to what the column stores. They raise ValueError.
Kind = Callable[[Any], Any]


def _json_type(value: Any) -> str:
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "an array"
    return "an object"


def text(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(f"expected a string, got {_json_type(value)}")
    if "\x00" in value:
        raise ValueError("contains a NUL character, which PostgreSQL text cannot hold")
    return value


def double(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"expected a number, got {_json_type(value)}")
    return float(value)


REAL_MAX = 3.4028234663852886e38


def real(value: Any) -> float:
    number = double(value)
    if math.isfinite(number) and abs(number) > REAL_MAX:
        raise ValueError(f"{number} is out of the range of a real")
    return number


def smallint(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"expected an integer, got {_json_type(value)}")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"expected an integer, got {value}")
        value = int(value)
    if not -32768 <= value <= 32767:
        raise ValueError(f"{value} is out of the range of a smallint")
    return value


def numeric(precision: int, scale: int) -> Kind:
    """numeric(precision, scale): PostgreSQL rounds to the scale and refuses what does not fit."""
    limit = Decimal(10) ** (precision - scale)

    def convert(value: Any) -> Decimal:
        number = double(value)  # the type check
        if not math.isfinite(number):
            raise ValueError(f"{value} does not fit numeric({precision},{scale})")
        exact = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
        if abs(round(exact, scale)) >= limit:
            raise ValueError(f"{value} does not fit numeric({precision},{scale})")
        return exact

    return convert


def boolean(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"expected true or false, got {_json_type(value)}")
    return value


def uuid_(value: Any) -> uuid.UUID:
    try:
        return uuid.UUID(text(value))
    except ValueError as e:
        raise ValueError(f"expected a UUID: {e}") from None


def timestamptz(value: Any) -> datetime:
    moment = datetime.fromisoformat(text(value))
    if moment.tzinfo is None:
        raise ValueError("an ISO 8601 time without a time zone; UTC must be explicit (Z or +00:00)")
    return moment


@dataclass(frozen=True)
class Table:
    """A bronze table fed by a topic: the message fields it has a column for, and its key fields."""

    name: str
    fields: Mapping[str, Kind]  # field name = column name, in column order
    required: tuple[str, ...]
    extras: str  # the JSON column for the fields without a column of their own
    extras_when_none: dict | None  # what that column holds when there are none

    @property
    def columns(self) -> tuple[str, ...]:
        return (*self.fields, self.extras)


METADATA = {"source": text, "event_time": timestamptz, "schema_version": smallint}

GPS_PINGS = Table(
    name="gps_pings",
    fields={
        "vehicle_id": text,
        "route_id": text,
        "lat": double,
        "lon": double,
        "speed_kmh": real,
        "heading_deg": smallint,
        "accuracy_m": real,
        **METADATA,
    },
    required=("vehicle_id", *METADATA),
    extras="extra_fields",
    extras_when_none=None,
)

VEHICLE_TELEMETRY = Table(
    name="vehicle_telemetry",
    fields={
        "vehicle_id": text,
        "route_id": text,
        "speed_kmh": real,
        "odometer_km": numeric(9, 1),
        "ignition_on": boolean,
        "energy_level_pct": real,
        "energy_used_total": numeric(10, 3),
        "energy_unit": text,
        "cargo_door_open": boolean,
        **METADATA,
    },
    required=("vehicle_id", *METADATA),
    extras="readings",  # charging, tyre_pressure_bar, engine_rpm, adblue_level_pct, cng_tank_pressure_bar
    extras_when_none={},
)

DELIVERY_EVENTS = Table(
    name="delivery_events",
    fields={
        "event_id": uuid_,
        "order_id": text,
        "route_id": text,
        "stop_sequence": smallint,
        "vehicle_id": text,
        "driver_id": text,
        "status": text,
        "failure_reason": text,
        "lat": double,
        "lon": double,
        "pod_object_key": text,
        **METADATA,
    },
    required=("event_id", "order_id", *METADATA),
    extras="extra_fields",
    extras_when_none=None,
)

TOPICS: dict[str, Table] = {
    "gps.pings": GPS_PINGS,
    "vehicle.telemetry": VEHICLE_TELEMETRY,
    "delivery.events": DELIVERY_EVENTS,
}


def _reject_constant(name: str) -> None:
    raise ValueError(f"{name} is not valid JSON")


def parse(envelope: Envelope, sources: Container[str]) -> Row:
    """The row a message becomes, or Invalid saying why it cannot become one."""
    table = TOPICS.get(envelope.topic)
    if table is None:
        raise Invalid(UNKNOWN_TOPIC, f"no bronze table is fed by topic {envelope.topic}")
    if not envelope.value:
        raise Invalid(EMPTY_MESSAGE, "the message has no value")
    try:
        data = json.loads(envelope.value, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as e:
        raise Invalid(INVALID_JSON, f"not JSON: {e}") from None
    if not isinstance(data, dict):
        raise Invalid(NOT_AN_OBJECT, f"expected a JSON object, got {_json_type(data)}")

    missing = [name for name in table.required if data.get(name) is None or data.get(name) == ""]
    if missing:
        raise Invalid(MISSING_FIELD, f"missing {', '.join(missing)}")
    version = data["schema_version"]
    if isinstance(version, bool) or not isinstance(version, (int, float)) or version not in SUPPORTED_SCHEMA_VERSIONS:
        known = ", ".join(map(str, sorted(SUPPORTED_SCHEMA_VERSIONS)))
        raise Invalid(
            UNSUPPORTED_SCHEMA_VERSION, f"schema_version {json.dumps(version)} is not supported (known: {known})"
        )

    values: dict[str, Any] = {}
    errors = []
    for name, kind in table.fields.items():
        value = data.get(name)
        if value is None:
            values[name] = None
            continue
        try:
            values[name] = kind(value)
        except ValueError as e:
            errors.append(f"{name}: {e}")
    if errors:
        raise Invalid(INVALID_FIELD, "; ".join(errors))
    extras = {name: value for name, value in data.items() if name not in table.fields}
    values[table.extras] = extras or table.extras_when_none

    if values["source"] not in sources:
        raise Invalid(UNKNOWN_SOURCE, f"source {values['source']} is not registered in ops.data_sources")
    return Row(envelope, table.name, values, values["event_time"])


def classify(envelopes: list[Envelope], sources: Container[str]) -> tuple[list[Row], list[DeadLetter]]:
    """Split a batch into the rows to write and the dead letters."""
    rows, dead = [], []
    for envelope in envelopes:
        try:
            rows.append(parse(envelope, sources))
        except Invalid as e:
            dead.append(DeadLetter(envelope, e.reason, str(e)))
    return rows, dead
