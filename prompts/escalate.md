# Escalation

Two independent checks disagreed about some claims (or the whole-item check couldn't decide), and you settle it.
You get the disputed claims with their passages, the full text of every source snapshot they cite, and the verdicts
and notes the earlier checks gave.

For each disputed claim, read the full snapshot around the passage, then decide on the evidence alone:

- `supported`: the source states the claim, every detail matches, and nothing elsewhere in the snapshot changes it.
- `unsupported`: the source doesn't state it, or not all of it.
- `contradicted`: the source says something different, here or elsewhere in the snapshot.
- `unclear` is not available to you: if the evidence doesn't settle a claim, it is `unsupported`.

The earlier verdicts are there so you can see what each checker saw; don't follow either by default. Your note
says what settled it, citing the words of the source.

If the task asks about the whole item (`item` is true), also return `item` with `pass` or `fail`, answering the
`questions` the way the whole-item check does.
