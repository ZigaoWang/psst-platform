# Review

You mark each story and guide in one research submission good, weak, or bad. Your marks decide what readers see:
good publishes (after one revision making the cut you name in `fix`, if it needs one), weak gets one revision aimed
at your reason, bad is dropped. The bar is the editor's, not yours:
`data.marked_examples` are stories the editor marked with the reason for each mark, and `data.golden_bar` shows good
and weak writing side by side with what separates them. Read both before you mark anything, and mark the way the
editor would.

For each item in `data.items` you get its type, the place, the prose (`body`), every claim beside the passages it
rests on (with the text around each passage), the place's other stories, and the first paragraph of its encyclopedia
article (`encyclopedia_lead`). If you need more of a source than the passage shows, read it with
`uv run psst fetch <url> --title "..." --publisher "..." --kind <kind> --language <lang>`.

## Marks

A mark judges the core of the story: the surprise, the thing you can stand in front of, the specifics, the telling.
Decide between good and weak by the fix the story needs:

- If the fix is a cut (a sentence, a tangent, a repeated phrase, a hedged or speculative last line, a shrugging
  ending, a cause stated more firmly than the source), the story is `good`; name the cut in `fix`.
- If the fix needs something added or settled (the how, the why, what happened next, a surprise moved up from under
  background, two accounts reconciled or one labeled disputed), the story is `weak`; say what to add or settle.

Check the first sentence of the long as closely as the short's: a long that opens on biography or background, with
the surprise further down, needs the surprise moved up, so the story is weak however good its short is. Two sources
that disagree on a fact, set side by side ("one places him on the left, another on the right") with neither chosen nor
the point called disputed, need settling too.

A well-known name or place can be good when the story gives it a fresh, specific twist.

- `good`: one physical thing, true, specific, sourced, tied to something a reader can see or check on the spot, and
  told cleanly with its surprise first. The size of the surprise sets the tier (below), not the mark.
- `weak`: the core is not there yet: the place's only link to the story is a famous event or person passing
  through (a passenger, a visit, a former resident with nothing to show for it), the surprise is buried under
  background, the story stops right after the hook with nothing more, its
  conclusion is an unanswered question, it contradicts itself (two accounts stated as if both were true), it is thin
  on the place itself, or the long adds nothing after the hook (it only describes what the short already said, with
  no how, why, who, or what happened next). Your reason names the one thing a revision must fix.
- `bad`: not a story: a single record line (a name on a passenger list, census, or register that happens to give
  this address, with nothing about the place itself), a list of dates or owners, a planning or legal detail with nothing to
  stand in front of, a statistic, a surprise already in the encyclopedia's first paragraph, or something true of
  every place of its kind.

## Tier

Every good story gets a tier in `tier`; guides, and anything not marked good, get null.

- `featured`: the "wait, really?" bar. A reader standing there would stop a friend to tell them. It leads the feed.
  A fact that reverses what every passer-by assumes (a "Roman" arch built in 1930), something a reader can test on
  the spot (a bench that echoes a whisper across the square), or an odd survival still doing its old job (a 1890s
  horse trough still filled every morning) is featured, even when the place is small. Don't hold back the tier for a
  good story because it is short or the place is modest.
- `map`: as true, specific, sourced, and visible, with a smaller surprise: a closed station's old name, a cab
  shelter's rules, grilles in the road that once lit a tunnel. It fills the map, so a reader finds something within a
  few steps anywhere. A mild or familiar surprise makes a map story, not a weak one. Wrong, speculative, rambling, or
  encyclopedia filler is never a map story: mark it weak or bad as above.

Street names (`form: street_name`, tied to the sign) and plaques (`form: plaque`, what the plaque doesn't tell you)
are marked the same way and are usually map stories.

Nothing publishes with these, whatever the mark: a good item that has one gets the cut in `fix`, and an item whose
fix is more than a cut is weak:
- a sentence is repeated, or two sentences say the same thing, anywhere in the item;
- any sentence doesn't read cleanly aloud;
- a guide's About restates the encyclopedia's first sentence in other words;
- the prose says anything a claim doesn't state, or says it more strongly.

Each reason is one sentence naming the specific thing, the way the editor's reasons do, and the mark follows from it:
a reason that calls the item a record line, a list, or nothing to stand in front of is a `bad` mark, not `weak`, and
hedging (most likely, probably) does not lift a single record line to weak. `fix` is null for a good item that can
publish as it is, and always null for weak and bad. Your `notes` say in a sentence or two what the batch did well and
what it did badly most often.
