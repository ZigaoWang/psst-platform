# Progress

Where the build stands. Updated before every milestone and whenever the plan changes, so work can resume from this file alone.

## Questions for the editor

1. London budget (asked 2026-10-11): London has spent 7.94 of its 8 USD. About 229 revisions (listing cuts in code among them) and their reviews wait, about 1 USD with review and revise run eight at a time. Raise London to 9 USD to finish them, with no new research? Total spend is about 9.9 of 18 USD.

## Done

- Content standard ([content.md](content.md)), design version 2 ([design.md](design.md)), [decisions.md](decisions.md), [operations.md](operations.md).
- M1 Foundation: schema and lifecycle in Postgres, roles and grants, rulebook (`rules/`), `psst` command, throwaway test database, CI.
- M2 Evidence: quote matching, source reading, the fetch service (the only writer of snapshots), tool checks.
- M3 Tasks: queue with leases and independence rules, task files, prompts (`prompts/`), claim and item checks, escalation, audits, the system worker.
- M4 Publishing: format 2 output, staging, acceptance over HTTPS, promotion, rollback, publication records.
- M5 Console: SvelteKit console at `/admin` with sign-in, every section, editor actions, measured accuracy, coverage map.
- M6 Server: deployed to `/www/wwwroot/psst-platform` (database `psst_platform`, services, nginx at `https://psst-platform.67-230-170-225.sslip.io`, nightly backups to the private `psst-platform-backup` repository). Reference data imported (boundaries, tags, demand, 2,713 previous places as the coverage checklist). Cities set up: London (406 cells), Shanghai (309), Hong Kong (376), Kuala Lumpur (83).

## In progress

- M7 Content through the harness (decisions 32 to 36). Research runs on Claude Haiku 5.5 through OpenRouter: triage over 60 leads a pass, code gathers each lead's record and references, one call picks the facts, one call writes. Review runs on DeepSeek V4.1 Flash with reasoning off and no tools, and passes the gate under review prompt version of 2026-10-10 (24 of 24 good stories published, 44 of 44 constructed defects caught). Revision runs on Haiku in one call. Publishing waits for the editor.
- An unattended run started 2026-10-10 22:17 UTC on London's densest cells: window 3 USD, stops at 0.02 USD per place still standing or when more than half of a pass's places fail. London's 8 USD budget ends it first, at about 2.26 USD. Nothing is published. Report: `psst harness report --since 2026-10-10T22:17:34Z`.
- The proof cell (87195da69ffffff, 37 places in the previous app) ran under the earlier rules: 14 places, mostly guide-only, and the reviewer then judged guides as stories. Both fixed since (decision 35, review prompt).
- M8 Website: frozen until London has 50 places the editor is happy with; the map is the center when it resumes.

## Next

1. Read the night run's report; the editor checks samples. Then a per-city monthly budget for the harness service.
2. Shanghai proof cell (87309959dffffff), with Chinese heritage record properties added to `record_properties`.
3. The first publish that replaces the app's live content needs explicit approval; the previous system keeps serving the app until then.
4. Later: reader signals (saves, read-through, reports) as a second check on the reviewer.

## Open issues

- Places close together can be merged as one (the George IV statue was refused as the same place as the Charles I statue nearby).
- About half of chosen leads end as guide-only or skipped: listed buildings whose record holds no story. Their count against the previous app's places is in the night report.
- Old revise tasks from before the harness (about 170) are routed to Haiku with the rest and are revised as the service reaches them.

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
