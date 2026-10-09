# Worker runs

How content work is done through the task queue: who does what, the steps every run follows, and how an operator keeps the queue moving. The standard itself is [content.md](content.md); the machinery is [design.md](design.md), sections 7 and 8.

## Roles

Each task type is routed to one model (`routing.<type>` in the console's settings). A run only receives the task types routed to its model.

| Role | Task types | Model | Tasks per run |
|---|---|---|---|
| Researcher | `research_cell` | Haiku 5.5 | 3 |
| Story writer | `write_story` | Sonnet 5.5 | 4 |
| Guide writer | `write_guide` | Haiku 5.5 | 6 |
| Trail writer | `write_trail` | Sonnet 5.5 | 2 |
| Checker | `check_item`, `check_claims_a`, `check_claims_b`, `check_photo` | Haiku 5.5 | 12 |
| Reviser | `revise`, `escalate` | Sonnet 5.5 | 8 |
| Auditor | `audit` | Sonnet 5.5 | 10 |
| Translator | `translate` | Sonnet 5.5 | 6 |
| Translation checker | `check_translation` | Haiku 5.5 | 12 |
| Photo finder | `find_photos` | Haiku 5.5 | 10 |

## Every run

Commands run from the repository root, with the worker settings in `~/.config/psst-platform/env`.

1. Start the run once: `uv run psst run start --model <model id> --notes "<city> <role>"`. It prints a token; put `PSST_RUN_TOKEN=<token>` in front of every later command, since shell state does not carry over.
2. Take a task: `uv run psst task next --type <type> [--type <type>] --city <city>`. It writes the task file to `work/tasks/` and prints its path, or says nothing is waiting.
3. Read the task file. `prompt` is the instructions, `data` everything the task needs, `result_schema` the shape of the answer.
4. Write the result to `work/results/<task id>.json` and submit it: `uv run psst task submit <task file> <result file>`. It checks the result first and lists anything to fix; fix it and submit again. If it says the task is no longer yours, another check has already moved the item on: go to the next task.
5. If the task can't be done properly, give it back with the reason: `uv run psst task return <task file> --problem "<why>"`. It goes to a different run; after three returns it waits for an editor.
6. Stop at the run's task count or when nothing is waiting, then end the run: `uv run psst run end --notes "<one line>"`. Ending a run gives back any task it still holds.

Rules for every run:

- Write only under `work/`, and delete scratch files before ending. Never change the repository's code, rules, or prompts.
- Read every source with `uv run psst fetch <url> --title "..." --publisher "..." --kind <kind> --language <code> [--find "words"]`. Quotes are copied exactly from what it prints; nothing is quoted from memory or from a search summary.
- Never run a command that waits for input.
- Plain US English, no dashes, no exclamation marks, no hype, in notes as well as content.

## Role notes

**Researcher.** Go through every lead, famous ones included, and look for an angle beyond the first paragraph of the place's encyclopedia article. List a record (a listing, a survey, an old newspaper, an official history) among an angle's sources whenever one exists. At least half the places added are ones a visitor would never look up.

**Story writer.** Read content.md once. Find the records with a web search: heritage list entries, the Survey of London, the operator's own history, old newspapers, local history societies. In a `fact` story every claim needs a primary or scholarly passage, or two independent sources; otherwise it is a `legend`. Before submitting, read every sentence against the claims and cut any detail no claim states. If the angle doesn't hold up, or its surprise is already in the encyclopedia's opening and no better one has a record behind it, give the task back.

**Guide writer.** Fetch the Wikidata item (`data.wikidata.url`) and the official listing or the operator's page. For a Historic England listing use `https://historicengland.org.uk/listing/the-list/list-entry/<number>`. The identifier's year and maker belong to the structure standing now, not an earlier one or a reopening; leave out a Wikidata value the other sources contradict. Every word of detail in the identifier and About is stated by a claim.

**Checker.** Judge only from the task file. Look for the mismatch: a different year, event, or thing, a part described as the whole, a story told as fact. Each note names the detail compared.

**Reviser.** For an escalation, decide from the full snapshots and cite the words that settled it. For a revision, fix exactly what the problems name, then read the whole text once more against the claims so it doesn't come back a second time.

## Keeping the queue moving

An operator watches the queue (`uv run psst task queue --city <city>`, `/admin/tasks`, or each city page) and starts runs where work is waiting:

- Checks first: they unblock everything behind them. About one checker per 12 waiting checks.
- Revisions and escalations next, then writing, then research.
- When fewer than about ten research cells are queued for a city, queue more from its console page (most wanted first).
- Audits are planned by the system worker; start auditor runs when audit tasks appear.
- Publish from the console when the publish page shows content ready and no audit batch is failing. The first publish that replaces the app's live content needs explicit approval.
- Read each run's closing summary. A pattern of the same problem across runs (a check that fails for a reason the standard doesn't intend, a source that keeps refusing) is a fault in a prompt or a rule, to be fixed there rather than worked around in each task.
