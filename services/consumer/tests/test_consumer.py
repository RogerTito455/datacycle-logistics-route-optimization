"""The consumer loop against a fake broker and a fake database: batching, commits, dead letters, lag."""

from __future__ import annotations

import threading
from collections import Counter
from datetime import UTC, datetime

import psycopg
import pytest
from conftest import DELIVERED, PING, SOURCES, TELEMETRY, FakeConsumer, envelope
from llobregat_consumer.consumer import Batch, StreamConsumer, next_offsets
from llobregat_consumer.sink import Written


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeSink:
    """Records the batches; `fail` makes the next writes lose the connection."""

    def __init__(self, consumer: FakeConsumer):
        self.consumer = consumer
        self.batches: list[tuple[list, list]] = []
        self.lag: list = []
        self.fail = 0
        self.closed = 0
        self.commits_seen_at_write: list[int] = []

    def sources(self):
        return set(SOURCES)

    def last_positions(self, group):
        return {}

    def write(self, rows, dead):
        self.commits_seen_at_write.append(len(self.consumer.commits))
        if self.fail:
            self.fail -= 1
            raise psycopg.OperationalError("server closed the connection unexpectedly")
        self.batches.append((list(rows), list(dead)))
        return Written(
            inserted=Counter(r.table for r in rows),
            rows=list(rows),
            dead_letters=list(dead),
            ingested_at=datetime(2026, 9, 29, 3, 0, tzinfo=UTC),
        )

    def record_lag(self, group, measurements):
        self.lag.append((group, measurements))

    def close(self):
        self.closed += 1


def pings(n: int, partition: int = 0, start: int = 0):
    return [
        envelope(
            "gps.pings",
            {**PING, "event_time": f"2026-09-28T06:{(i // 60) % 60:02d}:{i % 60:02d}Z"},
            partition=partition,
            offset=start + i,
        )
        for i in range(n)
    ]


@pytest.fixture
def setup(fake_consumer):
    clock = Clock()
    sink = FakeSink(fake_consumer)
    app = StreamConsumer(
        fake_consumer,
        sink,
        "test-group",
        batch_size=500,
        batch_wait_s=1.0,
        lag_interval_s=10.0,
        clock=clock,
        sleep=clock.sleep,
    )
    app.start()
    return app, fake_consumer, sink, clock


# -- the batch on its own -------------------------------------------------------------------------


def test_a_batch_is_due_when_full():
    batch = Batch(size=3, wait_s=1.0)
    for i, e in enumerate(pings(3)):
        assert not batch.due(0.0)
        batch.add(e, 0.0)
        assert batch.room == max(3 - (i + 1), 1)
    assert batch.due(0.0)
    assert [e.offset for e in batch.take()] == [0, 1, 2]
    assert len(batch) == 0 and not batch.due(100.0)


def test_a_batch_is_due_a_second_after_its_first_message():
    batch = Batch(size=500, wait_s=1.0)
    batch.add(pings(1)[0], 10.0)
    batch.add(pings(1, start=1)[0], 10.8)
    assert not batch.due(10.99)
    assert batch.time_left(10.5) == pytest.approx(0.5)
    assert batch.due(11.0)
    assert batch.time_left(12.0) == 0.0
    batch.take()
    assert batch.time_left(20.0) == 1.0  # an empty batch waits a whole second for its first message


def test_next_offsets_commits_after_the_last_message_of_each_partition():
    batch = [*pings(3, partition=0, start=5), *pings(2, partition=2, start=40), envelope("delivery.events", DELIVERED)]
    assert [(tp.topic, tp.partition, tp.offset) for tp in next_offsets(batch)] == [
        ("delivery.events", 0, 1),
        ("gps.pings", 0, 8),
        ("gps.pings", 2, 42),
    ]


# -- the loop -------------------------------------------------------------------------------------


def test_the_loop_writes_by_count(setup):
    app, broker, sink, clock = setup
    broker.send(*pings(1200))
    app.step()  # 500 arrive at once: written at once, without waiting for the second
    assert [len(rows) for rows, _ in sink.batches] == [500]
    app.step()
    app.step()
    assert [len(rows) for rows, _ in sink.batches] == [500, 500]
    app.step()  # the last 200 are not a full batch
    assert [len(rows) for rows, _ in sink.batches] == [500, 500]
    clock.now += 1.0
    app.step()
    assert [len(rows) for rows, _ in sink.batches] == [500, 500, 200]


def test_the_loop_writes_by_time(setup):
    app, broker, sink, clock = setup
    broker.send(*pings(3))
    app.step()
    assert sink.batches == []
    clock.now += 0.6
    broker.send(*pings(2, start=3))
    app.step()
    assert sink.batches == []  # 0.6 s after the first message
    clock.now += 0.4
    app.step()
    assert [len(rows) for rows, _ in sink.batches] == [5]


def test_offsets_are_committed_after_the_database_and_never_before(setup):
    app, broker, sink, clock = setup
    broker.send(*pings(3))
    app.step()
    clock.now += 1.0
    app.step()
    assert sink.commits_seen_at_write == [0]  # nothing committed when the batch was written
    assert [(tp.topic, tp.partition, tp.offset) for tp in broker.commits[-1]] == [("gps.pings", 0, 3)]


