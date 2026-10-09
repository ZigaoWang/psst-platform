"""The rulebook loads, every type schema is a valid JSON Schema, and the writing rules catch what they should."""

from __future__ import annotations

import jsonschema
import pytest

from psst import rules
from psst.rules import writing
from psst.rules.report import Report


def test_every_type_schema_is_valid():
    rulebook = rules.load()
    assert set(rulebook.types) == {"story", "guide", "photo", "trail", "translation"}
    for name, spec in rulebook.types.items():
        if "schema" in spec:
            jsonschema.Draft202012Validator.check_schema(spec["schema"])
        assert set(spec["checks"]) <= {"tool", "claims", "item", "translation"}, name


def test_the_version_is_a_hash_of_the_files(tmp_path):
    (tmp_path / "types").mkdir()
    (tmp_path / "writing.yaml").write_text("a: 1\n")
    first = rules.version_of(tmp_path)
    (tmp_path / "writing.yaml").write_text("a: 2\n")
    assert rules.version_of(tmp_path) != first
    assert len(first) == 12


def test_story_long_leaves_room_for_look_in_format_2():
    schema = rules.load().type("story")["schema"]["properties"]
    assert schema["long"]["maxLength"] + 2 + schema["look"]["maxLength"] <= 1200


@pytest.mark.parametrize("text, problem", [
    ("The tower was built in 1902 — by hand.", "em dash"),
    ("Open 1902–1910.", "en dash"),
    ("A stunning view.", "'stunning'"),
    ("Nestled between two banks.", "'nestled'"),
    ("The colour of the brick.", "British spelling 'colour'"),
    ("They organised a market.", "British spelling 'organised'"),
    ("It closed in 1952!", "exclamation mark"),
    ("The arch - finished in 1912 - stands here.", "hyphen as a dash"),
])
def test_prose_refusals(text, problem):
    report = Report()
    writing.check_prose(report, "short", text)
    assert any(problem in r for r in report.refusals), report.refusals


def test_names_keep_their_own_spelling():
    report = Report()
    writing.check_prose(report, "long", "The Southbank Centre opened beside the National Theatre in 1976.")
    assert report.ok, report.refusals


def test_guide_text_never_judges():
    report = Report()
    writing.check_neutral(report, "about", "One of the oldest and most famous pubs in the city.")
    for word in ("'famous'", "'oldest'", "'one of the'"):
        assert any(word in r for r in report.refusals), word


def test_sentences_are_counted_past_abbreviations():
    assert writing.count_sentences("Built by C. W. Smith in 1871. It closed in 1952.") == 2


@pytest.mark.parametrize("word", ["honours", "honoured", "neighbours", "centres", "theatres", "kilometres"])
def test_british_word_families_are_refused(word):
    report = Report()
    writing.check_prose(report, "short", f"It {word} the past.")
    assert any("British spelling" in r for r in report.refusals)


def test_proper_names_keep_their_own_spelling():
    report = Report()
    writing.check_prose(report, "short", "The National Theatre faces the Southbank Centre.")
    assert not report.refusals
