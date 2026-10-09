# Progress

Where the build stands. Updated before every milestone and whenever the plan changes, so work can resume from this file alone.

## Done

- Content standard ([content.md](content.md)), design version 2 ([design.md](design.md)), [decisions.md](decisions.md), [operations.md](operations.md).
- M1 Foundation: schema and lifecycle in Postgres, roles and grants, rulebook (`rules/`), `psst` command, throwaway test database, CI.
- M2 Evidence: quote matching, source reading, the fetch service (the only writer of snapshots), tool checks.
- M3 Tasks: queue with leases and independence rules, task files, prompts (`prompts/`), claim and item checks, escalation, audits, the system worker.
- M4 Publishing: format 2 output, staging, acceptance over HTTPS, promotion, rollback, publication records.
- M5 Console: SvelteKit console at `/admin` with sign-in, every section, editor actions, measured accuracy, coverage map.
- M7 Content (in progress): photos (Commons candidates, our own stripped copies, checked like everything else), reader intake for reports and demand (`/api/v1/`), rule rechecks, place lookup by name. London research and writing run through the task queue; see the console for live counts.
- M8 Website (in progress): static SvelteKit site at the platform host's root, prerendered from production with city## Next

1. London: keep the waves going (research on Haiku, story writing and revision on Sonnet, guides and checks on Haiku, escalations and audits on Sonnet) until the queued cells are researched and the audit batches pass; then publish to the platform's production channel.
2. Translations into Simplified Chinese once stories are published (console, city page).
3. Shanghai next, then Hong Kong and Kuala Lumpur.
4. The first publish that replaces the app's live content needs explicit approval; the previous system keeps serving the app until then.

## Open issues

- Research angles from Haiku are often already in the encyclopedia's opening or rest on one community source; writers give those back. Measure the share and tighten the research prompt if it stays high.

he private `psst-platform-backup` repository). Reference data imported (boundaries, tags, demand, 2,713 previous places as the coverage checklist). Cities set up: London (406 cells), Shanghai (309), Hong Kong (376), Kuala Lumpur (83).

## Next

M7 Content, London first: queue research cells, run research, writing, and checking workers through the task system, audit, and publish to the platform's own production channel. The first publish that replaces the app's live content waits for approval.

## Open issues

None.

## How to resume

1. Read docs/design.md, docs/content.md, docs/decisions.md, docs/operations.md, and this file.
2. Tests: start Docker, then `uv run pytest`.
3. Workers on this Mac use `~/.config/psst-platform/env` (SSH host and the worker password). System and publisher commands run on the server (operations.md).
4. The console account's password is in `/www/wwwroot/psst-platform/env/console-account.txt` on the server (root only).
