# Simulator

Simulates the daily operation of Llobregat Express on the real road network: the **baseline route
plan** of a service date, the fixed plan of each delivery wave that the company's planners make
before the vans leave, and **the vans that drive it**, publishing what a real fleet sends: GPS
pings, vehicle telemetry and the scans of the drivers' handhelds, with a proof-of-delivery photo for
every delivered parcel. The optimizer (issue #16) will be compared with the baseline plan.

| Command | What it does |
|---|---|
| `make plan DATE=2026-09-28` | Plans the date's generated orders into routes: rows in `bronze.route_plans` and `bronze.route_plan_stops` (`WAVE=morning` or `afternoon` for one wave) |
| `make simulate DATE=2026-09-28 SPEED=60` | Drives the date's baseline plan and publishes to Redpanda: `gps.pings`, `vehicle.telemetry` and `delivery.events`, with the photos in RustFS. `SPEED=60` runs a simulated minute in a second, `1` in real time, `0` as fast as possible; `WAVE=` and `SEED=` as for `plan` and `generate` |
| `make test-simulator` | Runs the tests, offline |

The platform must be running (`make up`) and the date generated (`make generate`), because the
planner reads the orders from `bronze.orders` and both ask OSRM for the roads.

## Where the data comes from

| Data | Source |
|---|---|
| Orders to plan | `bronze.orders`, written by the [order generator](../generator/README.md) |
| Zones, vehicle types, capacities, stops per route, minutes per stop, waves, 120-minute promise, 390-minute maximum route, shifts and breaks | Company profile, [`company.json`](../generator/seed/company.json) (prompt 001) |
| Vans, their type and home zone, which ones run the afternoon wave | Fleet register, [`fleet.json`](../generator/seed/fleet.json) (prompt 002) |
| Drivers, their shift, the zones they know and the vans they are cleared for | Driver roster, [`drivers.json`](../generator/seed/drivers.json) (prompt 003) |
| Travel times and distances between stops | The stack's OSRM over the OpenStreetMap road network of Catalonia (`/table`) |
| The road each van drives, segment by segment, and OSRM's time for each | The same OSRM (`/route`) |
| Failed-first-attempt probabilities | Demand model, [`demand.json`](../generator/seed/demand.json) (prompt 004) |
| Labels of the delivery notes: likely longer stop, likely failed attempt, category | [`delivery_notes.json`](../generator/seed/delivery_notes.json) (prompt 008), through `bronze.orders.note_id` |
| Vehicle energy, consumption, range and sensors | Company profile, `fleet.vehicle_types`; odometer and battery health from the fleet register |

The seeds are read with the generator's own code (`llobregat-generator` is a dependency), so the
simulator and the generator can never read them differently, and the photos are drawn by the
generator's [proof-of-delivery module](../generator/README.md#proof-of-delivery-photos).

## Baseline plan

The company plans every wave the same way today, with one fixed plan and no changes during the
day. [`planner.py`](llobregat_simulator/planner.py) follows these rules:

| Step | Rule | From |
|---|---|---|
| Vans | Every van of the wave goes out: the 30 of the fleet in the morning, the 10 the fleet register marks `runs_afternoon_wave` in the afternoon | `company.json`, `fleet.json` |
| Routes per zone | A zone needs its stops divided by its `stops_per_route`, its estimated minutes divided by a route's, or its parcels divided by the mean van capacity, whichever is more. Every zone with orders gets a route; the other routes go one at a time to the zone with the highest need per route (D'Hondt). With fewer vans than zones, the smallest zone joins its nearest neighbour until there are as many areas as vans | `company.json` |
| Vans to routes | A zone takes its own vans first (home zone), preferred types and larger vans first; routes without a van, the busiest first, take a free van of a preferred type from the nearest home zone | `fleet.json`, `preferred_vehicle_type_ids` |
| Orders to routes | The zone's orders are swept by angle around their centre and cut into consecutive slices in proportion to the vans' capacity. A slice never exceeds the van's `parcel_capacity` or the 390-minute maximum, estimated at the zone's minutes per stop plus 1.8 minutes of driving per stop, 25 minutes from the hub and the break. Orders that do not fit go to the route with room nearest to them; orders no route has room for stay at the hub (held) | `company.json` |
| Stop order | Nearest neighbour on OSRM travel times from the hub, among the stops whose window is open when the van gets there or opens within 15 minutes; with none open, the van goes to the window that opens first and waits | OSRM `/table` |
| Times | Vans leave from 07:30 (morning) or 14:35 (afternoon), one every 40 seconds; each stop takes its zone's `minutes_per_stop`; the 30-minute break comes after the first stop that ends three hours after departure. Travel times are OSRM's without traffic, so the plan is optimistic | `company.json` hub timetable, shifts |
| Promise | An order whose customer accepted any time in the wave (`window_type` `wave`) gets its 120-minute window from the plan: it starts on the half hour at or before the planned arrival minus an hour, inside the wave. Slot and business orders keep their own window | demand model (prompt 004), `promised_window_minutes` |
| Drivers | A driver of the wave's shift cleared for the van, who knows the route's zone if possible; the route with the fewest candidates is served first | `drivers.json` |

