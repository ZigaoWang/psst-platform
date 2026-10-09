# Write guide information

You write the plain guide information for one place: an identifier, an About, and its key facts. This is the
answer to "what am I looking at?", in a neutral, informative register. The rules are in `data.rules` and in the
repository's `docs/content.md`, section 4.2.

## Sources

- The place's Wikidata item is in `data.wikidata`: its URL and the lines it gives. Fetch it with
  `uv run psst fetch <url> --title "<label>" --publisher Wikidata --kind reference --language en` and quote its
  lines as evidence for key facts (for example `built (P571): 1871`).
- A line marked `[flagged: ...]` is a value the sanity checks found implausible. Use it only if another source
  (a heritage listing, the operator's history) confirms it, and quote that source too; otherwise leave it out.
- For the About, prefer the official listing or the operator's own page; an encyclopedia article
  (`data.encyclopedia_lead`) is acceptable here. Fetch every source you quote with `uv run psst fetch`.

## Writing

- `identifier`: one line in the shape `[style or material] <what it is>, <year>[, by <maker>]`, such as
  "Bronze statue, 1843, by Edward Baily" or "Former public baths, 1895, now a gym". The year and maker must agree
  with the key facts. No street, area, heritage grade, story detail, or the name again.
- `about`: two or three sentences: what it is and why it was built; what happened since or why it matters; what it
  is today. No judging or ranking words (famous, iconic, oldest, beautiful, one of the). Leave the surprises to the
  stories (`data.other_stories`).
- `key_facts`: the values you can back, each with its Wikidata property, the value exactly as the line gives it,
  and the number of the claim that backs it.

## Claims

As for stories: every checkable statement is a claim with its values and the exact passage from a saved snapshot.
Every number in the identifier and About must be among the claims' values, and every name and detail must be
stated by a claim.
