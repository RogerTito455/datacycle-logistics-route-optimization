"""Delivery notes on orders: which orders carry one, and which note (prompt 008).

The corpus, seed/delivery_notes.json, has 300 notes written the way recipients type them, each
labelled by the generating model with its language, one category and whether it is likely to make
the stop longer or the first attempt fail. Prompt 008 told the model that a program would attach
one of them, at random, to about a third of the orders. These are that program's rules; the corpus
says nothing about them:

1. An order carries a note with probability NOTE_SHARE, a third.
2. Who could have written a note is read from the note itself, not from its category alone
   (context). A business, when its category is "business hours" or its text names business
   premises: an office, a reception, a loading dock, the 22@, an industrial estate, or a shop, bar
   or restaurant it opens with. A home, when its text names a home or a part of one (a flat or a
   house, a flat's floor and door, a staircase, the intercom, the letterbox, a concierge), the
   neighbours, the family, the pets, or a recipient who works or sleeps there or elsewhere. Anyone,
   otherwise (neutral). A shop or a bar named later in a note is a neighbour or a
   landmark ("dejadlo en el bar de abajo"), not the recipient's premises. Business recipients draw
   BUSINESS_CONTEXT_SHARE (80%) of their notes from the business notes and the rest from the neutral
   ones; consumers draw from every note that is not a business's. So a business never gets a home
   note, and the location hints that describe a home reach consumers.
3. A note that names a place (PLACES) goes only to orders of the zone that place is in, so
   "Es L'Hospitalet, NO Barcelona!!" is never read at a door in Gràcia. A note that names a place
   outside the service area is never attached.
4. The languages keep their corpus shares as closely as the notes an order can get allow. The
   groups of rule 2 are taken in turn, and each gives each of its languages what is left of that
   language's corpus share, in proportion; the notes of one language in a group are equally likely.
   The business notes have no French, Italian or mixed note, so the neutral notes a business
   recipient gets make up for them, and both kinds of recipient get the corpus mix.

The draws have a random stream of their own, seeded with the date, the seed and NOTES_STREAM, so
attaching notes changes no other field of an order, and a date and seed always give the same notes.
The two labels are not used here: they are for the simulator (issue #7) and for analysis.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np

from llobregat_generator.rules import Recipient, SeedError

# Rules of this generator, where the corpus says nothing.
NOTE_SHARE = 1 / 3  # "about a third of the orders" (prompt 008)
BUSINESS_CONTEXT_SHARE = 0.8  # business recipients' notes written by a business (rule 2)
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


class Language(StrEnum):
    """The language of a note, as delivery_notes.json labels it."""

    SPANISH = "es"
    CATALAN = "ca"
    ENGLISH = "en"
    FRENCH = "fr"
    ITALIAN = "it"
    MIXED = "mixed"


class Category(StrEnum):
    """The category of a note, as the generating model labelled it in delivery_notes.json."""

    ACCESS = "access"
    SCHEDULE = "schedule"
    NEIGHBOUR_OR_CONCIERGE = "neighbour or concierge"
    BUSINESS_HOURS = "business hours"
    CALL_BEFORE = "call before"
    PETS_OR_CHILDREN = "pets or children"
    FRAGILE_OR_SPECIAL_HANDLING = "fragile or special handling"
    LOCATION_HINT = "location hint"
    CONTRADICTORY = "contradictory"
    OTHER = "other"


class Context(StrEnum):
    """Who could have written a note (rule 2)."""

    BUSINESS = "business"
    HOME = "home"
    NEUTRAL = "neutral"


def _words(*words: str) -> re.Pattern:
    """Any of the words, whole, in any case; a word ending in * also matches what follows it."""
    alternatives = "|".join(re.escape(w[:-1]) + r"\w*" if w.endswith("*") else re.escape(w) for w in words)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


# Rule 2, in the languages of the corpus: Spanish, Catalan, English, French and Italian.
BUSINESS_PREMISES = _words(
    "office*", "oficina*", "despacho", "coworking",
    "reception", "recepción", "recepcion", "recepció",
    "loading dock", "muelle de carga", "moll de càrrega", "moll de carrega",
    "22@", "polígono industrial", "poligono industrial", "polígon industrial", "horario comercial", "horari comercial",
)  # fmt: skip
# A note that opens with its premises: "bar, opens at 6pm", "Es una tienda", "restaurant, per la porta...".
BUSINESS_OPENING = re.compile(
    r"^\W*(?:(?:es|és) una? |it'?s an? )?"
    r"(?:shop|store|tienda|botiga|bar|cafe|café|cafeteria|cafetería|restaurant|restaurante)(?!\w)",
    re.IGNORECASE,
)
HOME = _words(
    "casa", "house", "home", "flat", "apartment", "apartamento", "appartamento", "appartement",
    "piso", "pis", "ático", "atico", "àtic", "pral", "entresuelo", "entresòl", "entresol", "entlo", "entl",
    "escalera", "escala", "esc.", "portal", "rellano", "replà", "felpudo",
    "telefonillo", "porter automàtic", "portero automático", "portero automatico", "intercom", "interfono",
    "citofono", "buzón", "buzon", "buzones", "bústia", "bustia", "letterbox", "mailbox",
    "portería", "porteria", "portero", "portera", "porter", "conserje*", "conserge*", "conserjería",
    "consergeria", "concierge",
    "vecino*", "vecina*", "veí", "veïna", "veïns", "neighbour*", "neighbor*",
    "urbanización", "urbanizacion", "urbanització", "urbanitzacio", "gated community",
    "jardín", "jardin", "jardí", "huerto", "patio", "pati",
    "bebé", "bebe", "baby", "nadó", "recién nacido", "niño", "niña", "nena", "nen", "madre", "mare", "àvia",
    "gato", "gat", "cat", "cats", "perro*", "gos", "gossos", "dog",
    "teletrabajo", "teletreballo", "wfh", "trabajo", "treballo", "feina", "work nights", "working from",
    "turno de noche", "duermo", "despierta", "despierto",
)  # fmt: skip
# A flat's floor and door: "4º 2ª", "3r 2a", "2n 3a", "floor door 1". Offices give a floor alone.
FLAT_DOOR = re.compile(r"(?<!\w)\d+\s*(?:º|°|r|n|t|è)\.?\s+\d+\s*(?:ª|a)(?!\w)|floor,? door \d", re.IGNORECASE)


def context(note: Mapping) -> Context:
    """Who could have written the note (rule 2). Its category decides only for business hours; a
    note naming a home is a home's even if it names an office too ("leave it at the key collection
    office round the corner" of a holiday flat)."""
    text = note["text"]
    if Category(note["category"]) is Category.BUSINESS_HOURS:
        return Context.BUSINESS
    if HOME.search(text) or FLAT_DOOR.search(text):
        return Context.HOME
    if BUSINESS_PREMISES.search(text) or BUSINESS_OPENING.search(text):
        return Context.BUSINESS
    return Context.NEUTRAL


