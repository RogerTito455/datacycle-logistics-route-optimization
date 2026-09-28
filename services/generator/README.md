# Generator

Loads the reference data of Llobregat Express into the bronze layer and generates its daily
orders. The business data comes from AI-generated seeds, the delivery addresses from real open
data.

| Command | What it does |
|---|---|
| `make load-reference` | Loads the hub, zones, shifts, vehicle types, vehicles, drivers, shippers, streets and postal addresses into their `bronze` tables, and stores the files they come from in the RustFS `bronze` bucket |
| `make generate DATE=2026-09-28` | Generates the orders of one service date: a Parquet file in the `bronze` bucket and the same rows in `bronze.orders` |
| `make validate-seeds` | Checks the four AI-generated seeds: structure, consistency with each other, geography |
| `make test-generator` | Runs the tests, offline |

## Where the data comes from

| Data | Source | Licence |
|---|---|---|
| Company profile: hub, zones, shifts, vehicle types, volumes | [`seed/company.json`](seed/company.json), AI-generated from [prompt 001](../../prompts/001-company-profile.md) | MIT, this repository |
| Fleet register, one record per vehicle | [`seed/fleet.json`](seed/fleet.json), [prompt 002](../../prompts/002-fleet-register.md) | MIT, this repository |
| Driver roster, fictional people | [`seed/drivers.json`](seed/drivers.json), [prompt 003](../../prompts/003-driver-roster.md) | MIT, this repository |
| Demand model: shippers, hourly curve, windows, parcels per stop | [`seed/demand.json`](seed/demand.json), [prompt 004](../../prompts/004-demand-model.md) | MIT, this repository |
| Barcelona addresses, every street number with district and WGS84 coordinates | Open Data BCN [`taula-direle`](https://opendata-ajuntament.barcelona.cat/data/dataset/taula-direle), Ajuntament de Barcelona | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Barcelona street names, joined to the addresses by street code | Open Data BCN [`carrerer`](https://opendata-ajuntament.barcelona.cat/data/dataset/carrerer), Ajuntament de Barcelona | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Addresses of L'Hospitalet, El Prat, Cornellà, Esplugues and Sant Boi de Llobregat | [Adreces simplificat](https://www.icgc.cat/ca/Geoinformacio-i-mapes/Dades-i-productes/Geoinformacio-cartografica/Adreces-simplificat), Institut Cartogràfic i Geològic de Catalunya (ICGC) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| Zone boundaries, for checks only ([`llobregat_generator/zone_boundaries.geojson`](llobregat_generator/zone_boundaries.geojson)) | Barcelona districts from Open Data BCN [`20170706-districtes-barris`](https://opendata-ajuntament.barcelona.cat/data/dataset/20170706-districtes-barris); municipal boundaries at 1:50,000 from ICGC [divisions administratives](https://datacloud.icgc.cat/datacloud/divisions-administratives/); simplified to about 5 m | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |

The five neighbouring municipalities are not in `taula-direle`, which covers Barcelona city only.
The ICGC register covers all of Catalonia, so the loader keeps the street addresses of the five
municipalities of the zones (46,290 of 1,669,529) and converts their ETRS89 UTM zone 31N
coordinates to WGS84 with PROJ. Converted this way, a `taula-direle` point lands within 1 cm of the
WGS84 coordinates the city publishes for it. A row without coordinates cannot be placed, so it is
skipped and counted in the `skipped` column of the load summary; the current file has none.

Each address belongs to a zone by what its register says, not by distance: the district code of
`taula-direle` (Nou Barris and Sant Andreu make zone Z08) or the municipality of the ICGC record.
The names come from `company.json`, so a renamed zone fails loudly. Checked against the official
boundaries, 127 of the 218,160 addresses (0.06%) fall outside their zone. 122 of them are within
50 m of its boundary, which the 1:50,000 municipal line and the 5 m simplification draw less
precisely than the address points. One is a register error: `taula-direle` puts Carrer de
Muntaner, 79, in the Eixample, at a point in Montjuïc 1.4 km away. Bronze keeps it as published.

Downloads are cached in `services/generator/.cache/` (git-ignored): the first `make load-reference`
fetches about 70 MB, later runs reuse them. Only small extracts are committed: the zone boundaries
and, for the tests, 560 sample addresses (40 per zone) as the registers publish them, in
[`tests/fixtures/`](tests/fixtures/): `taula_direle_sample.csv` and `carrerer_sample.csv` for
Barcelona, `icgc_sample.csv` for the five towns. [`scripts/build_fixtures.py`](scripts/build_fixtures.py)
rebuilds them from the cache.

## Outputs

Every row names its origin in `source` and gets `ingested_at` when it is written; orders also have
`event_time`, the moment the shipper registered them (ADR 0001, decision 20). The Parquet files the
generator writes carry the same `source` and `ingested_at` columns, and their file metadata holds
`source`, `owner`, `schema_version` and `ingested_at`: decision 20 asks for them on every file too.
`owner` and `schema_version` are those of the bronze table the file is loaded into, read from
`ops.table_metadata`, and a day's orders file and its rows share one `ingested_at`.

| Table | Rows | `source` | File in the `bronze` bucket |
|---|---|---|---|
| `bronze.hubs` | 1, with the 400 m geofence radius of migration 007 | `generator/company-profile` | |
| `bronze.zones` | 14 | `generator/company-profile` | |
| `bronze.shifts` | 2: `morning` and `afternoon` | `generator/company-profile` | |
| `bronze.vehicle_types` | 6 | `generator/company-profile` | |
| `bronze.vehicles` | 30 | `generator/fleet` | `reference/generator/fleet/vehicles.parquet` |
| `bronze.drivers` | 48; the relief pool has no shift and status `reserve` | `generator/drivers` | `reference/generator/drivers/drivers.parquet` |
| `bronze.shippers` | 40 | `generator/demand-model` | `reference/generator/demand-model/shippers.parquet` |
| `bronze.streets` | 4,770 | `opendata-bcn/carrerer` | `reference/opendata-bcn/carrerer/<download date>/carrerer.csv` |
| `bronze.addresses` | 171,901 | `opendata-bcn/taula-direle` | `reference/opendata-bcn/taula-direle/<download date>/adreces_postals_elementals.csv` |
| `bronze.icgc_addresses` | 46,290 | `icgc/adreces-simplificat` | `reference/icgc/adreces-simplificat/<download date>/adreces-simplificat-v1r0-<version>.zip` |
| `bronze.orders` | about 2,500 orders on a mean weekday | `generator/orders` | `orders/date=<service date>/orders.parquet` |

Rows loaded from a file keep `raw_object_key`, the key of that file in the bucket: vehicles,
drivers, shippers, streets, addresses and orders. The orders file records the service date, the
seed and the generator version in its Parquet metadata.

**Re-running.** Bronze is write-once, so `load-reference` inserts only the rows whose key is not in
the table yet, and uploads a file only when the bucket does not hold it yet: a download when its
key holds no file of the same size, a fleet, driver or shipper file when the SHA-256 of its content
(rows and metadata, without `ingested_at`) differs from the one stored with the object. A second
run writes nothing, and its summary says so. `generate` for a date that was generated before
deletes that date's rows and inserts the new ones in one transaction, and uploads the date's file
inside that transaction, before the commit. If the database or the upload fails, the transaction
rolls back and the date keeps its rows and its file. If the commit fails after the upload, the
bucket holds the new file with the old rows until the next run of the date overwrites it. A date is
never duplicated. Regenerating is the one case where rows leave bronze, and only the generator's own
orders of that date (`source = 'generator/orders'`).

## How to run

The platform must be running (`make up`), because the commands write to TimescaleDB and RustFS.

```bash
make load-reference                   # once; downloads about 70 MB the first time
make generate DATE=2026-09-28         # a Monday
make generate DATE=2026-09-26 SEED=7  # a Saturday, another random draw
```

The Makefile reads the credentials from `.env`. Without it, run the CLI with the project's pinned
environment and set the variables yourself:

```bash
uv run --project services/generator --frozen llobregat-generator orders --date 2026-09-28 --seed 0
uv run --project services/generator --frozen llobregat-generator summary --date 2026-09-28
```

| Variable | Default | Meaning |
|---|---|---|
| `POSTGRES_HOST`, `POSTGRES_PORT` | `localhost`, `POSTGRES_HOST_PORT` or 15432 | TimescaleDB; inside Compose use `timescaledb` and 5432 |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | from `.env` | Database credentials |
| `S3_ENDPOINT`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` | `http://localhost:9000`, from `.env` | RustFS |
| `GENERATOR_CACHE_DIR` | `services/generator/.cache` | Where downloads are cached |

`generate` prints a sanity summary of the day, and `summary --date` prints it again from
`bronze.orders`: orders, parcels, business and same-day shares against the demand model, the parcel
mix, the largest gap between a zone's share and `company.json`, and the share of orders inside
their zone's official boundary.

## How a day of orders is generated

The date is the service date, the day the parcels are delivered. One random generator, seeded with
the date and `--seed` (default 0), makes every draw, so the same date and seed always give the same
orders; `numpy` is pinned for that reason.

| Step | Rule | From |
|---|---|---|
| Day total | Normal draw with mean 3,500 and standard deviation 350 parcels, times the weekday multiplier and the seasonal peak (below). No orders on Sunday | `company.json`, `weekday_multipliers` |
| Shippers | The total is split by `share_of_daily_parcels`, then into consumer and business parcels by `business_share` | `shippers` |
| Saturday | Business parcels only for shops and healthcare (pharmacies); consumer parcels are scaled up to keep the total | assumptions |
| Stops | Parcels are grouped into orders by `parcels_per_stop`; a "4+" stop gets 4 parcels plus a geometric extra with mean 0.4 (consumer) or 1.5 (business). One order is one stop: one shipper, one address, one size | `parcels_per_stop`, assumptions |
| Zone | The day's parcels are split over the zones by `share_of_daily_parcels` with the largest-remainder method, as over the shippers. A business shipper's parcels are split the same way over its `business_recipient_zones`; consumer parcels fill what the business parcels left of each zone. Each stop goes to a zone drawn in proportion to the parcels that zone still needs, preferring zones that need the whole stop, so every zone ends within a few parcels of its share | `company.json`, assumptions |
| Address | A real address of that zone, uniformly | Open Data BCN, ICGC |
| Size | By the shipper's `parcel_mix` | `shippers` |
| Registration | Hour from `hourly_registration_share`, minute and second uniform | `hourly_registration_share` |
| Same day | Only midday-injection shippers, only before the 11:00 cut-off, with probability `same_day_share` / 0.282 (the share registered before 11:00). Every other order is next-day and was registered the day before; for a Monday, on Saturday or Sunday | assumptions |
| Wave | Same-day and midday-injection parcels go in the afternoon-evening wave; other business parcels in the morning wave; other consumer parcels by `consumer_window_choice` | assumptions |
| Window | A consumer picks one of the three 120-minute slots of the wave with `specific_slot_share` (`window_type` `slot`); the others accept the whole wave (`wave`) until route planning sets their 120 minutes. A business gets a 120-minute window inside its `business_opening_hours`, outside the lunch break (`opening_hours`) | `consumer_window_choice`, `business_opening_hours` |

Where the seeds say nothing, the generator decides, and these rules are its own:

- `company.json` names the November peak "Black Friday and Cyber Monday week" and gives it a
  month. Its ×1.55 applies from the Monday before Black Friday, the fourth Friday of November, to
  Cyber Monday, the Monday after it: eight days, which end on 1 December when Black Friday is on
  28 November. The rest of November has no peak (×1.0). The other peaks apply to their whole month:
  December ×1.4, January ×1.2, September ×1.1.
- The opening hours of a business recipient follow its shipper's segment: retail replenishment
  keeps shop hours, healthcare distributors healthcare hours, office suppliers office hours,
  industrial distributors industry hours. Business recipients of partner networks, e-commerce and
  marketplace shippers keep office hours. On Saturday the clinics that healthcare distributors
  supply are not told apart from pharmacies.
- Business windows start on the half hour.
- `weight_kg` is the sum of the order's parcels, each uniform within its size class: small
  0.1-2 kg, medium 2-8 kg, large 8-25 kg.
- `priority` is `high` for same-day orders and `normal` otherwise.
- `origin_address` names the shipper and how its parcels reach the hub; the demand model has no
  shipper addresses.
- Order ids are `O-<service date>-<n>`, numbered in order of registration.
- `recipient_name` stays empty: no AI-generated recipient names exist yet. `notes`, the free-text
  delivery notes, stays empty until issue #25 adds them.

`orders` refuses a service date after today (in Barcelona): its orders would be registered after
they are ingested, a negative pipeline delay (`ingested_at - event_time`). `--allow-future`, or
`ALLOW_FUTURE=1` with `make generate`, generates it anyway, for instance to show the days ahead in
a demo; the `event_time` of such orders can then be later than their `ingested_at`.

## Tests

`make test-generator` runs offline, with no database or network. It reads the sample addresses
with the loader's own code and assigns their zones as the loader does, then checks that each lies
inside its zone's official boundary, which comes from other files. It generates a week of orders
and a Saturday from them and checks those against the seeds: day totals by weekday and season, the
Black Friday week, zone shares, the business share and where business parcels go, the same-day
rule, waves and windows, registration hours, parcels per stop, parcel mix, that every order goes to
a real address of its zone, and that the same date and seed give identical orders and an identical
Parquet file. Shares pooled over the week are compared within four standard errors, computed from
the orders themselves; zone shares, split exactly, within 5% of each zone's share on a single day.
Other tests cover the ICGC reading with its conversion to WGS84, the file metadata, the checksum of
the reference files and the refusal of future dates. The figures the seeds must satisfy on their
own are the seed validators' job, not the tests'.

CI runs the tests and the seed validators on every pull request.
