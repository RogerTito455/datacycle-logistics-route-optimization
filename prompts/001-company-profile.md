# 001 · Company profile

- **Generates:** [`services/generator/seed/company.json`](../services/generator/seed/company.json)
- **Validated by:** [`services/generator/validate_company.py`](../services/generator/validate_company.py) against [`company.schema.json`](../services/generator/seed/company.schema.json)
- **Model:** Claude Opus 5.5 (`claude-opus-5-5`)
- **How it was run:** as the only message of a fresh conversation with no prior context, in an
  agent session that could run shell commands. The model was told not to browse.
- **Date:** 2026-09-28
- **Version:** 1

## Why this prompt looks the way it does

- **Fixed facts first.** The name, the hub location and the fleet size are decisions the team
  already took (ADR 0001). The model fills in everything else.
- **Realism is spelled out.** Barcelona has specific delivery constraints (the ZBE low emission
  zone, superblocks, DUM loading zones, access control in Ciutat Vella). Naming them makes the
  model reason about them instead of producing a generic city.
- **Consistency is required, then checked.** The prompt asks for numbers that agree with each
  other; the validator checks that they do, and checks the geography against OpenStreetMap and
  the real road network.
- **The output shape is fixed.** The JSON skeleton makes the result machine-readable for the
  generators, and the schema file rejects anything that drifts from it.

## Prompt

```text
You are generating seed data for a university data-engineering project. The project simulates the data platform of a fictional last-mile parcel carrier in the Barcelona metropolitan area. The company must feel like a real Spanish parcel operator, similar to the networks of SEUR, MRW, GLS or Correos Express, but it is fictional and must not reuse any real company's brand, slogans or vehicle liveries.

Produce the company profile as a single JSON document. Use only your own knowledge; do not browse the web.

Fixed facts:
- Name: Llobregat Express.
- One cross-dock hub in the Zona Franca logistics area of Barcelona, next to the Llobregat river delta.
- It delivers business-to-consumer and business-to-business parcels: same day for orders received before the morning cut-off, next day otherwise.
- Exactly 30 delivery vehicles are on the road on a normal weekday. The vehicle mix is up to you, but it must be allowed inside Barcelona's Low Emission Zone (ZBE Rondes de Barcelona) and realistic for 2026: mostly electric vans, with some vehicles carrying the ECO or C label.

Realism requirements:
- Service zones: 10 to 14 zones covering the 10 districts of Barcelona city plus the neighbouring municipalities that a carrier based in Zona Franca would serve, such as L'Hospitalet de Llobregat, El Prat de Llobregat, Cornellà de Llobregat, Esplugues de Llobregat and Sant Boi de Llobregat. Use real district and municipality names. Each zone centroid is in WGS84 with 4 decimal places and falls on land inside that district or municipality.
- For each zone, say what makes deliveries there easy or hard: street layout, pedestrian areas, superblocks ("superilles"), urban goods loading zones ("zones DUM") and their time limits, access restrictions in Ciutat Vella, hills, parking. Give realistic figures for stops per route, minutes per stop and share of daily parcels.
- Figures must be internally consistent: zone shares sum to 1.0; vehicle counts sum to 30; the fleet's total parcel capacity covers the mean weekday volume; route durations fit inside the drivers' shifts.
- The delivery-time targets must be consistent with the KPI "Average Delivery Time per Route", defined as the time from the vehicle leaving the hub until its last delivery on that route is completed.
- Vehicle descriptions name the vehicle class, never a brand or model.

Return only the JSON document, with no commentary and no code fences, following exactly this structure. Angle brackets describe the expected type; replace them with values.

{
  "schema_version": 1,
  "company": {
    "name": "Llobregat Express",
    "legal_name": <string>,
    "founded_year": <integer>,
    "headquarters_municipality": <string>,
    "business_model": <string, one or two sentences>,
    "modeled_on": <string, which kind of real Spanish parcel networks it resembles and how>,
    "customer_segments": [<string>]
  },
  "hub": {
    "name": <string>,
    "address": <string>,
    "municipality": <string>,
    "lat": <number>,
    "lon": <number>,
    "floor_area_m2": <integer>,
    "loading_docks": <integer>,
    "sorting_capacity_parcels_per_hour": <integer>,
    "timetable": {
      "inbound_trucks_arrive": "HH:MM-HH:MM",
      "sorting": "HH:MM-HH:MM",
      "first_departure": "HH:MM",
      "last_departure": "HH:MM",
      "same_day_cutoff": "HH:MM"
    }
  },
  "service_promise": {
    "delivery_windows": [{"name": <string>, "start": "HH:MM", "end": "HH:MM"}],
    "promised_window_minutes": <integer>,
    "on_time_target_pct": <number>,
    "first_attempt_success_target_pct": <number>,
    "failed_delivery_policy": <string>
  },
  "daily_volume": {
    "weekday_parcels_mean": <integer>,
    "weekday_parcels_stddev": <integer>,
    "saturday_parcels_mean": <integer>,
    "sunday_operates": <boolean>,
    "seasonal_peaks": [{"name": <string>, "month": <integer 1-12>, "multiplier": <number>}],
    "parcel_mix": {"small_pct": <number>, "medium_pct": <number>, "large_pct": <number>},
    "b2b_share_pct": <number>
  },
  "zones": [
    {
      "zone_id": "Z01",
      "name": <string>,
      "municipality": <string>,
      "districts": [<string>],
      "centroid": {"lat": <number>, "lon": <number>},
      "distance_from_hub_km": <number, by road>,
      "share_of_daily_parcels": <number between 0 and 1>,
      "stops_per_route": <integer>,
      "minutes_per_stop": <number>,
      "delivery_difficulty": "low" | "medium" | "high",
      "difficulty_factors": [<string>],
      "preferred_vehicle_type_ids": [<string>]
    }
  ],
  "fleet": {
    "vehicle_types": [
      {
        "type_id": <string, short code>,
        "description": <string, vehicle class without brand>,
        "count": <integer>,
        "energy": "electric" | "plug-in hybrid" | "diesel" | "CNG",
        "dgt_label": "0" | "ECO" | "C",
        "payload_kg": <integer>,
        "cargo_volume_m3": <number>,
        "parcel_capacity": <integer>,
        "consumption": {"value": <number>, "unit": "kWh/100km" | "l/100km" | "kg/100km"},
        "range_km": <integer>,
        "urban_average_speed_kmh": <number>,
        "telemetry_sensors": [<string>]
      }
    ],
    "total_vehicles": 30
  },
  "drivers": {
    "headcount": <integer>,
    "shifts": [{"name": <string>, "start": "HH:MM", "end": "HH:MM", "break_minutes": <integer>, "drivers": <integer>}],
    "max_route_duration_minutes": <integer>
  },
  "kpi_targets": {
    "avg_delivery_time_per_route_minutes": {"current_baseline": <number>, "target_with_optimization": <number>, "rationale": <string>},
    "avg_delay_vs_plan_minutes": {"current_baseline": <number>, "target": <number>},
    "on_time_share_pct": {"current_baseline": <number>, "target": <number>}
  },
  "operational_risks": [<string, a real-world factor in the Barcelona area that delays delivery routes>]
}
```

