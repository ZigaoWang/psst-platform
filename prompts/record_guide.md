# Write the guide for a place from its official records

You get the official records for one place (`data.leads`, `data.passages`): a single listed thing, or listed houses of
one terrace or street, which become one place with one guide covering their numbers. In one answer, pick the facts
and write the guide from them.

Facts: for each give `id` (f1, f2, ...), `text` (one plain sentence of your own), `kind` (date, name, number, place,
event, or attribute), `values` (leave empty; they are taken from your quotes), and `evidence`: the snapshot id and the
exact words copied from its passage, long enough to hold every name, date, and number the fact states. A fact says
nothing its quotes don't. Give at least two.

The guide: `body` with `identifier` (`[style or material] <what it is>, <year>[, by <maker>]`, for what stands now,
never its listing or grade; for houses, name them as a group, such as "Stock brick terrace houses, 1840s"), `about`
(two or three plain sentences in your own words: what it is, when and by whom it was built, and what it is today when
a fact says so; never its listing, grade, or listing date), and `key_facts` (empty), plus `facts`, the ids it rests
on. Plain US English, no dashes, no exclamation marks, no judgments such as fine or handsome.

The place: `name` (for houses, the numbers and the street, such as "1 to 14 Northampton Park"), `kind` (building for
houses; otherwise transit, crossing, street, building, worship, memorial, green, water, or culture), `size` (small,
medium, or large), and `ordinary` (true when a visitor would never look it up).

`angle`: true when a record says something a passer-by would stop for (a named person who lived or worked there, an
event, something unusual about how it was built or used), false when it only describes how the place looks and is
built. `specific`: for houses, the lead ids of single houses whose own record says something specific about that house;
leave them out of the guide and its facts, since each gets its own place. Empty for a single listed thing.

Answer only `{"angle": ..., "specific": [...], "place": {...}, "facts": [...], "guide": {"body": {...}, "facts": [...]}}`.
