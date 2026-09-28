# Phase 1 · The practical case

> **Case 3 · Logistics (Route Optimization).** A transportation company wants to optimize routes
> in real time to reduce costs and delays. Lineage KPI: *Average Delivery Time per Route*.

This document sets the scene for every other phase: who the company is, what problem it has,
exactly how the KPI is measured, and which data exists to measure it.

## The company: Llobregat Express

Regional last-mile parcel carrier that receives parcels from e-commerce shippers, local fulfilment centres and partner carriers at a single cross-dock in the Zona Franca and delivers them across Barcelona and the lower Llobregat area: same day for shipments registered before 11:00, next day otherwise. It charges shippers per parcel by size and service level, and also works as the final-mile subcontractor for national networks that have no fleet of their own in Barcelona.

It works like the Barcelona metropolitan branch of a Spanish national parcel network such as SEUR, MRW, GLS or Correos Express. Overnight linehaul trucks feed one cross-dock, parcels are sorted by delivery zone before dawn, and salaried drivers run fixed zone routes in the morning, with a second afternoon wave for same-day e-commerce. Unlike those networks it has no national coverage of its own: it only delivers in the Barcelona area and takes parcels from shippers and partner carriers.

The profile below was generated with AI from [prompt 001](../../prompts/001-company-profile.md)
and checked by a validator against OpenStreetMap and the real road network. The machine-readable
version is [`company.json`](../../services/generator/seed/company.json); every figure in this
section comes from it.

| | |
|---|---|
| Legal name | Llobregat Express Logística, S.L., founded 2014, headquartered in Barcelona |
| Hub | Llobregat Express Hub Zona Franca (BCN-ZF), Carrer 4, 18-24, Sector C, Polígon Industrial de la Zona Franca, 08040 Barcelona (41.3395, 2.1365) |
| Hub size | 7,500 m², 36 loading docks, sorts 2,500 parcels per hour |
| Daily rhythm | Trucks arrive 02:30–12:30, sorting 03:00–14:00, vans leave 07:30–14:45, same-day cut-off 11:00 |
| Volume | 3,500 parcels on a weekday (standard deviation 350), 1,050 on Saturday, closed on Sunday; 32% business-to-business (B2B), the rest to consumers (B2C) |
| Parcel mix | 58% small, 30% medium, 12% large |
| Seasonal peaks | Black Friday and Cyber Monday week (November) ×1.55, Christmas gift season (December) ×1.4, Three Kings gifts and January sales returns (January) ×1.2, back to school (September) ×1.1 |
| Delivery waves | Morning 08:00–14:00 (next-day B2C and B2B), afternoon-evening 15:00–21:00 (same-day and evening B2C) |
| Service promise | The customer gets a 120-minute window; targets of 95.0% delivered on time and 92.0% delivered at the first attempt |
| Failed deliveries | Second attempt on the next working day or redirection to a pick-up point or locker; after a second failure the parcel waits 7 days at a pick-up point and then returns to the shipper |
| Drivers | 48 in total; 30 on the morning shift (07:00–15:30) and 10 on the afternoon-evening shift (13:30–22:00), each with a 30-minute break |
| Route length | At most 390 minutes from hub departure to last stop |

Customer segments:

- E-commerce retailers (fashion, electronics, home goods) shipping to consumers in the Barcelona metropolitan area
- Marketplace sellers and local online shops buying same-day delivery
- National parcel networks and couriers subcontracting final-mile delivery in Barcelona
- Pharmacies and healthcare distributors (ambient-temperature goods only)
- Retail chains and independent shops in Ciutat Vella, Eixample and Gràcia (store replenishment and supplies)
- Offices and professional services in the 22@, Diagonal and Gran Via L'Hospitalet business districts
- Industrial and spare-parts distributors in the Zona Franca, El Prat, Cornellà and Sant Boi industrial estates

### Fleet

Thirty vehicles, 25 of them zero-emission (DGT label 0), all allowed inside Barcelona's low
emission zone. One full-fleet load is 4,195 parcels, above the weekday mean of 3,500. Only the
morning wave uses the whole fleet; the afternoon-evening wave runs 10 vehicles, one per driver on
that shift.

