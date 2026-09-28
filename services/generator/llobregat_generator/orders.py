"""One day of orders, drawn from the demand model (prompt 004) at real postal addresses.

The date is the service date, the day the parcels are delivered. The steps follow the demand
model's fields and its written assumptions:

1. Day total: a normal draw with the weekday mean and standard deviation of company.json, times
   the weekday multiplier and the seasonal peak of the month. No service on Sunday.
2. The total is split by shipper share into consumer and business parcels (business_share). On
   Saturday only shops and healthcare receive business parcels, and consumer parcels are scaled up
   to keep the total.
3. Parcels are grouped into stops by the parcels-per-stop distribution. A stop is one order: one
   shipper, one address, one parcel size.
4. Zone: a business order goes to one of its shipper's business zones, in proportion to the zone
   shares; consumer orders fill each zone up to its share of the day. Then a real address in it.
5. Registration time from the hourly curve. Only midday-injection shippers sell same-day, only
   before the 11:00 cut-off, with probability same_day_share / (share registered before 11:00);
   every other order is next-day and was registered the day before (for a Monday, on Saturday or
   Sunday).
6. Wave and window: same-day and midday parcels go in the afternoon-evening wave, other business
   parcels in the morning wave, other consumer parcels by the consumer window choice. Consumers
   pick a 120-minute slot with specific_slot_share, otherwise accept the whole wave; business
   recipients get a 120-minute window inside their opening hours.

Everything random comes from one generator seeded with (seed, date), so a date and a seed always
give the same orders.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from llobregat_generator.addresses import Address
from llobregat_generator.rules import (
    MIDDAY_INJECTION,
    Recipient,
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
    quotas = [total * w / sum(weights) for w in weights]
    counts = [int(q) for q in quotas]
    by_remainder = sorted(range(len(quotas)), key=lambda i: (counts[i] - quotas[i], i))
    for i in by_remainder[: total - sum(counts)]:
        counts[i] += 1
    return counts


def day_total(rng: np.random.Generator, service_date: date, seeds: Seeds) -> int:
    volume = seeds.company["daily_volume"]
    day_name = DAY_NAMES[service_date.weekday()]
    if day_name == "Sun" and not volume["sunday_operates"]:
        raise NoServiceError(f"{service_date} is a Sunday; Llobregat Express does not deliver on Sundays")
    season = {p["month"]: p["multiplier"] for p in volume["seasonal_peaks"]}.get(service_date.month, 1.0)
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
        self.business_starts = {
            (category, wave): business_window_starts(hours, span, self.window)
            for category, hours in seeds.demand["business_opening_hours"].items()
            for wave, span in self.waves.items()
        }


def at(day: date, minute_of_day: int) -> datetime:
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

    # Business parcels land in their shippers' zones; consumer parcels fill every zone up to its share.
    business_zones: dict[str, tuple[list[str], np.ndarray]] = {}
    business_expected = dict.fromkeys(zone_share, 0.0)
    for stream, count in zip(streams, counts, strict=True):
        if stream.recipient is Recipient.BUSINESS:
            weights = business_zone_weights(stream.shipper, zone_share)
            business_zones[stream.shipper["shipper_id"]] = (list(weights), cdf(list(weights.values())))
            for zone, weight in weights.items():
                business_expected[zone] += count * weight / sum(weights.values())
    consumer_left = [max(0.0, zone_share[z] * total - business_expected[z]) for z in zone_share]
    consumer_zones = (list(zone_share), cdf(consumer_left if sum(consumer_left) > 0 else list(zone_share.values())))

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
    for stream, count in zip(streams, counts, strict=True):
        shipper, recipient = stream.shipper, stream.recipient
        business = recipient is Recipient.BUSINESS
        size_cdf = cdf([shipper["parcel_mix"][size] for size in SIZES])
        midday = shipper["arrives_at_hub"] == MIDDAY_INJECTION
        same_day_odds = shipper["same_day_share"] / before_cutoff if midday else 0.0
        zones, zone_cdf = business_zones[shipper["shipper_id"]] if business else consumer_zones
        starts = calendar.business_starts[stream.hours, business_wave(shipper)] if business else []
        left = count
        while left > 0:
            parcels = draw(rng, stop_cdf[recipient]) + 1
            if parcels == 4:
                parcels += int(rng.geometric(1 / (1 + FOUR_PLUS_EXTRA_MEAN[recipient]))) - 1
            parcels = min(parcels, left)
            left -= parcels

            zone_id = zones[draw(rng, zone_cdf)]
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
                    "window_start": at(service_date, start),
                    "window_end": at(service_date, end),
                    "notes": None,  # delivery notes are attached by issue #25
                    "source": SOURCE_ID,
                    "event_time": at(registered_on, minute_of_day) + timedelta(seconds=second),
                }
            )

    # Order ids follow registration time; the generation position breaks ties.
    ordered = sorted(enumerate(orders), key=lambda item: (item[1]["event_time"], item[0]))
    stamp = service_date.strftime("%Y%m%d")
    rows = [{"order_id": f"O-{stamp}-{n:05d}", **order} for n, (_, order) in enumerate(ordered, start=1)]
    return Day(service_date, seed, total, [{column: row[column] for column in COLUMNS} for row in rows])
