# Free open data sources for a Barcelona/Catalonia last-mile routing simulator (verified 28 Sep 2026)

All claims below come from pages/endpoints fetched on 28 Sep 2026. "Poll OK" = realistic to poll every 1–5 min from a small Docker service.

## 1. Real-time road traffic

| Source | Endpoint | Auth | Limits / freq | Format / licence | Poll OK? |
|---|---|---|---|---|---|
| **Open Data BCN – `itineraris`** (traffic state per section, current vs. average + 15-min forecast) | Live: `https://opendata-ajuntament.barcelona.cat/data/dataset/1dffc2aa-882e-4765-bb98-9f77e1b21d4a/resource/b253025f-e1ea-454d-83ae-b960dace1617/download` (CKAN: `…/api/3/action/package_show?id=itineraris`) | None (`token_required: No`) | Updated every 5 min (`CINC_MINUTS`); tested live: HTTP 200, 2.7 KB, `#`-delimited `.dat`, last-modified today | `.dat` + 62 monthly CSVs 2017→Sep 2026 (gaps 2018-19, 2020, Mar–Nov 2023); CC BY 4.0 | **Yes** – tiny file, no key |
| **Open Data BCN – `trams`** (traffic state 1–6 per section) | `https://opendata-ajuntament.barcelona.cat/data/dataset/8319c2b1-4c21-4962-9acd-6db4c5ff1148/resource/2d456eb5-4ea6-4f68-9794-2f3f1a58a933/download` (`package_show?id=trams`) | None | Every 5 min; 108 resources (monthly CSV since Oct 2017) | `.dat`/CSV, CC BY 4.0 | **Yes** |
| **Open Data BCN – `transit-relacio-trams`** (section geometry to join the above) | `…/dataset/transit-relacio-trams` (wide/long CSV) | None | Static | CSV, CC BY 4.0 | Download once |
| **SCT (Generalitat) incidents + cameras** – Socrata records are just `href` pointers (SODA returns 403 "non-tabular") to: | RSS `https://www.gencat.cat/transit/opendata/incidenciesRSS.xml`, GML `…/incidenciesGML.xml`, cameras `…/cameres.xml` / `.kml` (from `analisi.transparenciacatalunya.cat/api/views/uyam-bs37.json`, `3tzz-6b9y.json`) | None | "Contínua"; tested live (pubDate today), `application/xml` | RSS/GML/KML; Generalitat open licence ("See terms of use") | **Yes** |
| **SCT DATEX II via DGT NAP** ("Incidencias SCT") | `https://nap.dgt.es/datex2/sct/SituationPublication/all/content.xml` (`nap.dgt.es/dataset/incidencias-sct`) | None (registration optional, for change notices) | Every 5 min | DATEX II XML; "No licence – no contract" | **Yes** |
| **SCT traffic state (density, travel times)** | WMS only: `https://sctwms.gencat.cat/WMS/mapserv.exe?map=EstatDelTransit.map…` (transit.gencat.cat "dades-estat-transit") | None | Layers refresh 8–15 min | Map images (WMS) – **not machine-readable** | No (images) |
| **DGT DATEX II v3.7 incidents** | `https://nap.dgt.es/datex2/v3/dgt/SituationPublication/datex2_v37.xml` | None | 1-min updates | DATEX II XML, CC-BY; **excludes Catalonia & Basque Country** | Yes, but no BCN data. v3 feed "A EXTINGUIR 12/01/2026" (deprecated); DGT panels datasets end 30/09/2026 |
| **TomTom Traffic** | `docs.tomtom.com/pricing` (developer.tomtom.com/pricing now 301s there) | Free API key, no credit card | Free/month: Flow Segment Data 20K, Incident Details 2.5K, Flow/Incident tiles 200K | JSON, proprietary ToS | Marginal: 20K/month ≈ one segment every ~2 min |
| **HERE Traffic** | `here.com/get-started/pricing` | **Payment method required** – Limited plan (1,000/day, no card) decommissioned 27 Mar 2025 (HERE April-2025 release notes) | ~5,000 free tx/month (third-party placematic; official page JS-only) | JSON | Avoid (card) |
| **Google Routes/Roads** | `developers.google.com/maps/billing-and-pricing/pricing` | Cloud project with billing | Routes Essentials 10,000 free events/month; Roads 5,000 | JSON | Avoid (billing account) |

Truly real-time **and** free with no key: Open Data BCN `itineraris`/`trams` (city), SCT RSS/GML + SCT DATEX II on NAP (Catalonia roads).

