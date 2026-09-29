# 002 · Fleet register

- **Generates:** [`services/generator/seed/fleet.json`](../services/generator/seed/fleet.json)
- **Validated by:** [`services/generator/validate_seeds.py`](../services/generator/validate_seeds.py) against [`fleet.schema.json`](../services/generator/seed/fleet.schema.json) and [`company.json`](../services/generator/seed/company.json)
- **Used by:** `make load-reference`, which loads it into `bronze.vehicles` ([generator](../services/generator/README.md))
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **How it was run:** as the only message of a fresh conversation with no prior context, in an
  agent session that could run shell commands. The model was told not to browse.
- **Date:** 2026-09-28
- **Version:** 1

## Why this prompt looks the way it does

- **The company profile fixes the frame.** The founding year, the six vehicle types with their
  counts and DGT labels, the 14 zones and the vehicle types each zone prefers are copied from
  `company.json` (prompt 001), so the register cannot contradict it. The validator checks each of
  them against `company.json` again.
- **The afternoon wave is decided here.** The profile runs 10 afternoon routes with vehicles that
  already did a morning route. The prompt asks the model to mark which 10, and to pick vehicles
  that can recharge or refuel at midday.
- **Realism is spelled out where a reader would notice it:** the current Spanish plate format and
  the letter series by year, odometer readings that match age and urban use, battery health for
  electric vans only, the diesel vans as the oldest units.
- **The output shape is fixed.** The JSON skeleton maps to the columns of `bronze.vehicles`, and
  `fleet.schema.json` rejects anything that drifts from it.

## Prompt

```text
You are generating seed data for a university data-engineering project that simulates a fictional last-mile parcel carrier, Llobregat Express, with one hub in the Zona Franca logistics area of Barcelona. Use only your own knowledge; do not browse the web. You may run calculations to keep the numbers consistent.

Produce the fleet register: one record per delivery vehicle.

Fixed facts from the company profile:
- The company was founded in 2014 and operates exactly 30 delivery vehicles.
- Vehicle types and counts: EV-L large battery-electric panel van, 3.5 t, 7 units; EV-M medium battery-electric panel van, 3.1 t, 11 units; EV-S compact battery-electric city van, 2.3 t, 5 units; EV-Q battery-electric heavy utility quadricycle (L7e-CU) for the old town, 2 units; CNG-L large compressed-natural-gas panel van, 3.5 t, DGT label ECO, 3 units; DSL-L large Euro 6d diesel panel van, 3.5 t, DGT label C, 2 units, used for bulky B2B loads and as peak reserve. All electric types carry the DGT label 0.
- Zones: Z01 Ciutat Vella, Z02 Eixample, Z03 Sants-Montjuïc, Z04 Les Corts, Z05 Sarrià-Sant Gervasi, Z06 Gràcia, Z07 Horta-Guinardó, Z08 Nou Barris i Sant Andreu, Z09 Sant Martí, Z10 L'Hospitalet de Llobregat, Z11 El Prat de Llobregat, Z12 Cornellà de Llobregat, Z13 Esplugues de Llobregat, Z14 Sant Boi de Llobregat.
- Preferred vehicle types per zone: Z01 EV-Q, EV-S; Z02 EV-M, EV-S; Z03 EV-M, EV-L; Z04 EV-L, EV-M; Z05 EV-S, EV-M; Z06 EV-S, EV-M; Z07 EV-S, EV-M; Z08 EV-M, CNG-L, EV-L; Z09 EV-L, EV-M; Z10 EV-M, EV-L; Z11 EV-L, CNG-L, DSL-L; Z12 EV-L, CNG-L; Z13 EV-M, EV-S; Z14 CNG-L, DSL-L, EV-L.
- Two delivery waves: 30 morning routes (every vehicle) and 10 afternoon routes, run by 10 of the same vehicles after a midday recharge or refuel at the hub.

Realism requirements:
- Spanish number plates in the current national format: four digits, a space, three consonants (no vowels, no Ñ or Q). The letters must be plausible for the registration year: the series advances roughly one first letter every two years, from about "K" in 2018-2019 to about "N" in 2025-2026. Plates are unique.
- Registration years between 2016 and 2026, consistent with the technology: electric vans mostly from 2020 onward, the two quadricycles recent, the diesel vans the oldest in the fleet.
- Odometer readings consistent with age and urban use (roughly 20,000 to 35,000 km per year for vans, less for quadricycles).
- For electric vehicles, a battery state of health that declines with age and mileage; null for the others.
- Each vehicle has a home zone that matches its type's preferred zones, and the 30 home zones are spread in proportion to each zone's workload (the Eixample, Sant Martí, L'Hospitalet de Llobregat and Nou Barris i Sant Andreu get more).
- Exactly 10 vehicles are marked as also running the afternoon wave, and they are ones that can recharge or refuel in the middle of the day.
- A small, realistic maintenance picture: one or two vehicles have a service due soon or a known minor defect, described in plain words.
- No brand or model names anywhere.

Return only the JSON document, with no commentary and no code fences, following exactly this structure. Angle brackets describe the expected type; replace them with values.

{
  "schema_version": 1,
  "generated_for": "Llobregat Express fleet register",
  "vehicles": [
    {
      "vehicle_id": "V-01",
      "type_id": <"EV-L" | "EV-M" | "EV-S" | "EV-Q" | "CNG-L" | "DSL-L">,
      "plate": <string, e.g. "1234 LBC">,
      "registration_year": <integer>,
      "odometer_km": <integer>,
      "battery_state_of_health_pct": <number or null>,
      "home_zone_id": <"Z01" ... "Z14">,
      "runs_afternoon_wave": <boolean>,
      "telematics_unit_id": <string, e.g. "TLM-4F2A91">,
      "maintenance_note": <string or null>
    }
  ]
}
```

## Post-processing

**No hand edits.** `fleet.json` is the model's answer byte for byte, plus a final newline. The
answer was a single JSON document with no commentary and no code fences, as the prompt asked.

**How the model worked.** It did not browse. It made two shell calls during the run, both arithmetic
to keep the figures consistent.

**Validation on 2026-09-29** with `make validate-seeds`: 0 errors, 0 warnings in the 13 checks of
the fleet register.

| Layer | Checks | Result |
|---|---|---|
| Structure | Every field and type against `fleet.schema.json` | pass |
| Against `company.json` | 30 vehicles; type counts EV-L 7, EV-M 11, EV-S 5, EV-Q 2, CNG-L 3, DSL-L 2; every home zone is a zone of the profile that lists the vehicle's type among its preferred types; exactly 10 vehicles in the afternoon wave, one per afternoon driver | pass |
| Internal | Unique vehicle ids, plates and telematics units; plates in the format `NNNN CCC` with no vowels, Ñ or Q; no diesel van in the afternoon wave; a battery state of health for exactly the electric vehicles; the diesel vans, registered in 2020, older than every other vehicle, registered in 2021 or later | pass |

## History

- v1 · 2026-09-28 · initial