## Post-processing

**No hand edits.** `company.json` is the model's answer byte for byte, plus a final newline. The
answer was a single JSON document with no commentary and no code fences, as the prompt asked.

**How the model worked.** It did not browse. It made four shell calls during the run: a scratch
Python calculation to make the figures add up (volume, stops per route, route durations) and a
check that its JSON parsed.

**Validation on 2026-09-28** with `make validate-seeds`: 0 errors, 1 warning.

| Layer | Checks | Result |
|---|---|---|
| Structure | Every field and type against `company.schema.json` | pass |
| Consistency | Zone shares sum to 1.000; 30 vehicles; fleet capacity 4,195 parcels for a 3,500 mean; 83% zero-emission; routes fit the shifts; KPI target below baseline | pass |
| Geography | Hub and all 14 centroids fall in the district or municipality they claim (OpenStreetMap reverse geocoding) and within 300 m of a drivable road | pass |
| Road distances | Distance from the hub claimed by the model against a real route computed by OSRM | 1 warning |

The warning is a real finding. The model's road distances are mostly short: 11 of the 14 claims
are shorter than the route OSRM computes on the real network, the median one by about 16%,
and Sants-Montjuïc is claimed at 4.8 km where the route is 8.0 km. The field stays as generated,
and nothing downstream uses it: the simulator and the optimizer take every distance and travel
time from OSRM.

## History

- v1 · 2026-09-28 · initial
