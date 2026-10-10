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

- M7 Content: the content loop of decisions 22 to 25 is live. Research cells write stories and guides; tool checks; a review marks each item good, weak, or bad against the editor's golden set; one revision at most; a 10 percent audit gates publishing. Dense cells route research to Opus 5.5, everything else to Sonnet 5.5.
- The review gate (decision 25) is live and closed. Calibration agreement with the editor's 26 marked stories, by review prompt version: 65, 81, 88.5, 84.6, 88.5, 88.5 percent; it needs 90. Reviews and publishing wait until it passes.
- Golden bar version `4c675466e16b` is live in the database, carried by every research, review, and calibration task, and shown in the console under Quality with the gate's history and a monthly sample for the editor to mark.
- M8 Website: frozen until London has 50 places the editor is happy with; the map is the center when it resumes.

## Next

1. Open the gate: settle how to reach 90 percent agreement (see open issues), then calibrate again.
2. Review the overnight drafts through the gate; scale research only if they pass.
3. London to 50 good places, then Shanghai, Hong Kong, and Kuala Lumpur; translations into Simplified Chinese once stories are published.
4. The first publish that replaces the app's live content needs explicit approval; the previous system keeps serving the app until then.
5. Later: reader signals (saves, read-through, reports) as a second check on the reviewer.

## Open issues

- Calibration sits at 85 to 88.5 percent. Two stories disagree in most rounds (the reviewer marks weak what the editor marked good with a cut), and the rest move from round to round. With 26 stories one mark is 3.8 points, so part of the gap is noise; more editor marks (the console sample) would steady it.
- 35 places in the platform's queue still sit in research cells planned under the old loop; they are researched in order of open leads.

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

### Overnight research batch, 2026-10-09 (research only, drafts held)

Six London cells, densest first, on Opus 5.5 (it had the lower cost per good story in the dense-cell test: about 115,000 tokens per good story against 475,000 on Sonnet 5.5). Budget: 2.0 million tokens or six cells, whichever came first.

| Cell | Places | Stories | Guides | Tokens |
|---|---|---|---|---|
| 87194ada4ffffff (Notting Hill, Holland Park) | 10 | 10 | 9 | 334,414 |
| 87194ad35ffffff (Stepney, Shadwell, Wapping) | 8 | 8 | 8 | 322,309 |
| 87195da4affffff (North Kensington, Maida Vale) | 5 | 5 | 5 | 302,513 |
| Three more cells, stopped when the sessions lost their sign-in | 0 | 0 | 0 | 600,999 |
| Total | 23 | 23 | 22 | 1,560,235 |

- One place appears in two cells (All Saints Notting Hill, written twice on the same angle); a tool check now refuses a story that tells the same angle as an earlier story on its place.
- Two places (4 items) were refused after submitting because their Wikidata coordinate was too coarse; research is now checked for this before it is submitted.
- Leads were mostly dropped because the surprise was already in the encyclopedia's first paragraph, there was nothing to see, the lead was not one place, or the evidence was thin.
- 41 items wait for review behind the gate. The three unfinished cells are queued again.

## How to resume

1. Read docs/design.md, docs/content.md, docs/decisions.md, docs/operations.md, and this file.
2. Tests: start Docker, then `uv run pytest`.
3. Workers on this Mac use `~/.config/psst-platform/env` (SSH host, the worker password, the public address). System and publisher commands run on the server (operations.md).
4. The console account's password is in `/www/wwwroot/psst-platform/env/console-account.txt` on the server (root only).
