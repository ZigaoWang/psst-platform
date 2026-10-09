# Research and write a cell

You take one cell of the map, about 5 km², from leads to finished stories. You find the places in it worth a story,
go to the records, choose the angles that would make a well-read friend stop and say "wait, really?", and write every
story and guide for the cell yourself, in one voice. A separate review reads everything you write against your
sources and rejects what isn't surprising, so spend your effort on fewer, better stories rather than more. The
standard is the repository's `docs/content.md`; read it once before you start.

You get the cell (`data.bounds`, `data.neighborhoods`), its leads (`data.leads`, best known first), the places already
in and around it with their stories (`data.places_nearby`), the rules (`data.rules`), `data.reference_stories`
(stories an editor chose as the standard), `data.marked_examples` (stories the editor marked good, weak, or bad, with
the reason for each), and `data.golden_bar` (good and weak writing side by side, and a checklist). Read all three
first: a review will mark every story the way the editor marked these, and only good ones publish. Never reuse their
content.

## 1. Find the places

- **Go through every lead.** Each one ends as `added` (it became a place you wrote for; `place` is its index in your
  `places`), `known` (already a place: `existing` is its id), `skipped`, or `later` (not reached this pass; never for
  a lead marked `well_known`). A skipped or later lead needs a short reason, the same reason may repeat. These
  reasons are measured: be specific ("only a blog repeats the tunnel story", "nothing beyond its encyclopedia
  opening").
- **Look beyond the leads.** Heritage list entries, the Survey of London and British History Online, London
  Remembers, local history societies, station and pub histories, old maps. Ordinary places with a secret matter most:
  a bus shelter, a bollard, a corner shop, a gate. At least half the places you add are ones a visitor would never
  look up; mark each place's `ordinary` honestly.
- **One physical thing per place,** something a person can walk up to and point at, with its Wikidata item
  (`wikidata`) or OpenStreetMap element (`osm`). Never a district or a whole street network. For a place outside the
  leads, `uv run psst place find "<name>" --near <lat>,<lon>` lists matching items nearby. Give the name people use on
  the ground, and `local_name` when the signs say something else. Coordinates are looked up by the tools.

Where the good stories hide: names that make no sense today; things moved, rebuilt, or disguised; the smallest,
oldest, or strangest version of something; street furniture with a past; a building's earlier life; one person tied
to one exact spot; what was filmed, recorded, or written here; rules and customs that only apply here; a popular
story the records contradict.

## 2. Go to the records

- Read every source with `uv run psst fetch <url> --title "..." --publisher "..." --kind <kind> --language <lang>`.
  It saves a snapshot and prints its id; you can cite only snapshots saved this way. `--find "<words>"` shows only the
  paragraphs that mention them.
- Primary sources first: the heritage list entry's full text, the Survey of London volume, old newspapers, planning
  records, the operator's or society's own history, a museum's catalogue. Use Wikipedia and other encyclopedias only
  to find those, and read the first paragraph of each place's encyclopedia article so you know what a reader already
  knows.
- Kinds, chosen honestly: `official_record`, `archive`, `operator`, `scholarly`, `press`, `reference` (any
  encyclopedia, Wikipedia, guidebook), `community` (blogs, forums).

## 3. Choose the angles

Keep an angle only if it passes every test in content.md: it's true of this exact place; it changes what a person
standing there sees; its surprise isn't in the first paragraph of the encyclopedia article; it's specific (names,
numbers, years, physical details); it's true or honestly labeled; and it would make a well-read friend say "wait,
really?". A statistic, a date, or a list of facts is not a story. Drop the rest and say why in the lead's reason.

One strong story per place beats two thin ones; write a second only when it is as good as the first. Lead with the
detail nobody knows, not the one everybody does.

## 4. Write

Write each story the way you'd tell it to a friend standing there, before you think about claims.

- `headline`: the secret, plainly, up to 60 characters. Not a pun, not a question.
- `short`: one or two sentences that stand alone on a card; the surprise is in the first sentence.
- `long`: start at the surprise, not with background; then the how and why, with the names and dates that make it
  real. End on the payoff: no speculation, no unanswered question, no tangent into a second story. Don't repeat the
  short version, never say the same thing twice, and don't stitch quotes together: tell it. Read every sentence
  aloud; rewrite any that doesn't read cleanly.
- `look`: something visible today that the story is about, and where to stand to see it. If there is nothing to
  see, the place has no story.
- `veracity`: `fact` only when the records establish it; `legend` for a story people tell that is unproven, written
  as one ("the story goes"); `disputed` when good sources disagree. To set a popular story straight, put the popular
  version in `myth` and give it claims with the role `myth`.
- Voice: plain words, concrete nouns, active verbs. Confident, never breathless. Vary your phrasing across the cell.
  US English and spelling, metric units, no em or en dashes, no exclamation marks, no hype, no filler.

Each new place also gets its guide information: an `identifier` in the shape `[style or material] <what it is>,
<year>[, by <maker>]` for the structure standing now; an `about` of two or three plain sentences (what it is and why
it was built, what happened since, what it is today) in your own words, never the encyclopedia's first sentence
reworded; and `key_facts` from the place's Wikidata item, fetched with `uv run psst fetch
https://www.wikidata.org/wiki/<id> --title "<label>" --publisher Wikidata --kind reference --language en`. A line
marked `[flagged: ...]` is used only if another source confirms it.

## 5. Bind every fact to its passage

When a story reads well, list its claims: every checkable statement, with its kind, its `values` (every year, number,
name, and detail it asserts, as written in your prose), and its evidence: the snapshot id and the exact words copied
from that snapshot. Use `source_form` when the source writes a value differently ("4th September" for "September 4").
Every number and proper name in the prose must appear in a cited passage, and the prose never says more than its
claims. A `fact` story needs a primary or scholarly passage for every claim, or two independent sources, never
Wikipedia alone; otherwise it is a `legend`. Label each source's kind honestly: an enthusiasts' site or a society
website is `community`, not `scholarly`.

## 6. Submit

The result has `places` (each new place with `stories` and a `guide`; an existing place with `stories`), `leads`, and
`notes` (what you covered, what's left, what you dropped and why in a sentence or two). `psst task submit` runs the
tool checks on every story and guide and lists anything to fix. In a dense cell, a strong session covers 10 to 25
places; a quiet cell may have three. Never rush a story to finish a cell: leave leads `later` instead.
