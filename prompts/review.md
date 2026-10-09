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

- `good`: one physical thing, a real surprise in the first sentence, specific (names, numbers, a detail you can
  check on the spot), told plainly, ending on the payoff, and true to its sources. A reader standing there would
  show it to a friend.
- `weak`: true and worth something, but one fixable thing keeps it from good: background before the surprise, an
  ending that drifts into speculation or an unanswered question, a tangent, a look at nothing visible, a claim that
  contradicts another, thin sourcing a second source would fix. Your reason names that one thing so the revision can
  fix exactly it.
- `bad`: not a story, or not worth fixing: the surprise is already in the encyclopedia's first paragraph, it is a
  statistic or a list of facts, it is true of every place of its kind, it says more than its sources and can't be
  rescued, or there is nothing to stand in front of.

Mark bad or weak whatever the facts, when:
- a sentence is repeated, or two sentences say the same thing, anywhere in the item;
- any sentence doesn't read cleanly aloud;
- a guide's About restates the encyclopedia's first sentence in other words;
- the prose says anything a claim doesn't state, or says it more strongly.

Each reason is one sentence naming the specific thing, the way the editor's reasons do. Your `notes` say in a
sentence or two what the batch did well and what it did badly most often.
