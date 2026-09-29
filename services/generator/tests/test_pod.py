"""Proof-of-delivery placeholders: a JPEG drawn by code whose EXIF says when and where it was taken."""

from __future__ import annotations

import io
from contextlib import nullcontext
from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import MONDAY
from llobregat_generator import cli, pod
from llobregat_generator.metadata import FileMetadata
from llobregat_generator.orders import LOCAL_TZ
from llobregat_generator.rules import ParcelSize
from llobregat_generator.storage import CHECKSUM
from PIL import ExifTags, Image

SUMMER = pod.Delivery(
    "O-20260928-00042",
    date(2026, 9, 28),
    datetime(2026, 9, 28, 10, 15, 7, tzinfo=LOCAL_TZ),
    pod.LatLon(41.3921234, 2.1614567),
)
WINTER = pod.Delivery(
    "O-20261214-00007",
    date(2026, 12, 14),
    datetime(2026, 12, 14, 19, 58, 31, tzinfo=LOCAL_TZ),
    pod.LatLon(41.3544455, 2.0716612),
    parcels=3,
    parcel_size="large",
)


@pytest.mark.parametrize(
    ("delivery", "local_time", "offset", "utc_date", "utc_time"),
    [
        (SUMMER, "2026:09:28 10:15:07", "+02:00", "2026:09:28", (8, 15, 7)),
        (WINTER, "2026:12:14 19:58:31", "+01:00", "2026:12:14", (18, 58, 31)),
    ],
    ids=["summer-time", "winter-time"],
)
def test_the_exif_of_a_photo_says_when_and_where_it_was_taken(delivery, local_time, offset, utc_date, utc_time):
    jpeg = pod.render(delivery)
    capture = pod.read_exif(jpeg)
    assert capture.taken_at == delivery.delivered_at
    assert capture.position.lat == pytest.approx(delivery.position.lat, abs=1e-7)  # about a centimetre
    assert capture.position.lon == pytest.approx(delivery.position.lon, abs=1e-7)
    assert capture.matches(delivery)

    # The tags as a camera writes them, which any EXIF reader understands.
    tags = Image.open(io.BytesIO(jpeg)).getexif()
    photo, gps = tags.get_ifd(ExifTags.IFD.Exif), tags.get_ifd(ExifTags.IFD.GPSInfo)
    assert photo[ExifTags.Base.DateTimeOriginal] == local_time
    assert photo[ExifTags.Base.OffsetTimeOriginal] == offset
    assert (gps[ExifTags.GPS.GPSLatitudeRef], gps[ExifTags.GPS.GPSLongitudeRef]) == ("N", "E")
    assert gps[ExifTags.GPS.GPSMapDatum] == "WGS-84"
    assert gps[ExifTags.GPS.GPSDateStamp] == utc_date
    assert tuple(int(v) for v in gps[ExifTags.GPS.GPSTimeStamp]) == utc_time
    assert delivery.order_id in tags[ExifTags.Base.ImageDescription]
    assert "Synthetic placeholder drawn by code" in tags[ExifTags.Base.ImageDescription]


def test_southern_and_western_coordinates_keep_their_sign():
    delivery = pod.Delivery("O-1", date(2026, 9, 28), SUMMER.delivered_at, pod.LatLon(-33.4488897, -70.6692655))
    capture = pod.read_exif(pod.render(delivery))
    assert capture.position == pod.LatLon(pytest.approx(-33.4488897, abs=1e-7), pytest.approx(-70.6692655, abs=1e-7))
    assert capture.matches(delivery)


def test_a_capture_matches_only_its_delivery_time_and_position():
    capture = pod.read_exif(pod.render(SUMMER))
    moved = pod.LatLon(SUMMER.position.lat + 2e-6, SUMMER.position.lon)  # about 22 cm north
    assert not capture.matches(pod.Delivery(SUMMER.order_id, SUMMER.service_date, SUMMER.delivered_at, moved))
    later = SUMMER.delivered_at + timedelta(seconds=1)
    assert not capture.matches(pod.Delivery(SUMMER.order_id, SUMMER.service_date, later, SUMMER.position))


