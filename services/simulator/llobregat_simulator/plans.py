"""Route plans in the bronze layer: the baseline plan written by the planner, read back by the simulator."""

from __future__ import annotations

from datetime import date

import psycopg
from llobregat_generator import db, publish
from llobregat_generator.rules import Wave

from llobregat_simulator.company import DEFAULT_GEOFENCE_M, Order
from llobregat_simulator.planner import PLAN_VERSION, PLANNER, REPLAN_REASON, SOURCE_ID, WavePlan

PLAN_COLUMNS = (
    "route_id",
    "plan_version",
    "planner",
    "replan_reason",
    "service_date",
    "wave",
    "zone_id",
    "vehicle_id",
    "driver_id",
    "stops",
    "planned_departure",
    "planned_completion",
    "planned_distance_km",
    "source",
    "event_time",
)
STOP_COLUMNS = (
    "route_id",
    "plan_version",
    "stop_sequence",
    "order_id",
    "planned_arrival",
    "leg_distance_km",
    "leg_duration_s",
    "window_start",
    "window_end",
    "source",
    "event_time",
)


class PlanError(RuntimeError):
    """The plan cannot be written or read as asked."""


def read_orders(conn: psycopg.Connection, service_date: date) -> list[Order]:
    """The generated orders of the date, from bronze.orders."""
    return [Order.from_row(row) for row in publish.read_day(conn, service_date)]


def read_geofence(conn: psycopg.Connection, hub_id: str) -> int:
    """The hub's geofence radius in metres (bronze.hubs, migration 007)."""
    row = conn.execute("SELECT geofence_radius_m FROM bronze.hubs WHERE hub_id = %s", (hub_id,)).fetchone()
    return row[0] if row and row[0] is not None else DEFAULT_GEOFENCE_M


def write_plans(conn: psycopg.Connection, service_date: date, plans: list[WavePlan]) -> int:
    """Replace the baseline plan of the date's waves in one transaction; return the routes replaced.

    Bronze is write-once, and this is its one other exception after the order generator: planning
    a date again replaces its baseline plan (source planner/baseline, version 0), so a date never has
    two. It refuses when the optimizer has re-planned a route of those waves, whose versions build on
    the baseline.
    """
    waves = [p.wave.value for p in plans]
    with conn.transaction():
        replans = conn.execute(
            "SELECT count(*) FROM bronze.route_plans WHERE service_date = %s AND wave = ANY(%s) AND plan_version > 0",
            (service_date, waves),
        ).fetchone()[0]
        if replans:
            raise PlanError(
                f"{service_date} has {replans} re-plans of the optimizer in bronze.route_plans; "
                "the baseline plan they build on is not replaced"
            )
        old = "SELECT route_id FROM bronze.route_plans WHERE service_date = %s AND wave = ANY(%s) AND source = %s"
        params = (service_date, waves, SOURCE_ID)
        conn.execute(f"DELETE FROM bronze.route_plan_stops WHERE plan_version = 0 AND route_id IN ({old})", params)
        replaced = conn.execute(f"DELETE FROM bronze.route_plans WHERE route_id IN ({old})", params).rowcount
        plan_rows, stop_rows = [], []
        for plan in plans:
            for r in plan.routes:
                plan_rows.append(
                    (
                        r.route_id,
                        PLAN_VERSION,
                        PLANNER,
                        REPLAN_REASON,
                        service_date,
                        r.wave.value,
                        r.zone_id,
                        r.vehicle.vehicle_id,
                        r.driver_id,
                        len(r.stops),
                        r.departure,
                        r.completion,
                        round(r.distance_m / 1000, 2),
                        SOURCE_ID,
                        plan.planned_at,
                    )
                )
                stop_rows += [
                    (
                        r.route_id,
                        PLAN_VERSION,
                        s.sequence,
                        s.order.order_id,
                        s.arrival,
                        round(s.leg_distance_m / 1000, 2),
                        round(s.leg_duration_s),
                        s.window_start,
                        s.window_end,
                        SOURCE_ID,
                        plan.planned_at,
                    )
                    for s in r.stops
                ]
        db.copy_rows(conn, "bronze.route_plans", PLAN_COLUMNS, plan_rows)
        db.copy_rows(conn, "bronze.route_plan_stops", STOP_COLUMNS, stop_rows)
    return replaced


def waves_of(name: str) -> list[Wave]:
    return list(Wave) if name == "all" else [Wave(name)]
