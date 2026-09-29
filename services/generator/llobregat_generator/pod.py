"""Proof-of-delivery photos: synthetic placeholder JPEGs drawn by code, with real EXIF metadata.

When a parcel is delivered, the driver's handheld photographs it at the door. A simulation has no
camera, so the photo is a placeholder that this module draws with Pillow: a wall, a door with an
intercom, the order's parcels on the doorstep and a caption with the order id, the delivery time
and the position. It is neither a photograph nor an AI-generated image, and it says so in the
picture and in its EXIF ImageDescription. The colours and the door vary with the order id, so a
set of photos does not look like one picture.

What it carries is what a real proof-of-delivery photo carries, as EXIF metadata a program reads
without looking at the pixels: when it was taken (DateTimeOriginal in Barcelona time with its UTC
offset in OffsetTimeOriginal, and GPSDateStamp and GPSTimeStamp in UTC) and where (GPSLatitude and
GPSLongitude of the delivery address, WGS84).

upload() stores a photo in the RustFS bronze bucket at pod/<service date>/<order id>.jpg and
returns the key, which the simulator (issue #7) writes into bronze.delivery_events.pod_object_key
of the `delivered` event. The object carries the metadata elements of ADR 0001, decision 20, as S3
user metadata. `llobregat-generator pod-sample` uploads a few for one generated date under
pod/samples/, so the documentation can point at real objects before the simulator exists.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np
from PIL import ExifTags, Image, ImageDraw, ImageFont
from PIL.TiffImagePlugin import IFDRational

from llobregat_generator import __version__
from llobregat_generator.metadata import FileMetadata
from llobregat_generator.orders import LOCAL_TZ
from llobregat_generator.storage import Bucket

SOURCE_ID = "simulator/pod-photos"
TABLE = "bronze.delivery_events"  # records the key of every photo, so the photo takes its owner and version
PREFIX = "pod"
SAMPLE_PREFIX = "pod/samples"
SIZE = (640, 480)
JPEG_QUALITY = 85
GPS_SECONDS_DENOMINATOR = 10_000  # a ten-thousandth of an arc second, about 3 mm
EXIF_TIME = "%Y:%m:%d %H:%M:%S"
DESCRIPTION = (
    "Llobregat Express proof of delivery of order {order_id}. "
    "Synthetic placeholder drawn by code, not a photograph and not an AI-generated image."
)
# Third entropy word of the sample's random stream (25, for issue #25).
SAMPLE_STREAM = 25

# How a Barcelona doorway looks, roughly: plaster in ochre, cream, terracotta, white or pink, and
# a green, blue, wooden, red, black or grey door.
WALLS = ((225, 196, 150), (236, 224, 200), (199, 128, 96), (230, 230, 224), (219, 182, 176))
DOORS = ((47, 84, 60), (40, 64, 112), (100, 64, 38), (126, 38, 38), (36, 36, 40), (108, 110, 114))
CARDBOARD = (176, 134, 86)
TAPE = (222, 202, 150)
BOX_SIZE = {"small": (62, 44), "medium": (92, 64), "large": (128, 90)}  # front face in pixels
MAX_BOXES = 3


@dataclass(frozen=True)
class Delivery:
    """A delivered stop, as much of it as its photo needs."""

    order_id: str
    service_date: date
    delivered_at: datetime  # with a time zone
    lat: float
    lon: float
    parcels: int = 1
    parcel_size: str = "small"

    def __post_init__(self):
        if self.delivered_at.tzinfo is None:
            raise ValueError(f"delivered_at of {self.order_id} has no time zone")


@dataclass(frozen=True)
class Capture:
    """What the EXIF metadata of a photo says: when and where it was taken."""

    taken_at: datetime
    lat: float
    lon: float


def object_key(delivery: Delivery, sample: bool = False) -> str:
    """pod/<service date>/<order id>.jpg, or under pod/samples/ for a sample."""
    return f"{SAMPLE_PREFIX if sample else PREFIX}/{delivery.service_date.isoformat()}/{delivery.order_id}.jpg"


def sample_prefix(service_date: date) -> str:
    return f"{SAMPLE_PREFIX}/{service_date.isoformat()}/"


# Drawing -------------------------------------------------------------------------------------


def _look(order_id: str) -> np.random.Generator:
    """The random generator of an order's picture: the same order always looks the same."""
    return np.random.default_rng(list(hashlib.sha256(order_id.encode()).digest()[:16]))