The rules the seeds do not give are the planner's own and are constants at the top of
`planner.py`: planning at 06:00 and 13:45, departures from 07:30 and 14:35 every 40 seconds, 15
minutes of early delivery, the break after three hours, windows on the half hour and the length
estimate. The estimate of 1.8 minutes of driving per stop is what OSRM gives these plans on the
streets (about 2 on 28 September 2026), where the company profile claims 1.1; with it every morning
order of that heavy Monday is planned.

Nothing is random: the same orders and the same road network always give the same plan.

### What it writes

| Table | Rows | `source` |
|---|---|---|
| `bronze.route_plans` | One per route: `plan_version` 0, `planner` `baseline`, `replan_reason` `initial`, wave, main zone, van, driver, stops, planned departure and completion, kilometres from the hub to the last stop | `planner/baseline` |
| `bronze.route_plan_stops` | One per stop, in order: order, planned arrival, the leg from the previous stop (km and seconds) and the promised window (`window_start`, `window_end`, migration 012) | `planner/baseline` |

Route ids are `R-<date>-<zone>-<M or A><n>`, such as `R-20260928-Z02-M1`, the first morning route
of the Eixample. `event_time` is when the wave's plan is made, 06:00 or 13:45 on the service date,
also when a past date is planned again. Planning a date again replaces its baseline plan in one
transaction, like regenerating its orders; it refuses if the optimizer has re-planned a route of
those waves.

### 28 September 2026

`make plan DATE=2026-09-28` on the orders of `make generate DATE=2026-09-28`, a Monday in September
with 4,678 parcels, a third more than the company profile's mean weekday:

| | Morning | Afternoon |
|---|---|---|
| Routes | 30 | 10 |
| Orders planned | 1,895 of 1,895 | 653 of 1,468 |
| Held at the hub | 0 | 815 orders, 1,041 parcels |
| Stops per route | 63 (35 to 74) | 65 (52 to 71) |
| Load | 67% of capacity | 64% |
| Planned length, departure to the end of the last stop | 6 h 20 min on average, 12 routes over 390 minutes | 6 h 28 min, 5 over |
| Stops served by a van of their zone | 90% | 72% |

**The afternoon wave cannot carry the demand model's afternoon.** The demand model sends about 40%
of the parcels to the 15:00-21:00 wave, but the company profile runs 10 vans in it: 1,270 parcels
of capacity and 10 routes of at most 390 minutes, about 650 stops. The planner fills them and holds
the rest, and says so. Either the fleet register and the driver roster need more afternoon vans
and drivers, or the demand model a smaller afternoon share.

## Simulation

