"""The tool checks refuse what code can decide, before any model looks (design.md, section 7.2). The records,
places, and people here are invented."""

from __future__ import annotations

import copy
import dataclasses

import pytest

from psst.checks.tools import Claim, Context, Evidence, Snapshot, Stop, check, numbers, proper_names
from psst.core.text import find_quote

RECORD = Snapshot("sn_record0000", "so_record0000", "https://records.example.org/pump-house", "official_record",
                  "List entry. The Old Pump House, Mill Lane. Built in 1871 to the design of the engineer Ada Thorne "
                  "for the Testville Water Company. Converted to a public library in 1952. The chimney is 31 meters "
                  "tall and carries a cast iron band at each floor level. The original boiler beams remain over the "
                  "reading room.")
PAPER = Snapshot("sn_paper00000", "so_paper00000", "https://news.example.com/library-at-80", "press",
                 "Readers at the Mill Lane library still sit under the old boiler beams, and staff say the "
                 "chimney's iron bands were made at the Ferris foundry nearby.")
WIKI = Snapshot("sn_wiki000000", "so_wiki000000", "https://en.wikipedia.org/wiki/Old_Pump_House", "official_record",
                "The Old Pump House is a former pumping station built in 1871 in Testville. It became a library "
                "in 1952.")
SNAPSHOTS = {s.id: s for s in (RECORD, PAPER, WIKI)}

LONG = ("Ada Thorne designed the building in 1871 for the Testville Water Company, and its steam pumps pushed water "
        "up to the town's reservoir for eight decades. When the pumps stopped, the council kept the shell and in 1952 "
        "turned it into a public library. Readers now sit under the original boiler beams. The 31 meter chimney "
        "was never taken down: its cast iron bands, one for each floor, still show where the engine house floors "
        "once stood inside.")


def story(**changes):
    body = {
        "category": "history", "veracity": "fact", "headline": "The library that pumped the town's water",
        "short": "The library on Mill Lane was built in 1871 as a pumping station, and readers sit under its boiler "
                 "beams.",
        "long": LONG,
        "look": "From the far pavement of Mill Lane, look up at the iron bands circling the chimney.",
        "tags": [],
    }
    body.update(changes)
    return body


def claims():
    return [
        Claim(1, "The pump house was built in 1871 to Ada Thorne's design.", "date",
              [{"value": "1871"}, {"value": "Ada Thorne"}],
              [Evidence(RECORD.id, "Built in 1871 to the design of the engineer Ada Thorne", 1)]),
        Claim(2, "It was built for the Testville Water Company.", "name", [{"value": "Testville Water Company"}],
              [Evidence(RECORD.id, "for the Testville Water Company", 2)]),
        Claim(3, "It became a public library in 1952.", "event", [{"value": "1952"}, {"value": "Mill Lane"}],
              [Evidence(RECORD.id, "Converted to a public library in 1952", 3),
               Evidence(PAPER.id, "the Mill Lane library", 4)]),
        Claim(4, "The chimney is 31 meters tall with an iron band at each floor.", "attribute", [{"value": "31"}],
              [Evidence(RECORD.id, "The chimney is 31 meters tall and carries a cast iron band at each floor level",
                        5)]),
        Claim(5, "Readers sit under the old boiler beams.", "attribute", [],
              [Evidence(PAPER.id, "Readers at the Mill Lane library still sit under the old boiler beams", 6),
               Evidence(RECORD.id, "The original boiler beams remain over the reading room", 7)]),
    ]


def refusals(result):
    return "\n".join(result.report.refusals)


def test_a_sound_story_passes():
    result = check("story", story(), claims(), SNAPSHOTS)
    assert result.ok, refusals(result)
    assert all(m["start"] is not None for m in result.matches)


def test_a_wrong_year_in_the_prose_is_refused():
    result = check("story", story(long=LONG.replace("in 1952", "in 1953")), claims(), SNAPSHOTS)
    assert "'1953' isn't among the claims' values" in refusals(result)


def test_a_claim_value_its_passage_doesnt_give_is_refused():
    wrong = claims()
    wrong[0].values[0] = {"value": "1872"}
    result = check("story", story(long=LONG.replace("1871", "1872")), wrong, SNAPSHOTS)
    assert "'1872' isn't in any of its passages" in refusals(result)


def test_a_quote_missing_from_its_snapshot_is_refused():
    wrong = claims()
    wrong[2].evidence[0] = Evidence(RECORD.id, "Converted to a lending library in 1952", 3)
    result = check("story", story(), wrong, SNAPSHOTS)
    assert "the quote isn't in snapshot sn_record0000" in refusals(result)
    assert {"evidence": 3, "start": None, "end": None} in result.matches


def test_claims_resting_only_on_reference_works_are_refused():
    wrong = claims()
    wrong[2].evidence = [Evidence(WIKI.id, "It became a library in 1952", 3)]
    result = check("story", story(), wrong, SNAPSHOTS)
    assert "claim 3: rests only on reference works" in refusals(result)


