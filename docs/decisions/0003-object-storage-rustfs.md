# ADR 0003 · Object storage on RustFS instead of MinIO

- **Date:** 2026-09-28
- **Status:** accepted
- **Supersedes:** the MinIO part of ADR 0001, decision 9

## Context

ADR 0001 chose MinIO for the bronze (raw) and archive layers. While building the Docker Compose
stack we found that MinIO no longer ships container images of its community edition: on
28 September 2026, `minio/minio` on Docker Hub and `quay.io/minio/minio` both return no
manifests for any tag, including `latest`. Building MinIO from source would make the team
maintain a Go build for a component that is not the point of the assignment.

## Decision

Use **RustFS 1.0.0** (`rustfs/rustfs:1.0.0`, Apache 2.0) as the S3-compatible object store.
The role in the architecture does not change: a `bronze` bucket with every raw payload as it
arrived, and an `archive` bucket that lifecycle rules move cold data into.

Before choosing it we ran it and checked what the pipeline needs:

| Check | Result |
|---|---|
| Create bucket, upload and list objects with the AWS CLI | works |
| `put-bucket-lifecycle-configuration` with a 30-day expiration rule, read back | works |
| Health endpoint for Docker healthchecks | `GET /health` returns 200 |
| Web console | port 9001 |
| Memory at idle | about 160 MB |

Buckets are administered with the official AWS CLI image (`amazon/aws-cli`), which works against
any S3-compatible store, so nothing in the repo depends on a vendor-specific client.

## Alternatives considered

| Option | Why not |
|---|---|
| MinIO built from source | Maintenance burden, and no official image to point the teacher to |
| Chainguard's MinIO image | Only a floating `latest` tag on the free tier, and the pull failed during evaluation |
| SeaweedFS | Mature, but several components (master, volume, filer, S3 gateway) to explain for one bucket |
| Garage | Lightweight, but no web console to show in the demo |

## Consequences

- Environment variables are vendor-neutral: `S3_ACCESS_KEY`, `S3_SECRET_KEY`, `S3_ENDPOINT`.
- Every client uses path-style addressing (`http://rustfs:9000/<bucket>/<key>`), which RustFS
  supports without extra configuration.
- If RustFS causes trouble, any S3-compatible store can replace it by changing one service in
  `docker-compose.yml`; the rest of the stack only speaks S3.
