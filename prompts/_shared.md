## What a claim must state

Every name, date, number, place, or other specific detail in a story, guide, or trail must be stated by one of its
claims. A plain synonym of a claim's words counts as stated ("tube station" for a London Underground station, "church"
for a parish church); a new fact, quality, cause, purpose, extent, or time does not. The one exception is the place's own record in `data.place`: its name, local name, neighborhood, district,
and city were set by the tools from Wikidata and boundary data, so they may be used without a claim.
In `look`, the directions for where to stand ("across the street", "from the corner", "opposite the church") guide
the reader and need no claim; what the reader is told they will see does.

## Returning your result

- Write the result as JSON that matches `result_schema` in the task file, and nothing else, to a file.
- Submit it: `uv run psst task submit <task file> <result file>`. It checks the result first and tells you what to fix.
- If you can't do the task properly (a source won't load, the task is wrong), give it back with the reason:
  `uv run psst task return <task file> --problem "<what went wrong>"`. Never submit a guess.
- Notes are one or two plain sentences saying what you checked and what you found. US English, no dashes, no
  exclamation marks, no filler.
