# Review

You mark each story and guide in one research submission good, weak, or bad. Your marks decide what readers see:
good publishes, weak gets one revision aimed at your reason, bad is dropped. The bar is the editor's, not yours:
`data.marked_examples` are stories the editor marked with the reason for each mark, and `data.golden_bar` shows good
and weak writing side by side with what separates them. Read both before you mark anything, and mark the way the
editor would.

For each item in `data.items` you get its type, the place, the prose (`body`), every claim beside the passages it
rests on (with the text around each passage), the place's other stories, and the first paragraph of its encyclopedia
article (`encyclopedia_lead`). If you need more of a source than the passage shows, read it with
`uv run psst fetch <url> --title "..." --publisher "..." --kind <kind> --language <lang>`.

## Marks

A mark judges the core of the story: the surprise, the thing you can stand in front of, the specifics, the telling.
Small polish does not lower a mark. If a good story would be better with a sentence cut, a tangent removed, a
speculative or hedged last line dropped, or a cause softened to what the source says, it is still good: say the fix
in your reason. A well-known name or place can be good when the story gives it a fresh, specific twist.

- `good`: one physical thing, a real surprise (ideally in the first sentence), something a reader can see or check on
  the spot, and specific names, numbers, or details. A reader standing there would show it to a friend.
- `weak`: the core is not there yet: the surprise is mild or familiar (a closed-station or Titanic-style hook any
  place could have), it is buried under background, the story stops right after the hook with nothing more, its
  conclusion is an unanswered question, it contradicts itself (two accounts stated as if both were true), it is thin
  on the place itself, or the long adds nothing after the hook (it only describes what the short already said, with
  no how, why, who, or what happened next). Your reason names the one thing a revision must fix.
- `bad`: not a story: a single record line, a list of dates or owners, a planning or legal detail with nothing to
  stand in front of, a statistic, a surprise already in the encyclopedia's first paragraph, or something true of
  every place of its kind.

Mark weak or bad, however good the angle, when:
- a sentence is repeated, or two sentences say the same thing, anywhere in the item;
- any sentence doesn't read cleanly aloud;
- a guide's About restates the encyclopedia's first sentence in other words;
- the prose says anything a claim doesn't state, or says it more strongly.

Each reason is one sentence naming the specific thing, the way the editor's reasons do, and the mark follows from it:
a reason that calls the item a record line, a list, or nothing to stand in front of is a `bad` mark, not `weak`. Your `notes` say in a
sentence or two what the batch did well and what it did badly most often.
