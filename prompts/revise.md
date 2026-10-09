# Revise

Review rejected this piece but judged that one revision could make it good, or an audit found an error in it. You get
the current text, its claims with their passages, and the problems found. This is its only revision: if it is
rejected again it is dropped.

- Fix the cause. If a claim isn't supported, find a source that supports it (`uv run psst fetch`) or cut the claim
  and everything that depends on it. If the telling was the problem, tell it better: plainly, as you would to a
  friend standing there. Never soften wording just to get past a check.
- If what's left can't pass the "so what" test in `docs/content.md`, give the task back and say so.
- The new revision is complete: every field and every claim, not only what changed.
- For a translation, translate again from the English revision named in `translation_of`.

The result follows `result_schema`; its `reason` says what you changed and why, in a sentence or two.
