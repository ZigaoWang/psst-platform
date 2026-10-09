# Psst platform design

Status: agreed. Version 2, October 9, 2026. Version 2 adds the content standard ([content.md](content.md)), the write-new decision, and the resolved open decisions.

This document specifies the Psst content platform: the database, the curation pipeline, the task workflow, the admin console, the public website, and the output the apps read. Decisions made while building are recorded in [decisions.md](decisions.md).

## Contents

1. Purpose
2. Principles
3. Decisions already made
4. System overview
5. Data model
6. Lifecycle
7. Evidence and checking
8. Tasks and workers
9. The rulebook
10. Places, areas, and coordinates
11. Publishing and the published output
12. Admin console
13. Website
14. Security
15. Environments, testing, and operations
16. Repository layout
17. Moving from the previous system
18. Settled decisions
19. Milestones

## 1. Purpose

Psst's value is its curated content: places, the surprising stories about them, and plain guide information, each traceable to sources and checked. [content.md](content.md) defines what that content must be. The platform makes its accuracy structural, keeps every change traceable, scales to hundreds of thousands of places, and serves the iOS app and a public website from one output.

Out of scope: the iOS app's own redesign, which follows once the platform and website exist.

## 2. Principles

1. **Evidence before prose.** Every claim carries the passage that supports it. Tools check what tools can check; models answer narrow questions; editors decide the hard cases.
2. **Nothing is overwritten.** Content changes by adding revisions. Any past state can be read back.
3. **One mechanism per job.** One lifecycle, one task system, one rulebook, one publishing path, used by every content type.
4. **The database enforces the rules.** Lifecycle transitions, attribution, and permissions are enforced by the database, not by each script.
5. **Measured quality.** Accuracy is a number per audit batch, task type, model, and city. Publishing requires it to be under a threshold.
6. **Least privilege.** Every role can do only its job. Workers can't publish or vouch for their own evidence; the website reads files, not the database.
7. **Plain everywhere.** Content, console, docs, and errors are written plainly, in US English, without dashes, hype, or filler.
8. **Built to grow.** No path loads everything at once. New content types, languages, and cities are configuration, not new code paths.

## 3. Decisions already made

| decision | choice |
| --- | --- |
| Content | Written new. Nothing from the previous system is copied as content, and its stories are not used as leads. Its place list is used only as a coverage checklist. |
| Place ids | A researched place that is the same Wikidata item or OpenStreetMap element as a previous place keeps that place's `pl_` id, so places saved in the app still resolve. |
| App during the rebuild | Keeps the previous content until the first publish from this platform, which replaces it. From then on the app shows only new, checked content. |
| Web stack | SvelteKit for both the public website and the admin console. |
| Database | A new PostgreSQL database with PostGIS, `psst_platform`, on the current server beside the previous one. |
| Accuracy | The mechanism in section 7, not stronger models. Each task runs on the cheapest model whose measured accuracy meets the threshold. |

## 4. System overview

```
             sources (web pages, Wikidata, OpenStreetMap, archives)
                                  │
                         fetch service (server)
                                  │ snapshots
 workers ──► psst CLI ──► Postgres (psst_platform) ◄── admin console (SvelteKit, private)
 (model      tasks,       content, evidence, tasks,         │
  runs)      results      runs, audits, history             ▼
                                  ▲                    editor actions
                          system worker
                     (tool checks, places, audits)
                                  │
                              publisher ──► staging ──► acceptance ──► production output
                                                                              │
                                                          ┌───────────────────┴────────────┐
                                                          ▼                                ▼
                                                     iOS app                  website (SvelteKit, static)
```

- **Postgres** holds everything curated. It is the single source of truth.
- **The psst CLI** is the only way workers and editors write content. It reaches the database through functions that enforce the lifecycle (section 6).
- **Workers** are model runs. They lease tasks, do them, and submit structured results (section 8).
- **The fetch service** runs on the server. It is the only thing that reads sources and writes snapshots, so evidence can't be typed in by a worker.
- **The system worker** runs the deterministic work: tool checks, coordinate lookups and area assignment, evaluating check results, planning audits, link checks.
- **The publisher** builds the output, stages it, checks it, and promotes it (section 11).
- **The admin console** is a private web app for watching, auditing, and acting (section 12).
- **The website** is a static site built from the published output (section 13).

