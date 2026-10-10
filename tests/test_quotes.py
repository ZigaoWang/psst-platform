"""Near quotes become exact (decision 28); far ones are left for the checks to refuse. Text is invented."""

from psst.harness import quotes

SOURCE = ("The Old Pump House on Mill Lane was built in 1871 by the engineer Ada Thorne for the Testville Water "
          "Company, and its engines ran until 1952, when the council turned it into a library.")


def test_a_retyped_quote_becomes_the_exact_passage():
    retyped = "the Old Pump House on Mill Lane was built in 1871 by engineer Ada Thorne for the Testville Water Company"
    exact, similarity = quotes.nearest(SOURCE, retyped)
    assert exact == "The Old Pump House on Mill Lane was built in 1871 by the engineer Ada Thorne for the Testville " \
                    "Water Company" and similarity >= 0.95


def test_a_quote_two_words_off_in_ten_is_invented_not_repaired():
    assert quotes.nearest(SOURCE, "built in 1880 by the architect Ada Thorne for the Testville Water Company") is None


def test_an_invented_quote_is_left_alone():
    assert quotes.nearest(SOURCE, "the pump house was designed in 1880 by a famous architect from London") is None


def test_an_exact_quote_needs_nothing():
    assert quotes.nearest(SOURCE, "its engines ran until 1952") is None


def test_evidence_is_found_anywhere_in_an_answer():
    answer = {"place": {"stories": [{"claims": [{"evidence": [{"snapshot": "sn_x", "quote": "q"}]}]}]}}
    assert quotes._evidence(answer) == [{"snapshot": "sn_x", "quote": "q"}]
