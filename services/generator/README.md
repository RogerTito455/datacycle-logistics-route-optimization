# Generator

Loads the reference data of Llobregat Express into the bronze layer and generates its daily
orders, about a third of them with a delivery note, and the proof-of-delivery photos of delivered
stops. The business data comes from AI-generated seeds, the delivery addresses from real open data,
and the photos are synthetic placeholders drawn by code.

| Command | What it does |
|---|---|
| `make load-reference` | Loads the hub, zones, shifts, vehicle types, vehicles, drivers, shippers, delivery notes, streets and postal addresses into their `bronze` tables, and stores the files they come from in the RustFS `bronze` bucket |
| `make generate DATE=2026-09-28` | Generates the orders of one service date: a Parquet file in the `bronze` bucket and the same rows in `bronze.orders` |
| `make pod-sample DATE=2026-09-28` | Uploads 20 proof-of-delivery placeholder photos for orders of a generated date under `pod/samples/` in the `bronze` bucket, a demonstration prefix (`COUNT=` for another number) |
| `make validate-seeds` | Checks the five AI-generated seeds: structure, consistency with each other and with their prompts, geography |
| `make test-generator` | Runs the tests, offline |

## Where the data comes from

| Data | Source | Licence |
|---|---|---|
| Company profile: hub, zones, shifts, vehicle types, volumes | [`seed/company.json`](seed/company.json), AI-generated from [prompt 001](../../prompts/001-company-profile.md) | MIT, this repository |
| Fleet register, one record per vehicle | [`seed/fleet.json`](seed/fleet.json), [prompt 002](../../prompts/002-fleet-register.md) | MIT, this repository |
| Driver roster, fictional people | [`seed/drivers.json`](seed/drivers.json), [prompt 003](../../prompts/003-driver-roster.md) | MIT, this repository |
| Demand model: shippers, hourly curve, windows, parcels per stop | [`seed/demand.json`](seed/demand.json), [prompt 004](../../prompts/004-demand-model.md) | MIT, this repository |
| Delivery notes: 300 free-text notes with their language, category and two labels | [`seed/delivery_notes.json`](seed/delivery_notes.json), [prompt 008](../../prompts/008-delivery-notes.md) | MIT, this repository |
| Proof-of-delivery photos | Drawn by [`llobregat_generator/pod.py`](llobregat_generator/pod.py) with Pillow: synthetic placeholders, not photographs and not AI-generated images | MIT, this repository |
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
fetches about 70 MB, later runs reuse them. Only a complete download is cached: the server must
answer HTTP 200 with as many bytes as it announced, and the file must read as what it should be, a
CSV with the published header, every row complete and at least as many rows as a complete file has
(100,000 for `taula-direle`, which publishes 171,901; 4,000 for `carrerer`, 4,770), or a zip with
the ICGC municipality and address files whose checksums match and at least 1,000 street addresses
in each of the five towns (3,119 to 22,862). The minimums catch a file cut exactly at a row
boundary, which a server that announces no length can send. Anything else, such as an error page
served with status 200, a download cut off halfway, a refused connection or a timeout, is discarded
with an error that says why. A download that passes is marked complete with a file next to it,
`<file>.ok`, holding its size and SHA-256, and a cached file is reused only while it matches its
marker: a file without one, such as a file cached before these checks existed, is downloaded again.

