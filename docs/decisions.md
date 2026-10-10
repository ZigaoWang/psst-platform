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

## 25. The editor's marks are the standing quality gate

The editor marked 26 stories blind once. Those marks, with their reasons, are now the golden set (in the database, never in git), and the gate is built on them. Review marks each story good, weak, or bad as the editor would, and the line between good and weak is the fix it needs: a cut leaves it good, anything that must be added or settled makes it weak. Good publishes, after one revision making the cut when it names one; weak gets one revision aimed at the reason; bad is dropped; reviewers no longer edit, since both errors the first audits found were in reviewers' own edits. Before the reviewer gates anything it re-marks the golden set blind, in two folds so no story is marked while its mark is in view, and must agree with the editor on at least 90 percent for the current review prompt, model, golden bar, and golden set. The system worker re-checks the gate every five minutes and queues a calibration whenever any of those changes or a week passes; while agreement is under 90 percent, reviews wait and nothing publishes. A guide of worked examples, the golden bar, shows good and weak writing side by side for each thing written; it is content too, versioned in the database, carried by every research and review task, and recorded on every revision written against it. The editor can mark a sample of published stories from the console at any time; those marks join the golden set and nothing waits on them.
Alternatives: marking every story by hand (does not scale, and the editor's time is the scarcest resource); trusting the reviewer prompt without measuring it (the first calibration agreed on 65 percent).

## 26. Research is submitted place by place

Three overnight research sessions stopped when their sign-in expired, before their final submit, and every place they had written was lost with them (about 600,000 tokens). A researcher now submits each place as soon as it is finished: the place, its stories, its guide, and the leads it covers are stored at once, and the submission renews a 90 minute lease. A session that stops loses only the place in hand; when its lease runs out the task goes back to the queue with a note, the stopped run ends, and the next researcher continues the cell, seeing the places already added. The cell's reviews wait for its final result so they cover the cell together. Each place is also checked against the live database before it is stored, so a place another session added since the lease is caught and written as an existing place with a new angle, or dropped.
Alternatives: checkpoint files on the worker's machine (lost with the machine, and invisible to the next worker); shorter cells (more sessions, each paying the reading cost again); a heartbeat from the session (a stopped session can't send one, and the lease already does the job).

## 27. Density: featured stories, map stories, and a target per hexagon

