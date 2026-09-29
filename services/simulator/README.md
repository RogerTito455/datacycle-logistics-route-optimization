# Simulator

Simulates the daily operation of Llobregat Express on the real road network. Today it makes the
**baseline route plan** of a service date: the fixed plan of each delivery wave that the company's
planners make before the vans leave, which the optimizer (issue #16) will be compared with.

| Command | What it does |
|---|---|
| `make plan DATE=2026-09-28` | Plans the date's generated orders into routes: rows in `bronze.route_plans` and `bronze.route_plan_stops` (`WAVE=morning` or `afternoon` for one wave) |
| `make test-simulator` | Runs the tests, offline |

The platform must be running (`make up`) and the date generated (`make generate`), because the
planner reads the orders from `bronze.orders` and asks OSRM for travel times.

## Where the data comes from

| Data | Source |
|---|---|
| Orders to plan | `bronze.orders`, written by the [order generator](../generator/README.md) |
| Zones, vehicle types, capacities, stops per route, minutes per stop, waves, 120-minute promise, 390-minute maximum route, shifts and breaks | Company profile, [`company.json`](../generator/seed/company.json) (prompt 001) |
| Vans, their type and home zone, which ones run the afternoon wave | Fleet register, [`fleet.json`](../generator/seed/fleet.json) (prompt 002) |
| Drivers, their shift, the zones they know and the vans they are cleared for | Driver roster, [`drivers.json`](../generator/seed/drivers.json) (prompt 003) |
| Travel times and distances between stops | The stack's OSRM over the OpenStreetMap road network of Catalonia (`/table`) |

The seeds are read with the generator's own code (`llobregat-generator` is a dependency), so the
planner and the generator can never read them differently.

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

## How to run

```bash
make plan DATE=2026-09-28                 # both waves
make plan DATE=2026-09-28 WAVE=morning    # one wave
```

Without `make`, run the CLI with the project's pinned environment and the variables of `.env`:

```bash
uv run --project services/simulator --frozen llobregat-simulator plan --date 2026-09-28
```

| Variable | Default | Meaning |
|---|---|---|
| `OSRM_URL` | `http://localhost:5000` | The stack's OSRM; inside Compose `http://osrm:5000` |
| `POSTGRES_*`, `S3_*` | as for the [generator](../generator/README.md#how-to-run) | TimescaleDB and RustFS |

## Tests

`make test-simulator` runs offline, with no database, OSRM or network. It generates a Monday of
orders at the generator's sample addresses and plans it on a straight-line road network (the
great-circle distance times 1.3, at 20 km/h). It checks that every order of a wave is planned once
or held and a mean morning holds none, that no van carries more parcels than its capacity, that the
morning sends the 30 vans and the afternoon the 10 of the register, that most stops go to a van of
their zone, that drivers belong to the shift and are cleared for their van, that times follow the
road and vans leave 40 seconds apart, the promised windows, the nearest-open-stop order on a small
example, that a fleet too small holds what it cannot carry, the grouping of zones, and that the same
orders give the same plan.
