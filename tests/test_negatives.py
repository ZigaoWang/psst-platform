"""Constructed negatives (decision 31): good stories broken in one known way each. Stories are invented."""

from psst.harness import negatives

GOOD = [{"id": f"gs_{n}", "place": f"Invented Hall {n}", "headline": f"A hall built twice {n}",
         "short": "The hall on Mill Lane was built in 1871 and rebuilt in 1902 after a fire.",
         "long": "Ada Thorne designed the first hall in 1871 for the town's water company. It burned in 1899, and "
                 "the council rebuilt it in 1902 to the same plan. The iron bands on the chimney are the originals.",
         "look": "From the far pavement, look up at the iron bands on the chimney."} for n in range(8)]


def test_every_defect_is_made_the_number_of_times_asked():
    rows = negatives.construct(GOOD, per_defect=6)
    made = [r for r in rows if "defect" in r]
    assert len(made) == 42 and {r["defect"] for r in made} == set(negatives.DEFECTS)
    assert all(sum(r["defect"] == d for r in made) == 6 for d in negatives.DEFECTS)


def test_a_broken_copy_differs_from_its_story_and_its_claims_are_the_story():
    rows = negatives.construct(GOOD, per_defect=1)
    number = next(r for r in rows if r.get("defect") == "number_mismatch")
    assert "1878" in number["long"] and "1871" not in number["long"]
    claims = next(r for r in rows if r.get("claims_for") == "gs_0")["claims"]
    assert "It burned in 1899, and the council rebuilt it in 1902 to the same plan." in claims
    look = next(r for r in rows if r.get("defect") == "look_at_nothing")
    assert look["look"].startswith("Look around")
