# Revise

The checks sent this piece back. You get the current text, its claims with their passages, the problems found, and
the notes the checks gave. Write a new revision that fixes every problem.

- Fix the cause. If a claim isn't supported, find a source that supports it (`uv run psst fetch`) or cut the claim
  and everything in the text that depends on it. Never soften the wording just to get past a check.
- If what's left no longer passes the "so what" test in `docs/content.md`, give the task back and say so.
- Keep what was right. The new revision is complete: every field and every claim, not only what changed.
- For a translation, translate again from the English revision named in `translation_of`.

The result follows `result_schema`; its `reason` says what you changed and why, in a sentence or two.
