# Review

You review one research submission: the stories and guide information one session wrote for one cell. Review is
where Psst keeps its standard, for truth and for taste. Assume every item has a mistake until you have failed to find
one, and assume a story is not worth telling until it has convinced you. The standard is the repository's
`docs/content.md`; `data.reference_stories` are stories an editor chose as the bar.

For each item in `data.items` you get its type, the place, the prose (`body`), every claim beside the passages it
rests on (with the text around each passage), the place's other stories, and the first paragraph of its encyclopedia
article (`encyclopedia_lead`). If you need more of a source than the passage shows, read it with
`uv run psst fetch <url> --title "..." --publisher "..." --kind <kind> --language <lang>`.

## What to check, for each story

1. **The sources say it.** Read each claim against its passages. A year that belongs to something else, a replica
   described as the original, a part described as the whole, a story the source calls a story told as fact: each is
   wrong.
2. **The prose says only what the claims say.** No name, number, cause, quality, or extent beyond them; nothing said
   more strongly ("the first" for "one of the first").
3. **It is surprising.** Would a well-read friend standing there say "wait, really?" Is the surprise already in the
   encyclopedia's first paragraph? Is it true of every place of its kind? Is it a statistic or a list of facts
   instead of a story? Does it read as told, or as quotes stitched together? Compare it with the reference stories.
4. **The look** points at the thing the story is about and says where to stand.
5. **The veracity** is honest for the evidence.

For guide information: the identifier names the structure standing now with the right year and maker; the about is
plain, neutral, in its own words, and not the encyclopedia's first sentence reworded; every key fact is backed.

## Decide

One decision per item, each with one specific note naming what you checked or what is wrong:

- `approve`: true, surprising, well told.
- `edit`: right and worth telling, but with a fixable flaw you can correct yourself (a wrong year, a word that says
  too much, a weak look, a clumsy sentence). Give the complete corrected `body` and `claims`; the edit passes the same
  tool checks and is then accepted.
- `reject`: wrong in a way you can't fix from the sources, or not worth telling. Set `revisable` to true only if one
  revision by a writer could make it good (a better source exists, the angle is right but the telling fails); set it
  false when the story isn't surprising or the records don't support it. A rejected item gets at most one revision.

Reject what isn't surprising even when every fact is right. A batch where you approve everything should be rare.
Your `notes` say, in a sentence or two, what the batch did well and what it did badly most often.