Only small extracts are committed: the zone boundaries and, for the tests, 560 sample addresses (40
per zone) as the registers publish them, in [`tests/fixtures/`](tests/fixtures/):
`taula_direle_sample.csv` and `carrerer_sample.csv` for Barcelona, `icgc_sample.csv` for the five
towns. [`scripts/build_fixtures.py`](scripts/build_fixtures.py) rebuilds them from the cache.

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
| `bronze.delivery_notes` | 300 | `generator/delivery-notes` | `reference/generator/delivery-notes/delivery_notes.parquet` |
| `bronze.streets` | 4,770 | `opendata-bcn/carrerer` | `reference/opendata-bcn/carrerer/<download date>/carrerer.csv` |
| `bronze.addresses` | 171,901 | `opendata-bcn/taula-direle` | `reference/opendata-bcn/taula-direle/<download date>/adreces_postals_elementals.csv` |
| `bronze.icgc_addresses` | 46,290 | `icgc/adreces-simplificat` | `reference/icgc/adreces-simplificat/<download date>/adreces-simplificat-v1r0-<version>.zip` |
| `bronze.orders` | about 2,500 orders on a mean weekday, a third with a note | `generator/orders` | `orders/date=<service date>/orders.parquet` |

Rows loaded from a file keep `raw_object_key`, the key of that file in the bucket: vehicles,
drivers, shippers, delivery notes, streets, addresses and orders. The orders file records the
service date, the seed and the generator version in its Parquet metadata.

