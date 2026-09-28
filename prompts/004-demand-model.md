# 004 · Demand model

- **Generates:** [`services/generator/seed/demand.json`](../services/generator/seed/demand.json)
- **Validated by:** [`services/generator/validate_seeds.py`](../services/generator/validate_seeds.py) against [`demand.schema.json`](../services/generator/seed/demand.schema.json) and [`company.json`](../services/generator/seed/company.json)
- **Used by:** `make load-reference`, which loads the shippers into `bronze.shippers`, and `make generate`, which draws every day's orders from it ([generator](../services/generator/README.md))
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **How it was run:** as the only message of a fresh conversation with no prior context, in an
  agent session that could run shell commands. The model was told not to browse.
- **Date:** 2026-09-28
- **Version:** 1

## Why this prompt looks the way it does

- **A model, not a list of orders.** The platform needs a new batch of orders every day, at real
  addresses. So the prompt asks for the parameters a program draws orders from (shippers, the
  hourly curve, weekday multipliers, window choice, parcels per stop, opening hours) and tells the
  model not to produce addresses: the generator takes them from Open Data BCN and ICGC.
- **The totals are fixed and must be reproduced.** Volume, parcel mix, business share, the 11:00
  cut-off, the two waves, the customer segments, the zone shares and the seasonal peaks come from
  `company.json` (prompt 001). The shipper list has to add up to them within half a percentage
  point, and the validator recomputes every sum.
- **Written assumptions make the model executable.** The skeleton ends with a list of assumptions
  in plain words. The model used it to state the rules its numbers depend on (how business parcels
  spread over zones, when an order can be same-day, what happens on Saturday and Monday), and the
  generator implements those rules as written.
- **The output shape is fixed.** `demand.schema.json` rejects anything that drifts from the
  skeleton.

## Prompt

```text
You are generating seed data for a university data-engineering project that simulates a fictional last-mile parcel carrier, Llobregat Express, with one hub in the Zona Franca logistics area of Barcelona. Use only your own knowledge; do not browse the web. You may run calculations to keep the numbers consistent.

Produce the demand model: who sends the parcels and how orders arrive over the day. A program will use it to generate each day's orders, drawing real delivery addresses from the Barcelona open data address register, so you do not produce addresses or individual orders.

Fixed facts from the company profile:
- 3,500 parcels on a mean weekday (standard deviation 350), 1,050 on Saturday, no Sunday operation.
- Parcel mix: 58% small, 30% medium, 12% large. Business customers (B2B deliveries) are 32% of parcels.
- Same-day delivery for orders registered before 11:00; next day otherwise. Delivery windows: morning wave 08:00-14:00 (next-day B2C and B2B), afternoon-evening wave 15:00-21:00 (same-day and evening B2C). The promise to the recipient is a 120-minute window.
- Customer segments: e-commerce retailers shipping to consumers; marketplace sellers and local online shops buying same-day delivery; national parcel networks and couriers subcontracting final-mile delivery in Barcelona; pharmacies and healthcare distributors (ambient goods only); retail chains and independent shops (store replenishment); offices and professional services; industrial and spare-parts distributors.
- Zones and their share of daily parcels: Z01 Ciutat Vella 0.06, Z02 Eixample 0.17, Z03 Sants-Montjuïc 0.08, Z04 Les Corts 0.05, Z05 Sarrià-Sant Gervasi 0.07, Z06 Gràcia 0.06, Z07 Horta-Guinardó 0.06, Z08 Nou Barris i Sant Andreu 0.09, Z09 Sant Martí 0.11, Z10 L'Hospitalet de Llobregat 0.11, Z11 El Prat de Llobregat 0.04, Z12 Cornellà de Llobregat 0.04, Z13 Esplugues de Llobregat 0.02, Z14 Sant Boi de Llobregat 0.04.
- Seasonal peaks: November ×1.55 (Black Friday week), December ×1.4, January ×1.2, September ×1.1.

Realism requirements:
- 35 to 45 shippers with invented names that are clearly fictional and do not imitate any real brand. Each has a segment, a short description, its share of the daily parcels, its parcel size mix, the share of its parcels that are same-day, whether its recipients are consumers or businesses, and the time its parcels reach the hub (linehaul arrival or local injection). Shares sum to exactly 1.0; the weighted parcel mix and B2B share across shippers reproduce the fixed totals within half a percentage point.
- For B2B shippers, the zones their business recipients concentrate in (offices in Sant Martí's 22@ and along the Diagonal, shops in Ciutat Vella, Eixample and Gràcia, industry in El Prat, Cornellà, Sant Boi and L'Hospitalet, healthcare around the big hospitals).
- An hourly curve of order registration for a weekday (share of the day's orders registered in each hour, 00-23), consistent with the 11:00 same-day cut-off and with how online shopping behaves in Spain.
- Day-of-week multipliers for Monday to Saturday relative to the mean weekday.
- The share of consumer recipients who choose each delivery window, and the share who pick a specific 120-minute slot versus "any time in the wave".
- The probability of a failed first attempt, by zone difficulty (low, medium, high) and by recipient type and window, consistent with a first-attempt success target of 92%.
- The distribution of parcels per stop (how often one stop receives 1, 2, 3, 4 or more parcels), separately for consumer and business recipients.
- Opening hours for business recipients by segment (shops, offices, industry, healthcare).

Return only the JSON document, with no commentary and no code fences, following exactly this structure. Angle brackets describe the expected type; replace them with values.

{
  "schema_version": 1,
  "generated_for": "Llobregat Express demand model",
  "shippers": [
    {
      "shipper_id": "S-01",
      "name": <string>,
      "segment": "e-commerce retailer" | "marketplace seller" | "partner network" | "healthcare distributor" | "retail replenishment" | "office supplies and services" | "industrial distributor",
      "description": <string, one sentence>,
      "share_of_daily_parcels": <number>,
      "parcel_mix": {"small": <number>, "medium": <number>, "large": <number>},
      "same_day_share": <number between 0 and 1>,
      "recipient_type": "consumer" | "business" | "mixed",
      "business_share": <number between 0 and 1>,
      "arrives_at_hub": "overnight linehaul" | "morning injection" | "midday injection",
      "business_recipient_zones": [<"Z01" ... "Z14">]
    }
  ],
  "hourly_registration_share": {"00": <number>, "01": <number>, "...": "... one key per hour up to 23"},
  "weekday_multipliers": {"Mon": <number>, "Tue": <number>, "Wed": <number>, "Thu": <number>, "Fri": <number>, "Sat": <number>},
  "consumer_window_choice": {"morning_wave": <number>, "afternoon_evening_wave": <number>, "specific_slot_share": <number between 0 and 1>},
  "failed_first_attempt_probability": {
    "consumer": {"low": <number>, "medium": <number>, "high": <number>},
    "business": {"low": <number>, "medium": <number>, "high": <number>},
    "evening_window_factor": <number, multiplier applied in the 15:00-21:00 wave>
  },
  "parcels_per_stop": {
    "consumer": {"1": <number>, "2": <number>, "3": <number>, "4+": <number>},
    "business": {"1": <number>, "2": <number>, "3": <number>, "4+": <number>}
  },
  "business_opening_hours": {
    "shops": {"open": "HH:MM", "close": "HH:MM", "lunch_break": "HH:MM-HH:MM" or null},
    "offices": {"open": "HH:MM", "close": "HH:MM", "lunch_break": "HH:MM-HH:MM" or null},
    "industry": {"open": "HH:MM", "close": "HH:MM", "lunch_break": "HH:MM-HH:MM" or null},
    "healthcare": {"open": "HH:MM", "close": "HH:MM", "lunch_break": "HH:MM-HH:MM" or null}
  },
  "assumptions": [<string, one assumption per item, in plain words>]
}
```