## 5. Data model

All tables live in schema `psst` of database `psst_platform`. Ids are permanent, prefixed, and random (Crockford base32, 10 characters; 8 for tags): `pl_` place, `it_` item, `rv_` revision, `cl_` claim, `so_` source, `sn_` snapshot, `tk_` task, `ru_` run, `tg_` tag, `im_` image file, `pb_` publication, `ab_` audit batch, `ld_` lead, `ac_` console account. Times are `timestamptz` in UTC.

### 5.1 Places

| table | purpose |
| --- | --- |
| `places` | One physical thing with a pin: `id`, `kind`, `size`, `geom` (WGS-84 point), `coord_source` (`wikidata` or `osm`), `coord_ref`, `wikidata_id` (unique), `osm_ref` (unique), `h3_r7`, `country_code`, `city_id`, `district_id`, `neighborhood_id`, `state` (`pending`, `active`, `merged`, `gone`, `refused`), `merged_into`, `created_by_run`. |
| `place_names` | `place_id`, `lang`, `role` (`display`, `local`, `alt`), `name`, `source`. |
| `place_identity` | Previous ids that resolve to a place (`legacy_id`, `place_id`): previous `pl_` ids and the older `areaId/spotId` ids. |

A place is created `pending` with its Wikidata item or OSM element. The system worker looks up its coordinate, assigns its areas, checks for duplicates, and makes it `active`, or refuses it with a reason. A place appears in the output only while it has published stories and published guide information.

### 5.2 Content items and revisions

Every piece of curated content is an **item** with an immutable chain of **revisions**.

| table | purpose |
| --- | --- |
| `item_types` | `story`, `guide`, `photo`, `trail`, and `translation` today; `audio` later. Whether the item belongs to one place, and its acceptance threshold. The revision body's schema and check plan live in the rulebook. |
| `items` | `id`, `type`, `place_id` (null for trails), `city_id`, `translates` and `language` (for translations), `state` (section 6), `current_revision`, `published_revision`, `position`, `checking_since`, `created_by_run`. |
| `revisions` | `id`, `item_id`, `number`, `translation_of` (for a translation, the English revision it was made from), `body` (JSONB), `rulebook` (version it was checked against), `created_by_run`, `created_by_task`, `created_at`, `reason`. Never updated or deleted. |

Revision bodies follow content.md section 4:

- **story:** `category`, `veracity`, `headline`, `short`, `long`, `look`, `myth` (optional), `tags`.
- **guide:** `identifier`, `about`, `key_facts` (each a Wikidata property, a structured value, and the claim that backs it).
- **photo:** `file`, `kind`, `year`, `alt`, `focus`, `pair`, and the credit fields copied from the source's metadata.
- **trail:** `title`, `intro`, `stops` (place id and `note`, in order), `tags`.

A translation is its own item of type `translation`, linked to the item it translates, so each language moves through the lifecycle on its own. Each of its revisions names the English revision it was made from and is checked against that revision's claims (section 7.5). An edit creates a new revision; approving, publishing, retiring, and reverting move pointers and states and never change a revision.

### 5.3 Claims and evidence

| table | purpose |
| --- | --- |
| `claims` | One checkable statement in a revision: `id`, `revision_id`, `n`, `text` (the claim in plain English), `kind` (`date`, `name`, `number`, `place`, `event`, `attribute`), `values` (the exact years, numbers, and names the claim asserts, each with the form it takes in the source when that differs, such as 一九三〇 for 1930). |
| `evidence` | `claim_id`, `snapshot_id`, `quote` (exact text from the snapshot), `quote_start`, `quote_end` (set by the tool check), `matched`. A claim needs at least one matched evidence row. |
| `sources` | One per canonical URL: `id`, `url`, `url_key`, `title`, `publisher`, `kind`, `language`. |
| `snapshots` | What a source said when read: `id`, `source_id`, `fetched_at`, `http_status`, `via` (`live`, `archive`, `mirror`), `read_url`, `content_hash`, `text` (normalized plain text, compressed), `run_id` (who asked). Written only by the fetch service. Immutable. |

Source kinds, which drive the source rules (section 9):

