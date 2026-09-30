# Phase 3 · DIKW

> Select one raw data element of the case that is related to the KPI and build the hierarchy
> **Data → Information → Knowledge → Action/Value**.

The element is the **GPS ping**, dataset 1 of the [phase 1 inventory](1-case.md#data-inventory).
It is the rawest data the platform receives: a position and a time, sent by every van every five
seconds. It is also where the KPI starts, because *Average Delivery Time per Route* measures each
route from its first ping outside the hub.

The theory calls the fourth level *Action/Value*; the example case calls it *Wisdom*. They are the
same level: the decision taken with the knowledge, and the value it produces.

Every figure below that does not link to another document comes from the running platform: the orders of Monday 28 September 2026, their
baseline plan and the simulated day, queried in `bronze`. The queries are in
[`queries/3-dikw.sql`](queries/3-dikw.sql) and [Reproduce](#reproduce) runs them.

## The hierarchy at a glance

| Level | What you do | Example from the platform | Where it lives |
|---|---|---|---|
| Data | Record | `{"vehicle_id": "V-08", "lat": 41.342012, "lon": 2.133056, "event_time": "2026-09-28T05:34:10Z", ...}` | Topic `gps.pings`, table `bronze.gps_pings` |
| Information | Put in context | Van V-08 left the hub at 07:34:10 on its Eixample route; at 09:30 it has finished 18 of its 69 stops, where the plan expected 23, and is 25 minutes behind | Today, a query on bronze; the planned dbt model `silver.fct_route` (issue #10) |
| Knowledge | Find the pattern and its cause | The baseline plan does not hold: routes last 425 minutes against 381 planned, and 31 of 40 go past the 390-minute maximum. On this day the lateness at 10:00 already told which ones | Today, queries on bronze; the planned gold models (#10) and Grafana dashboard (#12) |
| Action/Value | Decide | At 10:00, re-plan the pending stops of the 21 morning routes heading past 390 minutes; plan with the real speed of the streets from the start | Today, the list as a query; the planned optimizer (#16) writes the re-plan with `replan_reason` `delay` |

Each level answers a different question:

| Level | Question | Answer for the GPS ping |
|---|---|---|
| Data | What happened? | A device reported a position at a time |
| Information | What does it mean? | Van V-08 has left the hub, and is running late |
| Knowledge | Why is it happening? | The plan is built on empty-city travel times, so the routes fall behind from their first stops |
| Action/Value | What should we do? | Re-plan the routes that will not finish in time, and fix the plan itself |

## Data

These are four pings of van V-08, five seconds apart, as it drives out of the hub on
28 September 2026, as the stream consumer stored them from the topic `gps.pings`. The JSON is
the message the simulator sent (phase 2 shows its format):

```json
{"vehicle_id": "V-08", "route_id": "R-20260928-Z02-M1", "event_time": "2026-09-28T05:34:00Z", "lat": 41.341906, "lon": 2.133289, "speed_kmh": 9.2, "heading_deg": 291, "accuracy_m": 4.2, "source": "simulator/gps", "schema_version": 1}
{"vehicle_id": "V-08", "route_id": "R-20260928-Z02-M1", "event_time": "2026-09-28T05:34:05Z", "lat": 41.34192, "lon": 2.133192, "speed_kmh": 8.3, "heading_deg": 296, "accuracy_m": 4.7, "source": "simulator/gps", "schema_version": 1}
{"vehicle_id": "V-08", "route_id": "R-20260928-Z02-M1", "event_time": "2026-09-28T05:34:10Z", "lat": 41.342012, "lon": 2.133056, "speed_kmh": 9.0, "heading_deg": 296, "accuracy_m": 3.9, "source": "simulator/gps", "schema_version": 1}
{"vehicle_id": "V-08", "route_id": "R-20260928-Z02-M1", "event_time": "2026-09-28T05:34:15Z", "lat": 41.34204, "lon": 2.132947, "speed_kmh": 8.4, "heading_deg": 296, "accuracy_m": 4.5, "source": "simulator/gps", "schema_version": 1}
```

On its own each ping says very little: a device was at a pair of coordinates at a moment in UTC,
moving slowly towards the north-west. Nothing in it says that these coordinates are the edge of
the hub's yard, that the van has 69 stops ahead of it or that it was planned to leave its dock
at 07:32. That is what makes it data: a raw fact with no context.

The platform keeps it that way at this level. `bronze.gps_pings` stores every ping as it arrived,
226,713 of them for the day, next to 7,644 handheld scans, and rejects none for its values; checks and meaning come later
([data model](../data-model.md#layers)).

## Information

Information is the ping put in context. Three pieces of context turn these pings into facts about
the route:

| Context | From | What it adds |
|---|---|---|
| Where the hub is, and where it ends | `bronze.hubs`: 41.3395, 2.1365, geofence of 400 m | The distance of each ping from the hub |
| Which route, which van, what was planned | `bronze.route_plans` and `bronze.route_plan_stops`, the baseline plan | Planned departure 07:32:00, 69 stops, the planned arrival at each |
| What the driver has done | `bronze.delivery_events`, the handheld's scans | Which stops are finished, and when |

With the hub's position, the four pings are 379, 386, 401 and 410 metres from it. The third one is
the first outside the 400-metre geofence, so it marks the departure the KPI measures from:

> **Van V-08 left the hub at 07:34:10 on route R-20260928-Z02-M1, the first morning route of the
> Eixample. Its plan had it leaving the dock at 07:32:00; the 2 minutes and 10 seconds between
> the two include the drive out of the yard to the edge of the geofence.**

Two hours later the same pings, with the plan and the scans, describe how the route is going.
This is the route at 09:30:

| | |
|---|---|
| Last ping | 41.382252, 2.16339, in the Eixample, driving at 26.2 km/h |
| Stops finished | 18 of 69; stop 18 was a failed attempt |
| Stops the plan expected finished by 09:30 | 23 |
| Lateness | The scan of stop 18 came at 09:28:25; the plan had the van arriving there at 09:03:31. About 25 minutes late on the clock |

> **At 09:30 van V-08 is five stops and about 25 minutes behind its plan.**

In this document a route's *lateness* is always measured on the clock: how much later than
planned its last scan came. Its *delay against plan*, the supporting KPI of phase 1, compares
lengths instead: actual length from the geofence exit minus planned length.

This is the step that phase 2 describes as parsing: a semi-structured message becomes a typed row,
and the row is joined to the reference data and the plan. In the platform it will be the dbt model
`silver.fct_route` (issue #10), with one row per route and its departure from the geofence. Until
then, the same logic is a query on bronze.

## Knowledge

Knowledge comes from looking at many routes at once and asking why. The same calculation for the
40 routes of the day, from the geofence exit to the last scan, against the length of their plan:

| Wave | Routes | Actual length (average) | Planned length | Delay against plan | Past 390 minutes in the plan | Past 390 minutes at the end |
|---|---|---|---|---|---|---|
| Morning | 30 | 426 min | 379 min | 47 min | 11 | 22 |
| Afternoon | 10 | 423 min | 388 min | 34 min | 5 | 9 |
| Day | 40 | **425 min** | 381 min | **44 min** | 16 | **31** |

The *Average Delivery Time per Route* of the day is 425 minutes. The company profile gives 361
minutes as today's figure and 330 as the target ([phase 1](1-case.md#targets)); this Monday, with
4,678 parcels, was a third heavier than the profile's mean weekday of 3,500
([simulator](../../services/simulator/README.md#28-september-2026)).

Three things are learned from the data:

1. **The plan is already too tight before the vans leave.** It gives the average route 381
   minutes, close to the 390-minute maximum, and 16 of the 40 routes are over the maximum in the
   plan itself. The planner times the legs with OSRM on an empty city, so the plan is optimistic by
   construction ([simulator](../../services/simulator/README.md#baseline-plan)).
2. **The lateness builds up from the first stops, and does not recover.** V-08 crossed the
   geofence about 2 minutes after its planned departure, was 25 minutes late at 09:30 and 28 at
   10:00, and finished its last stop at 14:25:31, 35 minutes after the planned 13:50:53. Nobody changes the plan during the day, so nothing absorbs the delay.
3. **Some zones fall behind more than others.** In the morning, Sants-Montjuïc (73 minutes on
   average), Sant Boi (66), Nou Barris i Sant Andreu (64), Les Corts (58) and the hill districts of
   Horta-Guinardó and Sarrià-Sant Gervasi (56 and 54) lose the most against their plans. The flat grids of the
   Eixample, Sant Martí, El Prat and Cornellà lose the least (23 to 31). The zone is a segment of
   the KPI for that reason.

The most useful piece of knowledge for acting follows from the second point: **the lateness at
10:00 predicts the end of the route.** Move a route's planned completion by its lateness at
10:00, measure from its geofence exit, and the projected length says whether it will finish past
390 minutes. For the 30 morning routes of 28 September:

| At 10:00 the route was | Finished past 390 minutes | Finished within 390 minutes |
|---|---|---|
| Heading past 390 minutes | 21 | 0 |
| Within 390 minutes | 1 | 8 |

On this day all 21 routes flagged at 10:00 finished past 390 minutes, and only one such route
was missed. It is one simulated day, not a proven rule; the dashboards will show whether it holds
over more. Eleven of the 21
were over the maximum in the plan; the other ten were pushed over by the delay of their first two
hours.

In the platform this knowledge is the gold layer: `gold.kpi_route_duration` (the KPI by day, zone,
hour of departure, vehicle type and weather) and `gold.kpi_delay_and_on_time` (delay against plan
and on-time share). Both are planned dbt models (issue #10), to be shown in Grafana (issue #12);
until then the queries above compute them from bronze.

## Action/Value

The action is what the company does with the knowledge. At 10:00 the list of routes heading past
390 minutes is ready. These are its first eight rows, out of 21 morning routes:

| Route | Van | Zone | Stops done | Late by | Projected length |
|---|---|---|---|---|---|
| R-20260928-Z01-M1 | V-24 | Ciutat Vella | 17 of 47 | 39 min | 402 min |
| R-20260928-Z08-M2 | V-28 | Nou Barris i Sant Andreu | 17 of 63 | 36 min | 464 min |
| R-20260928-Z07-M2 | V-20 | Horta-Guinardó | 17 of 62 | 35 min | 478 min |
| R-20260928-Z04-M2 | V-02 | Les Corts | 18 of 62 | 35 min | 423 min |
| R-20260928-Z05-M2 | V-23 | Sarrià-Sant Gervasi | 18 of 62 | 30 min | 487 min |
| R-20260928-Z14-M1 | V-30 | Sant Boi de Llobregat | 19 of 72 | 30 min | 450 min |
| R-20260928-Z03-M1 | V-04 | Sants-Montjuïc | 20 of 69 | 30 min | 505 min |
| R-20260928-Z02-M1 | V-08 | Eixample | 24 of 69 | 28 min | 405 min |

With it the company can act on the day and on the plan:

| When | Action | Who does it in the platform |
|---|---|---|
| Now, at 10:00 | Re-plan the pending stops of the 21 routes with the travel times the vans are actually getting, and move the last stops of the worst ones to the eight morning routes that will finish within 390 minutes | The optimizer (issue #16) reads the latest pings and scans and writes a new version of the route in `bronze.route_plans`, with `replan_reason` `delay`; the van picks it up between stops |
| Tomorrow | Plan with the real speed of the streets and the hour of the day, not the empty-city times, and stagger the departures to avoid the peak | The planner and the optimizer, with the traffic loader (issue #9) |

The value is measured by the same KPI the hierarchy started from. The company's target is to take
the average route from 361 to 330 minutes, and [phase 1](1-case.md#targets) breaks down where the
31 minutes come from: time-dependent stop sequencing, clustering stops around loading bays,
staggered departures and small vehicles in the old town and the hills. Every minute off the
average route is driver overtime saved and deliveries that arrive inside their window: on
28 September only 63.4% of the deliveries were scanned inside their promised window, against a
target of 95%.

The optimizer is not built yet; its go/no-go decision is issue #15. The list at 10:00 is not an
estimate of what it would do: it is a query that runs today on the platform's data, and it becomes
a Grafana panel with the dashboards (issues #12 and #17).

## Reproduce

With the platform up (`make up`, or `docker compose up -d --wait` where `make` is not installed):

```bash
make load-reference
make generate DATE=2026-09-28
make plan DATE=2026-09-28
make simulate DATE=2026-09-28 SPEED=0
docker compose exec -T timescaledb psql -U llobregat -d logistics < docs/phases/queries/3-dikw.sql
```

Without `make`, the generator and the simulator run in the simulator's container:

```bash
docker compose run --rm --entrypoint llobregat-generator simulator load-reference
docker compose run --rm --entrypoint llobregat-generator simulator orders --date 2026-09-28 --seed 0
docker compose run --rm simulator plan --date 2026-09-28
docker compose run --rm simulator simulate --date 2026-09-28 --speed 0
```

The figures in this document come from that run on 30 September 2026: 226,713 pings, 7,644 scans,
40 routes.
