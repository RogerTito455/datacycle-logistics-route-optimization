"""The RustFS bronze bucket, through the S3 API."""

from __future__ import annotations

import io
from collections.abc import Collection
from pathlib import Path

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.config import Config
from botocore.exceptions import ClientError

from llobregat_generator.config import BRONZE_BUCKET, Settings

CONTENT_TYPES = {
    ".csv": "text/csv",
    ".zip": "application/zip",
    ".parquet": "application/vnd.apache.parquet",
    ".jpg": "image/jpeg",
}
# User metadata of an object: the checksum of its content, which decides whether it must be written.
CHECKSUM = "content-sha256"


class Bucket:
    """The bronze bucket."""

    def __init__(self, settings: Settings):
        self.name = BRONZE_BUCKET
        self.written: list[str] = []  # keys uploaded through this object, in order
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def head(self, key: str) -> dict | None:
        """The object's size and metadata, None when the key holds nothing."""
        try:
            return self.client.head_object(Bucket=self.name, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def put_file(self, key: str, path: Path) -> str:
        """Upload a downloaded file as it arrived, unless the same key already holds it."""
        head = self.head(key)
        if head is None or head["ContentLength"] != path.stat().st_size:
            self.client.upload_file(
                str(path), self.name, key, ExtraArgs={"ContentType": CONTENT_TYPES.get(path.suffix, "text/plain")}
            )
            self.written.append(key)
        return key

    def put_parquet(self, key: str, table: pa.Table, checksum: str | None = None) -> str:
        """Upload the table as a Parquet file, through put_bytes and with its checksum rule."""
        buffer = io.BytesIO()
        pq.write_table(table, buffer, compression="zstd")
        return self.put_bytes(key, buffer.getvalue(), checksum=checksum)

    def put_bytes(
        self, key: str, body: bytes, metadata: dict[str, str] | None = None, checksum: str | None = None
    ) -> str:
        """Upload an object with its content type from the key and its user metadata.

        With a checksum of its content, nothing is uploaded when the key already holds an object
        with that checksum; the checksum is stored with the object for the next upload to compare.
        """
        if checksum is not None and self.holds(key, checksum):
            return key
        self.client.put_object(
            Bucket=self.name,
            Key=key,
            Body=body,
            ContentType=CONTENT_TYPES.get(Path(key).suffix, "application/octet-stream"),
            Metadata={**(metadata or {}), **({CHECKSUM: checksum} if checksum else {})},
        )
        self.written.append(key)
        return key

    def holds(self, key: str, checksum: str) -> bool:
        """Whether the key holds an object stored with this checksum of its content."""
        head = self.head(key)
        return head is not None and head.get("Metadata", {}).get(CHECKSUM) == checksum

    def get_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.name, Key=key)["Body"].read()

    def delete_prefix(self, prefix: str, keep: Collection[str] = ()) -> int:
        """Delete every object whose key starts with prefix, except the keys in keep; return how many."""
        deleted = 0
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.name, Prefix=prefix):
            for item in page.get("Contents", []):
                if item["Key"] not in keep:
                    self.client.delete_object(Bucket=self.name, Key=item["Key"])
                    deleted += 1
        return deleted

    def get_parquet(self, key: str) -> pa.Table:
        return pq.read_table(io.BytesIO(self.get_bytes(key)))
