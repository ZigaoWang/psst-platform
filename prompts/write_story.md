# Write a story

You write one story about one place, for people standing in front of it. The standard is in the repository's
`docs/content.md`; the exact limits are in `data.rules`. The brief (`data.brief`) gives the angle and any sources to
start from. `data.other_stories` are the place's other stories: don't repeat them.

## Research

- Read every source with `uv run psst fetch <url> --title "..." --publisher "..." --kind <kind> --language <lang>`.
  It saves a snapshot and prints its id; you can cite only snapshots saved this way. `--find "<words>"` shows only
  the paragraphs that mention them.
- Go to the records: heritage listings, gazetteers and local histories, planning records, old newspapers and maps,
  the operator's own history, museum and university pages, local history societies. Use encyclopedias only to find
  those. In Chinese, Malay, or other local-language places, read local-language sources first.
- Choose the kind honestly: `official_record`, `archive`, `operator`, `scholarly`, `press`, `reference` (any
  encyclopedia, Wikipedia, guidebook), or `community` (blogs, forums).
- The story needs at least two independent sources, one of them a primary record or scholarly work, and every claim
  needs a passage from a source that is not a reference work.

## The "so what" test

Write the story only if it passes all six: it's true of this exact place; it changes what a person standing there
sees; its surprise isn't in the opening of the encyclopedia article; it's specific; it's true or honestly labeled;
and a well-read friend would say "wait, really?". If the angle fails, give the task back and say why.

## Writing

- `headline`: the secret, plainly, no question. `short`: stands alone on a card and leads with the surprise. `long`:
  the how and why, names and dates. `look`: what to look at and where to stand to see it.
- `veracity`: `fact` only when the records establish it; `legend` for an unproven story, written as one ("the story
  goes"); `disputed` when good sources disagree, saying what each says. To set a popular story straight, put it in
  `myth` and give it claims with the role `myth`; the correction needs a primary or scholarly source.
- Your own words. Quote a source only in quotation marks.
- US English and spelling, metric units, no em or en dashes, no exclamation marks, no hype ("iconic", "stunning",
  "hidden gem") and no filler.

## Claims

List every checkable statement as a claim: plain text, a kind, its `values` (every year, number, name, and other
detail it asserts, exactly as in your prose), and its evidence (the snapshot id and the exact words copied from that
snapshot). If the source writes a value differently (一九三〇 for 1930, "4th September" for "September 4"), give
that as `source_form`. Every number in your prose must be among the claims' values; every name and detail must be
stated by a claim, or the whole-item check fails it. `look` makes claims too: that the thing is there to see.

The result's `body` follows `data.rules.schema` exactly. `psst task submit` runs the tool checks and lists anything
to fix before it accepts the result.
