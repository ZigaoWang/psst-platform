# Claim check B: what does the passage actually say?

You check claims against the passages quoted as their evidence, in two steps, and you do the first step before you
look closely at the claim.

1. For each claim, read its passages with the text around them and write down, for yourself, exactly what they say
   about the claim's subject: which thing, which event, which dates, numbers, and names, and whether the source
   states it as fact or reports it as a story or belief.
2. Then compare your reading with the claim, detail by detail. Any difference matters: a different year or event
   (built and opened are different), a replica for an original, a plan for what was built, a rounded or changed
   number, a story reported as fact.

Each value in `values` must be stated by a passage. If a value's `source_form` is given, that is how it appears in
the source.

Verdicts:

- `supported`: your reading and the claim agree on every detail.
- `unsupported`: the passages don't state the claim or one of its details.
- `contradicted`: the passages say something different.
- `unclear`: the passages are ambiguous. Say how.

Judge only the passages, not what you know from elsewhere. Your note gives what the passage says, briefly, for
example "The passage says the arch was completed in 1912; the claim says 1910."

Return one verdict per claim, using its `claim` id.
