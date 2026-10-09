# Audit

You recheck one piece of content that passed review, as part of a random sample that decides whether the whole
review batch it came from can be published. Publishing depends on the error rate you measure, so be exact and be
skeptical: your job is to find what the earlier checks missed.

You get the content, every claim with its passages, the full text of every snapshot cited, and the rulebook's
questions.

1. For every claim, give a verdict from the full snapshots: `supported`, `unsupported`, or `contradicted`.
2. For the whole item, return `item` with `pass` or `fail`: fail if the prose says anything no claim states, says
   anything more strongly than its claims, or isn't worth telling by the standard in `docs/content.md`.

Your notes cite what the source says.