The old system had 1,753 London places, and in the same neighborhoods it had two to four times what the first cells of the new loop produced; the editor found even the old density too thin. The goal is something worth looking at within a few steps anywhere in a city center, measured on H3 resolution 9 hexagons (about 100 meters across): at least three published things per hexagon in dense areas. To get there without lowering accuracy, a story now has a tier. A featured story clears the calibrated "wait, really?" bar and leads the feed; a map story is as true, specific, sourced, and visible, with a smaller surprise, and fills the map. A story also has a form: a story, a street name (where the name comes from, tied to the sign), or a plaque (what it doesn't tell you). A place with a listed building and no story yet can publish with its guide alone. Every form goes through the same evidence, tool checks, review, and audit; bad never publishes. The reviewer sets the tier of every good story, the golden set carries a tier for every good story, and calibration counts a good mark in the wrong tier as a disagreement, with the bar still at 90 percent.
Alternatives: lowering the bar for all stories (trades accuracy and the feed's quality for count); publishing guides only (dense but says nothing a map app doesn't).

## 28. The harness: a purpose-built pipeline on API models

Interactive worker sessions were the most expensive part of the loop and could not run unattended or be measured per call. The harness is a pipeline runner, not a general agent. Code does everything deterministic: leasing, gathering a lead's own page, the tool checks, submitting, and the budget. A model is called only for judgment (triage, writing, review, audit, calibration), each call with the step's prompt and the shared data first and unchanged so providers can cache it, and inside writing, review, and revision the model may call a small set of typed tools (read a source through the fetch service, find a passage in a snapshot, look up Wikidata or OpenStreetMap, list nearby places, run the tool checks on a draft), within per-step limits on tool calls and tokens. Its answer is checked exactly as a worker's submission is; problems go back a limited number of times, then the task is given back with the reason. Research is triaged in one call and written one place per call, each place submitted as it passes (decision 26). Every model call and tool call is recorded with its tokens, cached tokens, cost, latency, prompt version, and tool version. A provider layer speaks to Anthropic and to any OpenAI-compatible API; models are named `<provider>:<model>`, keys live only in the server's environment file, and requests through OpenRouter go only to providers that neither keep nor train on what is sent. Spending stops before the total budget, or a city's daily or monthly budget, is reached. The harness works the same task queue, gate, and audits as everything else, so a step moves between a model and a person without changing the loop.
Alternatives: a general agent with a browsing loop per cell (what the worker sessions were: costly, unmeasured, hard to pause); one model call per cell (contexts too large and failures lose the cell).

## 29. Models are chosen by measurement, the most cost-effective that meets the bar

Every candidate is measured on our own golden set through the same harness, with the same prompt, at its real cost; public benchmarks only shape the shortlist. In the first review bake-off (26 tiered golden stories, one run each) the best agreement was 84.6 percent, reached by GLM 5.3, Qwen 3.8 Flash, and a three-model panel; Gemini 3.8 Flash, Grok 4.7, and DeepSeek V4.1 Flash reached 80.8; Sonnet 5.5 77; GPT-6.1 Sol 46. Among those at the top, GLM 5.3 costs about seven tenths of a cent per 13-story fold and answers in about nine seconds, against four times the cost and two minutes for Qwen 3.8 Flash, so reviews and calibrations route to GLM 5.3. A panel (vote:) and a writer rotation (rotate:) are measured the same way; the writer is chosen from the rotation in the proof cells by the review marks and audit results of what each model wrote, against its cost per published item. The bake-off runs again when a provider ships a new model or the golden set grows. Expensive models are left out unless the cheap ones cannot meet the bar.
Alternatives: choosing by public benchmarks (they measured none of our standard); one premium model everywhere (several times the cost for no measured gain).

## 30. The gate is the publish decision; a featured tier needs a second reader; repairs are logged

The editor re-marked the golden set under the tiers: every story is featured, map, or bad, with cuts, labels, and sources named as fixes. No model agreed with both the decision and the tier often enough, because the line between featured and map is a matter of degree. So the gate measures the publish decision: a calibration agrees with the editor when it publishes what the editor would publish (featured or map) and holds back what the editor would hold back (weak or bad), at 90 percent. Tier agreement is recorded and reported beside it, not gated. A story the reviewer tiers featured leads the feed only when a second, different model agrees; otherwise it publishes as a map story; reader signals will refine tiers later. Something to see means the reader can see the thing the story is about, or a marker of it, from where they stand; standing at the site of an event isn't enough. The editor settled two examples, now in the golden bar and the review prompt: the Primrose Hill Gorsedd is a map story because a plaque on the hill marks it, and South Kentish Town is a map story because its tiled facade is in view. Golden stories keep their look line, since it decides what can be seen. A writer's near quote is replaced by the snapshot's exact text only at a word similarity of 0.95 or more; every repair is logged on its place and shown to the reviewer and the auditor beside the claim, who judge the claim against the real passage; and each writer model's rate of repaired and invented quotes is reported, since a model that invents often doesn't qualify, however cheap.
Alternatives: gating on tier as well (no model could meet it, and tier is the softer judgment); refusing every inexact quote (the cheap writers' places would all be refused for a changed word).

## 31. Constructed negatives: the gate must catch defects as well as publish good stories

The re-marked golden set held 24 stories to publish and 2 to hold back, so a reviewer that published everything agreed on 92 percent and passed. Negatives with known labels are now built from the editor's good stories, each broken in one known way: a number that no longer matches its claims, an added sentence no claim supports, a look line pointing at nothing, an encyclopedia-style opening, a speculative ending, slop phrases, a duplicated sentence. Six of each, 42 in all, kept in the database only and rebuilt by a command when the golden set changes. Every calibration item shows its claims (the sentences of the unbroken story), as a review shows claims beside the prose. The gate requires both, separately: 90 percent of the editor's good stories published, and 90 percent of the negatives caught, where caught means held back, or, for a constructed defect, a named fix. A near paraphrase of a source is left out: judging it needs the source page, and the tool checks refuse it before review.
Alternatives: asking the editor to mark more bad stories (slow, and the defects would be whatever happened to turn up); one combined agreement number (a lenient reviewer passes it).

## 32. Writing in two steps: evidence verified by code, then prose from those facts only

Cheap one-step writers, asked to write a story and bind each claim to an exact passage at once, kept stating details their quotes didn't contain and ran out of fixes; a control run on Claude Sonnet 5.5 came close on the same lead but ran out of tokens before finding a primary source. Writing is now two calls. The evidence step, with tools, gathers the facts for one place, each with its values and the exact words of a source; code checks every quote against its snapshot, every value against its quote, and that the facts rest on enough independent sources with a primary record or scholarly source among them, and sends anything wrong back. If the evidence for a real story isn't there, the step answers skip with the reason, and the lead is skipped with it. The writing step, without tools, gets the verified facts and the golden bar for voice and returns the stories and guide with the ids of the facts each rests on; code builds the claims from those facts and refuses any year, number, or proper name in the prose that isn't in them, before the same tool checks and review as any submission. Before the evidence step, code reads the lead's own page and the official records its Wikidata item points to.
Alternatives: a stronger model in one step (several times the cost, and the control showed the same failure mode); looser quote matching (accuracy traded for throughput).

## 33. Throughput: places in parallel, pages read once, retries capped

The first two-step proof wrote a place every eleven or so minutes, one at a time. Model calls were about a sixth of that time; the rest was reading sources (one page at a time across all sites, with nothing reused) and fix rounds (43 of 56 calls). A cell's places are now written in parallel, eight at a time (harness.parallel_places), each still submitted as soon as it passes. A page read in the last 30 days is reused as its saved snapshot instead of read again, a place's own sources are read together, and the fetch service paces each site separately (one page at a time per site, with a short pause) instead of holding every site to four reads at once. Each judgment step allows two fix rounds, then hands the place back with the reason. Requests through OpenRouter go to the fastest provider that neither keeps nor trains on data, and the writing step asks for low reasoning effort, since it needs craft more than deliberation; whether quality holds is measured by the review and audit results of what it writes. Every tool call's time is now traced beside the model call's. Spend per place doesn't rise: the same calls, made at the same time.
Alternatives: more cells at once (helps only once one cell is fast, and spreads review batches thin); a faster, weaker model (the evidence rules, not the model, set the pace).

## 34. One short call per step: code gathers and trims, models only judge

Measured on five places, the evidence step took about 20 calls a place, each resending a conversation of some 11,000 tokens as the model browsed page by page; writing took about 7 calls of 31,000 tokens, since every call carried the whole golden set and rules and half were fix rounds; together about $0.10 and eleven minutes a place. Now code does the reading: the lead's page, the official records its Wikidata item names, and up to two links from its page to official, archive, or scholarly hosts, read together and reused, each cut to the paragraphs that name the place (about 2,500 characters). The evidence step is one call over those passages, with no tools; the writing step is one call with the writing rules and the golden bar only; triage gets one compact line per lead. Reasoning is off for all three, and each allows one fix round. Since the gate measures the reviewer, the writer's quality is measured by the review and audit results of what it writes; if they drop, the examples that matter are added back, not the whole set. A view of calls, tokens, reasoning tokens, cost, seconds, and fix rounds per step and per place written is shown permanently in the console. Targets: under $0.015 per published place and a 12-place cell in under five minutes.
Alternatives: keeping the model's browsing loop with smaller pages (still one call per page read, and the context still grows); one call for a whole cell (places don't usually share sources, and one failure would lose the cell).

## 35. A map story may rest on its official record; a plain record makes a guide-only place

Most listed buildings have two sources, the heritage list entry and an encyclopedia article that draws on it. Once facts resting only on the encyclopedia are set aside, the list entry is the one independent source, so under the two-source rule nearly every such place was skipped (one of twelve passed in a London cell). A map story may now rest on the official record alone, since the record is the authority on what it states; a featured story keeps two independent sources, and a story the reviewer tiers featured on one source is kept as a map story without a second reading. When the facts say only what a place is and how it is built, with no surprise a reader would stop for, the place gets a guide and no story, rather than a story forced out of architecture. Code decides whether the facts' sources can carry a story; the writer, who has the golden bar, decides whether they hold one. Asking the evidence step instead made nearly every place guide-only, including a pillar box suffragettes set on fire in 1913. Every claim still rests on something other than a reference work.
Alternatives: a paid web search per place for a second source (about $0.01 a place, and slower); writing only leads that already have two non-reference sources (far fewer places).

## 36. Unattended runs: densest cells first, a spending window, and two stops

A research pass now ends with a submission: its places are stored, its other leads are accounted for, and leads it chose but didn't write stay open. Before, a pass that wrote as many places as it was asked handed the cell back, and each hand-back counted as a failed attempt, so a dense cell failed after ten passes. Triage chooses at most the pass's number of places, and a pass is offered open leads before ones set aside for later. After each pass, the harness service queues its city's next cell. Cells are ranked densest first: each place the previous app had in a cell counts as one km nearer the city's middle, against 20 km for each earlier pass, so a dense cell is worked pass after pass. A cell's leads are swept once a week, not before every pass. An unattended run has a window (harness.window: a start time and a cap in USD), the task types it works (harness.work_types), and stops on its own when more than harness.max_failed_share of one pass's places fail, or when the window's spend per place still standing passes harness.max_usd_per_place, judged once it has spent what ten places may cost.
Alternatives: a fixed list of cells for the night (no continuation, and a dense cell needs many passes); stopping on the first pass with no places (one pass of an empty cell would end the run).

## 37. One check for prose: the tool checks

Decision 32 had code refuse any year, number, or name in the writing step's prose that wasn't in the facts it named, before the tool checks ran the same kind of check against the claims' values and the cited pages. The first check was stricter than the rule it stood in front of: on one night it sent back 97 answers for names the cited pages do state, such as the Second World War, the City, or a street the record names, and fix rounds became the largest cost of writing. It is gone; the tool checks alone hold every number to the claims' values and every name to the cited pages, as they do for every submission.
Alternatives: widening the first check to the cited pages (two checks for one job).
