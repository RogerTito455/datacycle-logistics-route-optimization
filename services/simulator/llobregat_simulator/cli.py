"""Command line of the simulator.

llobregat-simulator plan --date D [--wave all|morning|afternoon]
                    simulate --date D [--speed 60] [--wave all|morning|afternoon] [--seed N]
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from heapq import merge

import psycopg
from llobregat_generator import db, pod
from llobregat_generator.metadata import FileMetadata
from llobregat_generator.orders import LOCAL_TZ
from llobregat_generator.seeds import Seeds
from llobregat_generator.storage import Bucket

from llobregat_simulator.behaviour import note_labels
from llobregat_simulator.company import Company
from llobregat_simulator.config import SimulatorSettings
from llobregat_simulator.osrm import Osrm, OsrmError
from llobregat_simulator.planner import WavePlan, plan_wave
from llobregat_simulator.plans import PlanError, read_geofence, read_orders, read_plan, waves_of, write_plans
from llobregat_simulator.stream import KafkaSink, Pacer, Tally, publish
from llobregat_simulator.traffic import TimeOfDayProfile
from llobregat_simulator.van import drive_day


def _hm(seconds: float) -> str:
    return f"{int(seconds // 3600)} h {int(seconds % 3600 // 60):02d} min"


def report(plan: WavePlan, company: Company) -> str:
    """What a wave's plan looks like: size, load, length, and how well the vans fit their zones."""
    routes = plan.routes
    lines = [f"Baseline plan of {plan.service_date}, {plan.wave.value} wave (planned at {plan.planned_at:%H:%M})"]
    if not routes:
        return lines[0] + ": no orders"
    stops = sum(len(r.stops) for r in routes)
    parcels = sum(r.parcels for r in routes)
    capacity = sum(r.vehicle.capacity for r in routes)
    lengths = [(r.completion - r.departure).total_seconds() for r in routes]
    home = sum(1 for r in routes for s in r.stops if s.order.zone_id == r.vehicle.home_zone_id)
    drivers = {d.driver_id: d for d in company.drivers}
    known = sum(1 for r in routes if r.driver_id and r.zone_id in drivers[r.driver_id].zones)
    held = len(plan.held)
    lines += [
        f"  {len(routes)} routes; {stops:,} of {stops + held:,} orders planned, {parcels:,} parcels; "
        f"{held:,} held at the hub ({sum(o.parcels for o in plan.held):,} parcels)",
        f"  stops per route {stops / len(routes):.0f} (from {min(len(r.stops) for r in routes)} to "
        f"{max(len(r.stops) for r in routes)}); load {parcels / capacity:.0%} of the vans' capacity",
        f"  planned length, hub departure to the end of the last stop: {_hm(sum(lengths) / len(lengths))} on average, "
        f"longest {_hm(max(lengths))}; {sum(1 for x in lengths if x > company.max_route_min * 60)} routes over the "
        f"{company.max_route_min}-minute maximum; {sum(r.distance_m for r in routes) / 1000:,.0f} km to the last stops",
        f"  {home:,} of {stops:,} stops ({home / stops:.0%}) served by a van of their zone; "
        f"{known} of {len(routes)} drivers know their route's zone",
        "  vans: " + ", ".join(f"{t} {n}" for t, n in sorted(Counter(r.vehicle.type.type_id for r in routes).items())),
        "",
        f"  {'route':<20}{'van':<7}{'type':<7}{'driver':<7}{'stops':>6}{'parcels':>8}{'cap':>5}"
        f"{'leaves':>10}{'ends':>7}{'km':>6}",
    ]
    for r in routes:
        lines.append(
            f"  {r.route_id:<20}{r.vehicle.vehicle_id:<7}{r.vehicle.type.type_id:<7}{r.driver_id or '-':<7}"
            f"{len(r.stops):>6}{r.parcels:>8}{r.vehicle.capacity:>5}"
            f"{r.departure.astimezone(LOCAL_TZ).strftime('%H:%M:%S'):>10}"
            f"{r.completion.astimezone(LOCAL_TZ).strftime('%H:%M'):>7}{r.distance_m / 1000:>6.1f}"
        )
    return "\n".join(lines)


