"""Near quotes become exact (decision 28); far ones are left for the checks to refuse. Text is invented."""

from psst.harness import quotes

SOURCE = ("The Old Pump House on Mill Lane was built in 1871 by the engineer Ada Thorne for the Testville Water "
          "Company, and its engines ran until 1952, when the council turned it into a library.")


def test_a_retyped_quote_becomes_the_exact_passage():
    retyped = "built in 1871 by engineer Ada Thorne for the Testville Water Company"
    assert quotes.nearest(SOURCE, retyped) == "built in 1871 by the engineer Ada Thorne for the Testville Water Company"


def test_an_invented_quote_is_left_alone():
    assert quotes.nearest(SOURCE, "the pump house was designed in 1880 by a famous architect from London") is None


def test_an_exact_quote_needs_nothing():
    assert quotes.nearest(SOURCE, "its engines ran until 1952") is None


def test_evidence_is_found_anywhere_in_an_answer():
    answer = {"place": {"stories": [{"claims": [{"evidence": [{"snapshot": "sn_x", "quote": "q"}]}]}]}}
    assert quotes._evidence(answer) == [{"snapshot": "sn_x", "quote": "q"}]