def test_a_featured_story_needs_two_sources_and_a_map_story_may_rest_on_its_record():
    single = [c for c in claims() if all(e.snapshot == RECORD.id for e in c.evidence)]
    shorter = {"short": "The library on Mill Lane was built in 1871 as a pumping station.",
               "long": LONG.replace(" Readers now sit under the original boiler beams.", "")}
    result = check("story", story(**shorter, tier="featured"), single, SNAPSHOTS)
    assert "needs at least 2 independent sources; has 1" in refusals(result)
    result = check("story", story(**shorter, tier="map"), single, SNAPSHOTS)
    assert not any("independent sources" in r for r in refusals(result))


def test_copied_wording_is_refused():
    copied = LONG.replace("Readers now sit under the original boiler beams.",
                          "Readers at the Mill Lane library still sit under the old boiler beams.")
    result = check("story", story(long=copied), claims(), SNAPSHOTS)
    assert "write it in your own words" in refusals(result)


def test_quoting_a_source_is_not_copying():
    quoted = LONG.replace("Readers now sit under the original boiler beams.",
                          'A reporter wrote that "Readers at the Mill Lane library still sit under the old boiler '
                          'beams."')
    result = check("story", story(long=quoted), claims(), SNAPSHOTS)
    assert "own words" not in refusals(result)


def test_an_event_with_one_press_source_is_a_legend():
    wrong = claims()
    wrong[2].evidence = [Evidence(PAPER.id, "the Mill Lane library", 4)]
    result = check("story", story(), wrong, SNAPSHOTS)
    assert "which makes it a legend" in refusals(result)


def test_an_anecdote_is_a_legend_whatever_its_claim_kind():
    wrong = claims()
    wrong[4].kind = "name"
    wrong[4].evidence = wrong[4].evidence[:1]  # the boiler beams rest on the newspaper alone
    result = check("story", story(), wrong, SNAPSHOTS)
    assert "claim 5: rests on one press or community source" in refusals(result)


def test_a_myth_needs_its_popular_version_sourced():
    result = check("story", story(myth="People say the chimney was a lighthouse for barges."), claims(), SNAPSHOTS)
    assert "needs a claim with the role 'myth'" in refusals(result)


def test_a_legend_says_it_is_a_story():
    result = check("story", story(veracity="legend"), claims(), SNAPSHOTS)
    assert "a legend says it's a story people tell" in refusals(result)


@pytest.mark.parametrize("field, text, problem", [
    ("short", "The library on Mill Lane was built in 1871 — as a pumping station.", "em dash"),
    ("long", LONG.replace("Readers now", "Readers in this iconic building now"), "uses 'iconic'"),
    ("look", "Look at the chimney.", "is too short"),
    ("headline", "Why does a library have a chimney?", "contains '?'"),
])
def test_writing_rules_apply_to_every_field(field, text, problem):
    result = check("story", story(**{field: text}), claims(), SNAPSHOTS)
    assert problem in refusals(result)


def test_numbers_are_read_from_digits_only():
    assert numbers("Built in 1871, 1,200 bricks, the 1860s, the 19th century, M25, 3.5 meters.") == \
        ["1871", "1200", "1860s", "19th", "3.5"]


def test_chinese_quotes_match_across_extraction_spaces():
    text = "步高里 建于 1930 年,共有 78 幢 房屋。"
    assert find_quote(text, "步高里建于1930年") is not None


def guide(**changes):
    body = {"identifier": "Former pumping station, 1871, by Ada Thorne",
            "about": "A pumping station built in 1871 for the Testville Water Company. It became a public library "
                     "in 1952.",
            "key_facts": [{"property": "P571", "value": "1871", "claim": 1}]}
    body.update(changes)
    return body


def test_a_sound_guide_passes():
    result = check("guide", guide(), claims()[:3], SNAPSHOTS)
    assert result.ok, refusals(result)


def test_guide_text_never_judges():
    result = check("guide", guide(about=guide()["about"].replace("A pumping", "A famous pumping")),
                   claims()[:3], SNAPSHOTS)
    assert "'famous' is a judgment" in refusals(result)


def test_the_identifier_year_agrees_with_the_key_facts():
    result = check("guide", guide(identifier="Former pumping station, 1952"), claims()[:3], SNAPSHOTS)
    assert "gives 1952, but the key facts date it 1871" in refusals(result)


def test_trail_stops_must_be_published_and_walkable():
    stops = {f"pl_{c * 10}": Stop(51.5, -0.1 + i * 0.02, True) for i, c in enumerate("abcd")}
    stops["pl_dddddddddd"].published = False
    body = {"title": "Water in the old town", "intro": "", "tags": ["tg_aaaaaaaa"],
            "stops": [{"place": p, "note": "A stop on the walk with a detail worth seeing up close."} for p in stops]}
    body["intro"] = ("The walk follows the old water supply from the pumping station to the reservoir, past the "
                     "places the pipes once ran under, and ends at the reservoir gate after about an hour on foot.")
    result = check("trail", body, [], SNAPSHOTS, Context(stops=stops))
    text = refusals(result)
    assert "pl_dddddddddd has no published stories" in text
    assert "m from the stop before" in text


