"""Validate the AI-generated fleet register, driver roster, demand model and delivery notes
(prompts 002-004 and 008).

Two layers of checks for each seed, all offline:

1. Structure: the JSON matches its schema in seed/ (fleet, drivers, demand, delivery_notes).
2. Consistency: the figures agree with each other and with the company profile (company.json,
   prompt 001), which fixed the vehicle types and counts, the zones, the shifts and the volumes
   that prompts 002-004 repeat. The delivery notes are checked against what prompt 008 asked for
   (count, language mix, no personal data) and against the rules the generator applies to them.

Usage:
    uv run --project services/generator python services/generator/validate_seeds.py
"""

from __future__ import annotations

import re
import sys
from collections import Counter

import jsonschema
from llobregat_generator.notes import PLACES, NotePicker, places_named
from llobregat_generator.rules import (
    MIDDAY_INJECTION,
    RELIEF_POOL,
    SeedError,
    business_parcels_by_zone,
    business_wave,
    business_window_starts,
    business_zone_weights,
    delivery_waves,
    hours_category,
    minutes,
    weekday_business_share,
    weekday_same_day_share,
    zone_shares,
)
from llobregat_generator.seeds import Seeds

# Shared helpers: every check prints one line and failures are counted in the same lists.
from validate_company import SEED_DIR, check, error, errors, ok, read_json, warnings

