"""The consumer loop: the three topics in one consumer group, written to the database in batches.

A batch is written when it holds `batch_size` messages or `batch_wait_s` after its first message
arrived, whichever comes first. Offsets are committed to the group only after the database
transaction of the batch has committed, so a crash between the two reads the batch again and the
idempotent inserts write nothing twice: at-least-once delivery, exactly-once rows.

Every `lag_interval_s` the consumer records, per topic and partition, how many messages it has not
written yet and the newest event_time it has written, in ops.consumer_lag.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from confluent_kafka import TIMESTAMP_NOT_AVAILABLE, KafkaError, KafkaException, TopicPartition

from llobregat_consumer.messages import TOPICS, UNKNOWN_SOURCE, Envelope, classify
from llobregat_consumer.sink import Lag, Sink

log = logging.getLogger("llobregat_consumer")

# Errors of the database connection, not of a row: the batch is written again once it is back.
CONNECTION_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError)
SOURCES_REFRESH_S = 60  # a message naming an unknown source reloads the registry at most this often
SUMMARY_EVERY_S = 60


class Batch:
    """Messages read and not written yet. Due when full, or `wait_s` after its first message."""

    def __init__(self, size: int, wait_s: float):
        self.size, self.wait_s = size, wait_s
        self.envelopes: list[Envelope] = []
        self.started: float | None = None

    def __len__(self) -> int:
        return len(self.envelopes)

    @property
    def room(self) -> int:
        return max(self.size - len(self.envelopes), 1)

    def add(self, envelope: Envelope, now: float) -> None:
        if not self.envelopes:
            self.started = now
        self.envelopes.append(envelope)

    def due(self, now: float) -> bool:
        if not self.envelopes:
            return False
        return len(self.envelopes) >= self.size or now - self.started >= self.wait_s

    def time_left(self, now: float) -> float:
        """Seconds until the batch is due on time; the wait itself when it is empty."""
        if not self.envelopes:
            return self.wait_s
        return max(self.wait_s - (now - self.started), 0.0)

    def take(self) -> list[Envelope]:
        envelopes, self.envelopes, self.started = self.envelopes, [], None
        return envelopes

    def drop(self, partitions: set[tuple[str, int]]) -> None:
        """Forget the messages of partitions this consumer no longer owns; their new owner reads them."""
        self.envelopes = [e for e in self.envelopes if (e.topic, e.partition) not in partitions]
        if not self.envelopes:
            self.started = None


def next_offsets(envelopes: list[Envelope]) -> list[TopicPartition]:
    """What to commit after a batch: per partition, the offset after the last message written."""
    last: dict[tuple[str, int], int] = {}
    for e in envelopes:
        key = (e.topic, e.partition)
        last[key] = max(last.get(key, -1), e.offset)
    return [TopicPartition(topic, partition, offset + 1) for (topic, partition), offset in sorted(last.items())]


def envelope_of(message: Any) -> Envelope:
    kind, ms = message.timestamp()
    timestamp = None if kind == TIMESTAMP_NOT_AVAILABLE else datetime.fromtimestamp(ms / 1000, UTC)
    return Envelope(message.topic(), message.partition(), message.offset(), message.key(), message.value(), timestamp)


@dataclass
class Status:
    """What the consumer has done, for the health endpoint and the log."""

    started: float
    assigned: int = 0
    last_poll: float | None = None
    last_db_ok: float | None = None
    lag: int | None = None
    messages: int = 0
    inserted: Counter = field(default_factory=Counter)
    duplicates: Counter = field(default_factory=Counter)
    dead_letters: Counter = field(default_factory=Counter)
    commit_failures: int = 0

    POLL_STALE_S = 30.0
    DB_STALE_S = 60.0

    def report(self, now: float) -> tuple[bool, dict]:
        """Healthy: it polls the broker, owns partitions and has reached the database lately."""
        polled = None if self.last_poll is None else round(now - self.last_poll, 1)
        db = None if self.last_db_ok is None else round(now - self.last_db_ok, 1)
        healthy = (
            self.assigned > 0
            and polled is not None
            and polled < self.POLL_STALE_S
            and db is not None
            and db < self.DB_STALE_S
        )
        return healthy, {
            "status": "ok" if healthy else "unhealthy",
            "uptime_s": round(now - self.started),
            "assigned_partitions": self.assigned,
            "seconds_since_poll": polled,
            "seconds_since_database": db,
            "lag": self.lag,
            "messages": self.messages,
            "inserted": dict(self.inserted),
            "duplicates": dict(self.duplicates),
            "dead_letters": dict(self.dead_letters),
            "commit_failures": self.commit_failures,
        }


class StreamConsumer:
    def __init__(
        self,
        consumer: Any,  # a confluent_kafka.Consumer, or a fake one in the tests
        sink: Sink,
        group: str,
        batch_size: int = 500,
        batch_wait_s: float = 1.0,
        lag_interval_s: float = 10.0,
        db_retry_s: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.consumer, self.sink, self.group = consumer, sink, group
        self.batch = Batch(batch_size, batch_wait_s)
        self.lag_interval_s, self.db_retry_s = lag_interval_s, db_retry_s
        self.clock, self.sleep = clock, sleep
        self.status = Status(started=clock())
        self.sources: set[str] = set()
        self.sources_loaded = float("-inf")
        # (topic, partition): [newest event_time written, when the last row was written]
        self.positions: dict[tuple[str, int], list[datetime | None]] = {}
        self.next_lag = clock()
        self.next_summary = clock() + SUMMARY_EVERY_S

    # -- database, retried while the connection is down -------------------------------------------

    def _with_database(self, what: str, action: Callable[[], Any]) -> Any:
        delay, deadline = 1.0, self.clock() + self.db_retry_s
        while True:
            try:
                result = action()
                self.status.last_db_ok = self.clock()
                return result
            except CONNECTION_ERRORS as e:
                if self.clock() >= deadline:
                    raise
                log.warning("database unavailable while %s, retrying in %.0f s: %s", what, delay, str(e).strip())
                self.sink.close()
                self.sleep(delay)
                delay = min(delay * 2, 15.0)

    def load_sources(self) -> None:
        self.sources = self._with_database("reading ops.data_sources", self.sink.sources)
        self.sources_loaded = self.clock()

    # -- lifecycle ---------------------------------------------------------------------------------

    def start(self) -> None:
        self.load_sources()
        last = self._with_database("reading ops.consumer_lag", lambda: self.sink.last_positions(self.group))
        self.positions = {key: list(value) for key, value in last.items()}
        self.consumer.subscribe(
            list(TOPICS), on_assign=self._on_assign, on_revoke=self._on_revoke, on_lost=self._on_lost
        )
        log.info("subscribed to %s as group %s", ", ".join(TOPICS), self.group)

    def run(self, stop: threading.Event) -> None:
        self.start()
        try:
            while not stop.is_set():
                self.step()
        finally:
            try:
                self.flush()
            finally:
                self.consumer.close()
                self.sink.close()
                log.info("stopped")

    def step(self) -> None:
        """Poll once, write the batch when it is due, measure the lag when it is time."""
        timeout = self.batch.time_left(self.clock())
        messages = self.consumer.consume(num_messages=self.batch.room, timeout=timeout)
        now = self.clock()
        self.status.last_poll = now
        for message in messages:
            error = message.error()
            if error is None:
                self.batch.add(envelope_of(message), now)
            elif error.code() != KafkaError._PARTITION_EOF:
                if error.fatal():
                    raise KafkaException(error)
                log.warning("broker: %s", error)
        if self.batch.due(now):
            self.flush()
        if now >= self.next_lag:
            self.next_lag = now + self.lag_interval_s
            self.report_lag()
        if now >= self.next_summary:
            self.next_summary = now + SUMMARY_EVERY_S
            log.info("%s", self.status.report(now)[1])

    # -- rebalances --------------------------------------------------------------------------------

    def _on_assign(self, _consumer, partitions: list[TopicPartition]) -> None:
        self.status.assigned = len(partitions)
        self.next_lag = self.clock()  # record the new assignment's lag right away
        log.info("assigned %d partitions", len(partitions))

    def _on_revoke(self, _consumer, partitions: list[TopicPartition]) -> None:
        self.flush()  # write and commit what was read before the partitions go
        self.status.assigned = 0
        log.info("revoked %d partitions", len(partitions))

    def _on_lost(self, _consumer, partitions: list[TopicPartition]) -> None:
        self.batch.drop({(p.topic, p.partition) for p in partitions})
        self.status.assigned = 0
        log.warning("lost %d partitions; their unwritten messages are read again by their new owner", len(partitions))

    # -- the batch ---------------------------------------------------------------------------------

    def flush(self) -> None:
        envelopes = self.batch.take()
        if not envelopes:
            return
        rows, dead = classify(envelopes, self.sources)
        if any(d.reason == UNKNOWN_SOURCE for d in dead) and self.clock() - self.sources_loaded >= SOURCES_REFRESH_S:
            self.load_sources()  # a source registered after the consumer started
            rows, dead = classify(envelopes, self.sources)
        written = self._with_database("writing a batch", lambda: self.sink.write(rows, dead))
        self._commit(envelopes)

        self.status.messages += len(envelopes)
        self.status.inserted.update(written.inserted)
        self.status.duplicates.update(written.duplicates)
        for d in written.dead_letters:
            self.status.dead_letters[d.envelope.topic] += 1
            log.warning(
                "dead letter %s[%d]@%d: %s: %s",
                d.envelope.topic,
                d.envelope.partition,
                d.envelope.offset,
                d.reason,
                d.error,
            )
        for row in written.rows:
            position = self.positions.setdefault((row.envelope.topic, row.envelope.partition), [None, None])
            if position[0] is None or row.event_time > position[0]:
                position[0] = row.event_time
            position[1] = written.ingested_at

    def _commit(self, envelopes: list[Envelope]) -> None:
        """Commit the batch's offsets. A failure is logged: the rows are in, a replay writes nothing."""
        try:
            committed = self.consumer.commit(offsets=next_offsets(envelopes), asynchronous=False)
            failed = [tp for tp in committed or [] if tp.error is not None]
            if failed:
                raise KafkaException(failed[0].error)
        except KafkaException as e:
            self.status.commit_failures += 1
            log.warning("offset commit failed, the batch will be read again: %s", e)

    # -- lag ---------------------------------------------------------------------------------------

    def measure_lag(self) -> list[Lag]:
        assignment = self.consumer.assignment()
        if not assignment:
            return []
        measurements = []
        for tp in self.consumer.committed(assignment, timeout=10):
            low, high = self.consumer.get_watermark_offsets(
                TopicPartition(tp.topic, tp.partition), timeout=10, cached=False
            )
            committed = tp.offset if tp.offset >= 0 else None
            read_from = low if committed is None else max(committed, low)
            event_time, ingested_at = self.positions.get((tp.topic, tp.partition), (None, None))
            measurements.append(
                Lag(tp.topic, tp.partition, committed, high, max(high - read_from, 0), event_time, ingested_at)
            )
        return measurements

    def report_lag(self) -> None:
        """Measure and record the lag. A failure is logged and the next interval tries again."""
        try:
            measurements = self.measure_lag()
            self.status.assigned = len(measurements)
            if measurements:
                self.sink.record_lag(self.group, measurements)
                self.status.last_db_ok = self.clock()
                self.status.lag = sum(m.lag for m in measurements)
        except KafkaException as e:
            log.warning("could not measure the lag: %s", e)
        except CONNECTION_ERRORS as e:
            self.sink.close()
            log.warning("could not record the lag: %s", str(e).strip())
