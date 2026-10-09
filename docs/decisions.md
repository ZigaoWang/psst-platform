# Decisions

Decisions made while building, newest last. Each says what was decided, why, and what else was considered. Decisions settled in the design itself are in [design.md](design.md), sections 3 and 18.

## 1. Database roles are prefixed `psst_platform_`

Postgres roles are shared by every database on the server, and the previous system already uses `psst`, `psst_api`, and `psst_agent`. The new roles (`psst_platform_admin`, `_system`, `_worker`, `_publisher`, `_console`, `_api`) can't collide with them or change their grants.
Alternatives: reusing the previous role names (would change the previous system's permissions); a short prefix such as `pp_` (unclear on a shared server).

## 2. Only the fetch service writes snapshots

Evidence is only as good as the snapshot it is matched against. If a worker could store snapshot text, a misremembered quote could be stored as the source. The fetch service runs on the server, reads the page itself, and is the only writer of `sources` text and `snapshots`. Workers reach it through the same SSH tunnel as the database.
Alternatives: fetching in the CLI and storing through a function (the client could store any text); trusting workers (the failure the design exists to prevent).

## 3. The system worker runs the authoritative tool checks

Tool checks are code, and code on a worker's machine can be skipped. Submitting stores a revision in `checking` with a pending `system` task; the system worker runs the tool checks under its own role and records the verdict. The CLI runs the same code before submitting so writers see problems at once.
Alternatives: tool checks inside PL/pgSQL (text normalization, tokenization, and n-gram comparison are far clearer in Python); trusting the CLI's result.

## 4. Runs carry a secret token

Every write function takes the run's token and records the run it belongs to, so a worker can't act as another run, check its own writing under a different id, or write without a run. The database stores only the token's hash.
Alternatives: passing a run id (forgeable); one login role per run (heavy, and roles are cluster-wide).

## 5. Stories have a separate `look` field

content.md requires every story to say what to look at and from where. A field makes it checkable and lets the app and website show it on its own. The current app does not read new fields, so format 2 output also appends `look` to `long` as its last paragraph. `long` is limited to 1,000 characters so the two together stay within format 2's 1,200.
Alternatives: requiring the instruction inside `long` (not checkable); waiting for format 3 (current readers would not see it).

## 6. Item ids replace `fa_` and `gd_` in the output

Stories and guides are items with `it_` ids. The app decodes ids as plain strings, so it reads them without an update; the output schemas in `format/v2/` accept `it_` ids. The previous `fa_` and `gd_` ids belonged to content that is not carried over.
Alternatives: minting `fa_` and `gd_` ids for new items (two id schemes for one kind of thing).

## 7. Translations are items, published in Simplified Chinese for every city

"Served both ways" means a Chinese reader gets Chinese text, in every city, not only Shanghai. A translation is an item of type `translation` linked to the item it translates, so the English and the Chinese each have their own state in the one lifecycle. Each translation revision names the English revision it was made from, carries no claims of its own, and is checked by tools (numbers and names) and by a back translation compared with the English claims. It publishes only with the English revision it translates.
Alternatives: a translation as another revision of the same item (one state can't describe two languages at different stages); a separate translations table (a second content workflow); on-device translation only (unchecked, and unavailable to the website).

## 8. Audit batches pool accepted work by type and city

Sampling at least 30 revisions per batch needs batches of at least 30. Pooling by type and city gives that while keeping results meaningful per city. A failed batch sends its erroneous revisions back to their writers and the rest back to checking.
Alternatives: one batch per writer run (most runs are smaller than 30, so audits would cover everything at the strong model's cost); one batch per city (a single failure reopens too much).

## 9. Content rules in the rulebook, operating values in settings

The rulebook (`rules/`, in git, versioned by hash) holds what content must be. Thresholds, model routing, and lease lengths are tuned from the console, so they live in a `settings` table with full history.
Alternatives: everything in the rulebook (every threshold change would need a commit and deploy); everything in the database (content rules would lose review and tests).

## 10. Source kinds name what a source is, not who owns it

The kinds are `official_record`, `archive`, `operator`, `scholarly`, `press`, `reference`, and `community`. `archive` separates old newspapers and maps (primary) from today's press; `operator` is the building's own owner or operator; `scholarly` includes local history societies with cited research. Primary means `official_record`, `archive`, or `operator`.
Alternatives: the design's first list, which put old newspapers and modern press together.

## 11. Stories need two independent sources, one of them primary or scholarly

This is what "original synthesis of primary sources" means in a check. With content.md's other rule (every claim backed by a non-reference passage), a story can't rest on an encyclopedia.
Alternatives: one primary source (allowed a summary of a single listing); three sources (too few places have them).

## 12. Own words means no shared run of eight words

The tools compare the prose with every snapshot it cites and refuse any shared run of eight words. Eight is long enough that names and set phrases don't trip it.
Alternatives: a similarity score (harder to explain to a writer); no check (summaries slip through).

## 13. The platform is served from its own host until the switch

The platform publishes to `/www/wwwroot/psst-platform/public` and nginx serves it at `psst-platform.67-230-170-225.sslip.io`, with its own TLS certificate, in its own server block. The previous site's configuration is not touched. The switch points the live content channel at the platform's production output, and needs approval.
Alternatives: a path on the previous site (changes its configuration); a new DNS name (needs a DNS change that isn't available from the server).

## 14. Tests run against PostGIS 14 in Docker

The server runs PostgreSQL 14 with PostGIS 3. Tests start a throwaway `postgis/postgis:14-3.4` container (locally and as the CI service), create a fresh database from the migrations, and drop it. The harness refuses any database not named `psst_test_*` on localhost.
Alternatives: the local Homebrew Postgres (no PostGIS); a shared test database (state leaks between runs).

## 15. Shanghai is the second city

Bilingual research and translation are the hardest part of the standard. Doing Shanghai second proves them before Hong Kong and Kuala Lumpur, which need the same.
Alternatives: the design's proposed order (London, Hong Kong, Shanghai, Kuala Lumpur).

## 16. Model judgment where code would guess

Tool checks decide only what code decides exactly: whether a quote is in its snapshot, whether digits and years
trace to claim values, lengths, wording rules, copied runs of words, and source kinds. Whether a word is a proper
name, or a detail is stated by a claim, is language, so the whole-item check answers it as a structured list (any
entry fails the revision), checked independently and escalated on disagreement.
Alternatives: name detection with word lists (brittle, refuses good text and misses bad); a named-entity library
(another model, with less context than the check has).

## 17. A rollback doesn't change the database

Rolling back points production at an earlier manifest and records it; items stay `published` in the database. A
rollback is an emergency switch: the editor then fixes or retires what was wrong, and the next publish builds from
the database again.
Alternatives: reversing every transition since the earlier version (would also undo unrelated work published in the
same version).

## 18. The publisher has its own kind of run

Publishing is recorded under `publisher` runs, started only by the publisher login, so publications are attributed
and no other role can mark content published.
Alternatives: publishing under a system run (the publisher login would need the system role's rights).

## 19. Research runs on Haiku 5.5

Research finds places and angles with sources to start from; it doesn't write anything readers see. Every angle is then written by Sonnet 5.5 with quoted evidence, checked twice, checked as a whole, and audited, so a weak angle costs a writing task, not accuracy. The routing setting was changed in the console with this reason, and the measured rates will show whether it holds.
Alternatives: Sonnet 5.5 for research (several times the cost for work the later steps filter anyway).

## 20. Correcting a place's Wikidata link is a system task

An editor names the right item in the console; the system worker reads it and takes the coordinate and other-language names from it the same way a new place is resolved, keeps the display name, and sends the guide back to draft with a revision task, because the guide's key facts came from the wrong item. Stories stay as they are: their claims rest on their own sources.
Alternatives: editing the link in place from the console (the pin and names would still come from the wrong item); retiring the place and creating a new one (loses its id and its checked stories).

## 21. The whole-item check runs before the claim checks

In the first London waves about half of all items failed the whole-item check, and their two claim checks, running at the same time, were cancelled or thrown away. The item check now runs first and the claim checks follow only when it passes: one check instead of three for an item that goes back, at the cost of one more step before acceptance.
Alternatives: all three in parallel (faster to accept, a quarter or more of claim checks wasted); claim checks first (two checks spent before the cheaper, more often failing one).

## 22. One session researches and writes a cell; one session reviews it

The first London day split content into narrow tasks for different models: research angles, write each story, check each claim twice, check each item, escalate, audit. It cost 123 model tasks and about 2 million tokens per published place, revision rounds went on for days, and the stories that passed were accurate but flat: facts stitched from quotes, guides restating the encyclopedia. The previous system did better with less: one strong session researched a whole cell, chose the angles with full context, and wrote everything in one voice, and a separate session reviewed it against the sources. The loop now works that way (design.md, section 7): one research session per cell writes every story and guide, the tools check what is mechanical, one review session per submission approves, edits, or rejects with a note (rejecting what isn't surprising, not only what is wrong), a rejected item gets at most one revision, and a 10 percent random audit of each reviewed batch gates publishing. Narrow claim checks, item checks, and escalations are gone as task types. Routing is read when a task is leased, and a worker takes every type routed to its model, so no queue waits on a model that isn't running.
Alternatives: keeping the narrow checks and tuning their prompts (the cost sat in the checks themselves, and narrow tasks can't judge whether a story is worth telling); dropping review and relying on audits alone (an audit samples; review is where taste is applied to every story).

## 23. One dense cell is researched a second time on Opus 5.5, as a test

Research runs on Sonnet 5.5 by default, and Opus 5.5 is not used for content work. As a single exception, the densest central London cell is researched a second time by an Opus 5.5 run, leased before the Sonnet run submitted so neither sees the other's output. The best stories from each, shuffled with ten reference stories from the previous system, go to the editor unlabeled for marks; tasks, tokens, and time per published story are measured per group. Routing for dense cells is then set from the result and recorded here.
Alternatives: choosing the model without a test (the difference in quality is what the cost would buy, and only a blind comparison measures it); testing on several cells (more cost before the first result).

## 24. Dense cells are researched on Opus 5.5

The test of decision 23 researched the densest central London cell on Opus 5.5 and three dense cells on Sonnet 5.5, all reviewed and audited the same way, and the editor marked the results blind alongside ten reference stories. Opus: 8 stories, 7 published, 4 marked good, about 66,000 tokens and 0.6 model tasks per published story, 69 minutes from research to publish. Sonnet: 17 stories, 4 published so far, 3 marked good of 8 shown, about 356,000 tokens and 3.8 model tasks per published story, with two of three batches failing audit. The reference stories scored 9 of 10 good. A session on Opus costs more, but far less of its work is thrown away, so a published story and a good story both cost several times less. Research on a cell with at least `research.dense_leads` (100) open leads now goes to `routing.research_cell_dense` (Opus 5.5); other cells stay on Sonnet 5.5 until measured.
Alternatives: Opus for every cell (quiet cells were not measured, and their sessions are short); Sonnet everywhere (the measured cost per good story is about four times higher).