[`van.py`](llobregat_simulator/van.py) drives each van through its routes of the day, in order;
[`behaviour.py`](llobregat_simulator/behaviour.py) decides what happens at each stop and
[`traffic.py`](llobregat_simulator/traffic.py) how fast the roads move.

| Step | Rule | From |
|---|---|---|
| At the hub | The van is at its dock 15 minutes before its planned departure, cargo door open, ignition off. Its pings carry no route while it waits | platform assumption |
| Departure | At the planned departure every parcel of the route is scanned `out_for_delivery`. A van's afternoon route starts 20 minutes after it came back from the morning if that is later than planned | platform assumption |
| Driving | The van follows the OSRM geometry of hub, stops and hub, segment by segment. A segment takes OSRM's duration, turn penalties included, times the traffic factor when it starts, times a random factor per leg (lognormal, σ 0.12) | OSRM `/route` |
| Traffic | Until the traffic loader (#9) fills `bronze.traffic_state`, a weekday profile of Barcelona: ×1.2 from 07:00, ×1.5 in the morning peak 07:30-09:30, ×1.25 until 13:00, ×1.35 at midday until 15:00, ×1.25 until 17:30, ×1.45 in the evening peak until 20:00, ×1.15 until 22:00, ×1.0 at night; half the slowdown on Saturday. On 28 September 2026 the vans drive at 19.4 km/h on average, where the company profile gives its vans an urban average of 18 to 19 | platform assumption, `urban_average_speed_kmh` |
| Arrival | The handheld scans `arrived`. More than 15 minutes before the promised window, the driver waits | as the planner |
| The stop | Gamma-distributed around the zone's `minutes_per_stop` (coefficient of variation 0.5, at least 45 s). The cargo door opens 15 s into the stop and closes 15 s before the end; the ignition is off from 5 s after arriving to 5 s before leaving. The `delivered` or `failed` scan comes three quarters into the stop, at the address | `company.json` |
| Failure | With the demand model's failed-first-attempt probability: by recipient and the zone's `delivery_difficulty`, times the evening factor (0.7) for a consumer in the afternoon wave. A failed scan has a `failure_reason`, from the note when it says (a location hint: `address_not_found`; access: `access_restricted`; business hours or schedule: `recipient_absent`), otherwise drawn: consumers 75% `recipient_absent`, 8% `access_restricted`, 7% `address_not_found`, 5% `refused`, 2% `damaged`, 3% `other`; businesses 70% `recipient_absent`, 15% `access_restricted`, 10% `refused`, 5% `other` | demand model (prompt 004) |
| Notes | A stop whose note is labelled `likely_longer_stop` takes 1.5 times longer, and one labelled `likely_failed_attempt` fails 2.5 times more often; the other stops of the route are scaled down so the route keeps the model's expected minutes and failures | delivery notes (prompt 008) |
| Photo | Every `delivered` scan names its proof-of-delivery photo, `pod/<service date>/<order id>.jpg` in the RustFS `bronze` bucket, drawn by the generator's module with the scan's time and the address in its EXIF metadata. The photo is stored before the event is sent | generator `pod.py` |
| Break | 30 minutes after the first stop that ends three hours after departure, unless it was the last | as the planner |
| Back at the hub | After the last stop the van drives back; its pings keep the route until it is inside the hub. An electric van charges between waves at 50 kW, up to full | platform assumption |
| Energy | Falls with every kilometre at the vehicle type's consumption (`kWh/100km`, `l/100km` or `kg/100km`) from a level drawn at dawn: 88-100% for an electric van charged overnight, 35-95% of the tank for diesel, 40-95% for CNG. The level is a share of the usable battery (the type's range at its consumption, times the battery health of the fleet register) or tank. It only rises while charging | `company.json`, `fleet.json` |

