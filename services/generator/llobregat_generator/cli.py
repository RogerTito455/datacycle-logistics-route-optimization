"""Command line of the generator.

llobregat-generator load-reference | orders --date D [--seed N] [--allow-future] | summary --date D
                    | pod-sample --date D [--count N] [--seed N]
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

import psycopg
from botocore.exceptions import BotoCoreError, ClientError

from llobregat_generator import db, pod, publish
from llobregat_generator.addresses import DownloadError
from llobregat_generator.config import Settings
from llobregat_generator.metadata import FileMetadata
from llobregat_generator.orders import LOCAL_TZ, NoServiceError, generate_day
from llobregat_generator.reference import load_reference
from llobregat_generator.rules import SeedError
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
    today = datetime.now(LOCAL_TZ).date()
    if args.date > today and not args.allow_future:
        print(
            f"{args.date} is after today ({today}): its orders would be registered after they are ingested. "
            "Pass --allow-future to generate it anyway.",
            file=sys.stderr,
        )
        return 2
    seeds = Seeds.load(settings.seed_dir)
    with db.connect(settings) as conn:
        pool = publish.read_pool(conn, ZoneMap.from_company(seeds.company))
        day = generate_day(args.date, args.seed, seeds, pool)
        key, deleted, written = publish.publish_day(conn, Bucket(settings), day, datetime.now(UTC))
    print(f"bronze/{key}: {written} orders, {day.parcels} parcels (seed {args.seed})")
    print(
        f"bronze.orders: {written} rows written" + (f", {deleted} rows of an earlier run replaced" if deleted else "")
    )
    figures = summarise(day.orders, seeds, load_boundaries())
    print(report(args.date, figures, seeds))
    return 0


def cmd_summary(settings: Settings, args: argparse.Namespace) -> int:
    seeds = Seeds.load(settings.seed_dir)
    with db.connect(settings) as conn:
        orders = publish.read_day(conn, args.date)
    if not orders:
        print(f"no generated orders for {args.date} in bronze.orders")
        return 1
    print(report(args.date, summarise(orders, seeds, load_boundaries()), seeds))
    return 0


def cmd_pod_sample(settings: Settings, args: argparse.Namespace) -> int:
    """Photos for some orders of a generated date under pod/samples/, each read back and checked.

    The new photos are uploaded first; the photos of an earlier sample of the date that are not
    among them are removed afterwards, so a run that fails halfway never leaves fewer photos.
    """
    with db.connect(settings) as conn:
        orders = publish.read_day(conn, args.date)
        if not orders:
            print(f"no generated orders for {args.date} in bronze.orders; run make generate first", file=sys.stderr)
            return 1
        metadata = FileMetadata.for_table(conn, pod.TABLE, pod.SOURCE_ID, datetime.now(UTC))
    bucket = Bucket(settings)
    prefix = pod.sample_prefix(args.date)
    print(f"Proof-of-delivery placeholders for {args.date}, synthetic images drawn by code")
    keys, wrong = [], 0
    for delivery in pod.sample_deliveries(orders, args.count, args.seed):
        key = pod.upload(bucket, delivery, metadata, sample=True)
        keys.append(key)
        body = bucket.get_bytes(key)
        capture = pod.read_exif(body)
        matches = (
            capture.taken_at == delivery.delivered_at
            and abs(capture.lat - delivery.lat) < 1e-6
            and abs(capture.lon - delivery.lon) < 1e-6
        )
        wrong += not matches
        print(
            f"  bronze/{key}  {len(body) / 1000:.1f} kB  EXIF {capture.taken_at.isoformat()}  "
            f"{capture.lat:.6f}, {capture.lon:.6f}" + ("" if matches else "  DOES NOT MATCH THE DELIVERY")
        )
    removed = bucket.delete_prefix(prefix, keep=keys)
    if removed:
        print(f"  {removed} photos of an earlier sample, not in this one, removed from bronze/{prefix}")
    photos = len(keys)
    print(f"{photos} photos in bronze/{prefix}, read back: EXIF time and position match {photos - wrong} of {photos}")
    return 1 if wrong else 0


def positive(text: str) -> int:
    """An argparse type: a whole number above zero."""
    try:
        number = int(text)
    except ValueError:
        number = 0
    if number <= 0:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number above zero")
    return number


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="llobregat-generator",
        description="Reference data and daily orders of Llobregat Express, for the bronze layer.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "load-reference",
        help="load hub, zones, shifts, vehicle types, vehicles, drivers, shippers, delivery notes and addresses",
    ).set_defaults(run=cmd_load_reference)
    orders = commands.add_parser("orders", help="generate the orders of one service date")
    orders.add_argument("--date", required=True, type=date.fromisoformat, help="service date, YYYY-MM-DD")
    orders.add_argument("--seed", type=int, default=0, help="random seed (default 0)")
    orders.add_argument(
        "--allow-future",
        action="store_true",
        help="allow a date after today; its registration times (event_time) can then be later than ingested_at",
    )
    orders.set_defaults(run=cmd_orders)
    summary = commands.add_parser("summary", help="sanity figures of a generated date, read from bronze.orders")
    summary.add_argument("--date", required=True, type=date.fromisoformat, help="service date, YYYY-MM-DD")
    summary.set_defaults(run=cmd_summary)
    sample = commands.add_parser(
        "pod-sample",
        help="upload proof-of-delivery placeholder photos for some orders of a generated date, under pod/samples/",
    )
    sample.add_argument("--date", required=True, type=date.fromisoformat, help="service date, YYYY-MM-DD")
    sample.add_argument("--count", type=positive, default=20, help="number of photos, above zero (default 20)")
    sample.add_argument("--seed", type=int, default=0, help="random seed of the orders and times (default 0)")
    sample.set_defaults(run=cmd_pod_sample)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    try:
        return args.run(settings, args)
    except NoServiceError as exc:
        print(exc, file=sys.stderr)
        return 2
    except SeedError as exc:
        print(f"the seeds cannot be used: {exc}", file=sys.stderr)
        return 2
    except DownloadError as exc:
        print(f"download failed, nothing was cached: {exc}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as exc:
        print(
            f"cannot reach TimescaleDB at {settings.postgres_host}:{settings.postgres_port} ({exc}); "
            "start the platform with `make up`",
            file=sys.stderr,
        )
        return 1
    except (BotoCoreError, ClientError) as exc:
        print(
            f"the RustFS bronze bucket at {settings.s3_endpoint} failed ({exc}); check that the platform is up "
            "(`make up`) and the S3 credentials in .env",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