| kind | examples | role |
| --- | --- | --- |
| `official_record` | heritage listings, gazetteers, Hansard, government archives, planning records | primary |
| `archive` | old newspapers, old maps, directories, digitized collections | primary |
| `operator` | the building's owner or operator: the church, the company, the transit authority | primary |
| `scholarly` | museums, universities, journals, local history societies with cited research | scholarly |
| `press` | newspapers and magazines, specialist sites with editorial standards | secondary |
| `reference` | encyclopedias including Wikipedia, guidebooks, listicles, Wikidata | reference |
| `community` | blogs, forums, personal sites | secondary |

### 5.4 Checks, audits, and decisions

| table | purpose |
| --- | --- |
| `checks` | One verdict: `revision_id`, `claim_id` (null for a whole-item check), `kind` (`tool`, `claim_a`, `claim_b`, `item`, `escalation`, `audit`, `editor`, `translation`), `run_id`, `task_id`, `model`, `verdict` (`supported`, `unsupported`, `contradicted`, `unclear`, or `pass`/`fail` for tool and item checks), `note`, `details` (JSONB), `created_at`. |
| `audit_batches` | Accepted revisions grouped for one audit: `id`, `type`, `city_id`, `size`, `sample_size`, `errors`, `rate`, `threshold`, `outcome` (`open`, `passed`, `failed`). Members in `audit_members`, the sample in `audit_samples`. |
| `model_accuracy` | A view over checks: for each task kind and model, how often its verdicts were overturned by escalation, audit, or editor verdicts. |

### 5.5 Tags, areas, and reference data

- `tags`, `tag_labels`, `tag_names`, `item_tags`: canonical names, normalized aliases, Wikidata links; attached to items.
- `areas`, `area_names`, `area_parts`: the boundary hierarchy from Who's On First and OpenStreetMap, cut into small parts for fast lookups.
- `cities`: the cities set up for research, each an area with its research settings and readiness.
- `research_cells`: the H3 research grid (resolution 7) and each cell's coverage.
- `leads`: candidate places for research, from Wikipedia (English and local), OpenStreetMap, Wikidata, and the previous place list, with their fame and how each was accounted for.

### 5.6 Work, runs, and history

| table | purpose |
| --- | --- |
| `runs` | One worker or editor doing work: `id`, `kind` (`worker`, `editor`, `system`), `model`, `operator`, `token_hash`, `started_at`, `ended_at`, `notes`. |
| `tasks` | Section 8. |
| `transitions` | Every state change of every item, written only by the lifecycle functions: `item_id`, `from_state`, `to_state`, `revision_id`, `run_id`, `task_id`, `reason`, `at`. |
| `reports` | Problem reports from readers, attached to an item. |
| `demand` | Anonymous counts of empty areas viewed. |
| `publications` | Every staged and promoted output version with its manifest, counts, checks, item-level changes, and run. |
| `link_checks` | Each weekly check of each source: status, and whether the text changed from its latest snapshot. |
| `settings` | Thresholds, model routing, and lease lengths, with the history of every change. |
| `console_accounts`, `console_sessions`, `console_actions` | Section 12. |

History is complete by construction: revisions and snapshots are immutable, transitions and checks are written only by functions, and every row names its run.

### 5.7 Growth

- History tables (`transitions`, `checks`) are append only and indexed by time; they are partitioned by month once either passes ten million rows.
- Snapshot text is stored compressed and deduplicated by hash; large snapshots can move to object storage with only the hash and a pointer left in the table.
- Every list the console shows has an index that matches its filter and order, and every list is paged by key.

## 6. Lifecycle

Every item follows one state machine, enforced by database functions. Workers, the system worker, and the console call the functions; no role can update `state` directly.

```
draft ──submit──► checking ──all checks pass──► accepted ──publish──► published
  ▲                  │                              │                    │
  │               problems                       audit fails          report, source change,
  └──── revise ◄─────┘◄─────────────────────────────┘◄──────────────── or new revision
                                                                         │
                                       any state ──retire (with reason)──► retired
```

| state | meaning | who moves it |
| --- | --- | --- |
| `draft` | A revision being written or revised. | writer tasks |
| `checking` | Submitted; tool checks, claim checks, and the item check running. | the check workflow |
| `accepted` | Every check passed; waiting for its audit batch to pass and for publishing. | the check workflow |
| `published` | In the output. A newer accepted revision replaces it at the next publish. | the publisher |
| `retired` | Taken down or never accepted, with a reason. Kept forever. | check workflow, editors |