Proof-of-delivery photos are objects, not rows: the simulator (issue #7) will store one per
delivered stop at `pod/<service date>/<order id>.jpg` in the `bronze` bucket and write its key into
`bronze.delivery_events.pod_object_key`. Until then `pod-sample` writes a sample under
`pod/samples/<service date>/` ([below](#proof-of-delivery-photos)).

**Re-running.** Bronze is write-once, so `load-reference` inserts only the rows whose key is not in
the table yet, and uploads a file only when the bucket does not hold it yet: a download when its
key holds no file of the same size, a fleet, driver, shipper or delivery notes file when the
SHA-256 of its content (rows and metadata, without `ingested_at`) differs from the one stored with
the object. A second
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
mix, the largest gap between a zone's share and `company.json`, the share of orders inside their
zone's official boundary, and the delivery notes by language, by category and, for each kind of
recipient, by who could have written them.

## How a day of orders is generated

The date is the service date, the day the parcels are delivered. One random generator, seeded with
the date and `--seed` (default 0), makes every draw of the orders, and a second one, seeded with
both and the number 8, draws their [delivery notes](#delivery-notes), so the same date and seed
always give the same orders and notes, and the notes change nothing else; `numpy` is pinned for that
reason.

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
| Note | About a third of the orders carry a note of the corpus: its text in `notes`, its id in `note_id` ([below](#delivery-notes)) | `delivery_notes.json`, rules of the generator |

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
- `recipient_name` stays empty: no AI-generated recipient names exist yet.

`orders` refuses a service date after today (in Barcelona): its orders would be registered after
they are ingested, a negative pipeline delay (`ingested_at - event_time`). `--allow-future`, or
`ALLOW_FUTURE=1` with `make generate`, generates it anyway, for instance to show the days ahead in
a demo; the `event_time` of such orders can then be later than their `ingested_at`.

## Delivery notes

The notes are the recipients' free text for the driver, the platform's unstructured text. They come
from a corpus of 300 that prompt 008 generated in the languages people in Barcelona write them, each
labelled by the generating model with its language, one of ten categories and whether it is likely
to make the stop longer (146 notes) or the first attempt fail (84). The prompt told the model that a
program would attach one, at random, to about a third of the orders; the rules of that program are
the generator's own, in [`notes.py`](llobregat_generator/notes.py), and the seed validator checks
the corpus against them:

| Rule | Why |
|---|---|
| An order carries a note with probability 1/3 | "About a third of the orders" (prompt 008) |
| Who could have written a note is read from its text. A business: its category is `business hours`, or it names business premises (an office, a reception, a loading dock, the 22@, an industrial estate, or a shop, bar or restaurant it opens with). A home: it names a home or a part of one (a flat, a house, a flat's floor and door, the staircase, the intercom, the letterbox, a concierge), the neighbours, the family, the pets, or a recipient who works or sleeps there or elsewhere. Anyone (neutral): neither. The corpus has 32 business notes, 137 home notes and 131 neutral ones | The category alone is too coarse: 15 of the 39 location hints describe a home ("entresuelo 1ª, en el telefonillo pone ENTLO"), and three `access` notes are about the loading dock of a 22@ office. A shop or a bar named as a neighbour or a landmark ("dejadlo en el bar de abajo", "la puerta al lado de la farmacia") does not make the recipient a business |
| A business recipient draws 80% of its notes from the business notes and 20% from the neutral ones, never a home note. A consumer draws from every note that is not a business's | "Abrimos a las 10" makes no sense at a flat, nor a sleeping baby at an office |
| The languages keep the corpus mix as closely as the notes an order can get allow: the groups of notes are taken in turn, each gives each of its languages what is left of that language's corpus share, and the notes of one language in a group are equally likely | The business notes are all Spanish, Catalan or English, so the neutral notes of a business recipient make up for the French, Italian and mixed ones, and both kinds of recipient get the corpus mix: 50 / 30 / 15 / 1.3 / 1.3 / 2.3% Spanish, Catalan, English, French, Italian and mixed. The few neutral French, Italian and mixed notes therefore reach businesses more often than the other neutral notes: N-221, the only neutral mixed one, is 2.3% of a business's notes |
| A note that names a place goes only to orders of that zone: L'Hospitalet, El Prat, Cornellà, Esplugues and Sant Boi to their zones, 22@ to Sant Martí, Vallvidrera to Sarrià-Sant Gervasi. N-033 names Sant Joan Despí, outside the service area, and is never attached | "Es L'Hospitalet, NO Barcelona!!" is never read at a door in Gràcia |

The two labels are not used by the generator; they are there for the simulator (issue #7) and for
analysis. The two dates loaded on 29 September 2026 carry these notes:

| | Saturday 26 September | Monday 28 September |
|---|---|---|
| Orders with a note | 301 of 923 (32.6%) | 1,119 of 3,363 (33.3%) |
| Business recipients' notes | 31: 28 written by a business (90.3%), 3 neutral, no home note | 225: 179 written by a business (79.6%), 46 neutral, no home note |
| Consumers' notes | 270: 143 written by a home, 127 neutral, no business note | 894: 468 written by a home, 426 neutral, no business note |
| Location hints | 27 to consumers, 12 of them describing a home; 1 to a business | 99 to consumers, 51 of them describing a home; 20 to businesses |
| Languages: es, ca, en, fr, it, mixed | 161, 81, 49, 5, 2, 3 (53.5 / 26.9 / 16.3 / 1.7 / 0.7 / 1.0%) | 565, 320, 179, 16, 17, 22 (50.5 / 28.6 / 16.0 / 1.4 / 1.5 / 2.0%) |

| Category, business recipients / consumers | Saturday | Monday |
|---|---|---|
| access | 1 / 46 | 13 / 163 |
| business hours | 27 / 0 | 173 / 0 |
| neighbour or concierge | 0 / 53 | 1 / 150 |
| location hint | 1 / 27 | 20 / 99 |
| schedule | 0 / 30 | 5 / 108 |
| fragile or special handling | 2 / 27 | 2 / 104 |
| call before | 0 / 24 | 2 / 88 |
| pets or children | 0 / 24 | 0 / 68 |
| contradictory | 0 / 19 | 1 / 61 |
| other | 0 / 20 | 8 / 53 |

On Saturday only shops and pharmacies receive business parcels, so its 31 business notes move the
business share and the language mix by several points with a note or two.

`bronze.orders` keeps the text as the recipient typed it in `notes`, like a real order would, and
`note_id` says which note of `bronze.delivery_notes` it is, so the labels can be joined.

## Proof-of-delivery photos

When a parcel is delivered, the driver's handheld photographs it at the door. A simulation has no
camera, so [`pod.py`](llobregat_generator/pod.py) draws a **synthetic placeholder with code**, with
Pillow: a wall, a door with an intercom, the order's parcels on the doorstep (up to three, sized by
`parcel_size`) and a caption with the order id, the local delivery time, the position and the words
"synthetic placeholder drawn by code, not a photograph". It is not a photograph and not an
AI-generated image. Colours and door vary with the order id, and the same delivery always gives the
same bytes.

What makes it a proof of delivery is its EXIF metadata, which any EXIF reader shows without looking
at the pixels:

| EXIF tag | Holds |
|---|---|
| `DateTimeOriginal`, `OffsetTimeOriginal` | Local delivery time in Barcelona and its UTC offset: `2026:09:28 15:42:21`, `+02:00` |
| `GPSLatitude`, `GPSLongitude` and their refs, `GPSMapDatum` | The delivery address in WGS84, degrees, minutes and seconds to a ten-thousandth of an arc second (about 3 mm) |
| `GPSDateStamp`, `GPSTimeStamp` | The same moment in UTC, as GPS receivers record it |
| `ImageDescription`, `Software` | What the image is (the order id and "synthetic placeholder drawn by code") and what drew it |

`pod.upload()` stores a photo at `pod/<service date>/<order id>.jpg` in the `bronze` bucket, with
content type `image/jpeg` and the metadata elements of ADR 0001, decision 20, as S3 user metadata:
`source` (`simulator/pod-photos`), `owner` and `schema-version` (those of
`bronze.delivery_events`, which will record the key), `ingested-at` and `order-id`, and a
`content-sha256` of the image and those elements without `ingested-at`. When the key already holds
the same photo with the same elements, nothing is written, so the photo keeps the `ingested-at` of
the upload that wrote it. `upload()` returns the key, which the simulator (issue #7) will write into
`pod_object_key` of the `delivered` event.

Until the simulator exists, `make pod-sample DATE=2026-09-28` uploads photos for 20 orders of a
generated date under `pod/samples/<service date>/`, each at a time drawn inside the order's window,
and reads every one back: its EXIF time and position must be the delivery's and its S3 user
metadata the elements above. It uploads the new photos first and then removes the photos of an
earlier sample of the date that are not among them, so a run that fails halfway leaves the old
sample whole; a failing bucket ends it with a message, not a traceback. The same date, count and
seed give the same photos, so running it again writes nothing, and a larger count keeps the photos
of a smaller one. `pod/samples/` is a demonstration prefix outside bronze's write-once rule
([data model](../../docs/data-model.md#keys-and-constraints)); the sample writes no
`delivery_events` rows.

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
The delivery notes are checked on the same week: a third of the orders carry one, 80% of the
business recipients' notes and none of the consumers' come from the two business categories, the
corpus language mix is kept (exactly, in every group of candidates), a note that names a place only
reaches its zone, an order's text is its note's, and the same date and seed give the same notes
while a day generated without notes is otherwise identical. The photos are checked for an EXIF round
trip in summer and winter time, both hemispheres, the same bytes for the same delivery, the object
key and metadata of an upload, and a sample inside the orders' windows. Other tests cover the ICGC
reading with its conversion to WGS84, the file metadata, the checksum of the reference files, the
refusal of future dates and the download cache, which a local HTTP server feeds cut-off files, error
pages and HTTP errors that must not be cached. The figures the seeds must satisfy on their own are
the seed validators' job, not the tests'.

CI runs the tests and the seed validators on every pull request. Its compose smoke job also loads
the reference data into a fresh stack twice, generates a past Monday twice and checks bronze with
SQL: row counts, metadata filled, nothing written by the second load, the same orders after the
second run of the date and about a third of them with a note of the corpus. Then it uploads the
date's 20 sample photos twice, reading back their EXIF and S3 user metadata each time; the second
run must write nothing, and one photo's metadata is read straight from RustFS. It loads the sample
addresses instead of the downloads ([`scripts/sample_cache.py`](scripts/sample_cache.py) writes
them as a download cache, marked complete), so it needs no open-data portal. `make test-generator-db` runs the same checks on your stack with the full
data, `SAMPLE=1` with the sample on a fresh one.
