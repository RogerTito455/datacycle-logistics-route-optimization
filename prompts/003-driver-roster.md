# 003 · Driver roster

- **Generates:** [`services/generator/seed/drivers.json`](../services/generator/seed/drivers.json)
- **Validated by:** [`services/generator/validate_seeds.py`](../services/generator/validate_seeds.py) against [`drivers.schema.json`](../services/generator/seed/drivers.schema.json) and [`company.json`](../services/generator/seed/company.json)
- **Used by:** `make load-reference`, which loads it into `bronze.drivers` ([generator](../services/generator/README.md))
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **How it was run:** as the only message of a fresh conversation with no prior context, in an
  agent session that could run shell commands. The model was told not to browse.
- **Date:** 2026-09-28
- **Version:** 1

## Why this prompt looks the way it does

- **The company profile fixes the frame.** Headcount, shifts, the 390-minute maximum route, the
  vehicle types and the zones come from `company.json` (prompt 001). The profile puts 40 of its 48
  drivers on the two shifts; the prompt names the other 8 a relief pool that covers days off,
  leave and peaks, which is how a carrier of this size staffs its routes.
- **Personal data stays fictional.** The drivers are people, so the prompt asks for invented names
  and forbids phone numbers, e-mail addresses, identity numbers and home addresses. The validator
  searches every field for phone numbers and e-mail addresses.
- **Planning needs more than a name.** Zone knowledge, vehicle qualifications, contract type and
  a short planning note are what a route planner uses to assign a driver. The prompt asks that
  every zone is known by at least two morning drivers, so every morning route can get a driver who
  knows it.
- **Realism is spelled out:** the diversity of the Barcelona delivery workforce, languages that
  match each person's background, realistic home municipalities and contracts.
- **The output shape is fixed.** The JSON skeleton maps to the columns of `bronze.drivers`, and
  `drivers.schema.json` rejects anything that drifts from it.

## Prompt

```text
You are generating seed data for a university data-engineering project that simulates a fictional last-mile parcel carrier, Llobregat Express, with one hub in the Zona Franca logistics area of Barcelona. Use only your own knowledge; do not browse the web. You may run calculations to keep the numbers consistent.

Produce the driver roster: one record per driver. Every person is fictional: invent names that do not belong to any real, identifiable person, and include no phone numbers, email addresses, identity document numbers or home addresses.

Fixed facts from the company profile:
- 48 drivers in total.
- Shifts: "Morning wave" 07:00-15:30 with a 30-minute break, 30 drivers; "Afternoon-evening wave" 13:30-22:00 with a 30-minute break, 10 drivers. The remaining 8 drivers are a relief pool that covers days off, holidays, sick leave and seasonal peaks, and are assigned to either wave week by week.
- Routes last at most 390 minutes.
- Vehicle types: EV-L, EV-M and EV-S (battery-electric vans), EV-Q (battery-electric L7e-CU quadricycle for the old town), CNG-L (natural-gas van), DSL-L (diesel van). All can be driven with a standard category B licence.
- Zones: Z01 Ciutat Vella, Z02 Eixample, Z03 Sants-Montjuïc, Z04 Les Corts, Z05 Sarrià-Sant Gervasi, Z06 Gràcia, Z07 Horta-Guinardó, Z08 Nou Barris i Sant Andreu, Z09 Sant Martí, Z10 L'Hospitalet de Llobregat, Z11 El Prat de Llobregat, Z12 Cornellà de Llobregat, Z13 Esplugues de Llobregat, Z14 Sant Boi de Llobregat.

Realism requirements:
- Names reflect the real diversity of the delivery workforce of the Barcelona metropolitan area in 2026: mostly Spanish and Catalan names with two surnames, and a realistic share of people of Latin American, Moroccan, Pakistani, Romanian and other origins, named as they would be in Spain.
- Languages spoken are consistent with the person's background; Spanish for everyone; Catalan for a realistic share; English, Arabic, Urdu, Romanian and others where plausible.
- Home municipalities are realistic commuting places for a Zona Franca job (L'Hospitalet de Llobregat, El Prat de Llobregat, Cornellà de Llobregat, Sant Boi de Llobregat, Barcelona, Badalona, Santa Coloma de Gramenet, Viladecans, Gavà, Castelldefels and similar).
- Contract types and years of experience vary realistically for the sector (permanent full-time for most, some part-time and temporary, more temporary contracts in the relief pool).
- Each driver knows one to four zones well; the zone knowledge of the 30 morning drivers covers every zone at least twice.
- Some drivers are not yet cleared on some vehicle types (for example the quadricycle requires a short internal course), so qualified vehicle types differ between drivers.
- A small realistic share has a note that affects planning, in plain words, without health details (for example "prefers not to drive the diesel vans", "on a reduced-hours arrangement until December", "trainer for new drivers").

Return only the JSON document, with no commentary and no code fences, following exactly this structure. Angle brackets describe the expected type; replace them with values.

{
  "schema_version": 1,
  "generated_for": "Llobregat Express driver roster",
  "drivers": [
    {
      "driver_id": "D-001",
      "first_name": <string>,
      "last_names": <string>,
      "shift": "Morning wave" | "Afternoon-evening wave" | "Relief pool",
      "contract": "permanent full-time" | "permanent part-time" | "temporary",
      "hired_year": <integer between 2014 and 2026>,
      "years_driving_professionally": <integer>,
      "home_municipality": <string>,
      "languages": [<string>],
      "zone_knowledge": [<"Z01" ... "Z14">],
      "qualified_vehicle_types": [<"EV-L" | "EV-M" | "EV-S" | "EV-Q" | "CNG-L" | "DSL-L">],
      "planning_note": <string or null>
    }
  ]
}
```

## Post-processing

**No hand edits.** `drivers.json` is the model's answer byte for byte, plus a final newline. The
answer was a single JSON document with no commentary and no code fences, as the prompt asked.

**How the model worked.** It did not browse. It made two shell calls during the run: arithmetic, and
a count of how many morning drivers know each zone.

**Validation on 2026-09-29** with `make validate-seeds`: 0 errors, 0 warnings in the 10 checks of
the driver roster.

| Layer | Checks | Result |
|---|---|---|
| Structure | Every field and type against `drivers.schema.json` | pass |
| Against `company.json` | 48 drivers; 30 on the morning wave, 10 on the afternoon-evening wave and 8 in the relief pool; zone knowledge only of zones in the profile; qualified vehicle types only of types in the fleet; hired between 2014, when the company was founded, and 2026 | pass |
| Internal | Unique driver ids; one to four known zones per driver; every zone known by at least 2 morning drivers (the least known zones by 4); everyone speaks Spanish; no phone numbers or e-mail addresses in any field | pass |

## History

- v1 · 2026-09-28 · initial
