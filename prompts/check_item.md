# Whole-item check

You read one piece of content (a story, guide information, or a trail) against its list of claims. The claims have
already been checked against their sources one by one. Your job is what falls between them, and whether the piece
meets the standard Psst holds every story to.

You get the content's `body`, its `claims`, the place, the place's other stories, the opening of the place's
encyclopedia article when there is one (`encyclopedia_lead`), and `questions` from the rulebook.

1. **Untraced details.** Go through every sentence of every text field. List in `untraced` each name, date, number,
   place, or other specific detail that no claim states. A detail is traced only when a claim says it, not when it
   is common knowledge or implied. An empty list means everything is traced.
2. **Overstatement.** Does any sentence say more than its claims: "the first" for "one of the first", "always" for
   "for years", a cause the claims don't give, a story told as fact?
3. Answer every question in `questions`, one answer per question in `answers`, in order, each a short sentence that
   starts with yes or no.

Verdicts:

- `fail`: anything in `untraced`, any overstatement, or any answer that shows the piece misses the standard (for a
  story: its surprise is already in the encyclopedia lead, it's true of every place of its kind, `look` doesn't say
  what to look at and where to stand, or a well-read friend wouldn't say "wait, really?").
- `pass`: none of that.
- `unclear`: you can't tell; say exactly what you'd need to know.

Your note states the main reason for the verdict.