Rules the functions enforce:

- A run never checks or audits its own writing, and the two claim checks of one claim come from different runs.
- A revision moves to `accepted` only when the tool check passed, every claim has two agreeing `supported` verdicts or a `supported` escalation, the item check passed, and no `contradicted` verdict is unresolved.
- An accepted revision publishes only after its audit batch passes (section 7.7).
- A reader report or a changed source moves a published item back to checking; the published revision stays live until a replacement is accepted or an editor retires it.
- A translation is accepted only while the revision it translates is accepted or published.

## 7. Evidence and checking

This is the core of the design. A spot check on October 9, 2026 found 10 to 17 percent of a cheaper model's approvals wrong, and the errors were misreadings (a replica dated as the original, a closing year given as the build year), not invented sources. The mechanism catches them by structure.

### 7.1 Writing with evidence

A writer reads sources only through `psst fetch`, which asks the fetch service to read the page and save a snapshot. The writer returns the prose and its claims. Each claim lists its values and its evidence: the snapshot and the exact passage copied from it.

### 7.2 Tool checks (no model)

On submit the system worker refuses a revision, with every reason listed, unless:

1. **Passages match.** Every quoted passage appears in its snapshot after Unicode, whitespace, and quotation mark normalization.
2. **Numbers trace.** Every year and number in the prose appears among the claims' values, and every claim value appears in at least one of that claim's passages. Names and other details are language, not arithmetic, so the whole-item check traces them (section 7.4).
3. **Writing rules hold** (section 9): lengths, banned words, US spelling, dashes, the identifier shape, `look` present.
4. **Own words.** The prose shares no run of eight words with any snapshot it cites.
5. **Source rules hold.** For a story: at least two distinct sources; at least one primary or scholarly source; every claim backed by a passage from a source that is not `reference`; a `myth` story cites a source for the popular version and a primary or scholarly source for the correction; an anecdote with one source is `legend`.
6. **Structured values agree.** A guide's identifier year and maker match its key facts; a key fact without agreeing evidence is dropped.
7. **References resolve.** Tags exist, trail stops are published places within the distance limits, a photo's pair is a current photo of the same place.

These checks are free and deterministic. The writer's CLI runs the same code before submitting, so most problems are fixed before anything is stored.

### 7.3 Claim checks (narrow, independent)

Each claim is checked twice, by different runs with different instructions. A checker sees only the claim and its passages, never the prose or the writer's reasoning.

- **Check A** asks: does this passage say this? Find the mismatch.
- **Check B** asks: what exactly does this passage say about the claim's subject? It then compares its own reading with the claim.

Both answer `supported`, `unsupported`, `contradicted`, or `unclear`, with a one-line note.

- Both `supported`: the claim passes.
- Any disagreement or `unclear`: an escalation by a stronger model with the full snapshots.
- `unsupported` or `contradicted` after escalation: the revision goes back to the writer with the reasons.

### 7.4 Whole-item check

Some errors live between claims: a headline that overstates, "the first" where the claim says "one of the first", a replica described as the original, a `look` pointing at the wrong thing. One check per revision reads the prose against its claim list and the place's encyclopedia lead and answers narrow questions, with structured answers: which names, dates, or details in the prose does no claim state (any entry fails the revision)? Does the prose say anything more strongly than its claims? Is the story's surprise already in the encyclopedia lead? Is it true of this place rather than its kind? Does `look` name something to see and where to stand? A `fail` sends the revision back with the reasons; an `unclear` escalates.

### 7.5 Translations

A translation must preserve every claim. The tools check that every number and year matches the English and that names use the place's stored local names. A translation check then translates the text back without seeing the English and compares it claim by claim; any added, missing, or changed claim fails it.

### 7.6 Guide key facts

Key facts come from Wikidata as structured values with their property. Each becomes a claim whose evidence is the Wikidata item's snapshot and, where one exists, a passage from another source. Implausible values (future dates, an opening before the build date, impossible heights) are flagged by the tools; a flagged value without a non-Wikidata passage is dropped automatically.

### 7.7 Acceptance sampling

