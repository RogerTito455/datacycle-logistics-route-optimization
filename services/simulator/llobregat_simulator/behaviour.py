"""What happens at a stop: how long it takes and whether the parcel is delivered.

A stop takes its zone's minutes per stop (company profile) on average, drawn from a gamma
distribution with a coefficient of variation of 0.5, so most stops are close to the mean and a few
take twice as long. A delivery fails with the demand model's failed-first-attempt probability
(prompt 004): by recipient and the zone's delivery difficulty, times the evening factor for a
consumer in the afternoon-evening wave.

The delivery notes' labels (prompt 008) move the odds between stops without changing the averages:
a note labelled likely_longer_stop makes its stop LONGER_STOP times longer and likely_failed_attempt
its failure NOTE_FAIL times likelier, and the other stops of the route are scaled down so that the
route's expected minutes and failures are the model's. A failed stop has a reason: the note's when
its category says it (a location hint that cannot be found, a business that is closed), otherwise
one drawn from REASONS. These rules are the simulator's own.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from llobregat_generator.rules import Wave

from llobregat_simulator.company import Company, Order

STOP_SHAPE = 4.0  # gamma shape: coefficient of variation 1/sqrt(4) = 0.5
MIN_STOP_S = 45.0
LONGER_STOP = 1.5
NOTE_FAIL = 2.5
MAX_FAILURE = 0.95

# failure_reason of bronze.delivery_events, by recipient, when the note does not give it.
REASONS = {
    "consumer": {
        "recipient_absent": 0.75,
        "access_restricted": 0.08,
        "address_not_found": 0.07,
        "refused": 0.05,
        "damaged": 0.02,
        "other": 0.03,
    },
    "business": {"recipient_absent": 0.70, "access_restricted": 0.15, "refused": 0.10, "other": 0.05},
}
# The reason a failed stop has when its note is labelled likely_failed_attempt and is about this.
NOTE_REASONS = {
    "location hint": "address_not_found",
    "access": "access_restricted",
    "business hours": "recipient_absent",
    "schedule": "recipient_absent",
}


@dataclass(frozen=True)
class NoteLabels:
    category: str
    likely_longer_stop: bool
    likely_failed_attempt: bool


def note_labels(delivery_notes: dict) -> dict[str, NoteLabels]:
    """The labels of every note of the corpus (delivery_notes.json), by note id."""
    return {
        n["note_id"]: NoteLabels(n["category"], n["likely_longer_stop"], n["likely_failed_attempt"])
        for n in delivery_notes["notes"]
    }


def failure_probability(order: Order, company: Company, demand: dict) -> float:
    """The demand model's probability that the first attempt fails, without the note."""
    model = demand["failed_first_attempt_probability"]
    difficulty = company.zones[order.zone_id].difficulty
    if order.business:
        return model["business"][difficulty]
    evening = model["evening_window_factor"] if order.wave == Wave.AFTERNOON else 1.0
    return model["consumer"][difficulty] * evening


def _rescale(base: Sequence[float], flagged: Sequence[bool], factor: float) -> list[float]:
    """Multiply the flagged values by factor and the others by what keeps the total the same."""
    total = sum(base)
    marked = sum(b for b, f in zip(base, flagged, strict=True) if f)
    rest = total - marked
    if not marked or rest <= 0 or total - factor * marked < 0.25 * rest:  # too few others to balance
        return list(base)
    other = (total - factor * marked) / rest
    return [b * (factor if f else other) for b, f in zip(base, flagged, strict=True)]


@dataclass(frozen=True)
class Outcome:
    """What happens at one stop."""

    stop_s: float  # from the end of any wait for the window to leaving
    failed: bool
    reason: str | None


def outcomes(
    orders: Sequence[Order],
    company: Company,
    demand: dict,
    notes: dict[str, NoteLabels],
    rng: np.random.Generator,
) -> list[Outcome]:
    """The stops of a route, drawn in one go so that every route has the same random stream."""
    labels = [notes.get(o.note_id) if o.note_id else None for o in orders]
    mean_s = _rescale(
        [company.zones[o.zone_id].minutes_per_stop * 60 for o in orders],
        [bool(n and n.likely_longer_stop) for n in labels],
        LONGER_STOP,
    )
    odds = _rescale(
        [failure_probability(o, company, demand) for o in orders],
        [bool(n and n.likely_failed_attempt) for n in labels],
        NOTE_FAIL,
    )
    shape = rng.gamma(STOP_SHAPE, 1 / STOP_SHAPE, len(orders))
    draws, reason_draws = rng.random(len(orders)), rng.random(len(orders))
    result = []
    for order, label, mean, p, g, u, r in zip(orders, labels, mean_s, odds, shape, draws, reason_draws, strict=True):
        failed = bool(u < min(p, MAX_FAILURE))
        reason = None
        if failed:
            if label and label.likely_failed_attempt and label.category in NOTE_REASONS:
                reason = NOTE_REASONS[label.category]
            else:
                table = REASONS["business" if order.business else "consumer"]
                cumulative = np.cumsum(list(table.values()))
                pick = int(np.searchsorted(cumulative, r * cumulative[-1], side="right"))
                reason = list(table)[min(pick, len(table) - 1)]
        result.append(Outcome(max(MIN_STOP_S, mean * g), failed, reason))
    return result