## Post-processing

**No hand edits.** `demand.json` is the model's answer byte for byte, plus a final newline. The
answer was a single JSON document with no commentary and no code fences, as the prompt asked.

**How the model worked.** It did not browse. It made 15 shell calls and wrote one scratch file
during the run, iterating the shipper shares until the weighted parcel mix, the business share and
the hourly curve matched the fixed totals.

**Validation on 2026-09-29** with `make validate-seeds`: 0 errors and 1 warning in the 26 checks
of the demand model.

| Layer | Checks | Result |
|---|---|---|
| Structure | Every field and type against `demand.schema.json` | pass |
| Against `company.json` | Weighted parcel mix 58.1 / 30.2 / 11.7% against 58 / 30 / 12% (0.30 pp off, tolerance 0.5 pp); business share 32.1% against 32%; Saturday multiplier 0.30 = 1,050 / 3,500; Monday to Friday multipliers average 1.000; 28.2% of orders registered before the 11:00 cut-off; business zones only among the profile's zones; the opening hours of shops, offices, industry and healthcare each hold a 120-minute window in both waves; business parcels stay below every zone's share, so consumer parcels can fill the rest | pass |
| Internal | 40 shippers with unique ids and names; shares sum to 1.0000; each shipper's parcel mix sums to 1; recipient type agrees with business share; business zones listed exactly when the business share is above 0; same-day only for midday-injection shippers, none above the 28.2% registered before the cut-off; hourly curve, parcels per stop and window choice each sum to 1 | pass |
| Service target | Expected first-attempt failure against the 92% first-attempt success target | 1 warning |

The business share of each zone that the validator computes from the shipper list (Z01 35%, Z02
39%, ... Z14 37%) is exactly the list the model gives in its assumptions.

**A mismatch the review found.** The warning comes from one of the assumptions. It rates the
zones high for Z01, Z06 and Z07, medium for Z02, Z03, Z05, Z08, Z09 and Z10, and low for Z04 and
Z11 to Z14. `company.json` rates three of them differently: Z05 Sarrià-Sant Gervasi is high, Z09
Sant Martí is low and Z13 Esplugues de Llobregat is medium. The model's expected first-attempt
failure (10.1% consumer, 3.5% business, 8.0% overall) is exactly what its own ratings give. With the
ratings of `company.json` it is 10.2%, 3.5% and 8.06%: 0.06 points above the 8% that the 92% target
allows. The assumption is kept as generated. The zone difficulty that counts on the platform is the
one in `company.json` and `bronze.zones`; the order generator does not use the failure
probabilities.

## History

- v1 · 2026-09-28 · initial