## 2. Weather

| Source | Endpoint | Auth | Limits | Format / licence | Poll OK? |
|---|---|---|---|---|---|
| **Open-Meteo** | Forecast/current: `https://api.open-meteo.com/v1/forecast?latitude=…&longitude=…&current=…&hourly=…`; archive: `https://archive-api.open-meteo.com/v1/archive` (ERA5 from 1940, ~5-day delay) | None for non-commercial (key only for commercial) | 600/min, 5,000/h, 10,000/day; models refresh 1–6 h | JSON; CC BY 4.0; non-commercial use only | **Yes** |
| **AEMET OpenData** | Server `https://opendata.aemet.es/opendata`, e.g. `/api/observacion/convencional/todas`, `/api/prediccion/especifica/municipio/horaria/{municipio}` (64 paths in `AEMET_OpenData_specification.json`) | Free key via email+captcha (`/centrodedescargas/obtencionAPIKey`), header `api_key` | 50 req/min (datos.gob.es); 2-step call (JSON with temporary `datos` URL) | JSON; reuse allowed citing AEMET | Yes at ≥5 min (observations are hourly anyway) |
| **Meteocat (SMC)** | Docs `apidocs.meteocat.gencat.cat` (TLS chain fails in curl without `-k`); header `x-api-key`; plans XEMA / XDDE / Predicció (+ reference) | Free for citizens, students, research via web form; approval e-mail within 7 days | Monthly quota per plan (numbers not published for the free tier; paid plans start 1,500 calls/month at €67.14); 429 when exceeded | JSON | Marginal – monthly quota; base URL not exposed in docs HTML fetched |

## 3. Routing

| Option | Details | Verdict |
|---|---|---|
| **OSRM demo** `router.project-osrm.org` / `routing.openstreetmap.de` (osrm-backend wiki "Demo-server") | ≤1 req/s, non-commercial only, no uptime guarantee | Prototyping only |
| **Self-hosted OSRM** | Geofabrik `https://download.geofabrik.de/europe/spain/cataluna-latest.osm.pbf` = **258 MB** (Spain 1.4 GB, daily updates). Pipeline `osrm-extract → osrm-partition → osrm-customize → osrm-routed :5000`, endpoints route/table/match/nearest/trip; BSD-2. Wiki: planet (61 GiB) needs 415 GiB for extract and "sizes scale roughly linear" → Catalonia ≈ 2 GiB peak, minutes to build | **Recommended** – fits Docker Compose on a laptop/small VM |
| **Valhalla** | `ghcr.io/valhalla/valhalla-scripted:latest` with `-e tile_urls=<pbf url>` (docker/README.md); MIT; `gis-ops/docker-valhalla` archived Mar 2026 (moved upstream); public demo `valhalla1.openstreetmap.de` | Good alternative (isochrones, time-dependent) |
| **openrouteservice** | **`api.openrouteservice.org` deprecated, shut-off 24 Aug 2026** → `https://api.heigit.org/openrouteservice/v2/directions/driving-car/json`; key from `account.heigit.org` (JWT); free: Directions 2,000/day & 40/min, Matrix 500/day & 40/min (ORS forum), matrix ≤3,500 elements, ≤50 waypoints | Fallback only |
| **GraphHopper** | Free plan: 500 credits/day, 1 req/s, 100 credits/min, 5 locations, **no Matrix/Isochrone**, non-commercial, no card | Too small |

## 4. Addresses / POIs

| Source | Endpoint | Auth / limits | Format / licence |
|---|---|---|---|
| **Open Data BCN `taula-direle`** (all postal addresses, ETRS89 + WGS84) | CSV `https://opendata-ajuntament.barcelona.cat/data/dataset/6b5cfa7b-1d8d-45f0-990a-d1844d43ffd1/resource/50c9b17f-d297-4668-bad4-e1c217580747/download` (also JSON, GPKG) | None; monthly | CC BY 4.0 – **best stop generator** |
| Open Data BCN `taula-segimon` (building/portal addresses) | `…/dataset/25752522-…/resource/661fe190-…/download` | None; monthly | CSV/JSON, CC BY 4.0 |
| **ICGC simplified addresses (all Catalonia)** | `https://datacloud.icgc.cat/datacloud/adreces-simplificat/csv` (Apr 2026, ETRS89 UTM31) | None | CSV, CC BY 4.0 |
| ICGC geocoder | `https://eines.icgc.cat/geocodificador/cerca?text=…&size=1` – tested, returns GeoJSON, no key | Policy page not found; use sparingly | CC-BY (openicgc.github.io) |
| Cadastre INSPIRE ATOM (AD/BU/CP) | `catastro.hacienda.gob.es/webinspire` | None; twice-yearly | GML per municipality |
| **Overpass** | `https://overpass-api.de/api/interpreter` | <10,000 q/day, <1 GB/day (÷100 for regular apps); 180 s / 512 MiB per query | JSON/XML/CSV, ODbL – batch POIs once and cache |
| Nominatim | `nominatim.openstreetmap.org` | 1 req/s, real User-Agent, no bulk/autocomplete, cache results | ODbL |