def test_nothing_is_committed_while_the_database_is_down(setup):
    app, broker, sink, clock = setup
    app.db_retry_s = 5.0
    sink.fail = 10
    broker.send(*pings(3))
    app.step()
    clock.now += 1.0
    with pytest.raises(psycopg.OperationalError):
        app.step()
    assert broker.commits == []  # the batch is read again after a restart
    assert sink.closed >= 1


def test_a_short_database_outage_is_retried_and_then_committed(setup):
    app, broker, sink, clock = setup
    sink.fail = 2
    broker.send(*pings(3))
    app.step()
    clock.now += 1.0
    app.step()
    assert len(sink.batches) == 1 and len(broker.commits) == 1
    assert sink.commits_seen_at_write == [0, 0, 0]


def test_dead_letters_go_with_the_batch_and_do_not_block_the_partition(setup):
    app, broker, sink, clock = setup
    broker.send(
        envelope("gps.pings", PING, offset=0),
        envelope("gps.pings", b"{broken", offset=1),
        envelope("gps.pings", {**PING, "event_time": "2026-09-28T06:15:10Z"}, offset=2),
        envelope("vehicle.telemetry", {**TELEMETRY, "vehicle_id": None}, offset=0),
    )
    app.step()
    clock.now += 1.0
    app.step()
    rows, dead = sink.batches[0]
    assert [(r.table, r.envelope.offset) for r in rows] == [("gps_pings", 0), ("gps_pings", 2)]
    assert [(d.envelope.topic, d.envelope.offset, d.reason) for d in dead] == [
        ("gps.pings", 1, "invalid_json"),
        ("vehicle.telemetry", 0, "missing_field"),
    ]
    committed = {(tp.topic, tp.partition): tp.offset for tp in broker.commits[-1]}
    assert committed == {("gps.pings", 0): 3, ("vehicle.telemetry", 0): 1}  # past the dead letters
    assert app.status.dead_letters == {"gps.pings": 1, "vehicle.telemetry": 1}


def test_a_source_registered_after_the_start_is_picked_up(setup):
    app, broker, sink, clock = setup
    app.sources = {"simulator/telemetry"}  # as if simulator/gps had been registered after the start
    app.sources_loaded = clock.now - 61
    broker.send(*pings(1))
    app.step()
    clock.now += 1.0
    app.step()
    rows, dead = sink.batches[0]
    assert len(rows) == 1 and dead == []


def test_the_lag_and_the_newest_event_time_are_recorded_per_partition(setup):
    app, broker, sink, clock = setup
    broker.partitions = [("gps.pings", 0), ("gps.pings", 1)]
    broker.send(*pings(3, partition=0), *pings(4, partition=1))
    app.step()  # first step: the lag is measured at once, before anything is written
    group, first = sink.lag[-1]
    assert group == "test-group"
    assert [(m.partition, m.committed_offset, m.end_offset, m.lag) for m in first] == [(0, None, 3, 3), (1, None, 4, 4)]
    clock.now += 10.0
    app.step()  # the batch is due and written, then the lag measured
    _, second = sink.lag[-1]
    assert [(m.partition, m.committed_offset, m.lag) for m in second] == [(0, 3, 0), (1, 4, 0)]
    assert second[0].last_event_time == datetime(2026, 9, 28, 6, 0, 2, tzinfo=UTC)
    assert second[1].last_event_time == datetime(2026, 9, 28, 6, 0, 3, tzinfo=UTC)
    assert second[0].last_ingested_at == datetime(2026, 9, 29, 3, 0, tzinfo=UTC)
    assert app.status.lag == 0


def test_the_health_report(setup):
    app, broker, sink, clock = setup
    healthy, report = app.status.report(clock.now)
    assert not healthy and report["assigned_partitions"] == 0  # no partitions and no poll yet
    app.step()
    healthy, report = app.status.report(clock.now)
    assert healthy and report["lag"] == 0 and report["assigned_partitions"] == 1
    healthy, report = app.status.report(clock.now + 31)
    assert not healthy and report["status"] == "unhealthy"  # stopped polling


def test_a_revoked_partition_writes_its_batch_first(setup):
    app, broker, sink, clock = setup
    broker.send(*pings(3))
    app.step()
    assert sink.batches == []
    broker.on_consume = lambda: broker.callbacks["on_revoke"](broker, broker.assignment())
    app.step()
    assert len(sink.batches[0][0]) == 3 and len(broker.commits) == 1


def test_run_writes_what_is_left_and_closes(fake_consumer):
    clock = Clock()
    sink = FakeSink(fake_consumer)
    app = StreamConsumer(fake_consumer, sink, "g", clock=clock, sleep=clock.sleep)
    stop = threading.Event()
    fake_consumer.send(*pings(2))
    fake_consumer.on_consume = stop.set  # stop after the first poll
    app.run(stop)
    assert len(sink.batches[0][0]) == 2 and len(fake_consumer.commits) == 1
    assert fake_consumer.closed and fake_consumer.topics == ["gps.pings", "vehicle.telemetry", "delivery.events"]