@pytest.mark.parametrize(
    ("angle", "dms"),
    [
        (41.3, (41, 18, 0)),  # 41° 18′ exactly; 41.3 - 41 is 0.29999999999999716 as a float
        (41 + 18 / 60 - 0.00004 / 3600, (41, 18, 0)),  # rounds up across the minute
        (41 + 18 / 60 - 0.0002 / 3600, (41, 17, 59.9998)),  # just below the minute
        (2 + 10 / 60 - 0.00004 / 3600, (2, 10, 0)),
        (59.99999999, (60, 0, 0)),  # rounds up across the degree
        (2.1534189, (2, 9, 12.308)),
    ],
    ids=["41.3", "rounds-up-to-the-minute", "just-below-the-minute", "longitude", "rounds-up-to-the-degree", "address"],
)
def test_gps_seconds_are_rounded_once_and_stay_below_a_minute(angle, dms):
    degrees, minutes, seconds = pod._dms(angle)
    assert (degrees.denominator, minutes.denominator) == (1, 1)
    assert (int(degrees), int(minutes), float(seconds)) == pytest.approx(dms, abs=1e-9)
    assert 0 <= float(seconds) < 60
    assert pod._degrees((degrees, minutes, seconds), "N") == pytest.approx(angle, abs=1e-4 / 3600)


def test_a_photo_is_a_jpeg_drawn_the_same_way_every_time():
    jpeg = pod.render(SUMMER)
    image = Image.open(io.BytesIO(jpeg))
    assert (image.format, image.size, image.mode) == ("JPEG", pod.SIZE, "RGB")
    assert pod.render(SUMMER) == jpeg
    assert pod.render(WINTER) != jpeg


def test_a_delivery_needs_a_time_zone():
    with pytest.raises(ValueError, match="no time zone"):
        pod.Delivery("O-1", date(2026, 9, 28), datetime(2026, 9, 28, 10, 15), pod.LatLon(41.39, 2.16))


def test_a_delivery_takes_a_parcel_size_of_the_orders_and_no_other():
    medium = pod.Delivery("O-1", date(2026, 9, 28), SUMMER.delivered_at, pod.LatLon(41.39, 2.16), 2, "medium")
    assert medium.parcel_size is ParcelSize.MEDIUM
    assert set(pod.BOX_SIZE) == set(ParcelSize)
    with pytest.raises(ValueError, match="'huge' is not a valid ParcelSize"):
        pod.Delivery("O-1", date(2026, 9, 28), SUMMER.delivered_at, pod.LatLon(41.39, 2.16), 2, "huge")


def test_object_keys():
    assert pod.object_key(SUMMER) == "pod/2026-09-28/O-20260928-00042.jpg"
    assert pod.object_key(SUMMER, sample=True) == "pod/samples/2026-09-28/O-20260928-00042.jpg"
    assert pod.sample_prefix(SUMMER.service_date) == "pod/samples/2026-09-28/"


class MemoryBucket:
    """The bronze bucket in memory, with the upload rule of Bucket.put_bytes; log lists every put and delete."""

    def __init__(self, objects: dict[str, tuple[bytes, dict[str, str]]] | None = None):
        self.objects = dict(objects or {})
        self.written: list[str] = []
        self.log: list[tuple[str, str]] = []

    def fresh(self) -> MemoryBucket:
        """The same objects, as a new Bucket for the next run sees them."""
        self.written, self.log = [], []
        return self

    def put_bytes(self, key, body, metadata=None, checksum=None):
        if checksum is not None and self.objects.get(key, (b"", {}))[1].get(CHECKSUM) == checksum:
            return key
        self.objects[key] = (body, {**(metadata or {}), **({CHECKSUM: checksum} if checksum else {})})
        self.written.append(key)
        self.log.append(("put", key))
        return key

    def get_bytes(self, key):
        return self.objects[key][0]

    def user_metadata(self, key):
        return self.objects[key][1]

    def delete_prefix(self, prefix, keep=()):
        stale = [key for key in self.objects if key.startswith(prefix) and key not in keep]
        for key in stale:
            del self.objects[key]
            self.log.append(("delete", key))
        return len(stale)


def photo_metadata(ingested_at: datetime, schema_version: int = 2) -> FileMetadata:
    return FileMetadata(pod.SOURCE_ID, "operations", schema_version, ingested_at)


def test_upload_stores_the_photo_with_the_metadata_elements():
    bucket = MemoryBucket()
    key = pod.upload(bucket, SUMMER, photo_metadata(datetime(2026, 9, 29, 6, 30, tzinfo=UTC)))
    assert key == "pod/2026-09-28/O-20260928-00042.jpg"
    body, user_metadata = bucket.objects[key]
    assert body == pod.render(SUMMER)
    assert user_metadata.pop(CHECKSUM)
    assert user_metadata == {
        "source": "simulator/pod-photos",
        "owner": "operations",
        "schema-version": "2",
        "ingested-at": "2026-09-29T06:30:00+00:00",
        "order-id": "O-20260928-00042",
    }