| Type | Vehicle class | Units | Energy | DGT label | Parcels | Payload | Cargo volume | Consumption | Range |
|---|---|---|---|---|---|---|---|---|---|
| `EV-L` | Large battery-electric panel van, 3.5 t GVW, long wheelbase, high roof, fitted with parcel shelving | 7 | electric | 0 | 190 | 1,000 kg | 11.0 m³ | 27.0 kWh/100km | 260 km |
| `EV-M` | Medium battery-electric panel van, 3.1 t GVW, long wheelbase, standard roof low enough for underground car parks | 11 | electric | 0 | 120 | 950 kg | 6.1 m³ | 21.5 kWh/100km | 250 km |
| `EV-S` | Compact battery-electric city van, 2.3 t GVW, extended body with sliding doors on both sides | 5 | electric | 0 | 85 | 650 kg | 3.9 m³ | 17.0 kWh/100km | 220 km |
| `EV-Q` | Battery-electric heavy utility quadricycle (L7e-CU) with a box body, about 1.4 m wide, for the narrow streets of the old town | 2 | electric | 0 | 70 | 500 kg | 3.2 m³ | 9.5 kWh/100km | 110 km |
| `CNG-L` | Large compressed-natural-gas panel van, 3.5 t GVW, long wheelbase, high roof | 3 | CNG | ECO | 180 | 950 kg | 10.5 m³ | 9.0 kg/100km | 330 km |
| `DSL-L` | Large Euro 6d diesel panel van, 3.5 t GVW, extra-long wheelbase, high roof, used for bulky B2B loads and as peak reserve | 2 | diesel | C | 220 | 1,300 kg | 13.0 m³ | 10.5 l/100km | 700 km |

### Service zones

Fourteen zones: the ten districts of Barcelona (Nou Barris and Sant Andreu share a zone) and the
five neighbouring municipalities of the lower Llobregat. The municipality is shown in brackets
when it differs from the zone name.

| Zone | Area | Share of parcels | Stops per route | Min per stop | Difficulty | Preferred vehicles | Main difficulty factor |
|---|---|---|---|---|---|---|---|
| Z01 | Ciutat Vella (Barcelona) | 6% | 55 | 4.6 | high | `EV-Q`, `EV-S` | Medieval street pattern in the Gòtic, Born and Raval: lanes 3-5 m wide where a van cannot enter or turn, so most stops are walked with a hand trolley 150-400 m from the vehicle |
| Z02 | Eixample (Barcelona) | 17% | 78 | 3.0 | medium | `EV-M`, `EV-S` | Regular Cerdà grid with chamfered corners (xamfrans) where most DUM bays sit: stop sequencing is predictable and one parking often serves 3-5 addresses |
| Z03 | Sants-Montjuïc (Barcelona) | 8% | 80 | 3.0 | medium | `EV-M`, `EV-L` | Nearest city district to the hub (La Marina borders the Zona Franca), so the drive to the first stop takes only 10-15 minutes |
| Z04 | Les Corts (Barcelona) | 5% | 84 | 2.8 | low | `EV-L`, `EV-M` | Wide avenues (Diagonal, Travessera de les Corts, Numància, Joan Güell) and modern blocks with loading access and concierge desks |
| Z05 | Sarrià-Sant Gervasi (Barcelona) | 7% | 64 | 3.5 | high | `EV-S`, `EV-M` | Steep streets above Via Augusta (Bonanova, Putxet, Sant Gervasi, Tres Torres) with gradients over 10%: frequent hill starts and slow trolley work |
| Z06 | Gràcia (Barcelona) | 6% | 66 | 3.7 | high | `EV-S`, `EV-M` | Tight mesh of narrow one-lane streets in the Vila de Gràcia, many of them single-level pedestrian-priority streets with a 10 km/h limit |
| Z07 | Horta-Guinardó (Barcelona) | 6% | 60 | 3.6 | high | `EV-S`, `EV-M` | Hilliest district: El Carmel, La Teixonera, Can Baró and Sant Genís dels Agudells have gradients above 15%, dead ends and stairway streets |
| Z08 | Nou Barris i Sant Andreu (Barcelona) | 9% | 66 | 3.2 | medium | `EV-M`, `CNG-L`, `EV-L` | Farthest zone from the hub (about 16 km): the drive via the Ronda Litoral or Ronda de Dalt to the Nus de la Trinitat takes 30-45 minutes at peak |
| Z09 | Sant Martí (Barcelona) | 11% | 80 | 2.9 | low | `EV-L`, `EV-M` | Flat Cerdà grid in Poblenou and the 22@ district with wide streets and newer DUM bays, so stops sequence efficiently |
| Z10 | L'Hospitalet de Llobregat | 11% | 80 | 3.1 | medium | `EV-M`, `EV-L` | Collblanc-La Torrassa and La Florida are among the densest urban areas in Europe: narrow streets with cars parked on both sides and very few DUM bays |
| Z11 | El Prat de Llobregat | 4% | 84 | 2.7 | low | `EV-L`, `CNG-L`, `DSL-L` | Flat, compact town with a regular street layout and a pedestrianised centre around Plaça de la Vila |
| Z12 | Cornellà de Llobregat | 4% | 78 | 2.8 | low | `EV-L`, `CNG-L` | Mostly flat, with a regular grid in Almeda, Riera and Fontsanta-Fatjó |
| Z13 | Esplugues de Llobregat | 2% | 68 | 3.2 | medium | `EV-M`, `EV-S` | Built on the lower slopes of Collserola: steep streets in the old centre, Montesa and Finestrelles; only the lower areas next to L'Hospitalet (Can Vidalet) are flat |
| Z14 | Sant Boi de Llobregat | 4% | 74 | 2.8 | low | `CNG-L`, `DSL-L`, `EV-L` | Longest drive from the hub among the neighbouring towns (about 12.5 km) via the B-10, C-31 and C-32/C-245, and the Llobregat bridge crossings are single points of failure |

