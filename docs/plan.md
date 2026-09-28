# Plan

Delivery date: **Saturday 11 October 2026**. Presentation of about ten minutes with a live demo.

## Milestones

| Milestone | Date | Done when |
|---|---|---|
| **M1 · Foundations** | Wed 1 Oct | Repo, CI, Docker Compose bringing up the empty platform, company profile and generation prompts, first data model, phase 1 and 2 documents drafted |
| **M2 · Data flowing** | Sun 5 Oct | GPS stream landing in TimescaleDB, external connectors polling, dbt computing the KPI, minimal Grafana dashboard. Go/no-go decision on the real optimizer |
| **M3 · Optimizer and site** | Thu 8 Oct | OR-Tools optimizer re-planning routes on traffic changes, landing and docs complete, stack running on the public URL |
| **M4 · Presentation** | Sat 10 Oct | Slides, rehearsed demo script, PDF export for the school platform |
| Buffer | Sun 11 Oct | Nothing planned |

## Definition of done for the project

- `docker compose up` on a clean machine brings the whole platform up and the KPI appears in
  Grafana within five minutes.
- Every diagram in the docs corresponds to something running in the stack.
- Every AI-generated dataset has its prompt in `prompts/`.
- The landing site is live on GitHub Pages and links to the repo, the docs and the dashboard.
- The slides can be presented in ten minutes with the live demo inside.
