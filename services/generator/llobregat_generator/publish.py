"""Write a generated day to the bronze layer: a Parquet file in RustFS and the rows of bronze.orders."""

from __future__ import annotations

from datetime import date, datetime

import psycopg
import pyarrow as pa
from psycopg import sql
from psycopg.rows import dict_row

from llobregat_generator import __version__, addresses, db
from llobregat_generator.metadata import FileMetadata, parquet_table
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
        ("note_id", pa.string()),
        ("source", pa.string()),
        ("event_time", TIMESTAMP),
        ("ingested_at", TIMESTAMP),
    ]
)
# The generated columns, then ingested_at, which is set when the day is published.
if tuple(ORDER_SCHEMA.names) != (*COLUMNS, "ingested_at"):
    raise RuntimeError(f"the Parquet schema and orders.COLUMNS disagree: {ORDER_SCHEMA.names} against {COLUMNS}")


def object_key(service_date: date) -> str:
    return f"orders/date={service_date.isoformat()}/orders.parquet"


def orders_table(day: Day, metadata: FileMetadata) -> pa.Table:
    """The day's orders as an Arrow table; the file metadata also records how they were generated."""
    return parquet_table(
        day.orders,
        metadata,
        ORDER_SCHEMA,
        service_date=day.service_date.isoformat(),
        seed=str(day.seed),
        generator=f"llobregat-generator {__version__}",
    )


def publish_day(conn: psycopg.Connection, bucket: Bucket, day: Day, ingested_at: datetime) -> tuple[str, int, int]:
    """Replace the day's rows and file in one database transaction; a date is never duplicated.

    The rows of an earlier run of the date are deleted and the new rows copied in, then the file is
    uploaded, before the transaction commits. If the database or the upload fails, the transaction
    rolls back and the date keeps its rows and its file. If the commit fails after the upload, the
    bucket holds the new file with the old rows until the next run of the date overwrites it.

    File and rows get the same ingested_at. Returns the object key, the rows deleted (from an
    earlier run of the date) and the rows written.
    """
    key = object_key(day.service_date)
    with conn.transaction():
        metadata = FileMetadata.for_table(conn, "bronze.orders", SOURCE_ID, ingested_at)
        table = orders_table(day, metadata)
        deleted = conn.execute(
            "DELETE FROM bronze.orders WHERE service_date = %s AND source = %s", (day.service_date, SOURCE_ID)
        ).rowcount
        rows = ([*o.values(), metadata.ingested_at, key] for o in day.orders)
        db.copy_rows(conn, "bronze.orders", [*table.column_names, "raw_object_key"], rows)
        bucket.put_parquet(key, table)
    return key, deleted, table.num_rows


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
