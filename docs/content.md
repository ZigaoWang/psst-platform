# What makes Psst content worth it

Psst is a map and feed of surprising, sourced stories about specific places a person can stand in front of, with plain guide information about each place. Anyone can summarize an encyclopedia. This document says what Psst does instead, how every story is tested before it can exist, and what each kind of content must contain. The rulebook (`rules/`) turns these requirements into checks; [design.md](design.md) describes the machinery.

The examples below are real places in London and Shanghai, used to show the standard. Like everything else, they reach readers only after going through research and checking.

## 1. The six qualities

### 1.1 Made for standing there

Every story tells the reader what to look at and where to stand to see it. A story that could be read just as well at home is half a story.

- **Cleopatra's Needle, Victoria Embankment.** The pitted holes and gouges in the plinth and the bronze sphinx beside it are damage from a bomb dropped during a German air raid in September 1917. The scars were left unrepaired, with a small plaque explaining them. The story ends with where to look: the sphinx on the right as you face the obelisk from the river walk.
- **23 and 24 Leinster Gardens, Bayswater.** Two house fronts with no houses behind them, built in the 1860s to close the gap the Metropolitan Railway cut through the terrace, leaving the line open to the sky so steam engines could vent. From the pavement opposite, the windows are flat gray panels and the doors have no letter boxes.
- **Shanghai Concert Hall, Yan'an Road East.** In 2003 the whole 1930 building was jacked up and moved about 66 meters to make room for the Yan'an Road elevated highway. Standing at the front steps, the reader looks back toward the overpass, which runs where the hall used to stand.

Every story therefore has a required `look` field: one sentence naming the thing and the spot to see it from. Anything `look` says is there is a claim with evidence, like the rest of the story.

### 1.2 Original synthesis of primary sources

A Psst story is put together from the records: heritage listings, planning applications, old newspapers, old maps, directories, company histories, and local history societies. Encyclopedias and guidebooks are where research starts, not what it cites.

- **London.** The National Heritage List for England gives a listed building's date, architect, materials, and alterations in the official text. The Survey of London (on British History Online) gives street-by-street building histories. Old Ordnance Survey maps (National Library of Scotland) show what stood on a site before. Hansard and the London Gazette record acts, openings, and closures.
- **Shanghai.** The municipal and district gazetteers (上海地方志, published at shtong.gov.cn) record when a lane was built, by whom, and what it was called. The city's protected historic building list (上海市优秀历史建筑) gives the official date and architect, and many of these buildings carry a plaque with the same text. The Shen Bao (申报, 1872 to 1949) and the North-China Herald report events as they happened.

What this means in practice:

- Every claim in a story needs a passage from a source that is not a reference work (an encyclopedia, a guidebook, a listicle).
- Every story cites at least two independent sources, and at least one of them is a primary record or scholarly work.
- The prose is written fresh. The tools refuse a story that shares a long run of words with any of its sources.

### 1.3 Ordinary places with a secret

Landmarks are expected and must be covered, but the heart of Psst is the place nobody would look up: a bus shelter, a lane gate, a green hut, a bollard.

- **Cabmen's shelters, London.** The small green wooden huts by some taxi ranks were built by the Cabmen's Shelter Fund, founded in 1875, as places where cab drivers could rest and eat. They stand on the public highway, so the police allowed them to be no larger than a horse and cart. Of 61 built, 13 survive, and in 2024 the last of them was listed.
- **Bugaoli (步高里), Shaanxi Road South.** A shikumen lane of 1930 behind a gateway that carries its name three ways: 步高里, CITÉ BOURGOGNE, and the year. The Chinese name is a sound rendering of the French one. The reader stands at the gate on Shaanxi Road South and reads it.

Coverage rule: in every research cell, at least half the places with stories are places a visitor would not seek out. The research task reports this ratio and the city audit checks it.

### 1.4 Setting the record straight

Popular stories are checked against the records, and Psst says what the records show.

