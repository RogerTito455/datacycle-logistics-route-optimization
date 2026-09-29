"""TimescaleDB access: bulk loads through COPY, write-once inserts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import psycopg
from psycopg import sql

from llobregat_generator.config import Settings


def connect(settings: Settings) -> psycopg.Connection:
    return psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        user=settings.postgres_user,
        password=settings.postgres_password,
        dbname=settings.postgres_db,
        application_name="llobregat-generator",
    )


def table_metadata(conn: psycopg.Connection, table: str) -> tuple[str, int]:
    """Owner and schema version of a table, from its JSON comment through ops.table_metadata."""
    schema, name = table.split(".")
    row = conn.execute(
        "SELECT owner, schema_version FROM ops.table_metadata WHERE schema_name = %s AND table_name = %s",
        (schema, name),
    ).fetchone()
    if row is None or None in row:
        raise RuntimeError(f"{table} has no owner and schema_version in ops.table_metadata; run make migrate")
    return row[0], row[1]


def count(conn: psycopg.Connection, table: str) -> int:
    schema, name = table.split(".")
    return conn.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(schema, name))).fetchone()[0]


def copy_rows(conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence]) -> None:
    schema, name = table.split(".")
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(schema, name), sql.SQL(", ").join(map(sql.Identifier, columns))
    )
    with conn.cursor().copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def insert_new(conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence]) -> int:
    """Insert the rows whose key is not in the table yet; return how many were inserted.

    Bronze is write-once, so a row that is already there is left as it is (ON CONFLICT DO NOTHING)
    and loading the same file twice writes nothing the second time.
    """
    schema, name = table.split(".")
    staging = f"_load_{name}"
    conn.execute(
        sql.SQL("CREATE TEMP TABLE {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DROP").format(
            sql.Identifier(staging), sql.Identifier(schema, name)
        )
    )
    copy_rows(conn, f"pg_temp.{staging}", columns, rows)
    column_list = sql.SQL(", ").join(map(sql.Identifier, columns))
    cursor = conn.execute(
        sql.SQL("INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT DO NOTHING").format(
            sql.Identifier(schema, name), column_list, column_list, sql.Identifier(staging)
        )
    )
    return cursor.rowcount
