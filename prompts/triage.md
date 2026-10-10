# Triage a cell's leads

You decide, for every lead in one cell of the map, what happens to it before anything is written. A separate step
writes each lead you choose, one at a time, from primary sources; a review then marks every story the way the editor
marked `marked_examples`, against `golden_bar`. Your job is to choose well: the leads that will make good stories, and
an honest reason for every lead you don't.

For each lead in `data.leads`, decide one `action`:

- `write`: one physical thing a person can walk up to and point at, with a story worth telling that is not already
  the opening of its encyclopedia article. Give `form` (`story`; `street_name` for where a street's name comes from,
  tied to the sign; `plaque` for what a plaque or memorial leaves out), the `tier` you expect (`featured` for a
  "wait, really?" story, `map` for a true, specific, visible story with a smaller surprise), and the `angle` in one
  sentence: what the surprise is and what the reader can see.
- `known`: the lead is a place the platform already has (`data.places_nearby`); give its id in `existing`. Choose
  `write` instead only for an angle its stories don't tell.
- `skip`: not one physical thing (a district, a street network, an event, a firm, a constituency), nothing to see
  today, nothing beyond the encyclopedia's opening, or true of every place of its kind. Give a specific `reason`
  ("only a blog repeats the tunnel story", "nothing beyond its encyclopedia opening").
- `later`: worth a look but not this pass. Never for a lead marked `well_known`. Give a `reason`.

A lead with a `record` has an official record (a heritage list entry, say) that a story can rest on; a story needs
one primary record or scholarly source, so prefer these, and choose a lead without one only when you know where its
record is. Choose `data.max_writes` leads to write, best first, whenever there are that many with a record that a
reader could stand in front of: a listed building, kiosk, gate, wall, or memorial is a map story at least, and the
writer decides from its record whether there is a story; skip it only for a reason you can name. At least half of what you write should be ordinary
places a visitor would never look up: a bollard, a gate, a corner shop, a boundary stone, a street sign. Map stories
count: the goal is something worth looking at within a few steps anywhere. Never choose a lead you would have to pad,
guess, or speculate to make interesting.

Reply with only `{"decisions": [{"lead", "action", "existing", "reason", "form", "tier", "angle"}], "notes"}`,
leaving out the fields an action doesn't use, with one decision for every lead. Keep each reason and angle to a short
phrase: a cell can have hundreds of leads.
