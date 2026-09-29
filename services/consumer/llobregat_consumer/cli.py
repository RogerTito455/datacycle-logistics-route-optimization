"""llobregat-consumer: run the stream consumer until SIGTERM or Ctrl-C."""

from __future__ import annotations

import argparse
import logging
import signal
import threading

from confluent_kafka import Consumer

from llobregat_consumer import health
from llobregat_consumer.config import Settings
from llobregat_consumer.consumer import StreamConsumer
from llobregat_consumer.sink import Sink


def main(argv: list[str] | None = None) -> None:
    argparse.ArgumentParser(
        prog="llobregat-consumer",
        description="Consume gps.pings, vehicle.telemetry and delivery.events into the bronze tables. "
        "Settings come from the environment (services/consumer/README.md).",
    ).parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("psycopg").setLevel(logging.WARNING)
    settings = Settings.from_env()

    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())

    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap,
            "group.id": settings.group,
            "client.id": "llobregat-consumer",
            "enable.auto.commit": False,  # offsets are committed after the database, batch by batch
            "auto.offset.reset": "earliest",  # a new group starts from what the topics still keep
        }
    )
    app = StreamConsumer(
        consumer,
        Sink(settings.conninfo),
        settings.group,
        batch_size=settings.batch_size,
        batch_wait_s=settings.batch_wait_s,
        lag_interval_s=settings.lag_interval_s,
    )
    health.serve(app.status, settings.health_port)
    logging.getLogger("llobregat_consumer").info(
        "batches of %d messages or %.1f s, lag every %.0f s, health on port %d",
        settings.batch_size,
        settings.batch_wait_s,
        settings.lag_interval_s,
        settings.health_port,
    )
    app.run(stop)
