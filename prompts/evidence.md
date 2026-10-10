# Pick the evidence for one place

You pick the facts for one place from passages already read for it (`data.passages`: each is part of a page, with its
snapshot id and what kind of source it is). A separate step writes the story and guide from your facts alone, so the
facts must cover what a good story needs: the surprise, what a reader can see from where they stand (or its marker),
and the specifics. Then what the guide needs: what the place is, when and by whom it was made, and what it is today.

Use only these passages; there is nothing else to read. For each fact give `id` (f1, f2, ...), `text` (the fact in
one plain sentence of your own, never in the source's phrasing), `kind` (date, name, number, place, event, or
attribute), `values` (leave empty; they are taken from your quotes), and `evidence`: the snapshot id and the exact
words copied from that passage, long enough to hold every name, date, and number the fact states. Copy them character
for character; a quote that isn't in its passage is thrown out.

Pick first the facts a story would rest on: what happened there, who made it and why, what it was for, and any
detail a passer-by would miss; then what the guide needs. A fact only Wikipedia states is left out, since every fact
needs a record, scholarly, or other non-reference source. If the passages don't hold three such facts, answer
`{"skip": "<the reason, specific>"}`. Otherwise answer `{"place": {...}, "facts": [...]}`, where `place` is the new
place (`name`; `kind`, one of transit, crossing, street, building, worship, memorial, green, water, or culture;
`size`, one of small, medium, or large; `ordinary`, true when a visitor would never look it up; and its `wikidata` or
`osm`, given in `data.lead`) or `{"existing": <id>, "ordinary": ...}` for a place the platform already has.