def _shade(colour: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, round(c * factor))) for c in colour)


def _box(draw: ImageDraw.ImageDraw, rng: np.random.Generator, x: int, bottom: int, width: int, height: int) -> None:
    """A parcel in perspective: front, top and side, tape across and a label with a barcode."""
    depth, top = height // 3, bottom - height
    draw.polygon(
        [(x, top), (x + depth, top - depth), (x + width + depth, top - depth), (x + width, top)],
        fill=_shade(CARDBOARD, 1.15),
    )
    draw.polygon(
        [(x + width, bottom), (x + width, top), (x + width + depth, top - depth), (x + width + depth, bottom - depth)],
        fill=_shade(CARDBOARD, 0.8),
    )
    draw.rectangle([x, top, x + width, bottom], fill=CARDBOARD)
    middle = x + width // 2
    draw.rectangle([middle - 5, top, middle + 5, bottom], fill=TAPE)
    draw.polygon(
        [(middle - 5, top), (middle - 5 + depth, top - depth), (middle + 5 + depth, top - depth), (middle + 5, top)],
        fill=TAPE,
    )
    label_right, label_top = x + max(20, width // 2 - 10), bottom - max(16, height // 2)
    draw.rectangle([x + 6, label_top, label_right, bottom - 6], fill=(248, 248, 244))
    bar = x + 9
    while bar < label_right - 4:
        stroke = int(rng.integers(1, 3))
        draw.line([(bar, label_top + 3), (bar, bottom - 9)], fill=(20, 20, 20), width=stroke)
        bar += stroke + int(rng.integers(1, 4))


def _draw(delivery: Delivery) -> Image.Image:
    rng = _look(delivery.order_id)
    wall, door = WALLS[int(rng.integers(len(WALLS)))], DOORS[int(rng.integers(len(DOORS)))]
    width, height = SIZE
    ground, caption = 372, 424
    image = Image.new("RGB", SIZE, wall)
    draw = ImageDraw.Draw(image)

    for y in range(46, ground - 26, 44):  # plaster joints and a skirting
        draw.line([(0, y), (width, y)], fill=_shade(wall, 0.94), width=1)
    draw.rectangle([0, ground - 26, width, ground], fill=_shade(wall, 0.78))
    draw.rectangle([0, ground, width, caption], fill=(168, 164, 158))  # pavement
    for x in range(-40, width, 64):
        draw.line([(x, ground), (x + 40, caption)], fill=(150, 146, 140), width=2)

    left, top, right = 150, 70, 330  # the door: frame, leaf, panels, handle, doorstep
    draw.rectangle([left - 14, top - 14, right + 14, ground], fill=_shade(door, 0.6))
    draw.rectangle([left, top, right, ground - 6], fill=door)
    rows = 1 if rng.random() < 0.5 else 2
    panel_height = (ground - top - 40 - 12 * (rows - 1)) // rows
    for column in range(2):
        for row in range(rows):
            x0 = left + 18 + column * ((right - left - 36) // 2 + 6)
            y0 = top + 20 + row * (panel_height + 12)
            draw.rectangle(
                [x0, y0, x0 + (right - left - 36) // 2 - 6, y0 + panel_height], outline=_shade(door, 0.72), width=3
            )
    draw.rounded_rectangle([right - 34, 206, right - 22, 250], radius=4, fill=(206, 190, 140))
    draw.rectangle([left - 26, ground - 8, right + 26, ground + 8], fill=(192, 188, 180))
    intercom = right + 44  # a porter automàtic with its buttons
    draw.rectangle([intercom, 170, intercom + 36, 262], fill=(158, 158, 160), outline=(96, 96, 98), width=2)
    draw.rectangle([intercom + 8, 178, intercom + 28, 194], fill=(70, 70, 72))
    for y in range(204, 256, 12):
        draw.ellipse([intercom + 14, y, intercom + 22, y + 8], fill=(226, 226, 226))

    boxes = min(max(delivery.parcels, 1), MAX_BOXES)
    box_width, box_height = BOX_SIZE.get(delivery.parcel_size, BOX_SIZE["small"])
    x, bottom = 236, 414
    for n in range(boxes):
        scale = float(rng.uniform(0.9, 1.1))
        w, h = round(box_width * scale), round(box_height * scale)
        if n == 0:
            first_top = bottom - h
        if n < 2:
            _box(draw, rng, x, bottom, w, h)
            x += w + h // 3 + 8
        else:  # the third parcel goes on top of the first
            _box(draw, rng, 244, first_top - 2, round(w * 0.8), round(h * 0.8))

    big, small = ImageFont.load_default(size=19), ImageFont.load_default(size=13)
    draw.rectangle([0, 0, width, 24], fill=(20, 20, 24))
    draw.text((12, 5), "LLOBREGAT EXPRESS  ·  PROOF OF DELIVERY", font=small, fill=(235, 235, 235))
    draw.rectangle([0, caption, width, height], fill=(20, 20, 24))
    local = delivery.delivered_at.astimezone(LOCAL_TZ)
    draw.text((12, caption + 6), f"{delivery.order_id}   {local:%d/%m/%Y %H:%M}", font=big, fill=(245, 245, 245))
    position = f"{delivery.lat:.5f}, {delivery.lon:.5f}"
    draw.text((width - 12 - draw.textlength(position, font=big), caption + 6), position, font=big, fill=(245, 245, 245))
    notice = "SYNTHETIC PLACEHOLDER DRAWN BY CODE, NOT A PHOTOGRAPH"
    draw.text((12, caption + 32), notice, font=small, fill=(250, 190, 60))
    return image


# EXIF ----------------------------------------------------------------------------------------


def _dms(value: float) -> tuple[IFDRational, IFDRational, IFDRational]:
    """Degrees, minutes and seconds of an angle, as the three rationals of an EXIF GPS coordinate.

    The angle is rounded once, to a ten-thousandth of an arc second, and then split, so the seconds
    are always below 60: taking whole minutes off a float first turns 41.3 into 41° 17′ 60″.
    """
    total = round(abs(value) * 3600 * GPS_SECONDS_DENOMINATOR)  # in ten-thousandths of an arc second
    arc_minutes, seconds = divmod(total, 60 * GPS_SECONDS_DENOMINATOR)
    degrees, minutes = divmod(arc_minutes, 60)
    return IFDRational(degrees, 1), IFDRational(minutes, 1), IFDRational(seconds, GPS_SECONDS_DENOMINATOR)


def _degrees(dms: Sequence, ref: str) -> float:
    value = float(dms[0]) + float(dms[1]) / 60 + float(dms[2]) / 3600
    return -value if ref in ("S", "W") else value


def exif(delivery: Delivery) -> Image.Exif:
    """EXIF metadata of the photo: what it is, when and where it was taken."""
    local = delivery.delivered_at.astimezone(LOCAL_TZ)
    utc = delivery.delivered_at.astimezone(UTC)
    offset = local.strftime("%z")
    tags = Image.Exif()
    tags[ExifTags.Base.ImageDescription] = DESCRIPTION.format(order_id=delivery.order_id)
    tags[ExifTags.Base.Software] = f"llobregat-generator {__version__}"
    tags[ExifTags.Base.DateTime] = local.strftime(EXIF_TIME)
    photo = tags.get_ifd(ExifTags.IFD.Exif)
    photo[ExifTags.Base.DateTimeOriginal] = local.strftime(EXIF_TIME)
    photo[ExifTags.Base.OffsetTimeOriginal] = f"{offset[:3]}:{offset[3:]}"
    gps = tags.get_ifd(ExifTags.IFD.GPSInfo)
    gps[ExifTags.GPS.GPSVersionID] = b"\x02\x03\x00\x00"
    gps[ExifTags.GPS.GPSLatitudeRef] = "N" if delivery.lat >= 0 else "S"
    gps[ExifTags.GPS.GPSLatitude] = _dms(delivery.lat)
    gps[ExifTags.GPS.GPSLongitudeRef] = "E" if delivery.lon >= 0 else "W"
    gps[ExifTags.GPS.GPSLongitude] = _dms(delivery.lon)
    gps[ExifTags.GPS.GPSMapDatum] = "WGS-84"
    gps[ExifTags.GPS.GPSDateStamp] = utc.strftime("%Y:%m:%d")
    gps[ExifTags.GPS.GPSTimeStamp] = tuple(IFDRational(v, 1) for v in (utc.hour, utc.minute, utc.second))
    return tags


def render(delivery: Delivery) -> bytes:
    """The photo of a delivery as JPEG bytes with its EXIF metadata. The same delivery gives the same bytes."""
    buffer = io.BytesIO()
    _draw(delivery).save(buffer, "JPEG", quality=JPEG_QUALITY, optimize=True, exif=exif(delivery))
    return buffer.getvalue()


def read_exif(jpeg: bytes) -> Capture:
    """When and where a photo was taken, read from its EXIF metadata alone."""
    tags = Image.open(io.BytesIO(jpeg)).getexif()
    photo, gps = tags.get_ifd(ExifTags.IFD.Exif), tags.get_ifd(ExifTags.IFD.GPSInfo)
    taken_at = datetime.strptime(
        photo[ExifTags.Base.DateTimeOriginal] + photo[ExifTags.Base.OffsetTimeOriginal], EXIF_TIME + "%z"
    )
    return Capture(
        taken_at=taken_at,
        lat=_degrees(gps[ExifTags.GPS.GPSLatitude], gps[ExifTags.GPS.GPSLatitudeRef]),
        lon=_degrees(gps[ExifTags.GPS.GPSLongitude], gps[ExifTags.GPS.GPSLongitudeRef]),
    )


# Storage -------------------------------------------------------------------------------------


def upload(bucket: Bucket, delivery: Delivery, metadata: FileMetadata, sample: bool = False) -> str:
    """Store the photo of a delivered stop in the bronze bucket; return its key for pod_object_key.

    metadata gives the object source, owner, schema version and ingested_at (FileMetadata.for_table
    with TABLE and SOURCE_ID); the order id is added.
    """
    user_metadata = {name.replace("_", "-"): value for name, value in metadata.key_values().items()}
    return bucket.put_bytes(
        object_key(delivery, sample), render(delivery), {**user_metadata, "order-id": delivery.order_id}
    )


def sample_deliveries(orders: Sequence[dict], count: int, seed: int = 0) -> Iterator[Delivery]:
    """Deliveries for `count` of a day's orders, at a time inside each order's window.

    The orders and times are drawn from a random stream of the date and the seed: a larger count
    keeps the orders and times of a smaller one. Placeholders for the documentation only; the
    simulator (issue #7) delivers the real stops.
    """
    if not orders:
        return
    service_date = orders[0]["service_date"]
    rng = np.random.default_rng([seed, service_date.toordinal(), SAMPLE_STREAM])
    order = rng.permutation(len(orders))
    moments = rng.random(len(orders))
    for index in sorted(order[:count]):
        o = orders[index]
        window = int((o["window_end"] - o["window_start"]).total_seconds())
        yield Delivery(
            order_id=o["order_id"],
            service_date=o["service_date"],
            delivered_at=o["window_start"] + timedelta(seconds=int(moments[index] * window)),
            lat=o["destination_lat"],
            lon=o["destination_lon"],
            parcels=o["parcels"],
            parcel_size=o["parcel_size"],
        )
