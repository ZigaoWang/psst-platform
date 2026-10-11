# Write the guides for places from their official records

You get the official records for listed things in one cell (`data.leads`, `data.passages`), often several on one
street. Sort them into places and write each place's guide in one answer.

Places: listed houses of one terrace or row, built alike, are one place with one guide covering their numbers. A
listed thing that stands apart (a shop, an office block, a church, a statue) is a place of its own, and so is a house
whose own record says something specific about it (a named person who lived or worked there, an event, something
unusual about how it was built or used). Every guide names one thing a passer-by can see that its record states: a
date stone, an inscription, a sign, a carving, an odd detail. A listing whose record gives nothing like that has no pin
of its own: put it, with any others on the street like it, in one place for the street, named "Listed buildings on
<street>", whose guide covers them together and names the street's visible details. Every lead belongs to exactly one
place.

For each place give `leads` (its lead ids) and:
- `place`: `name` (for houses, the numbers and the street, such as "1 to 14 Northampton Park"), `kind` (building for
  houses; otherwise transit, crossing, street, building, worship, memorial, green, water, or culture), `size` (small,
  medium, or large), and `ordinary` (true when a visitor would never look it up).
- `facts`: each with `id` (f1, f2, ... across the whole answer), `text` (one plain sentence of your own), `kind` (date,
  name, number, place, event, or attribute), `values` (leave empty; they are taken from your quotes), and
  `evidence`: the snapshot id and the exact words copied from its passage, long enough to hold every name, date, and
  number the fact states. A fact says nothing its quotes don't. At least two for each place.
- `guide`: `body` with `identifier` (`[style or material] <what it is>, <year>[, by <maker>]`, for what stands now,
  never its listing or grade; for houses name them as a group, such as "Stock brick terrace houses, 1840s"), `about`
  (two or three sentences, never four, in your own words: what it is, when and by whom it was built, and what it is
  today when a fact says so; never its listing, grade, or listing date), and `key_facts` (empty); plus `facts`, the
  ids it rests on. Plain US English, no dashes, no exclamation marks, no judgments such as fine, famous, or handsome.
- `angle`: true when its record says something a passer-by would stop for, as above; false when it only describes how
  the place looks and is built. A record that only describes is still a good guide.

Answer only `{"places": [{"leads": [...], "angle": ..., "place": {...}, "facts": [...], "guide": {...}}]}`. Leave a
lead out only when its record gives no date, builder, or description of the thing at all, and say why in
`{"skipped": [{"lead": ..., "reason": ...}]}` beside `places`.
