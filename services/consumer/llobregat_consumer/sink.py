"""Writing a batch to TimescaleDB: the rows into bronze, the dead letters and the lag into ops.

A batch is one transaction. Each table's rows are copied (COPY) into a temporary staging table and
moved into bronze with one INSERT ... SELECT ... ON CONFLICT DO NOTHING on the table's key, so a
message read twice (a replay after a crash, a restarted consumer group) is written once. If the
database refuses a row the parser let through (a string PostgreSQL cannot store inside a JSON
field, say), the batch is written again row by row, each in a savepoint, and the refused rows
become dead letters: one bad message never blocks its partition.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from llobregat_consumer.messages import REJECTED_BY_DATABASE, TOPICS, DeadLetter, Row

JSON_COLUMNS = frozenset({"readings", "extra_fields"})
MAX_ERROR_CHARS = 1000

# Errors that belong to a row, not to the connection: the row is dead-lettered, the batch goes on.
ROW_ERRORS = (psycopg.errors.DataError, psycopg.errors.IntegrityError)


@dataclass(frozen=True, slots=True)
class Lag:
    """One measurement of one partition."""

    topic: str
    partition: int
    committed_offset: int | None  # the next offset the group reads; None before its first commit
    end_offset: int  # the high watermark: the offset the next message will get
    lag: int  # messages in the partition not yet written
    last_event_time: datetime | None  # the newest event_time written from the partition
    last_ingested_at: datetime | None  # when a row from the partition was last written


@dataclass
class Written:
    inserted: Counter = field(default_factory=Counter)  # table: rows inserted
    duplicates: Counter = field(default_factory=Counter)  # table: rows already there
    rows: list[Row] = field(default_factory=list)  # the rows now in bronze, inserted or not
    dead_letters: list[DeadLetter] = field(default_factory=list)  # parser's and database's
    ingested_at: datetime | None = None  # the ingested_at of the rows: when the transaction started


def _clean(error: str) -> str:
    return error.replace("\x00", "\\x00")[:MAX_ERROR_CHARS]


class Sink:
    """The consumer's connection to the database. `bronze` and `ops` name the schemas (tests use their own)."""

    def __init__(self, conninfo: str, bronze: str = "bronze", ops: str = "ops"):
        self.conninfo = conninfo
        self.bronze, self.ops = bronze, ops
        self.conn: psycopg.Connection | None = None
        self._stage, self._copy, self._move, self._insert_one = {}, {}, {}, {}
        for table in TOPICS.values():
            target, stage = sql.Identifier(bronze, table.name), sql.Identifier(f"stage_{table.name}")
            columns = sql.SQL(", ").join(map(sql.Identifier, table.columns))
            # Emptied at every commit; a rolled-back savepoint takes its rows along.
            self._stage[table.name] = sql.SQL(
                "CREATE TEMPORARY TABLE IF NOT EXISTS {} (LIKE {} INCLUDING DEFAULTS) ON COMMIT DELETE ROWS"
            ).format(stage, target)
            self._copy[table.name] = sql.SQL("COPY {} ({}) FROM STDIN").format(stage, columns)
            self._move[table.name] = sql.SQL(
                "INSERT INTO {target} ({columns}) SELECT {columns} FROM {stage} ON CONFLICT DO NOTHING"
            ).format(target=target, columns=columns, stage=stage)
            self._insert_one[table.name] = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                target, columns, sql.SQL(", ").join(sql.Placeholder() * len(table.columns))
            )
        self._dead_letter = sql.SQL(
            "INSERT INTO {} (topic, kafka_partition, kafka_offset, kafka_timestamp, message_key, payload, reason,"
            " error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING"
        ).format(sql.Identifier(ops, "dead_letters"))
        self._lag = sql.SQL(
            "INSERT INTO {} (event_time, consumer_group, topic, kafka_partition, committed_offset, end_offset, lag,"
            " last_event_time, last_ingested_at) VALUES (now(), %s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(sql.Identifier(ops, "consumer_lag"))

    # -- connection ------------------------------------------------------------------------------

    def connect(self) -> psycopg.Connection:
        if self.conn is None or self.conn.closed:
            self.conn = psycopg.connect(self.conninfo, autocommit=True, application_name="llobregat-consumer")
            for statement in self._stage.values():
                self.conn.execute(statement)
        return self.conn

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # -- reads -----------------------------------------------------------------------------------

    def sources(self) -> set[str]:
        """The registered sources, the only values a row's `source` can take (a foreign key)."""
        with self.connect().cursor() as cur:
            cur.execute("SELECT source_id FROM ops.data_sources")
            return {source for (source,) in cur}

    def last_positions(self, group: str) -> dict[tuple[str, int], tuple[datetime | None, datetime | None]]:
        """Per partition, the newest event_time and ingestion the last run recorded."""
        query = sql.SQL(
            "SELECT DISTINCT ON (topic, kafka_partition) topic, kafka_partition, last_event_time, last_ingested_at"
            " FROM {} WHERE consumer_group = %s ORDER BY topic, kafka_partition, event_time DESC"
        ).format(sql.Identifier(self.ops, "consumer_lag"))
        with self.connect().cursor() as cur:
            cur.execute(query, (group,))
            return {(topic, partition): (event, ingested) for topic, partition, event, ingested in cur}

    # -- writes ----------------------------------------------------------------------------------

    def _params(self, row: Row) -> list:
        return [Jsonb(v) if k in JSON_COLUMNS and v is not None else v for k, v in row.values.items()]

    def _insert_many(self, cur: psycopg.Cursor, table: str, rows: Sequence[Row]) -> int:
        with cur.copy(self._copy[table]) as copy:
            for row in rows:
                copy.write_row(self._params(row))
        cur.execute(self._move[table])
        return cur.rowcount

    def _insert(self, cur: psycopg.Cursor, row: Row) -> int:
        cur.execute(self._insert_one[row.table], self._params(row))
        return cur.rowcount

    def write(self, rows: Sequence[Row], dead: Iterable[DeadLetter]) -> Written:
        """Write a batch in one transaction and return what happened to each message."""
        written = Written(dead_letters=list(dead))
        by_table: dict[str, list[Row]] = {}
        for row in rows:
            by_table.setdefault(row.table, []).append(row)
        conn = self.connect()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute("SELECT now()")
            written.ingested_at = cur.fetchone()[0]
            try:
                with conn.transaction():  # a savepoint: a refused row undoes only the batch's inserts
                    for table, table_rows in by_table.items():
                        n = self._insert_many(cur, table, table_rows)
                        written.inserted[table] += n
                        written.duplicates[table] += len(table_rows) - n
                written.rows.extend(rows)
            except ROW_ERRORS:
                written.inserted.clear()
                written.duplicates.clear()
                for row in rows:
                    try:
                        with conn.transaction():
                            n = self._insert(cur, row)
                    except ROW_ERRORS as e:
                        error = f"the database refused the row: {str(e).strip()}"
                        written.dead_letters.append(DeadLetter(row.envelope, REJECTED_BY_DATABASE, error))
                        continue
                    written.inserted[row.table] += n
                    written.duplicates[row.table] += 1 - n
                    written.rows.append(row)
            if written.dead_letters:
                cur.executemany(
                    self._dead_letter,
                    [
                        (
                            d.envelope.topic,
                            d.envelope.partition,
                            d.envelope.offset,
                            d.envelope.timestamp,
                            d.envelope.key,
                            d.envelope.value,
                            d.reason,
                            _clean(d.error),
                        )
                        for d in written.dead_letters
                    ],
                )
        return written

    def record_lag(self, group: str, measurements: Sequence[Lag]) -> None:
        conn = self.connect()
        with conn.transaction(), conn.cursor() as cur:
            cur.executemany(
                self._lag,
                [
                    (
                        group,
                        m.topic,
                        m.partition,
                        m.committed_offset,
                        m.end_offset,
                        m.lag,
                        m.last_event_time,
                        m.last_ingested_at,
                    )
                    for m in measurements
                ],
            )
