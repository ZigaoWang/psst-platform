"""The writer trial's counting: a place is accepted only when every item of it passes review with nothing to cut.
Places and marks are invented."""

from __future__ import annotations

from psst.harness import trial


def place(name, stories=0):
    claim = {"text": "The hall was built in 1886.", "kind": "date", "values": [{"value": "1886"}],
             "evidence": [{"snapshot": "sn_1", "quote": "built in 1886"}]}
    body = {"identifier": "Brick hall, 1886", "about": "A hall built in 1886.", "key_facts": []}
    story = {"body": {"headline": "h", "short": "s", "long": "l", "look": "Look at the hall."}, "claims": [claim]}
    return {"place": {"name": name, "kind": "building", "guide": {"body": body, "claims": [claim]},
                      "stories": [story] * stories}, "leads": ["ld_1"]}


def test_a_place_is_accepted_only_when_all_its_items_pass_clean():
    placed = [place("One hall", stories=1), place("Two hall")]
    items = trial.review_items(placed)
    assert [i["type"] for i in items] == ["story", "guide", "guide"]
    marks = [{"revision": items[0]["revision"], "mark": "good", "fix": None, "unclaimed": []},
             {"revision": items[1]["revision"], "mark": "good", "fix": None, "unclaimed": ["a slate roof"]},
             {"revision": items[2]["revision"], "mark": "good", "fix": None, "unclaimed": []}]
    result = trial.outcome(placed, items, marks)
    assert result["accepted"] == 1 and result["accepted_places"] == [2] and result["clean_items"] == 2
