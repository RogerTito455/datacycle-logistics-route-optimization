# ADR 0002 · Hosting on GitHub Codespaces

- **Date:** 2026-09-28
- **Status:** accepted

## Context

The running stack must be reachable on a public URL for the presentation and for the teacher,
and the team has no budget for a VPS. The stack is about seven containers and needs roughly
2 GB of RAM during the one-off OSRM graph build.

## Decision

Run the full Docker Compose stack inside a **GitHub Codespace** started from this repository.

- A `.devcontainer/devcontainer.json` in the repo enables Docker-in-Docker, pins a 4-core /
  16 GB machine type and forwards the Grafana, Dagster, Redpanda Console and MinIO ports.
- The Grafana port is set to **public** visibility for the demo, so anyone with the URL can open
  the dashboard without a GitHub account. Everything else stays private to the team.
- The landing and docs site is on **GitHub Pages**, always on, and embeds a short recording of
  the dashboard so the public URL never looks empty when no Codespace is running.
- Each team member's personal free allowance (120 core-hours and 15 GB-month of storage per
  month on a free account) covers development plus the demo: about 30 hours of a 4-core machine
  per person per month.

## Alternatives considered

| Option | Why not |
|---|---|
| Laptop + Cloudflare quick tunnel | Free and simple, but depends on one laptop being on. Kept as the fallback for demo day |
| Oracle Cloud Free Tier VM | Always on and free, but needs a bank card for identity verification and capacity is not guaranteed |
| Render / Railway free tiers | Services sleep and the free tiers do not fit a broker plus a time-series database |

## Consequences

- The Codespace URL changes with every new Codespace. The landing links to the dashboard
  through a short redirect page in the repo that the team updates before the demo.
- Someone must start the Codespace a few minutes before the presentation and check the KPI
  is flowing. This is part of the demo checklist in `docs/phases/6-presentation.md`.
- Codespaces stop after 30 minutes idle by default; raise the timeout in the personal settings
  before demo day.