# Rule 2: the contexts each kind of recipient draws from, in groups, and the share of each group.
DRAWS: dict[Recipient, tuple[tuple[frozenset[Context], float], ...]] = {
    Recipient.BUSINESS: (
        (frozenset({Context.BUSINESS}), BUSINESS_CONTEXT_SHARE),
        (frozenset({Context.NEUTRAL}), 1 - BUSINESS_CONTEXT_SHARE),
    ),
    Recipient.CONSUMER: ((frozenset({Context.HOME, Context.NEUTRAL}), 1.0),),
}

_PLACE_PATTERNS = {place: re.compile(rf"(?<!\w){re.escape(place)}(?!\w)", re.IGNORECASE) for place in PLACES}


def places_named(text: str) -> set[str]:
    """The places of PLACES a note names, as whole words."""
    return {place for place, pattern in _PLACE_PATTERNS.items() if pattern.search(text)}


def zones_named(text: str) -> set[str | None]:
    """The zones of the places a note names, None for a place outside the service area."""
    return {PLACES[place] for place in places_named(text)}


def fits_zone(note: dict, zone_id: str) -> bool:
    """Whether a note can be read at a door in this zone: it names no place, or only this zone's."""
    return zones_named(note["text"]) <= {zone_id}


def language_shares(notes: Sequence[dict]) -> dict[Language, float]:
    counts = Counter(Language(n["language"]) for n in notes)
    return {language: n / len(notes) for language, n in counts.items()}


@dataclass(frozen=True)
class Candidates:
    """The notes an order of one kind can get in one zone, and the probability of each."""

    notes: tuple[dict, ...]
    probabilities: np.ndarray

    @classmethod
    def weighted(
        cls, groups: Sequence[tuple[Sequence[dict], float]], corpus_mix: Mapping[Language, float]
    ) -> Candidates:
        """The notes of the groups, each group with its share, languages weighted by rule 4.

        Each group in turn gives each of its languages what is left of that language's corpus share,
        in proportion, split equally among its notes of that language.
        """
        left = dict(corpus_mix)
        notes: list[dict] = []
        weights: list[float] = []
        for group, share in groups:
            counts = Counter(Language(n["language"]) for n in group)
            wanted = {language: max(left.get(language, 0.0), 0.0) for language in counts}
            if sum(wanted.values()) <= 0:  # the earlier groups gave these languages their whole share
                wanted = dict.fromkeys(counts, 1.0)
            total = sum(wanted.values())
            for language in counts:
                left[language] = left.get(language, 0.0) - share * wanted[language] / total
            notes += group
            weights += [share * wanted[n["language"]] / total / counts[n["language"]] for n in group]
        probabilities = np.array(weights)
        return cls(tuple(notes), probabilities / probabilities.sum())


class NotePicker:
    """The notes of the corpus, grouped by who can get them in which zone."""

    def __init__(self, corpus: dict, zone_ids: Iterable[str]):
        notes = corpus["notes"]
        mix = language_shares(notes)
        contexts = {n["note_id"]: context(n) for n in notes}
        self.candidates: dict[Recipient, dict[str, Candidates]] = {recipient: {} for recipient in DRAWS}
        for zone_id in zone_ids:
            for recipient, draws in DRAWS.items():
                groups = []
                for kinds, share in draws:
                    fitting = [n for n in notes if contexts[n["note_id"]] in kinds and fits_zone(n, zone_id)]
                    if not fitting:
                        kind = " or ".join(sorted(kinds))
                        raise SeedError(f"delivery_notes.json has no {kind} note that fits zone {zone_id}")
                    groups.append((fitting, share))
                self.candidates[recipient][zone_id] = Candidates.weighted(groups, mix)

    def pick(self, rng: np.random.Generator, recipient: Recipient, zone_id: str) -> dict:
        """A note for an order that carries one (rules 2 to 4)."""
        candidates = self.candidates[recipient][zone_id]
        return candidates.notes[int(rng.choice(len(candidates.notes), p=candidates.probabilities))]


def attach_notes(orders: Sequence[dict], picker: NotePicker, rng: np.random.Generator) -> None:
    """Give about a third of the orders a note: its id in note_id, its text in notes (rule 1).

    The orders are taken in the order given, so the same orders and random stream always give the
    same notes.
    """
    for order in orders:
        note = None
        if rng.random() < NOTE_SHARE:
            note = picker.pick(rng, Recipient(order["customer_type"]), order["destination_zone_id"])
        order["note_id"] = note["note_id"] if note else None
        order["notes"] = note["text"] if note else None
