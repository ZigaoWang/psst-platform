# Worker runs

How content work is done through the task queue: who does what, the steps every run follows, and how an operator keeps the queue moving. The standard itself is [content.md](content.md); the machinery is [design.md](design.md), sections 7 and 8.

## Roles

Each task type is routed to one model (`routing.<type>` in the console's settings). A run takes every type routed to its model unless `--type` narrows it.

| Role | Task types | Model | Tasks per run |
|---|---|---|---|
| Researcher | `research_cell` | Opus 5.5 on dense cells, Sonnet 5.5 elsewhere (`task queue` shows which) | 1 cell |
| Reviewer | `review` | Sonnet 5.5 | 2 |
| Reviser | `revise` | Sonnet 5.5 | 6 |
| Auditor | `audit` | Sonnet 5.5 | 10 |
| Trail writer | `write_trail` | Sonnet 5.5 | 2 |
| Translator | `translate` | Sonnet 5.5 | 6 |
| Translation and photo checker | `check_translation`, `check_photo` | Haiku 5.5 | 12 |
| Photo finder | `find_photos` | Haiku 5.5 | 10 |

## Every run

Commands run from the repository root, with the worker settings in `~/.config/psst-platform/env`.

1. Start the run once: `uv run psst run start --model <model id> --notes "<city> <role>"`. It prints a token; put `PSST_RUN_TOKEN=<token>` in front of every later command, since shell state does not carry over. The token is yours alone: one run per worker, never a token another run printed, never in a shared file. If you save it, name the file after your own run id (`work/<run id>.token`) and delete it at the end.
2. Take a task: `uv run psst task next --city <city>` (add `--type <type>` to take only that type). It writes the task file to `work/tasks/` and prints its path, or says nothing is waiting.
3. Read the task file. `prompt` is the instructions, `data` everything the task needs, `result_schema` the shape of the answer.
4. Write the result to `work/results/<task id>.json` and submit it: `uv run psst task submit <task file> <result file>`. It checks the result first and lists anything to fix; fix it and submit again. The reply says what happens next (a tool check, a review, acceptance, a revision); none of it needs anything more from this run. If it says the task is no longer yours, the item has already moved on: go to the next task.
5. If the task can't be done properly, give it back with the reason: `uv run psst task return <task file> --problem "<why>"`. It goes to a different run; after three returns it waits for an editor.
6. Stop at the run's task count or when nothing is waiting, then end the run: `uv run psst run end --notes "<one line>"`. Ending a run gives back any task it still holds.

Rules for every run:

- Write only under `work/`. Before ending, delete only the files this run created (its own task files, results, and scratch files); other runs working at the same time need theirs. Never change the repository's code, rules, or prompts.
- Read every source with `uv run psst fetch <url> --title "..." --publisher "..." --kind <kind> --language <code> [--find "words"]`. Quotes are copied exactly from what it prints; nothing is quoted from memory or from a search summary.
- Never run a command that waits for input.
- Plain US English, no dashes, no exclamation marks, no hype, in notes as well as content.

## Role notes

**Researcher.** Follow the task's prompt: one cell end to end, from leads to every story and guide, in one voice, with the reference stories as the bar. Primary sources first; drop what isn't surprising and say why. Submit each place with `uv run psst task place` as soon as it is finished; it renews the lease. A dense cell is a long session: keep going until the leads are done or left `later` with a reason, then submit the final result. If a session stops before that, nothing is lost but the place in hand: its lease runs out after 90 minutes, its run ends, and the next researcher continues the cell.

**Reviewer.** Read every item with its passages beside it and mark it good, weak, or bad the way the editor marked the examples in the task file. A good item that needs only a cut names the cut in `fix`; a weak one says what to add or settle; a bad one is not a story.

**Reviser.** This is the item's only revision. Fix exactly what the review or audit named; if the story can't be made worth telling, give the task back.

**Auditor.** Recheck a sampled item from the full snapshots. One error fails the batch, so be exact.

## Keeping the queue moving

An operator watches the queue (`uv run psst task queue --city <city>`, `/admin/tasks`, or each city page) and starts runs where work is waiting. The queue command lists the types no open run can take.

- Reviews and audits first: they unblock publishing. Then revisions, then research.
- When fewer than about ten research cells are queued for a city, queue more from its console page (most wanted first).
- Record each finished run's tokens: `uv run psst run tokens <run id> <tokens>`. Cost per published place is measured from them.
- Publish from the console when the publish page shows content ready. Publishing writes the platform's own production channel and website and leaves the app alone; pointing the app at the platform for the first time is a separate step that needs explicit approval.
- Read each run's closing summary. A pattern of the same problem across runs is a fault in a prompt or a rule, to be fixed there rather than worked around in each task.
