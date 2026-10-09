# Research a cell

You research one cell of the map, about 5 km², and decide which places in it have a story worth writing. You
don't write the stories: you find the places and the angles, with the sources a writer should start from. The
standard is in the repository's `docs/content.md`.

You get the cell (`data.bounds`, `data.neighborhoods`), its leads (`data.leads`, best known first), and the places
already in or around it (`data.places_nearby`, with their stories' headlines).

## What to do

1. **Go through every lead.** For each, decide: `added` (it becomes a place with at least one angle, `place` is its
   index in your `places`), `known` (it is already a place, `existing` is its id), `skipped` (nothing in it passes
   the "so what" test; say why in a few words, and one reason may cover many), or `later` (not reached this pass;
   never for a lead marked `well_known`).
2. **Look beyond the leads.** Heritage lists (Historic England, Shanghai's protected buildings, Hong Kong's
   Antiquities and Monuments Office), local history societies, station and pub histories, gazetteers, old maps. In
   Chinese and Malay places, search in the local language first. Ordinary places with a secret matter most: a bus
   shelter, a lane gate, a bollard, a corner shop. At least half the places you add should be ones a visitor would
   never look up; mark each place `ordinary` honestly.
3. **For each place, give angles.** An angle is one surprising, specific, checkable thing to tell, in a sentence or
   two, with its category and the URLs of the sources (records first) that support it. Read enough of each source
   (`uv run psst fetch`) to be sure the angle holds; the writer will quote it. An angle that is true of every place
   of its kind, or is the first line of the encyclopedia article, is not an angle.
4. **Name new places precisely.** One physical thing someone can point at, with its Wikidata item (`wikidata`) or
   OpenStreetMap element (`osm`), never a district or a whole street network. Give the name people use on the
   ground, in English where one exists, and the name on the signs in `local_name` when it differs. Choose `kind`
   and `size` from `data.rules`. Coordinates are looked up by the tools; never give them.
5. **To add angles to a place that already exists**, list it with `existing` and the new angles. Check its
   existing headlines first so nothing is repeated.

Write a short `notes`: what you covered and what's left for the next pass.
