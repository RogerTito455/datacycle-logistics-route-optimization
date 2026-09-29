"""Rules read from the seeds, shared by the order generator, the seed validators and the tests.

The seeds give times as "HH:MM" text and business opening hours with a lunch break; the
generator works in minutes after midnight. A shipper's business parcels are spread over its
business zones in proportion to the zone shares, as the demand model's assumptions say. Keeping
these rules in one place means the validators check exactly what the generator does.
"""

from __future__ import annotations

from datetime import time
from enum import StrEnum

from llobregat_generator.seeds import Seeds

# arrives_at_hub of the shippers whose parcels reach the hub at midday; only they sell same-day.
MIDDAY_INJECTION = "midday injection"
# shift of the drivers who cover either shift week by week (driver roster, prompt 003).
RELIEF_POOL = "Relief pool"

# Rules of this generator, where the demand model says nothing: the opening hours a business
# recipient keeps, by the segment of its shipper. The business recipients of mixed shippers
# (partner networks, e-commerce, marketplace) count as offices.
SEGMENT_HOURS = {
    "retail replenishment": "shops",
    "healthcare distributor": "healthcare",
    "office supplies and services": "offices",
    "industrial distributor": "industry",
}
DEFAULT_HOURS = "offices"
# Business windows start on the half hour.
WINDOW_STEP_MIN = 30


class SeedError(ValueError):
    """The seeds ask for something the generator cannot do."""


class Recipient(StrEnum):
    """Who receives an order. The value is what bronze.orders.customer_type holds."""

    CONSUMER = "B2C"
    BUSINESS = "B2B"

    @property
    def seed_key(self) -> str:
        """The key demand.json gives this recipient, as in parcels_per_stop."""
        return "business" if self is Recipient.BUSINESS else "consumer"


class Wave(StrEnum):
    """Delivery wave of the service promise. The value is what bronze.orders.wave holds."""

    MORNING = "morning"
    AFTERNOON = "afternoon"


class ParcelSize(StrEnum):
    """Size class of an order's parcels. The value is what bronze.orders.parcel_size holds."""

    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class WindowType(StrEnum):
    """How an order's time window was set. The value is what bronze.orders.window_type holds."""

    SLOT = "slot"  # the consumer chose a 120-minute slot of the wave
    WAVE = "wave"  # the consumer accepts any time in the wave
    OPENING_HOURS = "opening_hours"  # a business recipient, inside its opening hours


def minutes(hhmm: str) -> int:
    """Minutes after midnight of an "HH:MM" time."""
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


def clock(hhmm: str) -> time:
    """An "HH:MM" time as a time of day."""
    return time(*divmod(minutes(hhmm), 60))


def span(text: str) -> tuple[str, str]:
    """The two ends of an "HH:MM-HH:MM" period."""
    start, end = text.split("-")
    return start, end


def opening_ranges(hours: dict) -> list[tuple[int, int]]:
    """Open periods of a business in minutes after midnight, the lunch break taken out."""
    start, end = minutes(hours["open"]), minutes(hours["close"])
    if not hours["lunch_break"]:
        return [(start, end)]
    lunch_start, lunch_end = (minutes(t) for t in span(hours["lunch_break"]))
    return [(start, lunch_start), (lunch_end, end)]


def delivery_waves(company: dict) -> dict[Wave, tuple[int, int]]:
    """The morning and afternoon-evening waves of the service promise, in minutes after midnight."""
    morning, afternoon = sorted(company["service_promise"]["delivery_windows"], key=lambda w: minutes(w["start"]))
    return {
        Wave.MORNING: (minutes(morning["start"]), minutes(morning["end"])),
        Wave.AFTERNOON: (minutes(afternoon["start"]), minutes(afternoon["end"])),
    }


def hours_category(shipper: dict) -> str:
    """The opening hours (a key of business_opening_hours) of the shipper's business recipients."""
    return SEGMENT_HOURS.get(shipper["segment"], DEFAULT_HOURS)


def business_wave(shipper: dict) -> Wave:
    """The wave of a shipper's business parcels: midday-injection parcels miss the morning wave."""
    return Wave.AFTERNOON if shipper["arrives_at_hub"] == MIDDAY_INJECTION else Wave.MORNING


def business_window_starts(hours: dict, wave: tuple[int, int], window: int) -> list[int]:
    """Starts of the business windows: `window` minutes inside the opening hours and the wave."""
    wave_start, wave_end = wave
    starts: list[int] = []
    for open_start, open_end in opening_ranges(hours):
        first, last = max(open_start, wave_start), min(open_end, wave_end) - window
        first += -first % WINDOW_STEP_MIN
        starts += range(first, last + 1, WINDOW_STEP_MIN)
    return starts


def zone_shares(company: dict) -> dict[str, float]:
    return {z["zone_id"]: z["share_of_daily_parcels"] for z in company["zones"]}


def business_zone_weights(shipper: dict, zone_share: dict[str, float]) -> dict[str, float]:
    """The zones of company.json that the shipper's business parcels go to, each weighted by its share.

    Raises SeedError for a shipper with business parcels and no such zone with a share above 0,
    whose business parcels would have nowhere to go.
    """
    weights = {z: zone_share[z] for z in shipper["business_recipient_zones"] if zone_share.get(z, 0) > 0}
    if not weights and shipper["business_share"] > 0:
        raise SeedError(
            f"{shipper['shipper_id']} sends business parcels, but none of its business zones "
            f"{shipper['business_recipient_zones']} is a zone of company.json with a share above 0"
        )
    return weights


def business_parcels_by_zone(seeds: Seeds) -> dict[str, float]:
    """Share of the day's parcels that go to business recipients in each zone, on a weekday."""
    zone_share = zone_shares(seeds.company)
    business = dict.fromkeys(zone_share, 0.0)
    for shipper in seeds.demand["shippers"]:
        weights = business_zone_weights(shipper, zone_share)
        total = sum(weights.values())
        for zone, weight in weights.items():
            business[zone] += shipper["share_of_daily_parcels"] * shipper["business_share"] * weight / total
    return business


def weekday_business_share(demand: dict) -> float:
    """Share of a weekday's parcels that go to business recipients, by the shipper list."""
    return sum(s["share_of_daily_parcels"] * s["business_share"] for s in demand["shippers"])


def weekday_same_day_share(demand: dict) -> float:
    """Share of a weekday's parcels delivered the day they are registered, by the shipper list."""
    return sum(s["share_of_daily_parcels"] * s["same_day_share"] for s in demand["shippers"])