# Spanish plates since 2000: four digits and three consonants, never a vowel, Ñ or Q.
PLATE_RE = re.compile(r"^\d{4} [BCDFGHJKLMNPRSTVWXYZ]{3}$")
# Contact details must not appear anywhere in the roster (prompt 003).
PHONE_RE = re.compile(r"(?:\+34[\s.-]?)?\b[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
# Nor identity documents in the delivery notes (prompt 008): Spanish DNI and NIE numbers.
ID_DOCUMENT_RE = re.compile(r"\b(?:\d{8}|[XYZ]\d{7})[\s-]?[A-Z]\b", re.IGNORECASE)

# Tolerances for figures the model computes by hand.
SUM_TOLERANCE = 0.00005  # "shares sum to exactly 1.0", at the four decimals the model uses
DIST_TOLERANCE = 0.001  # a distribution given with two or three decimals sums to 1 within this
FIXED_TOTAL_TOLERANCE_PP = 0.5  # weighted parcel mix and B2B share against company.json (prompt 004)
MULTIPLIER_TOLERANCE = 0.0005  # Monday-Friday average and the Saturday ratio
FIRST_ATTEMPT_TOLERANCE_PP = 0.05  # expected first-attempt failure against the target, rounding slack
LANGUAGE_TOLERANCE_PP = 5  # the notes' language mix against the "about" shares of prompt 008

MIN_MORNING_ZONE_COVERAGE = 2  # every zone known by at least two morning drivers (prompt 003)
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri")
SAME_DAY_CUTOFF_HOUR = 11  # hours before this are "registered before the cut-off"
NOTES_EXPECTED = 300  # prompt 008
# Prompt 008: about 50% Spanish, 30% Catalan, 15% English, 5% other languages or mixed.
LANGUAGE_TARGETS = {"es": 50, "ca": 30, "en": 15}
OTHER_LANGUAGES_TARGET = 5


def check_structure(seeds: dict[str, dict]) -> None:
    print("Structure")
    for name, data in seeds.items():
        schema = read_json(SEED_DIR / f"{name}.schema.json")
        validator = jsonschema.Draft202012Validator(schema)
        problems = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
        for problem in problems:
            error(f"{name}.json {'/'.join(map(str, problem.path)) or '(root)'}: {problem.message}")
        if not problems:
            ok(f"schema violations of {name}.json against {name}.schema.json: 0")


def duplicates(values: list) -> str:
    counts = Counter(values)
    return ", ".join(sorted(str(v) for v, n in counts.items() if n > 1)) or "none"


def check_fleet(fleet: dict, company: dict) -> None:
    print("Fleet register (prompt 002)")
    vehicles = fleet["vehicles"]
    types = {t["type_id"]: t for t in company["fleet"]["vehicle_types"]}
    zones = {z["zone_id"]: z for z in company["zones"]}
    afternoon_drivers = company["drivers"]["shifts"][1]["drivers"]

    total = company["fleet"]["total_vehicles"]
    check(len(vehicles) == total, f"{len(vehicles)} vehicles (company.json: {total})")
    ids = [v["vehicle_id"] for v in vehicles]
    check(duplicates(ids) == "none", f"duplicated vehicle ids: {duplicates(ids)}")

    counts = Counter(v["type_id"] for v in vehicles)
    expected = {type_id: t["count"] for type_id, t in types.items()}
    summary = ", ".join(f"{type_id} {counts.get(type_id, 0)}" for type_id in expected)
    check(dict(counts) == expected, f"type counts {summary} (company.json: same types and counts)")

    plates = [v["plate"] for v in vehicles]
    bad_plates = [p for p in plates if not PLATE_RE.match(p)]
    check(not bad_plates, f"plates in the format NNNN CCC without vowels, Ñ or Q; wrong: {bad_plates or 'none'}")
    check(duplicates(plates) == "none", f"duplicated plates: {duplicates(plates)}")
    telematics = [v["telematics_unit_id"] for v in vehicles]
    check(duplicates(telematics) == "none", f"duplicated telematics unit ids: {duplicates(telematics)}")

    afternoon = [v for v in vehicles if v["runs_afternoon_wave"]]
    check(
        len(afternoon) == afternoon_drivers,
        f"{len(afternoon)} vehicles run the afternoon wave (company.json: {afternoon_drivers} afternoon drivers)",
    )
    diesel_afternoon = [v["vehicle_id"] for v in afternoon if types[v["type_id"]]["energy"] == "diesel"]
    check(not diesel_afternoon, f"diesel vehicles in the afternoon wave: {diesel_afternoon or 'none'}")

    unknown_zone = [v["vehicle_id"] for v in vehicles if v["home_zone_id"] not in zones]
    check(not unknown_zone, f"home zones missing from company.json: {unknown_zone or 'none'}")
    wrong_zone = [
        f"{v['vehicle_id']} {v['type_id']} in {v['home_zone_id']}"
        for v in vehicles
        if v["home_zone_id"] in zones and v["type_id"] not in zones[v["home_zone_id"]]["preferred_vehicle_type_ids"]
    ]
    check(not wrong_zone, f"home zones that do not prefer the vehicle's type: {wrong_zone or 'none'}")

    soh_wrong = [
        v["vehicle_id"]
        for v in vehicles
        if (types[v["type_id"]]["energy"] == "electric") != (v["battery_state_of_health_pct"] is not None)
    ]
    check(not soh_wrong, f"battery state of health set exactly for electric types; wrong: {soh_wrong or 'none'}")

    diesel_years = [v["registration_year"] for v in vehicles if types[v["type_id"]]["energy"] == "diesel"]
    other_years = [v["registration_year"] for v in vehicles if types[v["type_id"]]["energy"] != "diesel"]
    if diesel_years and other_years:
        check(
            max(diesel_years) <= min(other_years),
            f"diesel vans are the oldest: registered {max(diesel_years)} at the latest, "
            f"every other vehicle {min(other_years)} or later",
        )


def check_drivers(roster: dict, company: dict) -> None:
    print("Driver roster (prompt 003)")
    drivers = roster["drivers"]
    zones = {z["zone_id"] for z in company["zones"]}
    types = {t["type_id"] for t in company["fleet"]["vehicle_types"]}
    headcount = company["drivers"]["headcount"]
    shifts = {s["name"]: s["drivers"] for s in company["drivers"]["shifts"]}

    ids = [d["driver_id"] for d in drivers]
    check(len(drivers) == headcount, f"{len(drivers)} drivers (company.json headcount: {headcount})")
    check(duplicates(ids) == "none", f"duplicated driver ids: {duplicates(ids)}")

    by_shift = Counter(d["shift"] for d in drivers)
    expected = {**shifts, RELIEF_POOL: headcount - sum(shifts.values())}
    summary = ", ".join(f"{name} {by_shift.get(name, 0)}" for name in expected)
    check(
        dict(by_shift) == expected,
        f"shifts {summary} (company.json: {', '.join(f'{k} {v}' for k, v in expected.items())})",
    )

    morning_name = company["drivers"]["shifts"][0]["name"]
    coverage = Counter(z for d in drivers if d["shift"] == morning_name for z in d["zone_knowledge"])
    thin = sorted(z for z in zones if coverage.get(z, 0) < MIN_MORNING_ZONE_COVERAGE)
    lowest = min(coverage.get(z, 0) for z in zones)
    check(
        not thin,
        f"every zone known by at least {MIN_MORNING_ZONE_COVERAGE} morning drivers "
        f"(lowest coverage {lowest}); short: {thin or 'none'}",
    )

    bad_zones = sorted({z for d in drivers for z in d["zone_knowledge"] if z not in zones})
    sizes = Counter(len(d["zone_knowledge"]) for d in drivers)
    check(
        not bad_zones,
        f"zone knowledge of 1-4 zones, drivers by count {dict(sorted(sizes.items()))}; unknown: {bad_zones or 'none'}",
    )
    bad_types = sorted({t for d in drivers for t in d["qualified_vehicle_types"] if t not in types})
    check(not bad_types, f"qualified vehicle types missing from company.json: {bad_types or 'none'}")

    no_spanish = [d["driver_id"] for d in drivers if "Spanish" not in d["languages"]]
    check(not no_spanish, f"drivers who do not speak Spanish: {no_spanish or 'none'}")

    founded = company["company"]["founded_year"]
    out_of_range = [d["driver_id"] for d in drivers if not founded <= d["hired_year"] <= 2026]
    years = sorted(d["hired_year"] for d in drivers)
    check(
        not out_of_range,
        f"hired {years[0]}-{years[-1]}, within {founded} (company founded) to 2026; outside: {out_of_range or 'none'}",
    )

    contact = [
        d["driver_id"]
        for d in drivers
        for value in d.values()
        for text in (value if isinstance(value, list) else [value])
        if isinstance(text, str) and (PHONE_RE.search(text) or EMAIL_RE.search(text))
    ]
    check(not contact, f"phone numbers or e-mail addresses: {sorted(set(contact)) or 'none'}")


def expected_first_attempt_failure(demand: dict, company: dict, business: dict[str, float]) -> dict[str, float]:
    """Expected share of parcels that fail at the first attempt, by recipient type and overall."""
    zones = {z["zone_id"]: z for z in company["zones"]}
    fail = demand["failed_first_attempt_probability"]
    choice = demand["consumer_window_choice"]
    consumer_left = {z: zones[z]["share_of_daily_parcels"] - business[z] for z in zones}
    consumer_total = sum(consumer_left.values())

    failed = {"consumer": 0.0, "business": 0.0}
    parcels = {"consumer": 0.0, "business": 0.0}
    for shipper in demand["shippers"]:
        share, b = shipper["share_of_daily_parcels"], shipper["business_share"]
        evening_share = 1.0 if shipper["arrives_at_hub"] == MIDDAY_INJECTION else choice["afternoon_evening_wave"]
        factor = (1 - evening_share) + evening_share * fail["evening_window_factor"]
        for zone_id, left in consumer_left.items():
            p = fail["consumer"][zones[zone_id]["delivery_difficulty"]] * factor
            weight = share * (1 - b) * left / consumer_total
            failed["consumer"] += weight * p
            parcels["consumer"] += weight
    for zone_id, weight in business.items():
        failed["business"] += weight * fail["business"][zones[zone_id]["delivery_difficulty"]]
        parcels["business"] += weight
    return {
        "consumer": failed["consumer"] / parcels["consumer"],
        "business": failed["business"] / parcels["business"],
        "overall": (failed["consumer"] + failed["business"]) / (parcels["consumer"] + parcels["business"]),
    }


def check_demand(seeds: Seeds) -> None:
    print("Demand model (prompt 004)")
    demand, company = seeds.demand, seeds.company
    shippers = demand["shippers"]
    volume = company["daily_volume"]
    zone_ids = {z["zone_id"] for z in company["zones"]}

    check(35 <= len(shippers) <= 45, f"{len(shippers)} shippers (prompt: 35 to 45)")
    check(duplicates([s["shipper_id"] for s in shippers]) == "none", "shipper ids are unique")
    check(duplicates([s["name"] for s in shippers]) == "none", "shipper names are unique")

    total = sum(s["share_of_daily_parcels"] for s in shippers)
    check(abs(total - 1) <= SUM_TOLERANCE, f"shipper shares sum to {total:.4f} (expected 1.0000)")

    bad_mix = [s["shipper_id"] for s in shippers if abs(sum(s["parcel_mix"].values()) - 1) > DIST_TOLERANCE]
    check(not bad_mix, f"each shipper's parcel mix sums to 1; wrong: {bad_mix or 'none'}")

    mix = {
        size: 100 * sum(s["share_of_daily_parcels"] * s["parcel_mix"][size] for s in shippers) / total
        for size in ("small", "medium", "large")
    }
    fixed = volume["parcel_mix"]
    off = max(abs(mix[size] - fixed[f"{size}_pct"]) for size in mix)
    check(
        off <= FIXED_TOTAL_TOLERANCE_PP,
        f"weighted parcel mix {mix['small']:.1f}/{mix['medium']:.1f}/{mix['large']:.1f}% "
        f"(company.json: {fixed['small_pct']:.0f}/{fixed['medium_pct']:.0f}/{fixed['large_pct']:.0f}%, "
        f"off by {off:.2f} pp, tolerance {FIXED_TOTAL_TOLERANCE_PP} pp)",
    )
    b2b = 100 * weekday_business_share(demand) / total
    check(
        abs(b2b - volume["b2b_share_pct"]) <= FIXED_TOTAL_TOLERANCE_PP,
        f"weighted B2B share {b2b:.1f}% (company.json: {volume['b2b_share_pct']:.0f}%, "
        f"tolerance {FIXED_TOTAL_TOLERANCE_PP} pp)",
    )

    kinds = {"consumer": lambda b: b == 0, "business": lambda b: b == 1, "mixed": lambda b: 0 < b < 1}
    wrong_kind = [s["shipper_id"] for s in shippers if not kinds[s["recipient_type"]](s["business_share"])]
    check(not wrong_kind, f"recipient type agrees with business share (0, 1 or between); wrong: {wrong_kind or 'none'}")
    zones_wrong = [
        s["shipper_id"] for s in shippers if bool(s["business_recipient_zones"]) != (s["business_share"] > 0)
    ]
    check(
        not zones_wrong,
        f"business zones listed exactly when the business share is above 0; wrong: {zones_wrong or 'none'}",
    )
    unknown = sorted({z for s in shippers for z in s["business_recipient_zones"] if z not in zone_ids})
    check(not unknown, f"business zones missing from company.json: {unknown or 'none'}")

    hourly = demand["hourly_registration_share"]
    hourly_sum = sum(hourly.values())
    before_cutoff = sum(v for h, v in hourly.items() if int(h) < SAME_DAY_CUTOFF_HOUR)
    cutoff = company["hub"]["timetable"]["same_day_cutoff"]
    check(
        minutes(cutoff) == SAME_DAY_CUTOFF_HOUR * 60,
        f"same-day cut-off {cutoff} (company.json), the hour the checks below use",
    )
    check(
        abs(hourly_sum - 1) <= DIST_TOLERANCE,
        f"hourly curve sums to {hourly_sum:.4f}, {before_cutoff:.1%} registered before {cutoff}",
    )

    same_day_wrong = [
        s["shipper_id"] for s in shippers if s["same_day_share"] > 0 and s["arrives_at_hub"] != MIDDAY_INJECTION
    ]
    check(not same_day_wrong, f"same-day only for midday-injection shippers; wrong: {same_day_wrong or 'none'}")
    too_high = [s["shipper_id"] for s in shippers if s["same_day_share"] > before_cutoff]
    check(
        not too_high,
        f"no same-day share above the {before_cutoff:.1%} registered before the cut-off "
        f"(the generator's probability same_day_share / {before_cutoff:.3f} stays at or below 1); "
        f"above: {too_high or 'none'}",
    )
    same_day = weekday_same_day_share(demand)
    mean = volume["weekday_parcels_mean"]
    print(f"  info   same-day parcels {same_day:.1%} of the day, {same_day * mean:.0f} on a mean weekday")

    multipliers = demand["weekday_multipliers"]
    mon_fri = sum(multipliers[d] for d in WEEKDAYS) / len(WEEKDAYS)
    saturday = volume["saturday_parcels_mean"] / volume["weekday_parcels_mean"]
    check(abs(mon_fri - 1) <= MULTIPLIER_TOLERANCE, f"Monday-Friday multipliers average {mon_fri:.3f} (expected 1.000)")
    check(
        abs(multipliers["Sat"] - saturday) <= MULTIPLIER_TOLERANCE,
        f"Saturday multiplier {multipliers['Sat']:.2f} (company.json: "
        f"{volume['saturday_parcels_mean']} / {volume['weekday_parcels_mean']} = {saturday:.2f})",
    )

    for recipient, dist in demand["parcels_per_stop"].items():
        check(
            abs(sum(dist.values()) - 1) <= DIST_TOLERANCE,
            f"parcels per stop, {recipient}, sums to {sum(dist.values()):.3f}",
        )
    choice = demand["consumer_window_choice"]
    waves = choice["morning_wave"] + choice["afternoon_evening_wave"]
    check(abs(waves - 1) <= DIST_TOLERANCE, f"consumer window choice sums to {waves:.3f} across the two waves")

    waves = delivery_waves(company)
    window = company["service_promise"]["promised_window_minutes"]
    opening_hours = demand["business_opening_hours"]
    for name, hours in opening_hours.items():
        fits = [wave for wave, span in waves.items() if business_window_starts(hours, span, window)]
        check(bool(fits), f"{name} opening hours hold a {window}-minute window in: {', '.join(fits) or 'no wave'}")
    # The generator's rules: a shipper's segment gives its recipients' opening hours, and its hand-over
    # at the hub gives the wave its business parcels ride.
    needed = sorted({(hours_category(s), business_wave(s)) for s in shippers if s["business_share"] > 0})
    no_window = [
        f"{category} in the {wave} wave"
        for category, wave in needed
        if category not in opening_hours or not business_window_starts(opening_hours[category], waves[wave], window)
    ]
    check(
        not no_window,
        f"every business shipper's recipients get a {window}-minute window in the wave of its parcels "
        f"({len(needed)} opening hours and wave pairs); without one: {no_window or 'none'}",
    )

    zone_share = zone_shares(company)
    nowhere = []
    for shipper in shippers:
        try:
            business_zone_weights(shipper, zone_share)
        except SeedError:
            nowhere.append(shipper["shipper_id"])
    check(
        not nowhere,
        f"business shippers with a zone of company.json to deliver to; without one: {nowhere or 'none'}",
    )
    if nowhere:
        print("  skip   business parcels by zone and first-attempt failure: fix the business zones first")
        return
    business = business_parcels_by_zone(seeds)
    over = [z for z in zone_share if business[z] > zone_share[z]]
    check(
        not over,
        f"business parcels within each zone's share, so consumer parcels fill the rest; over: {over or 'none'}",
    )
    by_zone = ", ".join(f"{z} {business[z] / zone_share[z]:.0%}" for z in sorted(zone_share))
    print(f"  info   business share of each zone's parcels: {by_zone}")

    failure = expected_first_attempt_failure(demand, company, business)
    target = 100 - company["service_promise"]["first_attempt_success_target_pct"]
    check(
        100 * failure["overall"] <= target + FIRST_ATTEMPT_TOLERANCE_PP,
        f"expected first-attempt failure {failure['consumer']:.1%} consumer, {failure['business']:.1%} business, "
        f"{failure['overall']:.1%} overall (company.json target: at most {target:.1f}%)",
        warn_only=True,
    )


def check_delivery_notes(corpus: dict, company: dict) -> None:
    print("Delivery notes (prompt 008)")
    notes = corpus["notes"]
    check(len(notes) == NOTES_EXPECTED, f"{len(notes)} notes (prompt: {NOTES_EXPECTED})")
    for field, name in (("note_id", "note ids"), ("text", "texts")):
        repeated = duplicates([n[field] for n in notes])
        check(repeated == "none", f"duplicated {name}: {repeated}")
    lengths = sorted(len(n["text"]) for n in notes)
    print(f"  info   texts of {lengths[0]} to {lengths[-1]} characters, median {lengths[len(lengths) // 2]}")

    contact = [n["note_id"] for n in notes if PHONE_RE.search(n["text"]) or EMAIL_RE.search(n["text"])]
    check(not contact, f"phone numbers or e-mail addresses: {contact or 'none'}")
    documents = [n["note_id"] for n in notes if ID_DOCUMENT_RE.search(n["text"])]
    check(not documents, f"identity document numbers (DNI, NIE): {documents or 'none'}")

    languages = Counter(n["language"] for n in notes)
    pct = {language: 100 * count / len(notes) for language, count in languages.items()}
    other = 100 - sum(pct.get(language, 0) for language in LANGUAGE_TARGETS)
    off = max(
        [abs(pct.get(language, 0) - target) for language, target in LANGUAGE_TARGETS.items()]
        + [abs(other - OTHER_LANGUAGES_TARGET)]
    )
    counts = ", ".join(f"{language} {count}" for language, count in languages.most_common())
    targets = " / ".join(f"{target}" for target in [*LANGUAGE_TARGETS.values(), OTHER_LANGUAGES_TARGET])
    check(
        off <= LANGUAGE_TOLERANCE_PP,
        f"languages {counts}: "
        + ", ".join(f"{lang} {pct.get(lang, 0):.1f}%" for lang in LANGUAGE_TARGETS)
        + f", other or mixed {other:.1f}% (prompt: about {targets}%, off by {off:.1f} pp, "
        f"tolerance {LANGUAGE_TOLERANCE_PP} pp)",
    )

    schema = read_json(SEED_DIR / "delivery_notes.schema.json")
    categories = schema["properties"]["notes"]["items"]["properties"]["category"]["enum"]
    used = Counter(n["category"] for n in notes)
    unused = [c for c in categories if c not in used]
    (fewest, low), (most, high) = used.most_common()[-1], used.most_common(1)[0]
    check(
        not unused,
        f"all {len(categories)} categories used, from {low} {fewest!r} to {high} {most!r}; unused: {unused or 'none'}",
    )
    for label, meaning in (
        ("likely_longer_stop", "a likely longer stop"),
        ("likely_failed_attempt", "a likely failed attempt"),
    ):
        flagged = sum(n[label] for n in notes)
        check(0 < flagged < len(notes), f"{flagged} of {len(notes)} flagged as {meaning} (the label takes both values)")

    # The generator's rules (notes.py): a note that names a place goes only to orders of its zone.
    zone_ids = {z["zone_id"] for z in company["zones"]}
    unknown = sorted(f"{place} {zone}" for place, zone in PLACES.items() if zone is not None and zone not in zone_ids)
    check(not unknown, f"places of the generator in zones of company.json; unknown zones: {unknown or 'none'}")
    named = {place: [n["note_id"] for n in notes if place in places_named(n["text"])] for place in PLACES}
    unnamed = sorted(place for place, ids in named.items() if not ids)
    check(not unnamed, f"every place of the generator is named by a note; not named: {unnamed or 'none'}")
    placed = ", ".join(f"{place} {' '.join(ids)}" for place, ids in named.items())
    print(f"  info   notes that name a place, attached only in its zone (outside the area: never): {placed}")
    try:
        NotePicker(corpus, zone_ids)
        problem = None
    except ValueError as exc:
        problem = str(exc)
    check(
        problem is None,
        f"business and consumer notes to draw from in every zone; {problem or f'all {len(zone_ids)} have both'}",
    )


def main() -> int:
    company = read_json(SEED_DIR / "company.json")
    names = ("fleet", "drivers", "demand", "delivery_notes")
    seeds = {name: read_json(SEED_DIR / f"{name}.json") for name in names}
    check_structure(seeds)
    if errors:
        print(f"\n{len(errors)} structural errors; fix those first.")
        return 1
    check_fleet(seeds["fleet"], company)
    check_drivers(seeds["drivers"], company)
    check_demand(Seeds(company=company, **seeds))
    check_delivery_notes(seeds["delivery_notes"], company)
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