### Targets

| KPI | Today | Target |
|---|---|---|
| Average delivery time per route | 361 min | 330 min |
| Average delay against plan | 22 min | 8 min |
| Deliveries inside the promised window | 87.5% | 95.0% |

The baseline is measured per route from the geofence exit at the hub to the last delivered or
failed scan, averaged over the 40 weekday routes (30 morning, 10 afternoon), and it includes the
30-minute break. The profile breaks it down as follows:

| Where the 361 minutes go | Minutes |
|---|---|
| Hub to the first stop | 22 |
| Stopped at addresses (about 72 stops × 3.2 min) | 231 |
| Driving between stops | 78 |
| Break | 30 |

The target takes 31 minutes off that baseline, a reduction of 8.6%:

| Where the 31 minutes come from | Minutes |
|---|---|
| Time-dependent stop sequencing | −14 |
| Clustering stops around DUM loading bays, so one parking serves several addresses | −8 |
| Staggered departures that avoid the Ronda Litoral and Ronda de Dalt peak | −5 |
| Small vehicles in Ciutat Vella, Gràcia and the hill zones | −4 |

At the 330-minute target, morning routes that leave at about 07:40 finish by about 13:10 and
afternoon routes that leave at about 14:40 finish by about 20:10, inside their delivery waves. A
route that used the whole 390-minute maximum would finish at 14:10 or 21:10, after its wave ends.
The profile's own rationale attaches the earlier times to the maximum; the
[prompt record](../../prompts/001-company-profile.md#post-processing) notes that slip.

## The problem

Before each delivery wave the planners build one route per van: which stops, in which order. An
hour later that plan is out of date. A lorry blocks a loading zone in Gràcia, the Ronda Litoral
jams after an accident, rain slows everything down, a customer is not home and the parcel goes
back to the hub for another attempt on another day.
Each delay pushes every later stop further back, so a route that was planned for six hours
finishes in seven, drivers go into overtime and parcels miss their promised window.

Route optimization in real time means re-planning the stops that are still pending whenever the
conditions change, using what is happening now: where every van is, how the roads are moving and
what the weather is doing. The KPI tells the company whether it is working.

## The KPI

**Average Delivery Time per Route.** For every route, the time from the van leaving the hub to
the last stop on that route being completed, delivered or failed. The KPI is the average of that
duration over the routes that finished in a time window.

```text
route_duration(r) = completed_at(last stop of r) − departed_at(r)

avg_delivery_time_per_route(window) = average of route_duration(r)
                                      over the routes r completed inside window
```

| Term | Where it comes from |
|---|---|
| `departed_at` | First GPS ping of the van outside the hub's geofence on that route |
| `completed_at` | The final status event of the route's last stop: `delivered`, or `failed` when nobody was there to receive it. A failed attempt still ends the route, as the baseline in the targets above is measured |
| window | A day by default; the live dashboard shows today so far and the current wave. Routes finish in two bunches, around 13:00–14:10 and 20:00–21:10, so a window of the last hour would be empty most of the day |

The KPI is segmented by **zone**, **hour of departure**, **vehicle type** and **weather**, because
a long route in Ciutat Vella at noon in the rain and a long route in El Prat at 8:00 have
different causes. Two supporting KPIs give it context:

- **Average delay against plan:** actual route duration minus the planned duration. It separates
  "the route was long because it had many stops" from "the route went wrong".
- **On-time share:** deliveries completed inside the promised window, which is what the customer
  actually feels.

The KPI is a good lineage KPI because it cannot be computed from one source. It joins the GPS
stream (departure), the delivery events (end of route), the orders (which stops belong to which
route), the route plans (for the delay) and the batch reference data (zones, vehicles, weather).
Tracing it back to its sources crosses every stage of the lifecycle.

## Data inventory

The assignment lists seven types of data for this case. Each one maps to a named dataset in the
platform. Two unstructured datasets are added so that phase 2 has real examples of all three
categories; they extend the list and replace nothing.

| # | Assignment data type | Dataset in the platform | Origin | Produced by | Arrives | Role in the KPI |
|---|---|---|---|---|---|---|
| 1 | Vehicle GPS location (real time) | topic `gps.pings` → `bronze.gps_pings` | Simulated on real roads | GPS simulator moving each van along its OSRM route, slowed by the live traffic state | Stream, one ping per van every 5 s | Marks when a van leaves the hub and how long every leg takes |
| 2 | Orders (origin, destination, priority) | `bronze.orders`, plus topic `delivery.events` for status changes | AI-generated, with real Barcelona addresses | Order generator driven by the demand model (prompt 004) and the Open Data BCN address table; status events from the driver's simulated handheld | Orders through the day in micro-batches (next-day orders in a nightly batch), status events as a stream | Defines the stops of each route; the last `delivered` or `failed` event ends the route |
| 3 | Road traffic data (external API) | `bronze.traffic_state` | Real: Open Data BCN traffic state, which covers Barcelona city only. The SCT incidents feed (DATEX II on the DGT National Access Point) covers the ring roads and the Llobregat bridges and is planned in issue #9. AI-generated fallback, prompt 005 | Loader polling the `itineraris` and `trams` feeds | Every 5 minutes | Explains slow legs and triggers re-optimization |
| 4 | Route history | `bronze.route_history` | AI-generated | Generator seeded by a history prompt: 90 days of past routes | Nightly batch | Gives the KPI its baseline and the patterns the optimizer learns from |
| 5 | Fuel consumption | `bronze.fuel_consumption`, `bronze.fuel_prices` | Derived from telemetry. Diesel and CNG prices are real (MINETUR); electricity is priced at a documented fixed tariff, an assumption (issue #9) | Consumption aggregated per vehicle and route from telemetry; loader for prices | Per completed route; prices polled hourly, updated daily by MINETUR | Cost side of every re-plan |
| 6 | Vehicle status (sensor data) | topic `vehicle.telemetry` → `bronze.vehicle_telemetry` | Simulated | Simulator emitting battery or fuel level, ignition, cargo door and speed | Stream, every 30 s | Cargo-door events measure time at each stop; battery level limits re-planning |
| 7 | Weather conditions | `bronze.weather` | Real: Open-Meteo (AI-generated fallback, prompt 006) | Loader | Hourly | Rain slows legs; the KPI is segmented by weather |
| + | Delivery notes | `notes` column on `bronze.orders` | AI-generated (prompt 008) | Order generator | With the orders | Explains long or failed stops; unstructured text |
| + | Proof-of-delivery photos | RustFS `bronze/pod/` objects | AI-generated placeholder images | Simulator, one per completed delivery | With each `delivered` event | Evidence of delivery; unstructured binary |

Reference data that every dataset above depends on:

| Dataset | Origin | Used for |
|---|---|---|
| Company profile (`services/generator/seed/company.json`) | AI-generated, prompt 001 | Hub, zones, fleet, shifts, service promise, KPI targets |
| Fleet register | AI-generated, prompt 002 (issue #3) | One row per van: plate, vehicle type, home zone |
| Driver roster | AI-generated, prompt 003 (issue #3) | One row per driver: shift, home zone |
| Demand model | AI-generated, prompt 004 (issue #3) | How the order generator spreads orders over zones, hours, parcel sizes and priorities |
| Postal addresses (Open Data BCN `taula-direle`) | Real | Delivery stops at real doors |
| Traffic sections (Open Data BCN `transit-relacio-trams`) | Real | Street geometry of every section in the traffic feed |
| Road network (OpenStreetMap, Catalonia extract) | Real | Routes, travel times and the optimizer's distance matrix |

## Real, generated and simulated

The assignment asks for data generated with AI and for the prompts to be submitted. The platform
uses three origins and says which one every dataset has:

- **Generated with AI.** Everything that belongs to the company itself: its profile, fleet,
  drivers, orders and history. The prompts are in [`prompts/`](../../prompts/), verbatim, with
  model, date and version, and every generated file is validated before it is used.
- **Simulated.** The live signals of the vans: GPS pings, telemetry and delivery events. The
  simulator is code, but it moves the vans over the real road network and reacts to the real
  traffic state, so the stream behaves like a real fleet.
- **Real.** Signals the company would buy or download in real life: traffic state, weather,
  fuel prices, addresses and roads. All are free, open and need no API key.

Traffic and weather also get AI-generated fallbacks (prompts 005 and 006). The connectors will
switch to them with a single setting, so the platform keeps running on generated data alone if an
external feed is down.

## What the next phases build on this

| Phase | Uses from this document |
|---|---|
| [2 · Classification](2-classification.md) | The nine rows of the inventory (eleven datasets) and the seven reference datasets |
| 3 · DIKW (`3-dikw.md`, not written yet) | The GPS ping, dataset 1 |
| 4 · Lifecycle (`4-lifecycle.md`, not written yet) | Origins and arrival patterns: stream, 5-minute polls, micro-batches, daily and nightly batches |
| 5 · Metadata and lineage (`5-metadata-lineage.md`, not written yet) | The KPI definition and the sources it joins |
