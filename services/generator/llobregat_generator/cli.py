"""Command line: llobregat-generator load-reference | orders --date D [--seed N] | summary --date D."""

from __future__ import annotations

import argparse
import sys
from datetime import date

import psycopg

from llobregat_generator import db, publish
from llobregat_generator.config import Settings
from llobregat_generator.orders import NoServiceError, generate_day
from llobregat_generator.reference import load_reference
from llobregat_generator.seeds import Seeds
from llobregat_generator.storage import Bucket
from llobregat_generator.summary import report, summarise
from llobregat_generator.zones import ZoneMap, load_boundaries


def cmd_load_reference(settings: Settings, _: argparse.Namespace) -> int:
    results = load_reference(settings)
    print(f"\n{'table':<24}{'rows':>9}{'skipped':>9}{'inserted':>10}{'in table':>10}")
    for table, loaded in results.items():
        print(f"{table:<24}{loaded.rows:>9}{loaded.skipped:>9}{loaded.inserted:>10}{loaded.in_table:>10}")
    return 0


def cmd_orders(settings: Settings, args: argparse.Namespace) -> int:
    seeds = Seeds.load(settings.seed_dir)
    with db.connect(settings) as conn:
        pool = publish.read_pool(conn, ZoneMap.from_company(seeds.company))
        day = generate_day(args.date, args.seed, seeds, pool)
        key, deleted, written = publish.publish_day(conn, Bucket(settings), day)
    print(f"bronze/{key}: {written} orders, {day.parcels} parcels (seed {args.seed})")
    print(
        f"bronze.orders: {written} rows written" + (f", {deleted} rows of an earlier run replaced" if deleted else "")
    )
    figures = summarise(day.orders, seeds.company, load_boundaries())
    print(report(args.date, figures, seeds))
    return 0


def cmd_summary(settings: Settings, args: argparse.Namespace) -> int:
    seeds = Seeds.load(settings.seed_dir)
    with db.connect(settings) as conn:
        orders = publish.read_day(conn, args.date)
    if not orders:
        print(f"no generated orders for {args.date} in bronze.orders")
        return 1
    print(report(args.date, summarise(orders, seeds.company, load_boundaries()), seeds))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llobregat-generator",
        description="Reference data and daily orders of Llobregat Express, for the bronze layer.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "load-reference",
        help="load hub, zones, shifts, vehicle types, vehicles, drivers, shippers, streets and addresses",
    ).set_defaults(run=cmd_load_reference)
    orders = commands.add_parser("orders", help="generate the orders of one service date")
    orders.add_argument("--date", required=True, type=date.fromisoformat, help="service date, YYYY-MM-DD")
    orders.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    orders.set_defaults(run=cmd_orders)
    summary = commands.add_parser("summary", help="sanity figures of a generated date, read from bronze.orders")
    summary.add_argument("--date", required=True, type=date.fromisoformat, help="service date, YYYY-MM-DD")
    summary.set_defaults(run=cmd_summary)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    try:
        return args.run(settings, args)
    except NoServiceError as exc:
        print(exc, file=sys.stderr)
        return 2
    except psycopg.OperationalError as exc:
        print(
            f"cannot reach TimescaleDB at {settings.postgres_host}:{settings.postgres_port} ({exc}); "
            "start the platform with `make up`",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
