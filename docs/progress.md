# Progress

Where the build stands. Updated before every milestone and whenever the plan changes, so work can resume from this file alone.

## Done

- Content standard ([content.md](content.md)), design version 2 ([design.md](design.md)), [decisions.md](decisions.md), [operations.md](operations.md).
- M1 Foundation: schema and lifecycle in Postgres, roles and grants, rulebook (`rules/`), `psst` command, throwaway test database, CI.
- M2 Evidence: quote matching, source reading, the fetch service (the only writer of snapshots), tool checks.
- M3 Tasks: queue with leases and independence rules, task files, prompts (`prompts/`), claim and item checks, escalation, audits, the system worker.
- M4 Publishing: format 2 output, staging, acceptance over HTTPS, promotion, rollback, publication records.
- M5 Console: SvelteKit console at `/admin` with sign-in, every section, editor actions, measured accuracy, coverage map.
- M6 Server: deployed to `/www/wwwroot/psst-platform` (database `psst_platform`, services, nginx at `https://psst-platform.67-230-170-225.sslip.io`, nightly backups to the private `psst-platform-backup` repository). Reference data imported (boundaries, tags, demand, 2,713 previous places as the coverage checklist). Cities set up: London (406 cells), Shanghai (309), Hong Kong (376), Kuala Lumpur (83).

## In progress

- M7 Content: photos (Commons candidates, our own stripped copies, checked like everything else), reader intake for reports and demand (`/api/v1/`), rule rechecks, place lookup by name are built. London research and writing run through the task queue; the console shows live counts.
- M8 Website: static SvelteKit site at the platform host's root, prerendered from production with city, place, tag, and trail pages, a sitemap, and a Chinese interface; rebuilt by a timer when new content is published.

## Next

1. London: keep the waves going (research on Haiku, story writing and revision on Sonnet, guides and checks on Haiku, escalations and audits on Sonnet) until the queued cells are researched and the audit batches pass; then publish to the platform's production channel.
2. Translations into Simplified Chinese once stories are published (console, city page).
3. Shanghai next, then Hong Kong and Kuala Lumpur.
4. The first publish that replaces the app's live content needs explicit approval; the previous system keeps serving the app until then.

## Open issues

- Research angles: in the first London waves writers gave back or replaced roughly half, mostly because the surprise was already in the encyclopedia's first paragraph. The research prompt now holds angles to that test and asks for a record among the sources; measure the share on the next cells.

## Measurements

### Before the content loop change (London, first day, task graph of design.md section 7, version 2)

| Measure | Value |
|---|---|
| Places published | 6 (6 stories, 6 guides) |
| Model tasks done | 738: 34 write_story, 74 write_guide, 16 research_cell, 107 revise, 207 check_item, 230 claim checks, 15 escalate, 55 audit |
| Model tasks per published place | 123 |
| Worker runs | 63 Haiku 5.5 (11.2 h), 39 Sonnet 5.5 (6.2 h) |
| Tokens | about 13 million, estimated from per-run usage reports (Haiku runs about 135,000, Sonnet runs about 115,000); about 2 million per published place. Not recorded by the platform. |
| Elapsed time | 3 h 10 min of task creation, about 9 h to the first publish |
| Story angles given back by writers | 11 cancelled or returned, 5 failed after three writers; about half of research angles replaced or given back |
| Item check fail rate | about 50 percent per round |
| Audit error rate | 7 errors in 55 audited (13 percent); all three batches failed |
| Revisions per accepted item | about 1.5 |

The cost sat in checking (452 claim and item checks for 6 places) and in revision rounds, and the stories that passed were accurate but often flat: correct facts stitched from quotes, guides that restate the encyclopedia's first sentence.

## How to resume

1. Read docs/design.md, docs/content.md, docs/decisions.md, docs/operations.md, and this file.
2. Tests: start Docker, then `uv run pytest`.
3. Workers on this Mac use `~/.config/psst-platform/env` (SSH host, the worker password, the public address). System and publisher commands run on the server (operations.md).
4. The console account's password is in `/www/wwwroot/psst-platform/env/console-account.txt` on the server (root only).
