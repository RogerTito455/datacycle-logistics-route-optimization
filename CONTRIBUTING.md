# Contributing

## Git workflow

The repository follows a small git flow with two long-lived branches:

| Branch | Holds | Changes arrive through |
|---|---|---|
| `develop` | The integration branch and the default branch: every finished task | Pull requests from feature branches |
| `main` | What has been released: the state shown in a delivery or the presentation | Release pull requests from `develop` |

Both are protected. Nobody pushes to them directly.

1. **Branch from `develop`.** One branch per task, named `<type>/<short-description>`, e.g.
   `feat/gps-simulator`, `docs/phase-2-classification`.
2. **Open a pull request into `develop`.** One pull request per change. It needs one approval
   from another team member and a green CI run before it can be merged. Anyone on the team can
   approve.
3. **Stack when a task builds on an open pull request.** Branch from that pull request's branch,
   open the new pull request against it, and start the description with
   `Stacked on #NN. Merge after it.` Bring later fixes up the stack with `git merge`, not with a
   rebase, so nobody has to force-push.
4. **Squash-merge.** It is the only merge method enabled, so `develop` reads as one commit per
   task. The branch is deleted after the merge.
5. **Release with a pull request from `develop` into `main`.** Open it when `develop` is ready
   to be shown, with the same approval and green CI as any other pull request.

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
