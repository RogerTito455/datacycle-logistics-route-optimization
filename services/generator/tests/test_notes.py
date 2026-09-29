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
    BUSINESS_CONTEXT_SHARE,
    NOTE_SHARE,
    PLACES,
    Context,
    NotePicker,
    context,
    language_shares,
    names_places,
)
from llobregat_generator.orders import generate_day
from llobregat_generator.rules import Recipient, SeedError, zone_shares


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


@pytest.mark.parametrize(
    ("note_id", "expected"),
    [
        ("N-004", Context.BUSINESS),  # "Es una tienda, abrimos a las 10": business hours
        ("N-090", Context.BUSINESS),  # "despacho en el 2º piso ...": business hours, although "piso"
        ("N-027", Context.BUSINESS),  # "22@ office building, deliveries only through the loading dock ..."
        ("N-040", Context.BUSINESS),  # "oficina en el 22@. ... el muelle de carga ..., no por recepción"
        ("N-178", Context.BUSINESS),  # "edifici d'oficines al 22@, les entregues pel moll de càrrega ..."
        ("N-065", Context.BUSINESS),  # "poligono industrial, nave 14, persiana azul"
        ("N-288", Context.HOME),  # "entresuelo 1ª, en el telefonillo pone ENTLO": a location hint
        ("N-211", Context.HOME),  # "casa blanca amb persianes verdes"
        ("N-229", Context.HOME),  # "Escalera B, not A! both have a 3rd floor door 1"
        ("N-139", Context.HOME),  # "el buzón y el timbre están en la valla, no en la casa"
        ("N-084", Context.HOME),  # "Holiday flat, ... leave it at the key collection office round the corner"
        ("N-032", Context.HOME),  # "timbre roto, pica al 3r 2a y bajo": a flat's floor and door
        ("N-060", Context.HOME),  # "I work nights, please not before 1pm"
        ("N-101", Context.NEUTRAL),  # "si no estoy dejadlo en el bar de abajo": a bar as a neighbour
        ("N-120", Context.NEUTRAL),  # "... es la puerta al lado de la farmacia": a pharmacy as a landmark
        ("N-019", Context.NEUTRAL),  # "justo enfrente de la parada del bus"
    ],
)
def test_who_could_have_written_a_note_is_read_from_its_text(corpus, note_id, expected):
    assert context(corpus[note_id]) is expected


def test_business_recipients_draw_mostly_business_notes_and_consumers_home_and_neutral_ones(week, corpus):
    noted = with_note(pooled(week))
    business = [corpus[o["note_id"]] for o in noted if o["customer_type"] == Recipient.BUSINESS]
    consumer = [corpus[o["note_id"]] for o in noted if o["customer_type"] == Recipient.CONSUMER]
    got, error = share(business, lambda n: context(n) is Context.BUSINESS)
    assert got == pytest.approx(BUSINESS_CONTEXT_SHARE, abs=4 * error)
    assert not [n["note_id"] for n in business if context(n) is Context.HOME]
    assert not [n["note_id"] for n in consumer if context(n) is Context.BUSINESS]
    # Location hints that describe a home reach consumers.
    assert {"N-139", "N-211", "N-229", "N-288"} <= {n["note_id"] for n in consumer}


def test_every_group_of_candidates_keeps_the_corpus_language_mix(seeds):
    """Rules 2 and 4, exactly: in every zone, business and consumer recipients alike get the corpus
    language mix, and a business recipient 80% business notes and no home note."""
    corpus_mix = language_shares(seeds.delivery_notes["notes"])
    picker = NotePicker(seeds.delivery_notes, zone_shares(seeds.company))
    for recipient, by_zone in picker.candidates.items():
        for zone_id, candidates in by_zone.items():
            by_language, by_context = Counter(), Counter()
            for note, p in zip(candidates.notes, candidates.probabilities, strict=True):
                by_language[note["language"]] += p
                by_context[context(note)] += p
            assert by_language == pytest.approx(corpus_mix), (recipient, zone_id)
            if recipient is Recipient.BUSINESS:
                expected = {Context.BUSINESS: BUSINESS_CONTEXT_SHARE, Context.NEUTRAL: 1 - BUSINESS_CONTEXT_SHARE}
                assert by_context == pytest.approx(expected), zone_id
            else:
                assert Context.BUSINESS not in by_context, zone_id


def test_attached_notes_keep_the_corpus_language_mix(week, seeds, corpus):
    noted = [corpus[o["note_id"]] for o in with_note(pooled(week))]
    for language, expected in language_shares(seeds.delivery_notes["notes"]).items():
        got, error = share(noted, lambda n, lang=language: n["language"] == lang)
        assert got == pytest.approx(expected, abs=4 * error), language


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


def test_a_corpus_without_notes_for_a_zone_stops_the_generator(seeds):
    only_hospitalet = {"notes": [n for n in seeds.delivery_notes["notes"] if names_places(n["text"]) == {"Z10"}]}
    with pytest.raises(SeedError, match="no business note that fits zone Z01"):
        NotePicker(only_hospitalet, zone_shares(seeds.company))


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