## 5. Fuel prices

**MINETUR/MITECO REST** – `https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/PreciosCarburantes/EstacionesTerrestres/FiltroProvincia/08` (Barcelona) → tested: HTTP 200, `application/json`, 850 KB, `Fecha`, station lat/long and prices as **comma-decimal strings**; also `/EstacionesTerrestresHist/…/{FECHA}` and `/Listados/*`. No auth; prices updated daily; CC BY 4.0 (MITECO catalogue). Poll hourly at most – 5-min polling is pointless.

## 6. Seed datasets (GPS traces / logistics)

- **Amazon Last Mile Routing Research Challenge** – `s3://amazon-last-mile-challenges/` (`--no-sign-request`), 9,184 real 2018 routes, 5 US metros, obfuscated; **CC BY-NC 4.0**.
- **Modena last-mile GPS dataset** (Zenodo 21717592, Jul 2026) – GPS traces + orders + time windows, CSV, CC BY 4.0. Closest real European analogue.
- **LaDe** (Cainiao, 5 Chinese cities, 10.7 M packages, GPS) – Hugging Face, research use.
- Kaggle: nothing Spain-specific; mostly synthetic tables.
- Spain-real time series: Open Data BCN monthly traffic CSVs (2017→) and Bicing monthly 7z archives.

## 7. Barcelona real-time stand-ins for "vehicle/IoT status"

- **Bicing GBFS (public, no token)** – `https://barcelona.publicbikesystem.net/customer/gbfs/v2/gbfs.json` → `station_status`, `station_information`, `vehicle_types` (tested; `ttl: 0`). The Open Data BCN mirror (`estat-estacions-bicing`, "IMMEDIATA") **requires a free token** sent as `Authorization: <token>` after registering at `opendata-ajuntament.barcelona.cat/en/tokens`.
- Other Open Data BCN "IMMEDIATA" feeds: `aparcaments-sota-superficie` (B:SM car-park occupancy, token), `informacio-rutes-autobus-estacio-del-nord`.
- **TMB iBus / GTFS** – register at `developer.tmb.cat` (portal is behind login), `app_id`+`app_key`; GTFS weekly; rate limits not published.

## Recommended picks (Docker Compose on laptop + small VM)

- **Traffic:** Open Data BCN `itineraris` (+`trams`, joined to `transit-relacio-trams`) every 5 min, plus SCT DATEX II from `nap.dgt.es` for the metro-area roads. No keys. TomTom optional (key, no card).
- **Weather:** Open-Meteo, no key. AEMET as second source (free key).
- **Routing:** self-hosted OSRM container built from `cataluna-latest.osm.pbf` (258 MB, ~2 GB RAM at build). ORS on `api.heigit.org` only as fallback (key).
- **Stops/POIs:** Open Data BCN `taula-direle` CSV + ICGC CSV, Overpass for POIs (batch once).
- **Fuel:** MINETUR REST, hourly.
- **Realism seed:** Amazon LMRRC (non-commercial) + Modena dataset; Bicing GBFS as live "sensor" stream.

**Keys students must register for:** AEMET (email), Meteocat (form, 7-day approval), HeiGIT/ORS, GraphHopper, TomTom, TMB, Open Data BCN token (only for Bicing/parking mirrors).

**Deprecated / moved / paywalled as of today:** `api.openrouteservice.org` (shut off 24 Aug 2026 → `api.heigit.org`); DGT DATEX II v3 (ended 12 Jan 2026) and DGT panel feeds (end 30 Sep 2026); HERE Limited plan (gone, card required); Google Routes (billing account); `gis-ops/docker-valhalla` (archived, use `ghcr.io/valhalla/valhalla-scripted`); `developer.tomtom.com/pricing` → `docs.tomtom.com/pricing`; SCT traffic-state is WMS images only.