def test_the_same_photo_is_uploaded_once_and_keeps_its_ingested_at():
    bucket = MemoryBucket()
    first = datetime(2026, 9, 29, 6, 30, tzinfo=UTC)
    pod.upload(bucket, SUMMER, photo_metadata(first))
    pod.upload(bucket, SUMMER, photo_metadata(first + timedelta(days=1)))  # the same photo, a later run
    assert [op for op, _ in bucket.log] == ["put"]
    assert bucket.objects[pod.object_key(SUMMER)][1]["ingested-at"] == first.isoformat()
    pod.upload(bucket, SUMMER, photo_metadata(first, schema_version=3))  # new metadata elements
    assert [op for op, _ in bucket.log] == ["put", "put"]


@pytest.fixture
def stack(weekday, monkeypatch) -> MemoryBucket:
    """pod-sample's database and bucket: the Monday of the tests, and a bucket in memory."""
    bucket = MemoryBucket()
    monkeypatch.setattr(cli.db, "connect", lambda settings: nullcontext())
    monkeypatch.setattr(cli.publish, "read_day", lambda conn, service_date: weekday.orders)
    monkeypatch.setattr(
        cli.FileMetadata, "for_table", classmethod(lambda cls, conn, table, source, at: photo_metadata(at))
    )
    monkeypatch.setattr(cli, "Bucket", lambda settings: bucket.fresh())
    return bucket


def pod_sample(count: int) -> int:
    return cli.main(["pod-sample", "--date", MONDAY.isoformat(), "--count", str(count)])


def test_pod_sample_uploads_first_then_removes_only_the_photos_not_in_the_new_sample(stack, capsys):
    stale = f"{pod.sample_prefix(MONDAY)}O-20261005-99999.jpg"
    stack.objects[stale] = (b"a photo of an earlier sample", {})
    assert pod_sample(5) == 0
    puts = [key for op, key in stack.log if op == "put"]
    assert len(puts) == 5
    assert stack.log == [*(("put", key) for key in puts), ("delete", stale)]  # every upload before the delete
    out = capsys.readouterr().out
    assert "5 photos in bronze/pod/samples/2026-10-05/: 5 written, 0 unchanged, 1 of an earlier sample removed" in out
    assert "read back: EXIF time and position match 5 of 5, S3 user metadata matches 5 of 5" in out

    assert pod_sample(3) == 0  # a smaller sample: its photos are among the five, left as they are
    assert [op for op, _ in stack.log] == ["delete", "delete"]
    assert "3 photos in bronze/pod/samples/2026-10-05/: 0 written, 3 unchanged, 2 of" in capsys.readouterr().out


def test_pod_sample_fails_when_a_photo_does_not_read_back_as_uploaded(stack, capsys):
    assert pod_sample(2) == 0
    key = next(iter(stack.objects))
    stack.objects[key][1]["owner"] = "someone else"  # the same checksum, so it is not written again
    assert pod_sample(2) == 1
    out = capsys.readouterr().out
    assert "S3 METADATA DOES NOT MATCH" in out and "S3 user metadata matches 1 of 2" in out


def test_sample_deliveries_are_orders_of_the_day_inside_their_windows(weekday):
    sample = list(pod.sample_deliveries(weekday.orders, 20))
    assert len(sample) == 20
    by_id = {o["order_id"]: o for o in weekday.orders}
    for delivery in sample:
        order = by_id[delivery.order_id]
        assert order["window_start"] <= delivery.delivered_at < order["window_end"]
        assert delivery.position == pod.LatLon(order["destination_lat"], order["destination_lon"])
        assert delivery.service_date == MONDAY
        assert delivery.delivered_at.astimezone(LOCAL_TZ).date() == MONDAY
    assert list(pod.sample_deliveries(weekday.orders, 20)) == sample  # the same every time
    smaller = list(pod.sample_deliveries(weekday.orders, 5))
    assert set(smaller) <= set(sample)  # a larger sample keeps the orders and times of a smaller one
    assert list(pod.sample_deliveries(weekday.orders, 20, seed=1)) != sample
    assert all(d.delivered_at - by_id[d.order_id]["window_start"] < timedelta(hours=6) for d in sample)
