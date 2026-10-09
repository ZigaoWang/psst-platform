# Write a trail

You write one themed walk that links places with published stories. The brief (`data.brief`) gives the theme and
the candidate places; the limits are in `data.rules`.

- Choose 4 to 12 stops that belong to the theme for a reason you can state, in an order that makes sense on foot:
  consecutive stops at most 1 km apart, the whole walk at most 6 km.
- `title`: the theme, plainly. `intro`: what the walk is about and where it goes, in two to four sentences.
- Each stop's `note`: why it is on this trail and what to look at there, in one or two sentences. Don't repeat the
  stop's story; point to it.
- Tag the trail with its theme (`tags`, one or two existing tag ids).
- Every checkable statement in the intro and the notes is a claim with a quoted passage from a saved snapshot, as
  for stories (fetch sources with `uv run psst fetch`). The stops' own published stories are good starting points;
  quote their sources, not the stories.

Writing rules as for stories: US English, no dashes, no exclamation marks, no hype, your own words.
