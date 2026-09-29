# Datacycle · Logistics Route Optimization

> **Design the Data Lifecycle of a Real Company** — Case 3, Logistics (Route Optimization).
> Datacycle · Unit 1 · DAW2 2026-27.

A working, end-to-end data platform for **Llobregat Express**, a fictional Barcelona last-mile
parcel carrier modeled on Spain's large parcel networks, that re-plans delivery routes in real
time. Everything in this repository runs with a single
`docker compose up`, and every diagram in the documentation describes something that actually
executes.

**Lineage KPI:** *Average Delivery Time per Route* — for each route, the time from the vehicle
leaving the hub until its last delivery is completed, averaged over a time window and segmented
by zone and hour of day. Two supporting KPIs give it context: *average delay vs. plan* and
*share of deliveries inside the promised time window*.

## Architecture at a glance

```mermaid
flowchart LR
  subgraph Sources
    GEN[Synthetic generator<br/>company · fleet · orders]
    GPS[GPS simulator<br/>along real road geometry]
    TRF[Open Data BCN traffic<br/>every 5 min]
    WX[Open-Meteo weather]
    FUEL[MINETUR fuel prices]
  end
  subgraph Ingestion
    RP[(Redpanda<br/>Kafka API · streaming)]
    BATCH[Batch loaders]
  end
  subgraph Storage["Storage · medallion"]
    MINIO[(MinIO<br/>bronze / raw + archive)]
    PG[(Postgres + TimescaleDB<br/>silver / gold)]
  end
  subgraph Processing
    CONS[Stream consumer]
    DBT[dbt models]
    DAG[Dagster orchestration]
    OPT[OR-Tools optimizer<br/>+ self-hosted OSRM]
  end
  subgraph Serving
    GRAF[Grafana<br/>live KPI dashboard]
    SITE[Landing + docs<br/>Astro Starlight]
  end
  GPS --> RP --> CONS --> PG
  GEN --> BATCH
  TRF --> BATCH
  WX --> BATCH
  FUEL --> BATCH
  BATCH --> MINIO --> DBT
  PG --> DBT --> PG
  DAG -. orchestrates .-> DBT
  DAG -. orchestrates .-> OPT
  DAG -. orchestrates .-> BATCH
  PG --> OPT --> PG
  PG --> GRAF
  GRAF -. embedded .-> SITE
```

## How the assignment maps to this repository

| Phase | Deliverable | Where |
|---|---|---|
| 1 · Practical case | Company profile, data inventory | `docs/phases/1-case.md` |
| 2 · Data classification | Structured / semi-structured / unstructured, justified | `docs/phases/2-classification.md` |
| 3 · DIKW | GPS ping → information → knowledge → action | `docs/phases/3-dikw.md` |
| 4 · Data lifecycle | Generation → ingestion → storage → processing → analysis → action → archiving | `docs/phases/4-lifecycle.md` + `docker-compose.yml` |
| 5 · Metadata and lineage | Lineage diagram, dbt-generated lineage graph, 3 mandatory metadata elements | `docs/phases/5-metadata-lineage.md` + dbt docs |
| 6 · Presentation | Slides, live demo script | `slides/` |
| AI-generated data | Every prompt used, versioned, with model and date | `prompts/` |

## Stack

| Layer | Choice | Why |
|---|---|---|
| Streaming ingestion | Redpanda (Kafka API) | Full Kafka semantics in one container, with a web console |
| Batch ingestion | Python loaders scheduled by Dagster | Nightly history, hourly external APIs |
| Raw storage + archive | MinIO (S3 API) | Bronze layer and retention policies for the archiving phase |
| Serving storage | PostgreSQL + TimescaleDB | Relational model plus time series for GPS |
| Transformation | dbt | Silver/gold models and an auto-generated lineage graph |
| Orchestration | Dagster | Asset graph, run history, metadata per table |
| Route optimization | Google OR-Tools + self-hosted OSRM | Real vehicle-routing solver over real road distances |
| Dashboard | Grafana | Live map, KPI, before/after optimizer panels |
| Landing and docs | Astro Starlight on GitHub Pages | One site for the pitch and the full write-up |
| Runtime hosting | GitHub Codespaces | Zero cost, public port forwarding for the live demo (ADR 0002) |
| Diagrams | Mermaid | Versioned, renders on GitHub and in the docs |

Real external data (traffic, weather, road geometry, fuel prices) comes from free open sources
verified in [`docs/research/open-data-sources.md`](docs/research/open-data-sources.md).
Business data (company, fleet, drivers, orders, route history) is generated with AI; the prompts
live in [`prompts/`](prompts/).

## Quick start

> The runnable stack lands in milestone M2 (see [`docs/plan.md`](docs/plan.md)). Until then this
> section is a placeholder.

```bash
cp .env.example .env
docker compose up -d
```

## Documentation

- [Plan and milestones](docs/plan.md)
- [Architecture decisions](docs/decisions/)
- [Open data sources research](docs/research/open-data-sources.md)
- [Assignment phases](docs/phases/)
- [Contributing and Git workflow](CONTRIBUTING.md)

## Team

| Member | GitHub |
|---|---|
| Roger | [@RogerTito455](https://github.com/RogerTito455) |
| Zehao | [@zyin-08](https://github.com/zyin-08) |
| Izan | [@izaantorrico](https://github.com/izaantorrico) |

## License

MIT for the code in this repository. External datasets keep their own licenses, listed in the
research document.
