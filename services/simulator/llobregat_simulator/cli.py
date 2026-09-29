"""Command line of the simulator.

llobregat-simulator plan --date D [--wave all|morning|afternoon]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date

import psycopg
from llobregat_generator import db
from llobregat_generator.orders import LOCAL_TZ
from llobregat_generator.seeds import Seeds

from llobregat_simulator.company import Company
from llobregat_simulator.config import SimulatorSettings
from llobregat_simulator.osrm import Osrm, OsrmError
from llobregat_simulator.planner import WavePlan, plan_wave
from llobregat_simulator.plans import PlanError, read_geofence, read_orders, waves_of, write_plans


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
    args = parser.parse_args(argv)

    settings = SimulatorSettings.from_env()
    try:
        return args.run(settings, args)
    except (PlanError, OsrmError) as exc:
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
