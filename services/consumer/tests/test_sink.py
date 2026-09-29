"""The writes against the platform's TimescaleDB, in a scratch schema that copies the real tables.

The tables are created with LIKE from bronze and ops, so the tests see the columns and keys the
migrations made, and write nothing into the real ones. Skipped when the database is not reachable,
unless CONSUMER_TEST_REQUIRE_DB=1 (CI's compose job), which makes that a failure.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import psycopg
import pytest
from conftest import DELIVERED, FAILED, PING, SOURCES, TELEMETRY, envelope
from llobregat_consumer.config import Settings
from llobregat_consumer.messages import DeadLetter, Row, classify, parse
from llobregat_consumer.sink import Lag, Sink

pytestmark = pytest.mark.db

TABLES = {
    "gps_pings": "bronze",
    "vehicle_telemetry": "bronze",
    "delivery_events": "bronze",
    "dead_letters": "ops",
    "consumer_lag": "ops",
}


@pytest.fixture(scope="module")
def conninfo() -> str:
    conninfo = Settings.from_env().conninfo
    try:
        psycopg.connect(conninfo, connect_timeout=3).close()
    except psycopg.OperationalError as e:
        if os.environ.get("CONSUMER_TEST_REQUIRE_DB") == "1":
            raise
        pytest.skip(f"no database: {e}")
    return conninfo


@pytest.fixture
def sink(conninfo):
    schema = f"consumer_test_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(f"CREATE SCHEMA {schema}")
        for table, origin in TABLES.items():
            conn.execute(f"CREATE TABLE {schema}.{table} (LIKE {origin}.{table} INCLUDING ALL)")
    sink = Sink(conninfo, bronze=schema, ops=schema)
    sink.schema = schema
    yield sink
    sink.close()
    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")


def query(sink: Sink, sql: str, *params):
    with sink.connect().cursor() as cur:
        cur.execute(sql.replace("{s}", sink.schema), params)
        return cur.fetchall()


def batch():
    return [
        envelope("gps.pings", {**PING, "satellites": 9}, offset=0),
        envelope("vehicle.telemetry", TELEMETRY, offset=0),
        envelope("delivery.events", DELIVERED, offset=0),
        envelope("delivery.events", FAILED, offset=1),
        envelope("delivery.events", b"not json", offset=2),
    ]


def test_the_registered_sources_are_read(sink):
    assert SOURCES <= sink.sources()


def test_a_batch_is_written_with_every_field(sink):
    rows, dead = classify(batch(), sink.sources())
    written = sink.write(rows, dead)
    assert dict(written.inserted) == {"gps_pings": 1, "vehicle_telemetry": 1, "delivery_events": 2}
    assert [d.envelope.offset for d in written.dead_letters] == [2]
    ping = query(
        sink,
        "SELECT vehicle_id, route_id, lat, heading_deg, source, event_time, schema_version,"
        " extra_fields, ingested_at FROM {s}.gps_pings",
    )
    assert ping == [
        (
            "V-08",
            "R-20260928-Z02-M1",
            41.378359,
            134,
            "simulator/gps",
            datetime(2026, 9, 28, 6, 15, 5, tzinfo=UTC),
            1,
            {"satellites": 9},
            written.ingested_at,
        )
    ]
    telemetry = query(
        sink, "SELECT odometer_km, energy_used_total, readings, schema_version FROM {s}.vehicle_telemetry"
    )
    assert telemetry == [
        (Decimal("48213.4"), Decimal("9642.681"), {"charging": False, "tyre_pressure_bar": [4.81, 4.9, 5.02, 4.77]}, 1)
    ]
    events = query(
        sink,
        "SELECT event_id, status, failure_reason, pod_object_key, extra_fields"
        " FROM {s}.delivery_events ORDER BY event_time",
    )
    assert events == [
        (uuid.UUID(DELIVERED["event_id"]), "delivered", None, DELIVERED["pod_object_key"], None),
        (uuid.UUID(FAILED["event_id"]), "failed", "recipient_absent", None, None),
    ]


def test_a_replayed_batch_writes_nothing_twice(sink):
    rows, dead = classify(batch(), sink.sources())
    sink.write(rows, dead)
    before = query(
        sink,
        "SELECT (SELECT count(*) FROM {s}.gps_pings), (SELECT count(*) FROM {s}.vehicle_telemetry),"
        " (SELECT count(*) FROM {s}.delivery_events), (SELECT count(*) FROM {s}.dead_letters),"
        " (SELECT max(ingested_at) FROM {s}.delivery_events)",
    )
    again = sink.write(rows, dead)
    assert sum(again.inserted.values()) == 0
    assert dict(again.duplicates) == {"gps_pings": 1, "vehicle_telemetry": 1, "delivery_events": 2}
    assert len(again.rows) == 4  # already there counts as written
    after = query(
        sink,
        "SELECT (SELECT count(*) FROM {s}.gps_pings), (SELECT count(*) FROM {s}.vehicle_telemetry),"
        " (SELECT count(*) FROM {s}.delivery_events), (SELECT count(*) FROM {s}.dead_letters),"
        " (SELECT max(ingested_at) FROM {s}.delivery_events)",
    )
    assert after == before == [(1, 1, 2, 1, before[0][4])]


def test_the_same_key_twice_in_one_batch_is_written_once(sink):
    first = envelope("gps.pings", PING, offset=0)
    resent = envelope("gps.pings", {**PING, "lat": 41.0}, offset=1)  # same van and time, other offset
    written = sink.write([parse(first, SOURCES), parse(resent, SOURCES)], [])
    assert written.inserted["gps_pings"] == 1 and written.duplicates["gps_pings"] == 1
    assert query(sink, "SELECT lat FROM {s}.gps_pings") == [(41.378359,)]  # the first one stays


def test_a_dead_letter_keeps_the_raw_bytes_and_where_they_were(sink):
    raw = b"\xff\x00{not json"
    e = envelope("gps.pings", raw, partition=2, offset=77, key=b"V-\xff")
    e = type(e)(e.topic, e.partition, e.offset, e.key, e.value, datetime(2026, 9, 29, 1, 20, 49, tzinfo=UTC))
    sink.write([], [DeadLetter(e, "invalid_json", "not JSON: \x00 in the error too")])
    sink.write([], [DeadLetter(e, "invalid_json", "read again")])  # a replay records it once
    assert query(
        sink,
        "SELECT topic, kafka_partition, kafka_offset, kafka_timestamp, message_key, payload, reason,"
        " error, source FROM {s}.dead_letters",
    ) == [
        (
            "gps.pings",
            2,
            77,
            datetime(2026, 9, 29, 1, 20, 49, tzinfo=UTC),
            b"V-\xff",
            raw,
            "invalid_json",
            "not JSON: \\x00 in the error too",
            "consumer/dead_letters",
        )
    ]


def test_a_tombstone_is_recorded_without_a_payload(sink):
    sink.write(
        [], [DeadLetter(envelope("delivery.events", None, offset=5), "empty_message", "the message has no value")]
    )
    assert query(sink, "SELECT payload, reason FROM {s}.dead_letters") == [(None, "empty_message")]


def test_a_row_the_database_refuses_becomes_a_dead_letter_and_the_rest_is_written(sink):
    good = parse(envelope("gps.pings", PING, offset=0), SOURCES)
    # JSON may carry \u0000 but PostgreSQL's jsonb cannot store it: the parser lets it through.
    refused = parse(
        envelope("gps.pings", {**PING, "event_time": "2026-09-28T06:15:10Z", "note": "a\u0000b"}, offset=1), SOURCES
    )
    telemetry = parse(envelope("vehicle.telemetry", TELEMETRY, offset=0), SOURCES)
    overflow = Row(
        telemetry.envelope, telemetry.table, {**telemetry.values, "energy_level_pct": 1e300}, telemetry.event_time
    )  # past the range of a real: refused by the database
    written = sink.write([good, refused, overflow], [])
    assert dict(written.inserted) == {"gps_pings": 1}
    assert [(d.envelope.topic, d.envelope.offset, d.reason) for d in written.dead_letters] == [
        ("gps.pings", 1, "rejected_by_database"),
        ("vehicle.telemetry", 0, "rejected_by_database"),
    ]
    assert all(d.error.startswith("the database refused the row: ") for d in written.dead_letters)
    assert query(sink, "SELECT count(*) FROM {s}.gps_pings") == [(1,)]
    assert query(sink, "SELECT count(*) FROM {s}.vehicle_telemetry") == [(0,)]
    assert query(sink, "SELECT topic, kafka_offset, reason FROM {s}.dead_letters ORDER BY topic") == [
        ("gps.pings", 1, "rejected_by_database"),
        ("vehicle.telemetry", 0, "rejected_by_database"),
    ]


def test_the_lag_is_recorded_and_read_back_per_partition(sink):
    newest = datetime(2026, 9, 28, 21, 39, tzinfo=UTC)
    ingested = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)
    sink.record_lag("g", [Lag("gps.pings", 0, None, 100, 100, None, None), Lag("gps.pings", 1, 5, 9, 4, None, None)])
    sink.record_lag("g", [Lag("gps.pings", 0, 100, 100, 0, newest, ingested)])
    sink.record_lag("other", [Lag("gps.pings", 0, 1, 100, 99, None, None)])
    rows = query(
        sink,
        "SELECT consumer_group, topic, kafka_partition, committed_offset, end_offset, lag, source"
        " FROM {s}.consumer_lag ORDER BY consumer_group, kafka_partition, lag DESC",
    )
    assert rows == [
        ("g", "gps.pings", 0, None, 100, 100, "consumer/lag"),
        ("g", "gps.pings", 0, 100, 100, 0, "consumer/lag"),
        ("g", "gps.pings", 1, 5, 9, 4, "consumer/lag"),
        ("other", "gps.pings", 0, 1, 100, 99, "consumer/lag"),
    ]
    assert sink.last_positions("g") == {("gps.pings", 0): (newest, ingested), ("gps.pings", 1): (None, None)}
