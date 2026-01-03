---
name: review-checklist
description: Checklist-driven code review helper with prompts and light static checks. Use when reviewing PRs or spotting technical debt, and when you need reusable question sets by area (tests, security, migrations, docs) plus quick commands to surface risks.
---

# Review Checklist

## Overview

Use this skill to keep reviews consistent: pull the checklist, ask targeted follow-ups by area, and run quick local checks for common debt.

## Quick start
- Ask which areas to emphasize, then load `references/checklist.md` and jump to relevant sections.
- For each category, ask 1–2 prompts from the list; avoid dumping the entire checklist at once.
- Note risk hotspots and propose concrete follow-ups (tests, docs, debt tickets) rather than generic advice.

## Checklist navigation
- **Full list**: See `references/checklist.md` for all categories (style, tests, debt, deps, deploy, security, docs, observability, schema, UX).
- **Repo-specific overlays**: Add any local guardrails in the conversation before applying prompts (e.g., crypto invariants, zero-knowledge rules).
- **When time is short**: Prioritize Security/Privacy → Migrations/Schema → Tests/UX → Docs.

## Lightweight checks
- Search for TODOs/notes: `rg -n \"TODO|FIXME|XXX\"`
- Look for unused deps/imports: `rg -n \"import .*\" frontend backend` plus package manifests for extras
- Lockfile drift: compare declared vs lock versions; note mismatches
- Migrations: confirm up/down symmetry and data safety; flag raw SQL without safeguards
- Logging: scan for secrets or request bodies being logged