def test_a_translation_keeps_every_number():
    source = story()
    body = {"language": "zh-Hans", "headline": "曾为全镇供水的图书馆", "short": "米尔巷的图书馆建于1872年。",
            "long": "这座建筑建于1871年。", "look": "从米尔巷对面抬头看烟囱上的铁箍。"}
    result = check("translation", body, [], {}, Context(source_type="story", source_body=source))
    assert "short: its numbers differ from the English" in refusals(result)


def test_the_check_never_changes_its_inputs():
    body, given = story(), claims()
    before = (copy.deepcopy(body), copy.deepcopy(given))
    check("story", body, given, SNAPSHOTS)
    assert (body, given) == before


def test_a_name_no_cited_source_mentions_is_refused():
    result = check("story", story(long=LONG.replace("Ada Thorne designed", "Ada Thorne and Hugo Brandt designed")),
                   claims(), SNAPSHOTS)
    assert "'Brandt', 'Hugo' isn't in the claims' quotes" in refusals(result)


def test_a_source_sentence_told_in_other_words_is_refused():
    copied = ("The chimney rises 31 meters tall and carries a cast iron band at every floor level of the old "
              "building.")
    result = check("story", story(long=LONG + " " + copied), claims(), SNAPSHOTS)
    assert "repeats a sentence of snapshot sn_record0000 in other words" in refusals(result)


def test_a_look_at_something_the_story_never_mentions_is_refused():
    result = check("story", story(look="Stand by the bus stop and look across at the post office."), claims(),
                   SNAPSHOTS)
    assert "names nothing the story is about" in refusals(result)


def test_a_sentence_said_twice_is_refused():
    repeated = LONG + " Readers now sit under the original boiler beams."
    result = check("story", story(long=repeated), claims(), SNAPSHOTS)
    assert "says again what long already says" in refusals(result)


def test_a_host_with_a_fixed_kind_overrides_the_writer_label():
    from psst.evidence import urls
    assert urls.host_kind("https://en.wikipedia.org/wiki/Old_Pump_House") == "reference"
    assert urls.host_kind("https://www.subbrit.org.uk/sites/old-pump-house") == "community"
    assert urls.host_kind("https://records.example.org/old-pump-house") is None
    blog = dataclasses.replace(RECORD, url="https://www.subbrit.org.uk/sites/old-pump-house", kind="scholarly")
    result = check("story", story(), claims(), SNAPSHOTS | {RECORD.id: blog})
    assert "needs a primary record or scholarly source" in refusals(result)


def test_a_second_story_on_the_same_angle_is_refused():
    earlier = ("Readers in a former pumping station. Mill Lane's library began in 1871 pumping water, and its readers "
               "still sit beneath the boiler beams.")
    result = check("story", story(), claims(), SNAPSHOTS, Context(names=["Old Pump House"], siblings=[earlier]))
    assert "tells the same story as" in refusals(result)
    other = "Ada Thorne won the commission at twenty three, the youngest engineer the water company ever hired."
    result = check("story", story(), claims(), SNAPSHOTS, Context(names=["Old Pump House"], siblings=[other]))
    assert "tells the same story as" not in refusals(result)


def test_a_long_name_shared_with_the_source_is_not_copying():
    record = dataclasses.replace(RECORD, text=RECORD.text + " Concerts are given by the Academy of St Martin in the "
                                              "Fields Orchestra each spring.")
    named = story(long=LONG + " Concerts are now given here by the Academy of St Martin in the Fields Orchestra.")
    result = check("story", named, claims(), SNAPSHOTS | {RECORD.id: record})
    assert "copies" not in refusals(result)


def test_a_possessive_name_is_the_name():
    assert proper_names("We walked past Highbury's clock") == ["Highbury"]


def test_a_new_places_own_name_and_city_may_be_used_in_its_prose():
    body = story(short="The pump house at 12 Mill Lane in Testville was built in 1871 as a pumping station.")
    names = Context(names=["12 Mill Lane", "Testville"])
    result = check("story", body, claims(), SNAPSHOTS, names)
    assert not any("'12'" in r or "Testville" in r for r in refusals(result))


def test_a_name_only_elsewhere_on_a_cited_page_is_refused():
    page = Snapshot("sn_page0000000", "so_page0000000", "https://records.example.org/memorial", "official_record",
                    "Memorial in centre of road. Unveiled in 1880.\n\nLocation: Holborn, Westminster")
    body = story(look="Stand at the Holborn junction and look up at the memorial in the centre of the road.")
    found = [Claim(1, "The memorial was unveiled in 1880.", "date", [{"value": "1880"}],
                   [Evidence(page.id, "Memorial in centre of road. Unveiled in 1880", 1)])]
    assert "look: 'Holborn' isn't in the claims' quotes" in refusals(check("story", body, found, {page.id: page}))


def test_a_name_is_read_without_its_possessive_and_never_from_a_sentence_start():
    assert proper_names("From Fleet Street, look up. Inside St Botolph's the font stands.") == \
        ["Fleet", "Street", "St", "Botolph"]