- **The nose on Admiralty Arch.** Taxi drivers and tour guides say it is the Duke of Wellington's nose, placed for luck. Wellington died in 1852; the arch was finished in 1912; the nose is one of about 35 that the artist Rick Buckley glued to London buildings in 1997, which he made public in 2011.
- **The 1917 raid at Cleopatra's Needle** is often called a Zeppelin raid. It was a raid by Gotha airplanes.
- **The Public Garden on the Bund (now Huangpu Park).** A sign reading "No dogs or Chinese allowed" is widely remembered. Photographs of the gate show a board of regulations: the first reserved the garden for the foreign community, and a later one excluded dogs and bicycles. Chinese residents were excluded from 1890 to 1928, which is fact; the single sign with that wording is not supported by the evidence. The story says both.

A story that corrects a popular version has a `myth` field stating the popular version in one sentence. It must cite a source that tells the popular version and a primary or scholarly source for the correction. The headline states what is true, never the myth.

When the records disagree, Psst says so and does not choose one silently. Sources give the Concert Hall's move as 2002, 2003, or 2007; the story uses the date the primary record gives and, if the records truly conflict, is marked `disputed` and explains why.

### 1.5 Bridging languages

The best material about Shanghai's lanes is in Chinese, and much of what is written about London's Chinese history is in Chinese too. Psst reads sources in both languages and serves stories in both.

- **Waibaidu Bridge (外白渡桥).** Its English name was Garden Bridge. The Chinese name records that the 1873 bridge was free to cross (白, "free") after the toll bridge it replaced had charged Chinese pedestrians. English sources rarely explain the name; Chinese ones do, and they disagree about the 外, which the story says.
- **Lao She at 31 St James's Gardens, Notting Hill.** The writer lived here from 1925 to 1928 while teaching Chinese at what is now SOAS, and an English Heritage plaque marks the house. His own writing about London is in Chinese, and readers in China know him; few people in Notting Hill do.

What this means in practice:

- In Shanghai, Hong Kong, and Kuala Lumpur, research reads local-language sources first. Evidence passages stay in their original language; the claim states in English what the passage says.
- Every published story and guide is also published in Simplified Chinese, as a checked translation of the accepted English text. Numbers, dates, and names must match the English exactly, and names use the place's own local forms.

### 1.6 Trails, then and now, and audio

- **Trails** are themed walks linking places that already have published stories: for example the course of the buried River Fleet from Hampstead to Blackfriars, or the banks of the Bund in the order they were built. A trail has its own short text and an ordered list of stops, each with a sentence on why it belongs on the trail.
- **Then and now.** A historic photo with its year, paired with a current photo taken from the same spot, so the reader can line them up. The mosaics in the entrance dome of the former HSBC building on the Bund, hidden under plaster for decades and uncovered during a renovation, are the kind of thing a pair of photos shows better than words.
- **Audio** is left room for: a narration of an accepted story, never new material.

## 2. The "so what" test

A story exists only if it passes all six:

1. **This place, not its kind.** It is true of this exact thing, not of every K6 phone box or every shikumen lane.
2. **It changes what you see.** Standing there after reading it, the reader looks at something differently, and `look` names that thing.
3. **It is not the encyclopedia's opening.** The surprise is not in the first paragraph of the place's encyclopedia article.
4. **Specific.** It carries names, numbers, dates, or physical details, each a claim with evidence.
5. **True, or honestly labeled.** `fact` when the records establish it; `legend` for an unproven anecdote; `disputed` when good sources disagree.
6. **A friend would say "wait, really?"** Old, tall, famous, or designed by someone well known is not a story.

Writers apply the test before writing. The whole-item check asks tests 1 to 3 and 6 as narrow questions with the place's encyclopedia lead in view, and a story that fails any of them goes back.

## 3. What Psst never publishes

- An encyclopedia summary, or anything whose claims rest only on reference works.
- A claim no saved source passage supports, or a story stronger than its evidence ("the first" when the record says "one of the first").
- A legend presented as fact, or a myth repeated without the correction.
- Superlatives and generic praise in place of a story: oldest, busiest, iconic, stunning, must-see.
- Places a reader should not go: private homes, restricted or dangerous sites. Public exteriors of private buildings are fine.
- Anything pointing at a private living person, or the home of a recent crime victim. Historical tragedies are written with respect.
- Places with no pin from Wikidata or OpenStreetMap, or a whole district or street network as one place.
- Photos without a free license, AI-generated or retouched photos, or a photo of the wrong building.
- Translations or text that add anything the accepted English does not say.

