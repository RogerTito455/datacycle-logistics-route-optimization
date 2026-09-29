"""Delivery notes on orders: which orders carry one, and which note (prompt 008).

The corpus, seed/delivery_notes.json, has 300 notes written the way recipients type them, each
labelled by the generating model with its language, one category and whether it is likely to make
the stop longer or the first attempt fail. Prompt 008 told the model that a program would attach
one of them, at random, to about a third of the orders. These are that program's rules; the corpus
says nothing about them:

1. An order carries a note with probability NOTE_SHARE, a third.
2. Business recipients draw mostly (BUSINESS_OWN_SHARE, 80%) from the categories a business writes:
   when it is open ("business hours") and how to find it ("location hint"). Their other notes, and
   every consumer's, come from the other eight categories.
3. A note that names a place (PLACES) goes only to orders of the zone that place is in, so
   "Es L'Hospitalet, NO Barcelona!!" is never read at a door in Gràcia. A note that names a place
   outside the service area is never attached.
4. Within the notes an order can get, every language keeps its share of the corpus: a note weighs
   the corpus share of its language divided by the number of notes of that language it competes
   with. The notes of one language are equally likely.

The draws have a random stream of their own, seeded with the date, the seed and NOTES_STREAM, so
attaching notes changes no other field of an order, and a date and seed always give the same notes.
The two labels are not used here: they are for the simulator (issue #7) and for analysis.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from llobregat_generator.rules import Recipient, SeedError

# Rules of this generator, where the corpus says nothing.
NOTE_SHARE = 1 / 3  # "about a third of the orders" (prompt 008)
BUSINESS_CATEGORIES = frozenset({"business hours", "location hint"})
BUSINESS_OWN_SHARE = 0.8  # business recipients' notes from BUSINESS_CATEGORIES
# Places the notes name, and the zone of company.json each is in; None is outside the service area.
PLACES = {
    "L'Hospitalet": "Z10",
    "El Prat": "Z11",
    "Cornellà": "Z12",
    "Esplugues": "Z13",
    "Sant Boi": "Z14",
    "22@": "Z09",  # the innovation district of Sant Martí
    "Vallvidrera": "Z05",  # a neighbourhood of Sarrià-Sant Gervasi, in the hills
    "Sant Joan Despí": None,  # the town between Cornellà and Esplugues, not served
}
# Third entropy word of the notes' random stream (8, for prompt 008); the orders' stream has two,
# the seed and the date.
NOTES_STREAM = 8


_PLACE_PATTERNS = {place: re.compile(rf"(?<!\w){re.escape(place)}(?!\w)", re.IGNORECASE) for place in PLACES}


def places_named(text: str) -> set[str]:
    """The places of PLACES a note names, as whole words."""
    return {place for place, pattern in _PLACE_PATTERNS.items() if pattern.search(text)}


def names_places(text: str) -> set[str | None]:
    """The zones of the places a note names, None for a place outside the service area."""
    return {PLACES[place] for place in places_named(text)}


def fits_zone(note: dict, zone_id: str) -> bool:
    """Whether a note can be read at a door in this zone: it names no place, or only this zone's."""
    return names_places(note["text"]) <= {zone_id}


def language_shares(notes: Sequence[dict]) -> dict[str, float]:
    counts = Counter(n["language"] for n in notes)
    return {language: n / len(notes) for language, n in counts.items()}


def is_business_note(note: dict) -> bool:
    return note["category"] in BUSINESS_CATEGORIES


@dataclass(frozen=True)
class Candidates:
    """The notes an order of one kind can get in one zone, and the probability of each."""

    notes: tuple[dict, ...]
    probabilities: np.ndarray

    @classmethod
    def weighted(cls, notes: Sequence[dict], corpus_mix: dict[str, float]) -> Candidates:
        """Each language gets its corpus share, split equally among its notes (rule 4)."""
        counts = Counter(n["language"] for n in notes)
        weights = np.array([corpus_mix[n["language"]] / counts[n["language"]] for n in notes])
        return cls(tuple(notes), weights / weights.sum())


class NotePicker:
    """The notes of the corpus, grouped by who can get them in which zone."""

    def __init__(self, corpus: dict, zone_ids: Iterable[str]):
        notes = corpus["notes"]
        mix = language_shares(notes)
        own = [n for n in notes if is_business_note(n)]
        rest = [n for n in notes if not is_business_note(n)]
        self.own: dict[str, Candidates] = {}
        self.rest: dict[str, Candidates] = {}
        for zone_id in zone_ids:
            for group, pool, kind in ((self.own, own, "business"), (self.rest, rest, "consumer")):
                fitting = [n for n in pool if fits_zone(n, zone_id)]
                if not fitting:
                    raise SeedError(f"delivery_notes.json has no {kind} note that fits zone {zone_id}")
                group[zone_id] = Candidates.weighted(fitting, mix)

    def pick(self, rng: np.random.Generator, business: bool, zone_id: str) -> dict:
        """A note for an order that carries one (rules 2 to 4)."""
        group = self.own if business and rng.random() < BUSINESS_OWN_SHARE else self.rest
        candidates = group[zone_id]
        return candidates.notes[int(rng.choice(len(candidates.notes), p=candidates.probabilities))]


def attach_notes(orders: Sequence[dict], picker: NotePicker, rng: np.random.Generator) -> None:
    """Give about a third of the orders a note: its id in note_id, its text in notes (rule 1).

    The orders are taken in the order given, so the same orders and random stream always give the
    same notes.
    """
    for order in orders:
        note = None
        if rng.random() < NOTE_SHARE:
            business = order["customer_type"] == Recipient.BUSINESS
            note = picker.pick(rng, business, order["destination_zone_id"])
        order["note_id"] = note["note_id"] if note else None
        order["notes"] = note["text"] if note else None