def cmd_plan(settings: SimulatorSettings, args: argparse.Namespace) -> int:
    seeds = Seeds.load(settings.base.seed_dir)
    osrm = Osrm(settings.osrm_url)
    with db.connect(settings.base) as conn:
        company = Company.from_seeds(seeds)
        company = Company.from_seeds(seeds, read_geofence(conn, company.hub.hub_id))
        orders = read_orders(conn, args.date)
        if not orders:
            print(f"no generated orders for {args.date} in bronze.orders; run make generate first", file=sys.stderr)
            return 1
        plans = [plan_wave(args.date, wave, orders, company, osrm.table) for wave in waves_of(args.wave)]
        replaced = write_plans(conn, args.date, plans)
    for plan in plans:
        print(report(plan, company))
        print()
    routes = sum(len(p.routes) for p in plans)
    print(
        f"bronze.route_plans: {routes} routes written, bronze.route_plan_stops: "
        f"{sum(len(r.stops) for p in plans for r in p.routes):,} stops"
        + (f"; {replaced} routes of an earlier plan replaced" if replaced else "")
    )
    return 0


def _clock(t: float) -> str:
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}"


def cmd_simulate(settings: SimulatorSettings, args: argparse.Namespace) -> int:
    seeds = Seeds.load(settings.base.seed_dir)
    with db.connect(settings.base) as conn:
        company = Company.from_seeds(seeds)
        company = Company.from_seeds(seeds, read_geofence(conn, company.hub.hub_id))
        routes = read_plan(conn, args.date, waves_of(args.wave), company)
        if not routes:
            print(f"no baseline plan for {args.date} in bronze.route_plans; run make plan first", file=sys.stderr)
            return 1
        photo_metadata = FileMetadata.for_table(conn, pod.TABLE, pod.SOURCE_ID, datetime.now(UTC))

    osrm = Osrm(settings.osrm_url)
    roads = {r.route_id: osrm.route([company.hub, *(s.order for s in r.stops), company.hub]) for r in routes}
    by_van = defaultdict(list)
    for route in routes:
        by_van[route.vehicle.vehicle_id].append(route)
    notes = note_labels(seeds.delivery_notes)
    days = [
        drive_day(args.date, vans[0].vehicle, vans, roads, company, seeds.demand, notes, TimeOfDayProfile(), args.seed)
        for _, vans in sorted(by_van.items())
    ]
    start, end = min(d.start for d in days), max(d.end for d in days)
    wall = f", about {(end - start) / args.speed / 60:.0f} min at {args.speed:g}x" if args.speed > 0 else ""
    print(
        f"Simulating {len(routes)} routes of {args.date} with {len(days)} vans (seed {args.seed}): "
        f"{_clock(start)} to {_clock(end)} of simulated time{wall}"
    )

    bucket = Bucket(settings.base)

    def store(delivery: pod.Delivery) -> str:
        return pod.upload(bucket, delivery, dataclasses.replace(photo_metadata, ingested_at=datetime.now(UTC)))

    sink = KafkaSink(settings.kafka_bootstrap)
    pacer, tally = Pacer(args.speed), Tally.of(routes, company.hub, args.date)
    report_at = [start - start % 1800 + 1800]
    began = time.monotonic()

    def progress(t: int) -> None:
        if t >= report_at[0]:
            counts = ", ".join(f"{topic} {n:,}" for topic, n in sorted(tally.counts.items()))
            print(f"  {_clock(report_at[0])}  {counts}; {pacer.behind:.1f} s behind", flush=True)
            report_at[0] = t - t % 1800 + 1800

    publish(merge(*(d.messages() for d in days), key=lambda m: m.t), sink, store, pacer, tally, progress)
    sink.close()
    print(f"Done in {(time.monotonic() - began) / 60:.1f} min of wall-clock time.")
    print(tally.report())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llobregat-simulator",
        description="The daily operation of Llobregat Express: the baseline route plan and the vans that drive it.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="make the baseline route plan of a service date")
    plan.add_argument("--date", required=True, type=date.fromisoformat, help="service date, YYYY-MM-DD")
    plan.add_argument("--wave", choices=["all", "morning", "afternoon"], default="all", help="default: all")
    plan.set_defaults(run=cmd_plan)
    simulate = commands.add_parser(
        "simulate", help="drive the baseline plan of a date: GPS pings, telemetry and handheld scans to Redpanda"
    )
    simulate.add_argument("--date", required=True, type=date.fromisoformat, help="service date, YYYY-MM-DD")
    simulate.add_argument(
        "--speed", type=float, default=60, help="simulated seconds per wall-clock second (default 60; 0: no waiting)"
    )
    simulate.add_argument("--wave", choices=["all", "morning", "afternoon"], default="all", help="default: all")
    simulate.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    simulate.set_defaults(run=cmd_simulate)
    args = parser.parse_args(argv)

    settings = SimulatorSettings.from_env()
    try:
        return args.run(settings, args)
    except (PlanError, OsrmError, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(
            f"cannot reach TimescaleDB at {settings.base.postgres_host}:{settings.base.postgres_port} ({exc}); "
            "start the platform with `make up`",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
