# Prompts used to generate data

The assignment requires that all business data is generated with AI and that the prompts are
submitted. This folder is that submission.

## Rules

1. One Markdown file per prompt, named `NNN-<what-it-generates>.md` (`001-company-profile.md`,
   `002-fleet.md`, ...).
2. Each file follows the template below. The prompt text is quoted verbatim, never paraphrased.
3. The generated output is committed next to the pipeline that consumes it, and the prompt file
   links to it.
4. If a prompt is re-run with changes, bump the version inside the file and keep the old version
   in the history section. Do not create a second file.

## Template

```markdown
# 001 · Company profile

- **Generates:** `services/generator/seed/company.json`
- **Model:** Claude Fable 5.1
- **Date:** 2026-10-01
- **Version:** 1
- **Run by:** @handle

## Prompt

> (verbatim prompt)

## Post-processing

What was changed by hand or by script after generation, if anything.

## History

- v1 · 2026-10-01 · initial
```
