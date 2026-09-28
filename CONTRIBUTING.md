# Contributing

## Git workflow

- `main` is protected. Nobody pushes to it directly.
- One branch per task, named `<type>/<short-description>`, e.g. `feat/gps-simulator`,
  `docs/phase-2-classification`.
- One pull request per change. A PR needs one approval from another team member before merge.
  Anyone on the team can approve.
- Squash-merge, so `main` reads as one commit per task.

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): summary`.

Types used here: `feat`, `fix`, `docs`, `chore`, `ci`, `refactor`, `test`, `data` (for generated
datasets and prompts).

Examples:

```text
feat(generator): simulate GPS pings along OSRM route geometry
docs(phase-3): DIKW hierarchy for the GPS ping
data(prompts): fleet generation prompt v2
```

## Pull requests

Fill in the template. Link the issue the PR closes. Keep PRs small enough to review in ten
minutes.

## Language

All code, documentation, slides and commit messages are in English.
