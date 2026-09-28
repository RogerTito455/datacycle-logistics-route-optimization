# ADR 0001 · Architecture baseline

- **Date:** 2026-09-28
- **Status:** accepted

## Context

The assignment asks for a conceptual architecture map of the data lifecycle of a logistics
company, with the KPI *Average Delivery Time per Route*. The team chose to go beyond a
conceptual map and build a working platform, published on a public URL, so that every diagram
describes something that runs. The deadline is 11 October 2026, thirteen days from this record.

## Decisions

### Scope and framing

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 1 | Build a **working end-to-end pipeline**, not only diagrams | Conceptual only; hybrid with a small runnable piece | A live dashboard has more impact in a ten-minute presentation, and the team has the time budget |
| 2 | Model an **urban last-mile parcel carrier** with a hub in Barcelona's Zona Franca logistics area, serving the metropolitan area | Long-haul trucking | Many events per minute, the KPI moves visibly in real time, urban traffic data is available for free |
| 3 | **Fictional brand, Llobregat Express**, explicitly documented as modeled on Spain's large parcel networks. Named after the river delta next to the hub | Use a real company's name; "Meridiana Logistics" and "Delta Express" (both collide with existing companies) | Avoids trademark and logo issues while keeping the operation realistic |
| 4 | **Hybrid data**: real open APIs for traffic, weather, road geometry and fuel prices; AI-generated business data for company, fleet, drivers, orders and history; GPS pings simulated along real route geometry | All generated; all real | Meets the assignment's requirement to generate data with AI and submit the prompts, while keeping the external signals real |
| 5 | **Real route optimization** with Google OR-Tools over a distance matrix from a self-hosted OSRM | Simulated "before/after" numbers | Demonstrates the optimization instead of describing it. Fallback to simulation is possible without touching the rest of the pipeline |
| 6 | **KPI definition**: per route, time from hub departure to last completed delivery; averaged over a window, segmented by zone and hour. Supporting KPIs: average delay vs. plan, share of on-time deliveries | Time per stop | Matches the KPI name literally; supporting KPIs give it context on the dashboard |
| 7 | **DIKW raw element**: the GPS ping | Delivery event | The most raw and meaningless datum on its own, so the four steps of the hierarchy are clearly distinct |

### Platform

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 8 | **Redpanda** for streaming ingestion | Kafka + ZooKeeper; no broker | Kafka API and semantics in one container, with a web console for the demo |
| 9 | **MinIO** for raw and archive layers (replaced by RustFS, see [ADR 0003](0003-object-storage-rustfs.md)), **PostgreSQL + TimescaleDB** for served layers (medallion: bronze / silver / gold) | Postgres only; data lake only | Archiving phase is solved with bucket retention; Grafana reads Postgres natively |
| 10 | **dbt** for batch transformations | pandas scripts; Spark | Auto-generated lineage graph and column-level documentation cover the metadata and lineage phase with a real tool |
| 11 | **Dagster** for orchestration | cron; Airflow | Asset graph with run history and per-table metadata; native dbt integration. First component to cut if time runs short |
| 12 | **Grafana** for the dashboard | Metabase; Streamlit | Real-time panels, maps, alerts, anonymous read-only access for the public URL |
| 13 | **Self-hosted OSRM** built from the Catalonia OpenStreetMap extract | Public OSRM demo; openrouteservice; GraphHopper | Unlimited routing and distance-matrix calls, no key, fits Docker Compose |

### Delivery

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 14 | Everything in **English** | Spanish; Catalan | Team choice; the assignment is in English |
| 15 | **Astro Starlight** for landing and documentation, deployed to GitHub Pages | Hand-written HTML; Next.js; README only | One Markdown-based site for the pitch and the full write-up; free hosting tied to the repo |
| 16 | **Mermaid** for all diagrams | Excalidraw; draw.io | Versioned text, renders on GitHub and in the docs |
| 17 | Slides as a **PowerPoint file** built on a Canva design provided by the team | Marp; Slidev | Team preference for the visual result |
| 18 | Git workflow: protected `main`, feature branches, one PR per change with one approval, Conventional Commits, CI on every PR | Direct pushes | Shows process, not only result |

### Resolved later the same day

| # | Decision | Alternatives considered | Rationale |
|---|---|---|---|
| 19 | **Hosting on GitHub Codespaces**, see [ADR 0002](0002-hosting-codespaces.md) | Laptop + Cloudflare tunnel; Oracle Cloud Free Tier | Zero cost, one-click start for every member, public port forwarding |
| 20 | **Three mandatory metadata elements** on every table and file: `source` (origin system and license), `ingested_at` next to `event_time` (freshness and delay), `owner` with `schema_version` | `quality_score`; `retention_policy` | Implemented by dbt on every model and surfaced by Dagster as asset metadata, so definition and implementation are the same thing |

## Consequences

- About seven containers. A laptop with 8 GB of RAM is enough; OSRM needs roughly 2 GB during
  the one-off graph build.
- The team must be able to explain every component in the stack in one sentence each. The
  documentation for each phase includes that sentence.
