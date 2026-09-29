"""How much slower than OSRM the vans drive: a congestion factor on OSRM's free-flow durations.

OSRM times a road at the speed its profile gives each street, as if the city were empty. The vans
drive it slower by a factor that depends on when and where they are. Until the traffic loader
(issue #9) fills bronze.traffic_state, the factor comes from TimeOfDayProfile, a weekday curve of
Barcelona's traffic: the morning peak on the rondas, a busy midday, a lighter mid-afternoon and the
evening peak. It is a platform assumption, not a measurement, and its hours are below.

The hook for live traffic: anything with a `factor(when, lon, lat)` method is a Traffic, and the
simulator takes one. A live model would read the latest state of the Open Data BCN `trams` sections
near the van (bronze.traffic_state joined to bronze.traffic_section_points on feed_item_id =
section_id), map the state to a factor (1 fluid, 2 dense, 3 congested, 4 stopped, as the city
defines them) and fall back to this profile where the city publishes no section: the ring roads
and the five neighbouring towns. Nothing else in the simulator changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from llobregat_generator.orders import LOCAL_TZ

# (from minute of the day, factor): the factor holds until the next entry. Weekdays.
WEEKDAY = (
    (0, 1.00),
    (7 * 60, 1.20),
    (7 * 60 + 30, 1.50),  # morning peak: the rondas and the entrances to the city
    (9 * 60 + 30, 1.25),
    (13 * 60, 1.35),  # midday: deliveries, school runs and lunch
    (15 * 60, 1.25),
    (17 * 60 + 30, 1.45),  # evening peak
    (20 * 60, 1.15),
    (22 * 60, 1.00),
)
SATURDAY_SHARE = 0.5  # on Saturday, half of the weekday slowdown


class Traffic(Protocol):
    def factor(self, when: datetime, lon: float, lat: float) -> float:
        """How many times OSRM's duration a stretch of road takes, starting there at that moment."""
        ...


@dataclass(frozen=True)
class TimeOfDayProfile:
    """Barcelona's weekday traffic by the hour, the same everywhere; lighter on Saturday."""

    hours: tuple[tuple[int, float], ...] = WEEKDAY
    saturday_share: float = SATURDAY_SHARE

    def factor(self, when: datetime, lon: float, lat: float) -> float:
        local = when.astimezone(LOCAL_TZ)
        minute = local.hour * 60 + local.minute
        factor = next(f for start, f in reversed(self.hours) if start <= minute)
        if local.weekday() == 5:
            factor = 1 + (factor - 1) * self.saturday_share
        return factor