## 4. Content types

Every content type is an item with revisions, claims, and evidence (design.md, section 5). Prose of every type is bound to claims: every year, number, and proper name in it must appear in a claim, and every claim needs a matched passage.

### 4.1 Story

| field | rule |
| --- | --- |
| `category` | `name`, `hidden`, `history`, `design`, `engineering`, `people`, `pop`, or `quirk` |
| `veracity` | `fact`, `legend`, or `disputed` |
| `headline` | Up to 60 characters. Names the secret plainly. No question marks, puns, or clickbait. |
| `short` | Up to 220 characters. Stands alone on a card. Leads with the surprise. |
| `long` | 300 to 1,000 characters. The how and why, names and dates; for a legend or dispute, what the evidence shows. |
| `look` | 40 to 200 characters. What to look at and where to stand. Required. |
| `myth` | Optional. The popular version, in one sentence, for a story that sets the record straight. |
| `tags` | Up to four tag ids, for threads that connect several places. |
| `claims` | Every checkable statement, each with at least one evidence passage. |

Source rules: at least two independent sources; at least one primary record or scholarly work; every claim backed by a passage from a source that is not a reference work; an anecdote with one source is a `legend`.

### 4.2 Guide information

The plain answer to "what am I looking at?" It sits beside the stories, never inside them, and follows plainer rules: neutral, informative, third person. It may read like an encyclopedia, because that is its job.

| field | rule |
| --- | --- |
| `identifier` | Up to 70 characters, always in the shape `[style or material] <what it is>, <year>[, by <maker>]`, for example "Bronze statue, 1843, by Edward Baily" or "Former public baths, 1895, now a gym". No street, area, heritage grade, story detail, or the name again. |
| `about` | 100 to 700 characters, usually three sentences: what it is and why it was built; what happened since or why it matters; what it is today. No superlatives or judging words (famous, iconic, oldest, beautiful). Leaves the surprises to the stories. |
| `key_facts` | Structured values from Wikidata (maker, dates, style, heritage status, height, material), each with its property and evidence. A value with no agreeing evidence is dropped automatically. At most six are shown. |
| `claims` | As for stories. |

Source rules: at least one source. A reference work may support the About, but the identifier's year and maker must agree with the structured values and their evidence, and an official record is preferred when one exists. Every place with a published story has published guide information.

### 4.3 Photo

| field | rule |
| --- | --- |
| `kind` | `photo` (current) or `historic` |
| `year` | Required for `historic`: the year the source gives. |
| `alt` | 10 to 300 characters describing what a sighted reader would notice. Not "Photo of", no story. |
| `focus` | The point to keep in view when cropping. |
| `pair` | Optional, on a historic photo: the current photo taken from the same viewpoint, for then and now. |
| credit | Author, license, and source, copied from the source's own metadata, never typed. Free licenses only. |

### 4.4 Trail

| field | rule |
| --- | --- |
| `title` | Up to 60 characters. |
| `intro` | 150 to 600 characters: the theme and the route. |
| `stops` | 4 to 12 places, in walking order, each with published content and a `note` of up to 200 characters on why it is on this trail and what to look at. Consecutive stops at most 1 km apart; the whole walk at most 6 km. |
| `tags` | The theme. |

### 4.5 Translation

A Simplified Chinese version of an accepted story, guide, or trail. It may say nothing the English does not; every number and date is identical; names use the place's local names. It is checked by translating back and comparing claim by claim, and it is published only with the English revision it was made from.

### 4.6 Audio (later)

A narration of an accepted story or trail, recorded or generated from the exact accepted text, published with it and retired with it.

## 5. Writing

These apply to all content and to the guide's plainer register alike: US English spelling and punctuation; metric units, with imperial where a local reader expects it; no em or en dashes; no exclamation marks; no hype or filler ("iconic", "nestled", "boasts", "testament to", "hidden gem", "it's worth noting"); own words, never copied. Proper names keep their own spelling ("Southbank Centre"). Names from other languages appear as people see them on the ground, with the local script in the place's local name. The rulebook lists the exact words, lengths, and spellings the checks enforce.
