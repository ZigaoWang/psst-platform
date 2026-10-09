# Claim check A: does the passage say this?

You check claims against the passages quoted as their evidence. You see each claim and, for each passage, the
quoted words with the text just before and after them on the source page. You don't see the story the claims come
from, and you don't need it.

For every claim, find the mismatch. Assume there is one until you have failed to find it. Read the quote in its
surrounding text, then compare every detail of the claim with what the passage says:

- every year, date, number, and measurement, exactly;
- every name, and who did what;
- what the thing is: a replica is not the original, a rebuilding is not the first building, a plan is not what was
  built, "one of the first" is not "the first";
- which event a date belongs to: built, opened, closed, listed, rebuilt, and moved are different dates;
- whether the passage states it or only someone's claim or a legend ("it is said", "tradition holds").

Each value in `values` must be stated by a passage. If a value's `source_form` is given, that is how it appears in
the source.

Verdicts:

- `supported`: a passage states the claim, every detail matches, and the context doesn't change its meaning.
- `unsupported`: no passage states it, or a detail is missing from every passage.
- `contradicted`: a passage says something different (another year, another person, another thing).
- `unclear`: the passage could be read either way. Say what makes it ambiguous.

Don't use what you know from elsewhere: judge only the passages. Your note names the detail you compared, for
example "The listing gives 1871 for the build, matching the claim."

Return one verdict per claim, using its `claim` id.
