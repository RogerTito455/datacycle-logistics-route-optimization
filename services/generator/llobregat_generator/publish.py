"""Write a generated day to the bronze layer: a Parquet file in RustFS and the rows of bronze.orders."""

from __future__ import annotations

from datetime import date

import psycopg
import pyarrow as pa
from psycopg import sql
from psycopg.rows import dict_row

from llobregat_generator import __version__, addresses, db
from llobregat_generator.orders import COLUMNS, SOURCE_ID, Day
from llobregat_generator.storage import Bucket
from llobregat_generator.zones import ZoneMap

TIMESTAMP = pa.timestamp("us", tz="UTC")
ORDER_SCHEMA = pa.schema(
    [
        ("order_id", pa.string()),
        ("service_date", pa.date32()),
        ("service_level", pa.string()),
        ("priority", pa.string()),
        ("customer_type", pa.string()),
        ("shipper_id", pa.string()),
        ("shipper_name", pa.string()),
        ("origin_address", pa.string()),
        ("recipient_name", pa.string()),
        ("destination_address", pa.string()),
        ("destination_postcode", pa.string()),
        ("destination_municipality", pa.string()),
        ("destination_lat", pa.float64()),
        ("destination_lon", pa.float64()),
        ("destination_zone_id", pa.string()),
        ("address_ref", pa.string()),
        ("parcels", pa.int16()),
        ("parcel_size", pa.string()),
        ("weight_kg", pa.float64()),
        ("wave", pa.string()),
        ("window_type", pa.string()),
        ("window_start", TIMESTAMP),
        ("window_end", TIMESTAMP),
        ("notes", pa.string()),
        ("source", pa.string()),
        ("event_time", TIMESTAMP),
    ]
)
if tuple(ORDER_SCHEMA.names) != COLUMNS:
    raise RuntimeError(f"the Parquet schema and orders.COLUMNS disagree: {ORDER_SCHEMA.names} against {COLUMNS}")


def object_key(service_date: date) -> str:
    return f"orders/date={service_date.isoformat()}/orders.parquet"


def orders_table(day: Day) -> pa.Table:
    """The day's orders as an Arrow table; the file metadata records how they were generated."""
    schema = ORDER_SCHEMA.with_metadata(
        {
            "source": SOURCE_ID,
            "service_date": day.service_date.isoformat(),
            "seed": str(day.seed),
            "generator": f"llobregat-generator {__version__}",
        }
    )
    return pa.Table.from_pylist(day.orders, schema=schema)


def publish_day(conn: psycopg.Connection, bucket: Bucket, day: Day) -> tuple[str, int, int]:
    """Store the day's file and rows; a date generated before is replaced, not duplicated.

    Returns the object key, the rows deleted (from an earlier run of the date) and the rows written.
    """
    key = bucket.put_parquet(object_key(day.service_date), orders_table(day))
    with conn.transaction():
        deleted = conn.execute(
            "DELETE FROM bronze.orders WHERE service_date = %s AND source = %s", (day.service_date, SOURCE_ID)
        ).rowcount
        db.copy_rows(conn, "bronze.orders", [*COLUMNS, "raw_object_key"], ([*o.values(), key] for o in day.orders))
    return key, deleted, len(day.orders)


def read_pool(conn: psycopg.Connection, zone_map: ZoneMap) -> dict[str, list[addresses.Address]]:
    """The address pool from bronze.addresses, bronze.streets and bronze.icgc_addresses."""
    with conn.cursor(row_factory=dict_row) as cur:
        barcelona = cur.execute(
            """SELECT a.address_ref, a.street_code, a.street_number, a.number_letter, a.district_code,
                      a.postal_district, a.lat, a.lon, s.official_name
               FROM bronze.addresses a LEFT JOIN bronze.streets s USING (street_code)
               WHERE a.lat IS NOT NULL AND a.lon IS NOT NULL"""
        ).fetchall()
        towns = cur.execute("SELECT * FROM bronze.icgc_addresses WHERE lat IS NOT NULL AND lon IS NOT NULL").fetchall()
    names = {row["street_code"]: row["official_name"] for row in barcelona}
    return addresses.build_pool(barcelona, names, towns, zone_map)


def read_day(conn: psycopg.Connection, service_date: date) -> list[dict]:
    """The generated orders of one service date, as generate_day returned them."""
    query = sql.SQL("SELECT {} FROM bronze.orders WHERE service_date = %s AND source = %s ORDER BY order_id").format(
        sql.SQL(", ").join(map(sql.Identifier, COLUMNS))
    )
    with conn.cursor(row_factory=dict_row) as cur:
        return cur.execute(query, (service_date, SOURCE_ID)).fetchall()
