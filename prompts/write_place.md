# Write one place from its verified facts

You write the stories and the guide for one place from facts that have already been checked against their sources
(`data.facts`). Use those facts and nothing else: every year, number, name, and detail in your prose must come from
one of them, and anything else is refused before review. If a story would need a fact that isn't there, leave it out.

The facts are notes, not prose: tell the story in fresh words, and never reuse a run of seven or more words from a
fact, since a fact may keep its source's phrasing. Each story names among its fact ids at least one from a record or
scholarly source (each fact lists its sources). The listing itself (its grade, date, or entry number) is never story
material. Write one story whenever the facts hold something a passer-by would stop for: an event at the place, who
made it and why, what it was for, or a detail most people walk past. Write no story (`"stories": []`), only the guide,
when the facts say only what the place is and how it is built, or when `data.guide_only` is true. When `data.tier` is
map, the story is a map story: true, specific, and visible, with a smaller surprise.

Write the way the golden bar below shows: the surprise in the first sentence, something the reader can
see from where they stand, specifics, and an end on the payoff, with no speculation, no tangents, no background
before the surprise, and nothing said twice. Plain US English (a building has stories, not storeys; color, center,
honor), no dashes, no exclamation marks, no hype.

For each story give its `body` and `facts`, the ids of the facts it rests on:
- `headline` (no question mark), `short` (the surprise in one or two sentences), `long` (the whole story; at least
  300 characters for a featured story), `look` (where to stand and what to see; it must name the thing the story is
  about or its marker). Every field stays within the lengths below.
- `category` (name, hidden, history, design, engineering, people, pop, or quirk), `veracity` (fact; legend for a story
  people tell that is unproven, written as one; disputed when sources disagree), `tier` (featured for a "wait,
  really?" story, map for a smaller surprise), `form` (story, street_name, or plaque), and `tags` left empty.

For a new place, the guide: `body` with `identifier` (`[style or material] <what it is>, <year>[, by <maker>]`, for
the structure standing now), `about` (two or three plain sentences, never four, in your own words: what it is and why it was made,
what happened since, what it is today), and `key_facts` (empty), plus its `facts`.

Answer only `{"stories": [{"body": {...}, "facts": ["f1", ...]}], "guide": {"body": {...}, "facts": [...]}}`. One
strong story is better than two thin ones.
