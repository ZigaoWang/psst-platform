# Progress

Where the build stands. Updated before every milestone and whenever the plan changes, so work can resume from this file alone.

## Done

- Content standard ([content.md](content.md)), design version 2 ([design.md](design.md)), [decisions.md](decisions.md).
- M1 Foundation: schema (`db/migrations/0001` to `0005`), lifecycle functions, roles and grants, rulebook (`rules/`), `psst` command, throwaway test database, CI.
- M2 Evidence: text normalization and quote matching (`psst/core/text.py`), source reading (`psst/evidence/`), the fetch service (`psst/services/fetch_service.py`, the only writer of snapshots), tool checks (`psst/checks/tools.py`) and their runner, `psst fetch` and `psst run`.

## Next

M3 Tasks: task queue and leases, task types and their inputs and results, prompts, claim and item checks, escalation, audits.

## Open issues

None.

## How to resume

1. Read docs/design.md, docs/content.md, docs/decisions.md, and this file.
2. Start Docker; the tests start a throwaway PostGIS container (`uv run pytest`).
