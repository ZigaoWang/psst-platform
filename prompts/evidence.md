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

A story rests on a primary record or a scholarly source: either two independent sources with one of them such a
record, or, for a smaller story, the official record alone (a heritage list entry, say). Wikipedia alone never counts,
so a fact only Wikipedia states is left out. When the sources say only what the place is and how it is built, with no
surprise a reader would stop for, set `"story": false`: the place gets a guide and no story, and that is a good
outcome, better than a forced story. If the passages don't hold even that, answer `{"skip": "<the reason,
specific>"}`. Otherwise answer `{"story": true or false, "place": {...}, "facts": [...]}`, where `place` is the new
place (`name`; `kind`, one of transit, crossing, street, building, worship, memorial, green, water, or culture;
`size`, one of small, medium, or large; `ordinary`, true when a visitor would never look it up; and its `wikidata` or
`osm`, given in `data.lead`) or `{"existing": <id>, "ordinary": ...}` for a place the platform already has.