Accepted revisions are audited before they can publish. The system worker groups them into audit batches by type and city, each at least 30 revisions (smaller only when nothing else is waiting). It samples `min(size, 30 + 5% of the rest)` at random and creates audit tasks for a stronger model, which rechecks every claim and the item from the full snapshots. A sampled revision with any claim not `supported`, or a failed item check, is an error. If the error rate is above the type's threshold, the batch fails: its erroneous revisions go back to their writers and every other revision in the batch goes back to checking. Results feed `model_accuracy`.

### 7.8 Editors' checks

The console shows the same sample view: claim, passages, verdicts, and one action to mark a claim wrong. An editor's verdict outranks every model verdict and counts in the measured rates.

## 8. Tasks and workers

### 8.1 Task types

| type | input | output | default model |
| --- | --- | --- | --- |
| `research_cell` | a cell, its leads, nearby places | places to create, story angles with sources to read, leads accounted for | Sonnet 5.5 |
| `write_story` | a place and an angle | one story revision with claims and evidence | Sonnet 5.5 |
| `write_guide` | a place, its Wikidata item, sources | one guide revision with claims and evidence | Haiku 5.5 |
| `revise` | a revision and the problems found | a new revision | same as the writer |
| `check_claims_a`, `check_claims_b` | a batch of claims with their passages | verdicts | Haiku 5.5 |
| `check_item` | a revision, its claims, the encyclopedia lead | verdict and reasons | Haiku 5.5 |
| `escalate` | disputed claims or items with full snapshots | verdicts | Sonnet 5.5 |
| `audit` | a sample revision with full snapshots | verdicts | Sonnet 5.5 |
| `translate` | an accepted revision and its claims | a translated revision | Sonnet 5.5 |
| `check_translation` | a translated revision | back translation and verdict | Haiku 5.5 |
| `write_trail` | a theme and candidate places | a trail revision | Sonnet 5.5 |
| `find_photos`, `check_photo` | a place; a photo | candidates; a verdict | Haiku 5.5 |
| `recheck_source` | a source whose text changed | verdicts on its claims | Haiku 5.5 |
| `handle_report` | a reader report | a decision | Sonnet 5.5 |
| `system` | deterministic jobs: tool checks, place lookup, evaluation, audit planning, publish requests | results | system worker |

### 8.2 Leases

`psst task next --type <type> [--city <city>]` atomically leases the next task (`FOR UPDATE SKIP LOCKED`) the run may take, for the type's lease length: never its own writing, never a second check of a claim it already checked, and only types routed to its model. Two workers can never get the same task. `psst task submit <task> <result file>` validates the result against the type's schema and the rulebook, applies it through the lifecycle functions, and closes the task. An expired lease returns the task to the queue; a task that fails three times waits for an editor. Every task records its run, model, attempts, prompt version, and result.

### 8.3 Worker protocol

A worker needs one instruction: which task types to work on, and for how long. Each task arrives as a file with everything needed and the prompt for its type. Prompts live in `prompts/`, one per task type; a prompt's version is the hash of its text, recorded on every result.

### 8.4 Model routing

Each task type has a model from `settings`, starting with the defaults above. Narrow checks run on the cheapest model that meets the threshold; escalations and audits on a stronger one. The console shows measured rates per task type and model, so routing changes are made with evidence.

## 9. The rulebook

One versioned set of YAML files in `rules/` defines: writing rules (lengths, banned and soft words, US spelling, dashes), the identifier and About shapes, story categories and veracity rules, source kinds and what each can support, tag rules, photo rules, trail limits, and each item type's body schema and check plan. The CLI, the checks, the console, and the prompts read it; the docs explain it and never restate its numbers.

The rulebook's version is the hash of its files. Each revision records the version it was checked against, so a rule change can recheck exactly the content it affects. Rule changes are commits with tests. Operational values that editors tune (thresholds, routing, lease lengths) live in `settings`, not the rulebook.

## 10. Places, areas, and coordinates

Kept from the previous system:

- Coordinates only from Wikidata (preferred, CC0, when exactly one value precise to about 50 meters) or OpenStreetMap (ODbL), looked up by the tools, always WGS-84; the app handles GCJ-02 at runtime.
- Areas assigned from real boundary data (Who's On First, OpenStreetMap in mainland China and Hong Kong), never typed.
- Duplicate checks by Wikidata id, OSM element, and similar names within 150 meters.
- The H3 research grid at resolution 7.

Changed:

- One definition of city everywhere: the place's city, else its region.
- Lookups and area assignment run in the system worker after the place is stored, never holding locks during network calls.

## 11. Publishing and the published output

### 11.1 Output

The output keeps the shape of content format 2 (a manifest, a common pack, one pack per city), so the current app reads it without an update. Within format 2 it adds only optional fields:

- `look` on each story. The current app does not read it, so the publisher also appends it to `long` as its last paragraph; `long` plus `look` stays within the format's 1,200 characters.
- `claims` on each story and guide: the claim text and the indexes of the sources that back it.
- `myth`, `lastVerified`, and `translations` (`zh-Hans`) on stories and guides.
- `trails` in each city pack.

Item ids (`it_`) replace the previous `fa_` and `gd_` ids; the app treats ids as opaque strings. A format 3 with per-area packs and a spatial index comes with the app's redesign, published beside format 2.

### 11.2 Publishing

`psst publish` (or the console's button, through a `system` task) takes the publish lock, builds the output from accepted revisions whose audit batches passed plus everything already published, uploads it to staging, downloads it back over HTTPS and checks it (hashes, schemas, references, legacy ids, images served, no unexplained shrinkage), and promotes only the version it checked. A place publishes only with its guide information, and a city publishes only when every place in it has guide information. Rollback swaps the manifest back. Every publication records what changed, item by item, so the console shows a diff.

### 11.3 First publish

The platform publishes to its own staging and production channels first. The first publish that replaces the app's live content happens only with explicit approval; it points the live channel at this platform's output. Cities appear as they pass acceptance. The previous database is archived read-only and kept.

## 12. Admin console

A private SvelteKit app at `/admin/`, server-rendered, reading the database through the console role and acting only through console functions.

| section | shows | actions |
| --- | --- | --- |
| Home | Running workers, what needs an editor (escalations, failed audits, reports, stalled tasks), readiness per city | |
| Cities | Per city: research coverage, items by state, measured accuracy, open tasks | queue research, writing, or translation tasks |
| Places | Search and filters; a page per place with every item, its revisions, claims, evidence passages, checks, and history | flag, retire, mark a claim wrong |
| Checks | Escalations waiting, audit batches and results, measured accuracy per task type and model | decide an escalation, plan an audit |
| Tasks | Every task by type and state, leases, attempts | release a lease, cancel, requeue |
| Runs | Every run, its model, output, verdicts, and audits | end a stalled run |
| Publish | What the next publish contains, what's held back and why, versions with diffs | check, publish, roll back |
| Reports, Demand, Map | Reader reports, empty areas viewed, coverage map | |
| Settings | Thresholds, model routing, lease lengths, rulebook version | change settings |

Design: one component set shared with the website, one color scale for states, paged and searchable lists, a page with its own link for every place, item, task, and run, keyboard and screen reader access, dark mode, plain wording.

Sign-in: editor accounts with scrypt-hashed passwords and server-side sessions. Every action is logged with the account.

## 13. Website

A public SvelteKit site, prerendered from the published output and served by nginx.

- Pages for every city, neighborhood, place, tag, and trail, each with a stable link and a title and description search engines can use.
- A map view, a browse view, and search, in the app's design language.
- The same content as the app, with sources and claims visible and a way to report a problem.
- Accessible (keyboard, screen readers, contrast), fast on slow connections, readable without JavaScript.
- English and Simplified Chinese interface and content.

## 14. Security

| role | can |
| --- | --- |
| `psst_platform_admin` | owns the schema; runs migrations |
| `psst_platform_system` | run system jobs: write snapshots, tool checks, place lookups, evaluations, audit plans |
| `psst_platform_worker` | read content and evidence; start and end its runs; lease and submit tasks; nothing else |
| `psst_platform_publisher` | read accepted and published content; record publications |
| `psst_platform_console` | read everything; call editor action functions for a signed-in account |
| `psst_platform_api` | file reader reports and demand counts |

- Every write goes through a `SECURITY DEFINER` function that checks the caller's run token and records the run; a client can't choose who it is. Table privileges beyond `SELECT` are granted to no login role.
- Secrets live in environment files on the server and editors' machines, never in the repository.
- The database and the fetch service listen only on the server; the CLI reaches both through an SSH tunnel. The fetch service reads only public internet addresses.
- The console requires sign-in, a same-site origin, and CSRF protection; nginx sends HSTS, a content security policy, and no-referrer.
- Backups: a nightly compressed dump plus a sorted text export to the private backup repository, with a weekly restore test against the latest backup.

## 15. Environments, testing, and operations

- **Local:** a PostGIS 14 database in Docker.
- **Test:** every test session creates a fresh database from the migrations in a throwaway PostGIS container and drops it afterward. Fixtures are small invented records. The test harness refuses any database that is not a local `psst_test_` database.
- **Production:** the server, as for the previous system.
- **CI:** GitHub Actions on every push: Python tests against a PostGIS service container, type checks (mypy, svelte-check), linting, and the web builds.
- **Deploys:** from a pushed commit only; the deploy script refuses a dirty working tree or an unpushed commit.
- **Migrations:** numbered, never edited after they are applied, additive where possible.
- **Monitoring:** a health page in the console (database, fetch service, system worker, backups, last publish, link check).

## 16. Repository layout

```
psst-platform/
  rules/              the rulebook (YAML)
  prompts/            one prompt per task type
  format/v2/          JSON schemas of the published output
  psst/
    core/             config, database access, ids, text normalization, HTTP
    rules/            rulebook loading and writing checks
    evidence/         fetching, snapshots, passage matching
    checks/           tool checks, evaluation, audits
    tasks/            task types, leasing, task files, submit handlers
    places/           coordinates, areas, names, leads, research cells
    publish/          output builder, staging, acceptance, promotion
    services/         the fetch service and the system worker
    cli/              one module per command group
  db/migrations/      the schema, from 0001
  web/
    ui/               shared components and design tokens
    console/          admin console (SvelteKit)
    site/             public website (SvelteKit)
  server/             nginx, services, backups, deploy
  tests/
  docs/
```

## 17. Moving from the previous system

1. **Coverage checklist:** every previous place becomes a lead with its Wikidata id, OSM element, names, coordinate, and previous ids. Previous stories, guides, and photos are not read or copied.
2. **Place identity:** when a researched place is the same Wikidata item or OSM element as a previous place, it keeps that place's `pl_` id, and the previous `areaId/spotId` ids map to it in `place_identity`.
3. **Reference data:** boundaries, tags, and demand counts are copied as they are; they are not curated content. Research cells are planned again.
4. **History:** the previous database is left untouched, then archived read-only after the switch.
5. **Switch:** the first publish that replaces the live content (section 11.3).

## 18. Settled decisions

1. **Thresholds:** audit thresholds of 1 error in 50 for stories and trails, 1 in 30 for guides, photos, and translations. Editors change them in Settings.
2. **Model routing defaults:** as in section 8.1: Haiku 5.5 for claim, item, translation, and photo checks and guide writing; Sonnet 5.5 for research, story writing, escalations, audits, and translation. Changed only on measured rates.
3. **Order of cities:** London, then Shanghai, Hong Kong, and Kuala Lumpur. Shanghai moves up from fourth to second because the bilingual work it needs is the hardest to get right and benefits from being proven early.
4. **Console accounts:** one editor account now; more can be added with the same command.
5. **Hosting the website:** the current server behind nginx, with a CDN later if traffic needs it.

## 19. Milestones

Each milestone ends with its tests passing and a short report in [progress.md](progress.md).

| milestone | contents | done when |
| --- | --- | --- |
| M1 Foundation | Repository layout, rulebook, schema and lifecycle functions, roles, test database, CI | Lifecycle rules proven by tests, including the ones that must be refused |
| M2 Evidence | Fetch service and snapshots, claims and evidence, tool checks | A sample story with a wrong year or a missing passage is refused by tools alone |
| M3 Tasks | Task queue and leases, task types, prompts, claim and item checks, escalation, audits | Two workers in parallel never collide; an audit failure reopens a batch |
| M4 Publishing | Output builder in format 2, staging, acceptance, promotion, rollback, diffs | A city publishes from the new database to staging and checks out |
| M5 Console | The admin console, sign-in, editor actions | An editor can run the whole workflow from the console |
| M6 Server | The new database, services, and nginx site on the server; reference data and the coverage checklist loaded | Workers run against the server |
| M7 Content | Research and writing city by city through the task system | Each city passes its audits; London goes live with approval |
| M8 Website | The public website | City, place, and trail pages live, accessible, indexed |

The iOS app's redesign follows M8 and uses format 3.
