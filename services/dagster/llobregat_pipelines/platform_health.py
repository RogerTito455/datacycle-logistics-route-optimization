"""Platform health check.

Probes every service of the stack from inside the Docker network, writes one
row per service to ops.service_health and attaches the results to the asset as
metadata, so the Dagster UI and the Grafana home dashboard show the same thing.
"""

import os
import socket
import urllib.request
from contextlib import closing
from datetime import UTC, datetime

import dagster as dg
import psycopg2


def _http_ok(url: str) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return 200 <= response.status < 300, f"HTTP {response.status}"
    except Exception as exc:  # noqa: BLE001 - any failure means the service is down
        return False, f"{type(exc).__name__}: {exc}"


def _tcp_ok(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=5):
            return True, f"TCP {host}:{port} open"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _connect():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
    )


def _postgres_ok() -> tuple[bool, str]:
    try:
        with closing(_connect()) as conn, conn.cursor() as cur:
            cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'")
            row = cur.fetchone()
        return (
            row is not None,
            f"TimescaleDB {row[0]}" if row else "timescaledb extension missing",
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


@dg.asset(
    group_name="platform",
    kinds={"python", "postgres"},
    owners=["team:platform"],
    description="Probes every service of the stack and records the result in ops.service_health.",
)
def platform_health(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    kafka_host, kafka_port = os.environ["KAFKA_BOOTSTRAP"].split(":")
    checks = {
        "timescaledb": _postgres_ok(),
        "redpanda": _tcp_ok(kafka_host, int(kafka_port)),
        "redpanda-console": _http_ok("http://redpanda-console:8080/"),
        "rustfs": _http_ok(f"{os.environ['S3_ENDPOINT']}/health"),
        "osrm": _http_ok(f"{os.environ['OSRM_URL']}/route/v1/driving/2.1370,41.3405;2.1744,41.4036?overview=false"),
        "grafana": _http_ok("http://grafana:3000/api/health"),
        "dagster-webserver": _http_ok("http://dagster-webserver:3000/server_info"),
    }
    checked_at = datetime.now(UTC)

    with closing(_connect()) as conn, conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO ops.service_health (event_time, service, ok, detail) VALUES (%s, %s, %s, %s)",
            [(checked_at, name, ok, detail) for name, (ok, detail) in checks.items()],
        )

    up = sum(ok for ok, _ in checks.values())
    for name, (ok, detail) in checks.items():
        (context.log.info if ok else context.log.warning)(f"{name}: {'up' if ok else 'DOWN'} ({detail})")

    return dg.MaterializeResult(
        metadata={
            "services_up": dg.MetadataValue.int(up),
            "services_total": dg.MetadataValue.int(len(checks)),
            "checked_at": dg.MetadataValue.timestamp(checked_at),
            "results": dg.MetadataValue.md(
                "| Service | Status | Detail |\n|---|---|---|\n"
                + "\n".join(f"| {n} | {'up' if ok else 'DOWN'} | {d} |" for n, (ok, d) in checks.items())
            ),
            # The three mandatory metadata elements (ADR 0001, decision 20).
            "source": "dagster/platform_health",
            "owner": "team:platform",
            "schema_version": dg.MetadataValue.int(1),
        }
    )
