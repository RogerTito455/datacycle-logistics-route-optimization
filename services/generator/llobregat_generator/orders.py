"""One day of orders, drawn from the demand model (prompt 004) at real postal addresses.

The date is the service date, the day the parcels are delivered. The steps follow the demand
model's fields and its written assumptions:

1. Day total: a normal draw with the weekday mean and standard deviation of company.json, times
   the weekday multiplier and the seasonal peak (seasonal_multiplier). No service on Sunday.
2. The total is split by shipper share into consumer and business parcels (business_share). On
   Saturday only shops and healthcare receive business parcels, and consumer parcels are scaled up
   to keep the total.
3. Parcels are grouped into stops by the parcels-per-stop distribution. A stop is one order: one
   shipper, one address, one parcel size.
4. Zone: the day's total is split over the zones by their share with the largest-remainder
   method, as it is split over the shippers. A business shipper's parcels are split the same way
   over its business zones, and consumer parcels fill what the business parcels left of each zone.
   Each stop goes to a zone drawn in proportion to the parcels that zone still needs, so every zone
   ends within a few parcels of its share. Then a real address in it.
5. Registration time from the hourly curve. Only midday-injection shippers sell same-day, only
   before the 11:00 cut-off, with probability same_day_share / (share registered before 11:00);
   every other order is next-day and was registered the day before (for a Monday, on Saturday or
   Sunday).
6. Wave and window: same-day and midday parcels go in the afternoon-evening wave, other business
   parcels in the morning wave, other consumer parcels by the consumer window choice. Consumers
   pick a 120-minute slot with specific_slot_share, otherwise accept the whole wave; business
   recipients get a 120-minute window inside their opening hours.
7. Delivery notes: about a third of the orders carry a note of the corpus (prompt 008), by the
   rules in notes.py.

Everything random in steps 1-6 comes from one generator seeded with (seed, date), and the notes of
step 7 from a second one seeded with (seed, date, NOTES_STREAM), so a date and a seed always give
the same orders, and the notes change none of their other fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from llobregat_generator.addresses import Address
from llobregat_generator.notes import NOTES_STREAM, NotePicker, attach_notes
from llobregat_generator.rules import (
    MIDDAY_INJECTION,
    Recipient,
    SeedError,
    Wave,
    WindowType,
    business_wave,
    business_window_starts,
    business_zone_weights,
    delivery_waves,
    hours_category,
    minutes,
    zone_shares,
)
from llobregat_generator.seeds import Seeds

SOURCE_ID = "generator/orders"
LOCAL_TZ = ZoneInfo("Europe/Madrid")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SIZES = ("small", "medium", "large")

# Rules the demand model states in its assumptions, in prose rather than in fields:
# a "4+" stop gets 4 parcels plus a geometric extra with this mean.
FOUR_PLUS_EXTRA_MEAN = {Recipient.CONSUMER: 0.4, Recipient.BUSINESS: 1.5}
# On Saturday most offices, factories and clinics are closed; shops and pharmacies are open.
SATURDAY_OPEN = frozenset({"shops", "healthcare"})

# Rules of this generator, where the demand model says nothing (the opening hours of business
# recipients are in rules.py, which the seed validator shares):
# the weight of one parcel, uniform within its size class.
WEIGHT_KG = {"small": (0.1, 2.0), "medium": (2.0, 8.0), "large": (8.0, 25.0)}
# Monday's next-day orders were registered on Saturday or Sunday, with equal odds.
MONDAY_SATURDAY_ODDS = 0.5
# company.json names the November peak "Black Friday and Cyber Monday week": it applies from the
# Monday before Black Friday to Cyber Monday, not to the whole month.
BLACK_FRIDAY_MONTH = 11

COLUMNS = (
    "order_id",
    "service_date",
    "service_level",
    "priority",
    "customer_type",
    "shipper_id",
    "shipper_name",
    "origin_address",
    "recipient_name",
    "destination_address",
    "destination_postcode",
    "destination_municipality",
    "destination_lat",
    "destination_lon",
    "destination_zone_id",
    "address_ref",
    "parcels",
    "parcel_size",
    "weight_kg",
    "wave",
    "window_type",
    "window_start",
    "window_end",
    "notes",
    "note_id",
    "source",
    "event_time",
)


class NoServiceError(ValueError):
    """The company does not deliver on this date."""


@dataclass(frozen=True)
class Stream:
    """The parcels of one shipper to one kind of recipient on the day."""

    shipper: dict
    recipient: Recipient
    share: float
    hours: str | None  # opening-hours category of a business recipient


@dataclass(frozen=True)
class Day:
    service_date: date
    seed: int
    parcels: int  # the day's total, drawn in step 1
    orders: list[dict]


def cdf(weights: Sequence[float]) -> np.ndarray:
    """Cumulative distribution of non-negative weights, ending exactly at 1."""
    cumulative = np.cumsum(np.asarray(weights, dtype=float))
    cumulative /= cumulative[-1]
    cumulative[-1] = 1.0
    return cumulative


def draw(rng: np.random.Generator, cumulative: np.ndarray) -> int:
    """Index drawn from a cumulative distribution."""
    return int(np.searchsorted(cumulative, rng.random(), side="right"))


def apportion(total: int, weights: Sequence[float]) -> list[int]:
    """Split total in proportion to weights; the largest remainders get the leftover units."""
    if total == 0:
        return [0] * len(weights)
    quotas = [total * w / sum(weights) for w in weights]
    counts = [int(q) for q in quotas]
    by_remainder = sorted(range(len(quotas)), key=lambda i: (counts[i] - quotas[i], i))
    for i in by_remainder[: total - sum(counts)]:
        counts[i] += 1
    return counts


def black_friday(year: int) -> date:
    """The fourth Friday of November."""
    first = date(year, BLACK_FRIDAY_MONTH, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7, weeks=3)


def seasonal_multiplier(service_date: date, peaks: Sequence[dict]) -> float:
    """The seasonal peak of company.json that applies to the date, 1.0 outside every peak.

    The November peak is the Black Friday and Cyber Monday week: from the Monday before Black
    Friday to Cyber Monday, the Monday after it, eight days that may end on 1 December. The rest of
    November has no peak. Every other peak applies to its whole month.
    """
    by_month = {p["month"]: p["multiplier"] for p in peaks}
    friday = black_friday(service_date.year)
    if friday - timedelta(days=4) <= service_date <= friday + timedelta(days=3):
        return by_month.get(BLACK_FRIDAY_MONTH, 1.0)
    if service_date.month == BLACK_FRIDAY_MONTH:
        return 1.0
    return by_month.get(service_date.month, 1.0)


def day_total(rng: np.random.Generator, service_date: date, seeds: Seeds) -> int:
    volume = seeds.company["daily_volume"]
    day_name = DAY_NAMES[service_date.weekday()]
    if day_name == "Sun" and not volume["sunday_operates"]:
        raise NoServiceError(f"{service_date} is a Sunday; Llobregat Express does not deliver on Sundays")
    season = seasonal_multiplier(service_date, volume["seasonal_peaks"])
    base = rng.normal(volume["weekday_parcels_mean"], volume["weekday_parcels_stddev"])
    return max(0, round(base * seeds.demand["weekday_multipliers"][day_name] * season))


def day_streams(service_date: date, demand: dict) -> list[Stream]:
    saturday = DAY_NAMES[service_date.weekday()] == "Sat"
    streams = []
    for shipper in demand["shippers"]:
        share, business = shipper["share_of_daily_parcels"], shipper["business_share"]
        if business < 1:
            streams.append(Stream(shipper, Recipient.CONSUMER, share * (1 - business), None))
        hours = hours_category(shipper)
        if business > 0 and (not saturday or hours in SATURDAY_OPEN):
            streams.append(Stream(shipper, Recipient.BUSINESS, share * business, hours))
    if saturday:  # scale consumer parcels up so the shares still sum to 1
        b2b = sum(s.share for s in streams if s.recipient is Recipient.BUSINESS)
        b2c = sum(s.share for s in streams if s.recipient is Recipient.CONSUMER)
        streams = [
            Stream(s.shipper, s.recipient, s.share * (1 - b2b) / b2c, s.hours)
            if s.recipient is Recipient.CONSUMER
            else s
            for s in streams
        ]
    return streams


class Calendar:
    """Waves, slots and business windows of the service promise, in minutes after midnight."""

    def __init__(self, seeds: Seeds):
        self.window = seeds.company["service_promise"]["promised_window_minutes"]
        self.waves = delivery_waves(seeds.company)
        self.slots = {
            wave: list(range(start, end - self.window + 1, self.window)) for wave, (start, end) in self.waves.items()
        }
        self.opening_hours = seeds.demand["business_opening_hours"]

    def business_starts(self, category: str, wave: Wave) -> list[int]:
        """Starts of the windows a business recipient with these opening hours can get in the wave."""
        hours = self.opening_hours.get(category)
        if hours is None:
            raise SeedError(f"demand.json has no business_opening_hours for {category!r}")
        starts = business_window_starts(hours, self.waves[wave], self.window)
        if not starts:
            raise SeedError(
                f"the {category} opening hours {hours} hold no {self.window}-minute window in the {wave} wave, "
                "where the business parcels of their shippers are delivered"
            )
        return starts


def split(total: int, weights: Mapping[str, float]) -> dict[str, int]:
    """Split total over the keys of weights with the largest-remainder method (apportion)."""
    return dict(zip(weights, apportion(total, list(weights.values())), strict=True))


def deal(rng: np.random.Generator, need: dict[str, int], parcels: int) -> str:
    """A zone for a stop, drawn in proportion to the parcels each zone still needs.

    Zones that still need at least the stop's parcels are preferred, so a large stop does not
    overshoot a zone that needs only a few. The stop's parcels are taken off the zone's need.
    """
    zones = list(need)
    whole = [need[z] if need[z] >= parcels else 0 for z in zones]
    weights = whole if any(whole) else [max(0, need[z]) for z in zones]
    zone = zones[draw(rng, cdf(weights))]
    need[zone] -= parcels
    return zone


def local_datetime(day: date, minute_of_day: int) -> datetime:
    """The moment `minute_of_day` minutes after midnight of `day`, in Barcelona time."""
    return datetime.combine(day, time()).replace(tzinfo=LOCAL_TZ) + timedelta(minutes=minute_of_day)


def generate_day(service_date: date, seed: int, seeds: Seeds, pool: Mapping[str, Sequence[Address]]) -> Day:
    """The orders of one service date. Pure: the same inputs always give the same orders."""
    company, demand = seeds.company, seeds.demand
    rng = np.random.default_rng([seed, service_date.toordinal()])
    total = day_total(rng, service_date, seeds)
    streams = day_streams(service_date, demand)
    counts = apportion(total, [s.share for s in streams])

    zone_share = zone_shares(company)
    missing = sorted(z for z in zone_share if not pool.get(z))
    if missing:
        raise ValueError(f"no addresses for zones {missing}; run load-reference first")
    day_by_zone = split(total, zone_share)
    business_by_zone = dict.fromkeys(zone_share, 0)
    consumer_need: dict[str, int] = {}

    calendar = Calendar(seeds)
    hourly = demand["hourly_registration_share"]
    hour_cdf = cdf([hourly[f"{h:02d}"] for h in range(24)])
    cutoff_hour = minutes(company["hub"]["timetable"]["same_day_cutoff"]) // 60
    before_cutoff = sum(hourly[f"{h:02d}"] for h in range(cutoff_hour))
    choice = demand["consumer_window_choice"]
    morning_odds = choice["morning_wave"] / (choice["morning_wave"] + choice["afternoon_evening_wave"])
    stop_cdf = {
        recipient: cdf([demand["parcels_per_stop"][recipient.seed_key][n] for n in ("1", "2", "3", "4+")])
        for recipient in Recipient
    }
    monday = DAY_NAMES[service_date.weekday()] == "Mon"

    orders = []
    # Business streams first: their parcels are tied to their shippers' zones, and consumer parcels
    # then fill what the business parcels left of each zone's share.
    business_first = sorted(zip(streams, counts, strict=True), key=lambda sc: sc[0].recipient is Recipient.CONSUMER)
    for stream, count in business_first:
        shipper, recipient = stream.shipper, stream.recipient
        business = recipient is Recipient.BUSINESS
        if business:
            need = split(count, business_zone_weights(shipper, zone_share))
        else:
            if not consumer_need:
                consumer_total = sum(c for s, c in zip(streams, counts, strict=True) if s.recipient is recipient)
                room = {z: max(0, day_by_zone[z] - business_by_zone[z]) for z in zone_share}
                consumer_need.update(split(consumer_total, room if any(room.values()) else zone_share))
            need = consumer_need
        size_cdf = cdf([shipper["parcel_mix"][size] for size in SIZES])
        midday = shipper["arrives_at_hub"] == MIDDAY_INJECTION
        same_day_odds = shipper["same_day_share"] / before_cutoff if midday else 0.0
        starts = calendar.business_starts(stream.hours, business_wave(shipper)) if business else []
        left = count
        while left > 0:
            parcels = draw(rng, stop_cdf[recipient]) + 1
            if parcels == 4:
                parcels += int(rng.geometric(1 / (1 + FOUR_PLUS_EXTRA_MEAN[recipient]))) - 1
            parcels = min(parcels, left)
            left -= parcels

            zone_id = deal(rng, need, parcels)
            if business:
                business_by_zone[zone_id] += parcels
            address = pool[zone_id][int(rng.integers(len(pool[zone_id])))]
            size = SIZES[draw(rng, size_cdf)]
            low, high = WEIGHT_KG[size]
            weight = round(float(rng.uniform(low, high, parcels).sum()), 2)

            hour = draw(rng, hour_cdf)
            minute_of_day = hour * 60 + int(rng.integers(60))
            second = int(rng.integers(60))
            same_day = hour < cutoff_hour and rng.random() < same_day_odds
            if same_day:
                registered_on = service_date
            elif monday and rng.random() < MONDAY_SATURDAY_ODDS:
                registered_on = service_date - timedelta(days=2)
            else:
                registered_on = service_date - timedelta(days=1)

            if business:  # same-day parcels are midday parcels, so they ride the afternoon wave too
                wave, window_type = business_wave(shipper), WindowType.OPENING_HOURS
                start = starts[int(rng.integers(len(starts)))]
                end = start + calendar.window
            else:
                if same_day or midday:
                    wave = Wave.AFTERNOON
                else:
                    wave = Wave.MORNING if rng.random() < morning_odds else Wave.AFTERNOON
                if rng.random() < choice["specific_slot_share"]:
                    slots = calendar.slots[wave]
                    window_type, start = WindowType.SLOT, slots[int(rng.integers(len(slots)))]
                    end = start + calendar.window
                else:
                    window_type, (start, end) = WindowType.WAVE, calendar.waves[wave]

            orders.append(
                {
                    "service_date": service_date,
                    "service_level": "same_day" if same_day else "next_day",
                    "priority": "high" if same_day else "normal",
                    "customer_type": recipient.value,
                    "shipper_id": shipper["shipper_id"],
                    "shipper_name": shipper["name"],
                    "origin_address": f"{shipper['name']} ({shipper['arrives_at_hub']})",
                    "recipient_name": None,
                    "destination_address": address.street_address,
                    "destination_postcode": address.postcode,
                    "destination_municipality": address.municipality,
                    "destination_lat": address.lat,
                    "destination_lon": address.lon,
                    "destination_zone_id": zone_id,
                    "address_ref": address.address_ref,
                    "parcels": parcels,
                    "parcel_size": size,
                    "weight_kg": weight,
                    "wave": wave.value,
                    "window_type": window_type.value,
                    "window_start": local_datetime(service_date, start),
                    "window_end": local_datetime(service_date, end),
                    "notes": None,  # step 7, attach_notes
                    "note_id": None,
                    "source": SOURCE_ID,
                    "event_time": local_datetime(registered_on, minute_of_day) + timedelta(seconds=second),
                }
            )

    # Order ids follow registration time; the generation position breaks ties.
    ordered = sorted(enumerate(orders), key=lambda item: (item[1]["event_time"], item[0]))
    stamp = service_date.strftime("%Y%m%d")
    rows = [{"order_id": f"O-{stamp}-{n:05d}", **order} for n, (_, order) in enumerate(ordered, start=1)]
    notes_rng = np.random.default_rng([seed, service_date.toordinal(), NOTES_STREAM])
    attach_notes(rows, NotePicker(seeds.delivery_notes, zone_share), notes_rng)
    return Day(service_date, seed, total, [{column: row[column] for column in COLUMNS} for row in rows])
