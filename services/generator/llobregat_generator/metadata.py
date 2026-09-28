"""The metadata of ADR 0001, decision 20, on the Parquet files the generator writes.

Every file carries `source` and `ingested_at` as columns, like the rows of its bronze table, and
the four elements as file-level key-value metadata: `source`, `owner`, `schema_version` and
`ingested_at`. The owner and schema version are those of the bronze table the file is loaded
into, read from ops.table_metadata, so file and table cannot disagree.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import psycopg
import pyarrow as pa

from llobregat_generator import db


@dataclass(frozen=True)
class FileMetadata:
    source: str
    owner: str
    schema_version: int
    ingested_at: datetime

    @classmethod
    def for_table(cls, conn: psycopg.Connection, table: str, source: str, ingested_at: datetime) -> FileMetadata:
        """The metadata of a file loaded into `table`, with the table's owner and schema version."""
        owner, schema_version = db.table_metadata(conn, table)
        return cls(source, owner, schema_version, ingested_at.astimezone(UTC))

    def key_values(self) -> dict[str, str]:
        return {
            "source": self.source,
            "owner": self.owner,
            "schema_version": str(self.schema_version),
            "ingested_at": self.ingested_at.isoformat(),
        }


def content_checksum(rows: Sequence[Mapping], metadata: FileMetadata) -> str:
    """SHA-256 of the rows and the file metadata, without ingested_at, which changes on every run.

    Two loads of the same seed give the same checksum, so the second one need not write the file.
    """
    described = {k: v for k, v in metadata.key_values().items() if k != "ingested_at"}
    content = json.dumps({"metadata": described, "rows": list(rows)}, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()


def parquet_table(
    rows: Sequence[Mapping], metadata: FileMetadata, schema: pa.Schema | None = None, **extra: str
) -> pa.Table:
    """The rows as an Arrow table with `source` and `ingested_at` columns and the file metadata.

    `extra` adds key-value metadata of the file's own, such as the seed of a generated day.
    """
    stamped = [{**row, "source": metadata.source, "ingested_at": metadata.ingested_at} for row in rows]
    table = pa.Table.from_pylist(stamped, schema=schema)
    return table.replace_schema_metadata({**metadata.key_values(), **extra})
