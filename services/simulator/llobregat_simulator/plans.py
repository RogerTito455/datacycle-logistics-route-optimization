"""Route plans in the bronze layer: the baseline plan written by the planner, read back by the simulator."""

from __future__ import annotations

from datetime import date

import psycopg
from llobregat_generator import db, publish
from llobregat_generator.rules import Wave
from psycopg.rows import dict_row

from llobregat_simulator.company import DEFAULT_GEOFENCE_M, Company, Order
from llobregat_simulator.planner import PLAN_VERSION, PLANNER, REPLAN_REASON, SOURCE_ID, Route, Stop, WavePlan

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


def read_plan(conn: psycopg.Connection, service_date: date, waves: list[Wave], company: Company) -> list[Route]:
    """The baseline plan of the date's waves, with each stop's order, in order of departure.

    The simulator drives version 0. When the optimizer (issue #16) writes re-plans, this is where
    a van would pick up the latest version of its route between stops.
    """
    with conn.cursor(row_factory=dict_row) as cur:
        rows = cur.execute(
            """SELECT p.route_id, p.wave AS route_wave, p.zone_id, p.vehicle_id, p.driver_id,
                      p.planned_departure, p.planned_completion,
                      s.stop_sequence, s.planned_arrival, s.leg_distance_km, s.leg_duration_s,
                      s.window_start AS promised_start, s.window_end AS promised_end,
                      o.order_id, o.destination_lat, o.destination_lon, o.destination_zone_id, o.parcels,
                      o.parcel_size, o.customer_type, o.wave, o.window_type, o.window_start, o.window_end, o.note_id
               FROM bronze.route_plans p
               JOIN bronze.route_plan_stops s USING (route_id, plan_version)
               JOIN bronze.orders o ON o.order_id = s.order_id
               WHERE p.service_date = %s AND p.plan_version = %s AND p.source = %s AND p.wave = ANY(%s)
               ORDER BY p.planned_departure, p.route_id, s.stop_sequence""",
            (service_date, PLAN_VERSION, SOURCE_ID, [w.value for w in waves]),
        ).fetchall()
    vans = {v.vehicle_id: v for v in company.vehicles}
    routes: dict[str, Route] = {}
    for row in rows:
        if row["vehicle_id"] not in vans:
            raise PlanError(f"{row['route_id']} is planned for {row['vehicle_id']}, which is not in the fleet register")
        route = routes.get(row["route_id"])
        if route is None:
            route = routes[row["route_id"]] = Route(
                row["route_id"],
                Wave(row["route_wave"]),
                row["zone_id"],
                vans[row["vehicle_id"]],
                row["planned_departure"],
                [],
                row["planned_completion"],
                row["driver_id"],
            )
        order = Order.from_row(row)
        route.stops.append(
            Stop(
                order,
                row["stop_sequence"],
                row["planned_arrival"],
                float(row["leg_distance_km"] or 0) * 1000,
                float(row["leg_duration_s"] or 0),
                row["promised_start"] or order.window_start,
                row["promised_end"] or order.window_end,
            )
        )
    return list(routes.values())


def waves_of(name: str) -> list[Wave]:
    return list(Wave) if name == "all" else [Wave(name)]
