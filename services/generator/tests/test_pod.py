"""Proof-of-delivery placeholders: a JPEG drawn by code whose EXIF says when and where it was taken."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, timedelta

import pytest
from conftest import MONDAY
from llobregat_generator import pod
from llobregat_generator.metadata import FileMetadata
from llobregat_generator.orders import LOCAL_TZ
from PIL import ExifTags, Image

SUMMER = pod.Delivery(
    "O-20260928-00042", date(2026, 9, 28), datetime(2026, 9, 28, 10, 15, 7, tzinfo=LOCAL_TZ), 41.3921234, 2.1614567
)
WINTER = pod.Delivery(
    "O-20261214-00007",
    date(2026, 12, 14),
    datetime(2026, 12, 14, 19, 58, 31, tzinfo=LOCAL_TZ),
    41.3544455,
    2.0716612,
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
    assert capture.lat == pytest.approx(delivery.lat, abs=1e-7)  # about a centimetre
    assert capture.lon == pytest.approx(delivery.lon, abs=1e-7)

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
    delivery = pod.Delivery("O-1", date(2026, 9, 28), SUMMER.delivered_at, -33.4488897, -70.6692655)
    capture = pod.read_exif(pod.render(delivery))
    assert (capture.lat, capture.lon) == (pytest.approx(-33.4488897, abs=1e-7), pytest.approx(-70.6692655, abs=1e-7))


def test_a_photo_is_a_jpeg_drawn_the_same_way_every_time():
    jpeg = pod.render(SUMMER)
    image = Image.open(io.BytesIO(jpeg))
    assert (image.format, image.size, image.mode) == ("JPEG", pod.SIZE, "RGB")
    assert pod.render(SUMMER) == jpeg
    assert pod.render(WINTER) != jpeg


def test_a_delivery_needs_a_time_zone():
    with pytest.raises(ValueError, match="no time zone"):
        pod.Delivery("O-1", date(2026, 9, 28), datetime(2026, 9, 28, 10, 15), 41.39, 2.16)


def test_object_keys():
    assert pod.object_key(SUMMER) == "pod/2026-09-28/O-20260928-00042.jpg"
    assert pod.object_key(SUMMER, sample=True) == "pod/samples/2026-09-28/O-20260928-00042.jpg"
    assert pod.sample_prefix(SUMMER.service_date) == "pod/samples/2026-09-28/"


class RecordingBucket:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, dict]] = {}

    def put_bytes(self, key, body, metadata=None):
        self.objects[key] = (body, metadata)
        return key


def test_upload_stores_the_photo_with_the_metadata_elements():
    bucket = RecordingBucket()
    ingested_at = datetime(2026, 9, 29, 6, 30, tzinfo=UTC)
    metadata = FileMetadata(pod.SOURCE_ID, "operations", 2, ingested_at)
    key = pod.upload(bucket, SUMMER, metadata)
    assert key == "pod/2026-09-28/O-20260928-00042.jpg"
    body, user_metadata = bucket.objects[key]
    assert body == pod.render(SUMMER)
    assert user_metadata == {
        "source": "simulator/pod-photos",
        "owner": "operations",
        "schema-version": "2",
        "ingested-at": "2026-09-29T06:30:00+00:00",
        "order-id": "O-20260928-00042",
    }


def test_sample_deliveries_are_orders_of_the_day_inside_their_windows(weekday):
    sample = list(pod.sample_deliveries(weekday.orders, 20))
    assert len(sample) == 20
    by_id = {o["order_id"]: o for o in weekday.orders}
    for delivery in sample:
        order = by_id[delivery.order_id]
        assert order["window_start"] <= delivery.delivered_at < order["window_end"]
        assert (delivery.lat, delivery.lon) == (order["destination_lat"], order["destination_lon"])
        assert delivery.service_date == MONDAY
        assert delivery.delivered_at.astimezone(LOCAL_TZ).date() == MONDAY
    assert list(pod.sample_deliveries(weekday.orders, 20)) == sample  # the same every time
    smaller = list(pod.sample_deliveries(weekday.orders, 5))
    assert set(smaller) <= set(sample)  # a larger sample keeps the orders and times of a smaller one
    assert list(pod.sample_deliveries(weekday.orders, 20, seed=1)) != sample
    assert all(d.delivered_at - by_id[d.order_id]["window_start"] < timedelta(hours=6) for d in sample)
