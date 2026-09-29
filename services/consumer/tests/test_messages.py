"""Parsing and validation of each topic's messages: what becomes a row, and what a dead letter."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from conftest import DELIVERED, FAILED, PING, SOURCES, TELEMETRY, envelope
from llobregat_consumer.messages import (
    DELIVERY_EVENTS,
    GPS_PINGS,
    TOPICS,
    VEHICLE_TELEMETRY,
    Invalid,
    classify,
    parse,
)


def reason_of(topic: str, value, sources=SOURCES) -> str:
    with pytest.raises(Invalid) as caught:
        parse(envelope(topic, value), sources)
    return caught.value.reason


def without(message: dict, *names: str) -> dict:
    return {k: v for k, v in message.items() if k not in names}


# -- valid messages: every field is kept ------------------------------------------------------------


def test_a_ping_becomes_a_gps_pings_row_with_every_field():
    row = parse(envelope("gps.pings", PING), SOURCES)
    assert row.table == "gps_pings"
    assert list(row.values) == list(GPS_PINGS.columns)
    assert row.values == {
        "vehicle_id": "V-08",
        "route_id": "R-20260928-Z02-M1",
        "lat": 41.378359,
        "lon": 2.159104,
        "speed_kmh": 14.6,
        "heading_deg": 134,
        "accuracy_m": 6.0,
        "source": "simulator/gps",
        "event_time": datetime(2026, 9, 28, 6, 15, 5, tzinfo=UTC),
        "schema_version": 1,
        "extra_fields": None,
    }
    assert row.event_time == datetime(2026, 9, 28, 6, 15, 5, tzinfo=UTC)


def test_a_ping_at_the_hub_has_no_route():
    row = parse(envelope("gps.pings", without(PING, "route_id")), SOURCES)
    assert row.values["route_id"] is None


def test_telemetry_keeps_the_type_specific_sensors_in_readings():
    row = parse(envelope("vehicle.telemetry", TELEMETRY), SOURCES)
    assert row.table == "vehicle_telemetry"
    assert list(row.values) == list(VEHICLE_TELEMETRY.columns)
    assert row.values["readings"] == {"charging": False, "tyre_pressure_bar": [4.81, 4.9, 5.02, 4.77]}
    assert row.values["odometer_km"] == Decimal("48213.4")  # numeric columns get the decimal that was sent
    assert row.values["energy_used_total"] == Decimal("9642.681")
    assert row.values["ignition_on"] is True and row.values["cargo_door_open"] is False
    assert row.values["schema_version"] == 1


def test_telemetry_without_sensors_has_empty_readings():
    row = parse(envelope("vehicle.telemetry", without(TELEMETRY, "charging", "tyre_pressure_bar")), SOURCES)
    assert row.values["readings"] == {}


def test_a_delivered_and_a_failed_scan_become_delivery_events_rows():
    delivered = parse(envelope("delivery.events", DELIVERED), SOURCES)
    failed = parse(envelope("delivery.events", FAILED), SOURCES)
    assert delivered.table == failed.table == "delivery_events"
    assert list(delivered.values) == list(DELIVERY_EVENTS.columns)
    assert delivered.values["event_id"] == uuid.UUID(DELIVERED["event_id"])
    assert delivered.values["pod_object_key"] == "pod/2026-09-28/O-20260928-01152.jpg"
    assert delivered.values["failure_reason"] is None
    assert failed.values["failure_reason"] == "recipient_absent"
    assert failed.values["pod_object_key"] is None


def test_a_field_without_a_column_is_kept_in_extra_fields():
    row = parse(envelope("gps.pings", {**PING, "satellites": 9, "hdop": {"x": 0.8}}), SOURCES)
    assert row.values["extra_fields"] == {"satellites": 9, "hdop": {"x": 0.8}}
    row = parse(envelope("delivery.events", {**FAILED, "photo_attempts": 2}), SOURCES)
    assert row.values["extra_fields"] == {"photo_attempts": 2}
    row = parse(envelope("vehicle.telemetry", {**TELEMETRY, "cabin_temp_c": 21.5}), SOURCES)
    assert row.values["readings"]["cabin_temp_c"] == 21.5


def test_values_are_not_judged_in_bronze():
    """A ping in the sea, a negative speed, an unknown status: stored as they arrived, silver judges them."""
    odd = {**PING, "lat": 0.0, "lon": -200.5, "speed_kmh": -3, "heading_deg": 720}
    assert parse(envelope("gps.pings", odd), SOURCES).values["heading_deg"] == 720
    row = parse(envelope("delivery.events", {**DELIVERED, "status": "teleported", "stop_sequence": -1}), SOURCES)
    assert row.values["status"] == "teleported"


def test_the_order_of_keys_and_integral_floats_do_not_matter():
    shuffled = dict(reversed(list({**PING, "heading_deg": 134.0}.items())))
    assert parse(envelope("gps.pings", shuffled), SOURCES).values == parse(envelope("gps.pings", PING), SOURCES).values


def test_event_time_in_another_offset_is_the_same_moment():
    row = parse(envelope("gps.pings", {**PING, "event_time": "2026-09-28T08:15:05+02:00"}), SOURCES)
    assert row.event_time == datetime(2026, 9, 28, 6, 15, 5, tzinfo=UTC)


# -- dead letters ---------------------------------------------------------------------------------


@pytest.mark.parametrize("topic", list(TOPICS))
def test_what_is_not_a_json_object_is_a_dead_letter(topic):
    assert reason_of(topic, None) == "empty_message"
    assert reason_of(topic, b"") == "empty_message"
    assert reason_of(topic, b"not json") == "invalid_json"
    assert reason_of(topic, b'{"vehicle_id": "V-08",') == "invalid_json"
    assert reason_of(topic, b"\xff\xfe\x00garbage") == "invalid_json"
    assert reason_of(topic, b'{"lat": NaN}') == "invalid_json"  # not JSON, though Python would read it
    assert reason_of(topic, b"[1, 2]") == "not_an_object"
    assert reason_of(topic, b'"V-08"') == "not_an_object"


@pytest.mark.parametrize(
    ("topic", "message", "key_fields"),
    [
        ("gps.pings", PING, ["vehicle_id", "event_time", "source", "schema_version"]),
        ("vehicle.telemetry", TELEMETRY, ["vehicle_id", "event_time", "source", "schema_version"]),
        ("delivery.events", DELIVERED, ["event_id", "order_id", "event_time", "source", "schema_version"]),
    ],
)
def test_a_message_without_a_key_field_is_a_dead_letter(topic, message, key_fields):
    for name in key_fields:
        assert reason_of(topic, without(message, name)) == "missing_field", name
        assert reason_of(topic, {**message, name: None}) == "missing_field", name
        assert reason_of(topic, {**message, name: ""}) == "missing_field", name


def test_every_missing_key_field_is_named():
    with pytest.raises(Invalid, match="^missing vehicle_id, event_time$"):
        parse(envelope("gps.pings", without(PING, "event_time", "vehicle_id")), SOURCES)


def test_a_missing_field_that_is_not_a_key_is_null():
    row = parse(envelope("delivery.events", without(DELIVERED, "vehicle_id", "lat", "lon", "status")), SOURCES)
    assert row.values["vehicle_id"] is None and row.values["status"] is None


@pytest.mark.parametrize("version", [2, 0, "1", True, [1], 1.5])
def test_an_unknown_schema_version_is_a_dead_letter(version):
    assert reason_of("gps.pings", {**PING, "schema_version": version}) == "unsupported_schema_version"


@pytest.mark.parametrize(
    ("topic", "message", "field", "value"),
    [
        ("gps.pings", PING, "lat", "41.37"),
        ("gps.pings", PING, "speed_kmh", True),
        ("gps.pings", PING, "heading_deg", 134.5),
        ("gps.pings", PING, "heading_deg", 40000),
        ("gps.pings", PING, "speed_kmh", 1e39),
        ("gps.pings", PING, "vehicle_id", 8),
        ("gps.pings", PING, "route_id", "R-1\u0000"),
        ("gps.pings", PING, "event_time", "yesterday"),
        ("gps.pings", PING, "event_time", "2026-09-28T06:15:05"),  # no time zone
        ("gps.pings", PING, "event_time", 1790644849),
        ("vehicle.telemetry", TELEMETRY, "ignition_on", 1),
        ("vehicle.telemetry", TELEMETRY, "odometer_km", 123456789.0),  # numeric(9,1)
        ("vehicle.telemetry", TELEMETRY, "energy_used_total", "9642.681"),
        ("delivery.events", DELIVERED, "event_id", "e6097e9f"),
        ("delivery.events", DELIVERED, "stop_sequence", "1"),
        ("delivery.events", DELIVERED, "lat", [41.38]),
    ],
)
def test_a_value_its_column_cannot_hold_is_a_dead_letter(topic, message, field, value):
    with pytest.raises(Invalid) as caught:
        parse(envelope(topic, {**message, field: value}), SOURCES)
    assert caught.value.reason == "invalid_field"
    assert str(caught.value).startswith(f"{field}: ")


def test_every_bad_field_is_named():
    with pytest.raises(Invalid, match=r"lat: expected a number, got a string; heading_deg: expected an integer"):
        parse(envelope("gps.pings", {**PING, "lat": "x", "heading_deg": "y"}), SOURCES)


def test_a_source_that_is_not_registered_is_a_dead_letter():
    assert reason_of("gps.pings", {**PING, "source": "simulator/drone"}) == "unknown_source"
    assert reason_of("gps.pings", PING, sources=set()) == "unknown_source"


def test_a_topic_without_a_table_is_a_dead_letter():
    assert reason_of("orders.created", PING) == "unknown_topic"


def test_classify_splits_a_batch_and_keeps_where_each_message_was():
    batch = [
        envelope("gps.pings", PING, partition=2, offset=10),
        envelope("gps.pings", b"not json", partition=2, offset=11),
        envelope("delivery.events", DELIVERED, partition=1, offset=3),
        envelope("vehicle.telemetry", {**TELEMETRY, "schema_version": 9}, partition=0, offset=7),
    ]
    rows, dead = classify(batch, SOURCES)
    assert [(r.table, r.envelope.offset) for r in rows] == [("gps_pings", 10), ("delivery_events", 3)]
    assert [(d.envelope.topic, d.envelope.partition, d.envelope.offset, d.reason) for d in dead] == [
        ("gps.pings", 2, 11, "invalid_json"),
        ("vehicle.telemetry", 0, 7, "unsupported_schema_version"),
    ]
    assert dead[0].envelope.value == b"not json"  # the raw bytes travel with the dead letter


def test_the_simulator_messages_in_the_classification_document_parse():
    """The two scans quoted in docs/phases/2-classification.md, byte for byte as JSON."""
    for message in (DELIVERED, FAILED):
        text = json.dumps(message, separators=(",", ":")).encode()
        assert parse(envelope("delivery.events", text), SOURCES).values["order_id"] == message["order_id"]
