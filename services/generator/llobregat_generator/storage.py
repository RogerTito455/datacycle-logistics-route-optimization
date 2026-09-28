"""The RustFS bronze bucket, through the S3 API."""

from __future__ import annotations

import io
from pathlib import Path

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
from botocore.config import Config
from botocore.exceptions import ClientError

from llobregat_generator.config import BRONZE_BUCKET, Settings

CONTENT_TYPES = {".csv": "text/csv", ".zip": "application/zip", ".parquet": "application/vnd.apache.parquet"}


class Bucket:
    def __init__(self, settings: Settings, name: str = BRONZE_BUCKET):
        self.name = name
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 3}),
        )

    def size(self, key: str) -> int | None:
        try:
            return self.client.head_object(Bucket=self.name, Key=key)["ContentLength"]
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return None
            raise

    def put_file(self, key: str, path: Path) -> str:
        """Upload a downloaded file as it arrived, unless the same key already holds it."""
        if self.size(key) != path.stat().st_size:
            self.client.upload_file(
                str(path), self.name, key, ExtraArgs={"ContentType": CONTENT_TYPES.get(path.suffix, "text/plain")}
            )
        return key

    def put_parquet(self, key: str, table: pa.Table) -> str:
        buffer = io.BytesIO()
        pq.write_table(table, buffer, compression="zstd")
        self.client.put_object(Bucket=self.name, Key=key, Body=buffer.getvalue(), ContentType=CONTENT_TYPES[".parquet"])
        return key

    def get_parquet(self, key: str) -> pa.Table:
        body = self.client.get_object(Bucket=self.name, Key=key)["Body"].read()
        return pq.read_table(io.BytesIO(body))
