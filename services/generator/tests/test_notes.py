"""Delivery notes on the generated orders follow the rules of notes.py and keep the corpus (prompt 008).

Shares are of orders, pooled over a week and compared within four standard errors of a binomial
share; the rules that do not depend on chance are checked exactly.
"""

from __future__ import annotations

from collections import Counter

import pytest
from conftest import MONDAY, SEED
from llobregat_generator import notes
from llobregat_generator.notes import (
    BUSINESS_CATEGORIES,
    BUSINESS_OWN_SHARE,
    NOTE_SHARE,
    PLACES,
    NotePicker,
    language_shares,
    names_places,
)
from llobregat_generator.orders import generate_day
from llobregat_generator.rules import zone_shares


def pooled(days) -> list[dict]:
    return [o for day in days for o in day.orders]


def share(items, predicate) -> tuple[float, float]:
    """Share of the items that meet predicate, and its standard error."""
    hits = sum(map(predicate, items))
    p = hits / len(items)
    return p, (p * (1 - p) / len(items)) ** 0.5


@pytest.fixture(scope="session")
def corpus(seeds) -> dict[str, dict]:
    return {n["note_id"]: n for n in seeds.delivery_notes["notes"]}


def with_note(orders) -> list[dict]:
    return [o for o in orders if o["note_id"] is not None]


def test_about_a_third_of_orders_carry_a_note(week, saturday):
    got, error = share(pooled(week), lambda o: o["note_id"] is not None)
    assert got == pytest.approx(NOTE_SHARE, abs=4 * error)
    got, error = share(saturday.orders, lambda o: o["note_id"] is not None)
    assert got == pytest.approx(NOTE_SHARE, abs=4 * error)


def test_an_order_carries_the_text_of_its_note(week, saturday, corpus):
    for o in [*pooled(week), *saturday.orders]:
        if o["note_id"] is None:
            assert o["notes"] is None
        else:
            assert o["notes"] == corpus[o["note_id"]]["text"]


def test_business_recipients_draw_mostly_business_hours_and_location_hints(week, corpus):
    noted = with_note(pooled(week))
    business = [corpus[o["note_id"]] for o in noted if o["customer_type"] == "B2B"]
    consumer = [corpus[o["note_id"]] for o in noted if o["customer_type"] == "B2C"]
    got, error = share(business, lambda n: n["category"] in BUSINESS_CATEGORIES)
    assert got == pytest.approx(BUSINESS_OWN_SHARE, abs=4 * error)
    assert not [n["note_id"] for n in consumer if n["category"] in BUSINESS_CATEGORIES]
    # The consumers' notes cover the other eight categories.
    assert {n["category"] for n in consumer} == {n["category"] for n in corpus.values()} - BUSINESS_CATEGORIES


def test_every_group_of_candidates_keeps_the_corpus_language_mix(seeds):
    """Rule 4, exactly: in every zone, for business and consumer notes alike, each language has its
    corpus share among the languages the candidates have."""
    corpus_mix = language_shares(seeds.delivery_notes["notes"])
    picker = NotePicker(seeds.delivery_notes, zone_shares(seeds.company))
    for group in (picker.own, picker.rest):
        for zone_id, candidates in group.items():
            by_language = Counter()
            for note, p in zip(candidates.notes, candidates.probabilities, strict=True):
                by_language[note["language"]] += p
            present = sum(corpus_mix[language] for language in by_language)
            for language, p in by_language.items():
                assert p == pytest.approx(corpus_mix[language] / present), (zone_id, language)


def test_attached_notes_keep_the_corpus_language_mix(week, seeds, corpus):
    noted = [corpus[o["note_id"]] for o in with_note(pooled(week))]
    for language, expected in language_shares(seeds.delivery_notes["notes"]).items():
        got, error = share(noted, lambda n, lang=language: n["language"] == lang)
        # The business notes have no French or Italian note, which moves the mix by less than half a point.
        assert got == pytest.approx(expected, abs=4 * error + 0.005), language


def test_places_named_in_a_note():
    assert names_places("Es L'Hospitalet, NO Barcelona!! la calle se llama igual") == {"Z10"}
    assert names_places("oficina en el 22@. la mercancía se entrega por el muelle de carga") == {"Z09"}
    assert names_places("és a Sant Joan Despí, al costat de l'escola") == {None}
    assert names_places("casa blanca amb persianes verdes") == set()  # not Casablanca, a part of Sant Boi
    assert names_places("gracias por todo") == set()


def test_a_note_that_names_a_place_goes_only_to_orders_of_that_zone(week, saturday, seeds):
    zone_ids = set(zone_shares(seeds.company))
    assert {zone for zone in PLACES.values() if zone} <= zone_ids
    noted = with_note([*pooled(week), *saturday.orders])
    placed = [o for o in noted if names_places(o["notes"])]
    assert placed  # the rule is exercised
    for o in placed:
        assert names_places(o["notes"]) == {o["destination_zone_id"]}, (o["order_id"], o["notes"])


def test_the_same_date_and_seed_give_the_same_notes(seeds, pool, weekday):
    again = generate_day(MONDAY, SEED, seeds, pool)
    assert [(o["order_id"], o["note_id"]) for o in again.orders] == [
        (o["order_id"], o["note_id"]) for o in weekday.orders
    ]
    other = generate_day(MONDAY, SEED + 1, seeds, pool)
    assert [o["note_id"] for o in other.orders[:200]] != [o["note_id"] for o in weekday.orders[:200]]


def test_notes_have_their_own_random_stream(seeds, pool, weekday, monkeypatch):
    """Without notes the day is the same: the notes change no other field of an order."""
    monkeypatch.setattr(notes, "NOTE_SHARE", 0.0)
    without = generate_day(MONDAY, SEED, seeds, pool)
    assert not with_note(without.orders)

    def other_fields(order):
        return {k: v for k, v in order.items() if k not in ("notes", "note_id")}

    assert [other_fields(o) for o in without.orders] == [other_fields(o) for o in weekday.orders]
