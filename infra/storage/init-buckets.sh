#!/usr/bin/env bash
# Create the object storage buckets once. Safe to re-run.
# Lifecycle and archiving rules are added in issue #20.
set -euo pipefail

aws_s3() { aws --endpoint-url "$S3_ENDPOINT" "$@"; }

for bucket in bronze archive; do
  if aws_s3 s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    echo "bucket $bucket already exists"
  else
    aws_s3 s3api create-bucket --bucket "$bucket" >/dev/null
    echo "bucket $bucket created"
  fi
done

aws_s3 s3 ls