Everything random is drawn from generators seeded with `--seed`, the date and the van or the route,
so the same plan, road network and seed always give the same messages, and one route's draws do not
depend on the others. Event ids are UUIDs derived from route, order and status, so running a date
again with the same seed sends the same events, which the consumer (#8) writes once.

**The hook for live traffic.** `traffic.py` defines `Traffic`, anything with a
`factor(when, lon, lat)` method, and the simulator takes one. Once #9 loads
`bronze.traffic_state`, a live model can read the latest state of the Open Data BCN sections near
the van (joined to `bronze.traffic_section_points`), turn it into a factor and fall back to the
profile where the city publishes no section, the ring roads and the neighbouring towns. The plan
source has its hook too: `plans.read_plan` is where a van would pick up the optimizer's latest
version of its route (#16) between stops.

### Messages

Every message is a JSON object keyed by `vehicle_id`, so all of a van's messages land in one
partition, in order. Each carries the metadata of ADR 0001, decision 20, that a message can carry:
`source` (a key of `ops.data_sources`), `event_time` (UTC, when it happened in the simulation) and
`schema_version` (of the message, 1). `ingested_at` and `owner` belong to the table the consumer
(#8) writes it into. `event_time` is always simulated time: the speed changes when a message is
sent, never what it says.

| Topic | Every | Fields | Lands in |
|---|---|---|---|
| `gps.pings` | 5 s per van, from the dock to the hub | `vehicle_id`, `route_id` (absent while the van waits at the hub), `event_time`, `lat`, `lon` (with 3-8 m of GNSS noise), `speed_kmh`, `heading_deg`, `accuracy_m`, `source` `simulator/gps`, `schema_version` | `bronze.gps_pings` |
| `vehicle.telemetry` | 30 s per van | `vehicle_id`, `route_id`, `event_time`, `speed_kmh`, `odometer_km`, `ignition_on`, `energy_level_pct`, `energy_used_total`, `energy_unit`, `cargo_door_open`, `source` `simulator/telemetry`, `schema_version`; by vehicle type `charging` (electric), `tyre_pressure_bar` (types with TPMS), `engine_rpm` and `adblue_level_pct` (diesel), `cng_tank_pressure_bar` (CNG) | `bronze.vehicle_telemetry`, the type-specific keys in `readings` |
| `delivery.events` | Each scan | `event_id`, `order_id`, `route_id`, `stop_sequence`, `vehicle_id`, `driver_id`, `status` (`out_for_delivery`, `arrived`, `delivered`, `failed`), `lat`, `lon`, `failure_reason` (failed only), `pod_object_key` (delivered only), `event_time`, `source` `simulator/handheld`, `schema_version` | `bronze.delivery_events` |

The KPI's `departed_at` is the first ping of a route outside the hub geofence
(`bronze.hubs.geofence_radius_m`, 400 m): the van waits at the dock, 284 m from the hub point, and
the first ping more than 400 m away is the departure. Its `completed_at` is the last `delivered` or
`failed` scan of the route.

### 28 September 2026, driven

`make simulate DATE=2026-09-28 SPEED=120` drove the 40 routes of the plan above from 07:15 to 23:39
of simulated time in 8.2 minutes, never behind schedule, and sent:

| Topic | Messages (`rpk topic describe`) |
|---|---|
| `gps.pings` | 226,280 |
| `vehicle.telemetry` | 37,712 |
| `delivery.events` | 7,644: 2,548 `out_for_delivery`, 2,548 `arrived`, 2,292 `delivered`, 256 `failed` |

The 2,292 delivered events name 2,292 photos under `pod/2026-09-28/` in the `bronze` bucket, all of
them stored; for 50 sampled at random, the EXIF time and position are the event's.

| Measured from the messages, as silver will | Morning | Afternoon | Company profile today |
|---|---|---|---|
| Average delivery time per route, geofence exit to the last scan | 429 min (longest 558) | 423 min | 361 min |
| Deliveries inside the promised window | 69.3% | 46.0% | 87.5% |
| Failed at the first attempt, per stop | 10.8% | 7.8% | 9.3% expected by the demand model for these stops, 10.0% simulated |

The delay against plan is 45 minutes on average (the profile says 22 today). The baseline is worse
than the profile's figures on this date for reasons the data shows: a Monday a third heavier than a
mean weekday; about 70 km per route, the drive back included, where the profile's breakdown (100
minutes of driving at its 18 km/h) implies about 30, because a nearest neighbour that respects the
windows goes back and forth between the slots of a wave on the real one-way streets; and a plan made
on OSRM's empty-city times. The vans drive at 19.4 km/h on average, the company profile's own urban
speed, so the difference is in the plan, not in the traffic. Seven of the ten afternoon routes leave
15 to 88 minutes late because their vans come back late from the morning, and the last van is back
at the hub at 23:39. That is the room the optimizer (#16) has to work in.

## How to run

```bash
make plan DATE=2026-09-28                    # both waves
make plan DATE=2026-09-28 WAVE=morning       # one wave
make simulate DATE=2026-09-28 SPEED=60       # the whole day in about 16 minutes
make simulate DATE=2026-09-28 WAVE=morning SPEED=600
```

`simulate` prints the messages sent every half hour of simulated time and, at the end, the counts
per topic and the KPI measured from what it sent. `WAVE=` simulates one wave's routes only; the
whole day gives the afternoon vans their morning first, so their departure, charge and battery
follow from it.

Without `make`, run the CLI with the project's pinned environment and the variables of `.env`:

```bash
uv run --project services/simulator --frozen llobregat-simulator plan --date 2026-09-28
uv run --project services/simulator --frozen llobregat-simulator simulate --date 2026-09-28 --speed 60
```

Or inside the stack, as a Compose service that `docker compose up` leaves alone (profile
`simulator`), for a Codespace with nothing installed:

```bash
docker compose run --rm simulator plan --date 2026-09-28
docker compose run --rm simulator simulate --date 2026-09-28 --speed 60
```

| Variable | Default | Meaning |
|---|---|---|
| `OSRM_URL` | `http://localhost:5000` | The stack's OSRM; inside Compose `http://osrm:5000` |
| `KAFKA_BOOTSTRAP` | `localhost:19092` | Redpanda's Kafka API; inside Compose `redpanda:9092` |
| `POSTGRES_*`, `S3_*` | as for the [generator](../generator/README.md#how-to-run) | TimescaleDB and RustFS |

## Tests

`make test-simulator` runs offline, with no database, OSRM, broker or network. It generates a
Monday of orders at the generator's sample addresses, plans it on a straight-line road network (the
great-circle distance times 1.3, at 20 km/h) and drives the plan along straight roads cut every
60 m.

For the plan it checks that every order of a wave is planned once or held and a mean morning holds
none, that no van carries more parcels than its capacity, that the morning sends the 30 vans and the
afternoon the 10 of the register, that most stops go to a van of their zone, that drivers belong to
the shift and are cleared for their van, that times follow the road and vans leave 40 seconds
apart, the promised windows, the nearest-open-stop order on a small example, that a fleet too small
holds what it cannot carry, the grouping of zones, and that the same orders give the same plan.

For the simulation it checks that every van pings every 5 seconds from the dock to the hub and
reports telemetry every 30, that pings stay within 25 m of the road, that pings before a route are
inside the hub geofence and carry no route, and the first one outside comes after the planned
departure, that energy levels only fall between charges (and the afternoon vans do charge) while the
odometer and the energy counter never fall, that each order is scanned `out_for_delivery`, `arrived`
and `delivered` or `failed` in that order, that every delivery names its photo and every failure a
reason, that the failure rate is the demand model's within four standard deviations, that stops take
the zones' minutes on average, that notes move the odds but keep the total, that every message
carries `source`, `event_time` and `schema_version`, that the same date and seed give the same
messages and another seed others, the traffic profile, and that the stream paces the messages at the
speed asked and sends a delivery only after its photo is stored.
