"""The result each task type returns, as JSON Schema. `psst task submit` validates against these before anything
reaches the database, which checks the same rules again."""

from __future__ import annotations

from typing import Any

from psst import rules

VERDICT = {"enum": ["supported", "unsupported", "contradicted", "unclear"]}
NOTE = {"type": "string", "minLength": 3, "maxLength": 600}
CLAIM_VERDICTS = {
    "type": "array",
    "items": {
        "type": "object", "additionalProperties": False, "required": ["claim", "verdict", "note"],
        "properties": {"claim": {"type": "string", "pattern": "^cl_"}, "verdict": VERDICT, "note": NOTE},
    },
}
ITEM_VERDICT = {
    "type": "object", "additionalProperties": False, "required": ["verdict", "note"],
    "properties": {"verdict": {"enum": ["pass", "fail"]}, "note": NOTE},
}
EVIDENCE = {
    "type": "object", "additionalProperties": False, "required": ["snapshot", "quote"],
    "properties": {"snapshot": {"type": "string", "pattern": "^sn_"}, "quote": {"type": "string", "minLength": 8,
                                                                                "maxLength": 2000}},
}
CLAIMS = {
    "type": "array",
    "items": {
        "type": "object", "additionalProperties": False, "required": ["text", "kind", "values", "evidence"],
        "properties": {
            "text": {"type": "string", "minLength": 5, "maxLength": 400},
            "kind": {"enum": ["date", "name", "number", "place", "event", "attribute"]},
            "role": {"enum": ["fact", "myth"]},
            "values": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["value"],
                "properties": {"value": {"type": "string", "minLength": 1},
                               "source_form": {"type": "string", "minLength": 1}}}},
            "evidence": {"type": "array", "minItems": 1, "items": EVIDENCE},
        },
    },
}


def writing(item_type: str) -> dict[str, Any]:
    body = rules.load().type(item_type)["schema"]
    return {"type": "object", "additionalProperties": False, "required": ["body", "claims", "reason"],
            "properties": {"body": body, "claims": CLAIMS, "reason": NOTE}}


def schema(task_type: str, item_type: str | None = None) -> dict[str, Any]:
    if task_type == "audit":
        return {"type": "object", "additionalProperties": False, "required": ["verdicts", "item"],
                "properties": {"verdicts": CLAIM_VERDICTS, "item": ITEM_VERDICT}}
    if task_type in ("check_photo", "check_translation"):
        return {"type": "object", "additionalProperties": False, "required": ["verdict", "note", "untraced", "answers"],
                "properties": {
                    "verdict": {"enum": ["pass", "fail"]}, "note": NOTE,
                    "untraced": {"type": "array", "items": {"type": "string"}},
                    "answers": {"type": "array", "items": {"type": "string"}},
                    "back_translation": {"type": "string"}}}
    if task_type == "write_trail":
        return writing("trail")
    if task_type == "revise":
        assert item_type
        if item_type == "translation":
            return translation()
        return writing(item_type)
    if task_type == "translate":
        return translation()
    if task_type == "research_cell":
        return research()
    if task_type == "review":
        return review()
    if task_type == "calibrate":
        mark = {"type": "object", "additionalProperties": False, "required": ["golden", "mark", "reason"],
                "properties": {"golden": {"type": "string", "pattern": "^gs_"},
                               "mark": {"enum": ["good", "weak", "bad"]}, "reason": NOTE}}
        return {"type": "object", "additionalProperties": False, "required": ["marks", "notes"],
                "properties": {"marks": {"type": "array", "items": mark}, "notes": NOTE}}
    if task_type == "find_photos":
        return photos()
    raise KeyError(f"no result schema for {task_type}")


def translation() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["language", "body", "reason"],
            "properties": {"language": {"enum": rules.load().type("translation")["languages"]},
                           "body": {"type": "object"}, "translation_of": {"type": "string", "pattern": "^rv_"},
                           "reason": NOTE}}


def research() -> dict[str, Any]:
    """Places found in the cell, each with its stories and (for a new place) its guide, and every lead accounted
    for."""
    spec = rules.load()
    item = {"story": {"type": "object", "additionalProperties": False, "required": ["body", "claims"],
                      "properties": {"body": spec.type("story")["schema"], "claims": CLAIMS}},
            "guide": {"type": "object", "additionalProperties": False, "required": ["body", "claims"],
                      "properties": {"body": spec.type("guide")["schema"], "claims": CLAIMS}}}
    place = {"wikidata": {"type": "string", "pattern": "^Q[1-9][0-9]*$"},
             "osm": {"type": "string", "pattern": "^(node|way|relation)/[1-9][0-9]*$"},
             "name": {"type": "string", "minLength": 2, "maxLength": 120},
             "local_name": {"type": "object", "additionalProperties": False, "required": ["lang", "name"],
                            "properties": {"lang": {"type": "string"}, "name": {"type": "string"}}},
             "kind": {"enum": list(spec.places["kinds"])},
             "size": {"enum": list(spec.places["sizes"])},
             "ordinary": {"type": "boolean"},
             "stories": {"type": "array", "minItems": 1, "items": item["story"]},
             "guide": item["guide"]}
    new_place = {"type": "object", "additionalProperties": False,
                 "required": ["name", "kind", "size", "ordinary", "stories", "guide"],
                 "anyOf": [{"required": ["wikidata"]}, {"required": ["osm"]}], "properties": place}
    existing = {"type": "object", "additionalProperties": False, "required": ["existing", "ordinary", "stories"],
                "properties": {"existing": {"type": "string", "pattern": "^pl_"}, "ordinary": {"type": "boolean"},
                               "stories": place["stories"], "guide": item["guide"]}}
    lead = {"type": "object", "additionalProperties": False, "required": ["lead", "status"],
            "properties": {"lead": {"type": "string", "pattern": "^ld_"},
                           "status": {"enum": ["added", "known", "skipped", "later"]},
                           "place": {"type": "integer", "minimum": 0},
                           "existing": {"type": "string", "pattern": "^pl_"},
                           "reason": {"type": "string", "minLength": 5, "maxLength": 300}}}
    return {"type": "object", "additionalProperties": False, "required": ["places", "leads", "notes"],
            "properties": {"places": {"type": "array", "items": {"oneOf": [new_place, existing]}},
                           "leads": {"type": "array", "items": lead}, "notes": NOTE}}


def review() -> dict[str, Any]:
    """One mark per item, good, weak, or bad, with the reason, and for a good item the cut it needs, if any."""
    decision = {"type": "object", "additionalProperties": False, "required": ["revision", "mark", "reason", "fix"],
                "properties": {"revision": {"type": "string", "pattern": "^rv_"},
                               "mark": {"enum": ["good", "weak", "bad"]}, "reason": NOTE,
                               "fix": {"anyOf": [NOTE, {"type": "null"}]}}}
    return {"type": "object", "additionalProperties": False, "required": ["decisions", "notes"],
            "properties": {"decisions": {"type": "array", "items": decision}, "notes": NOTE}}


def photos() -> dict[str, Any]:
    choice = {"type": "object", "additionalProperties": False, "required": ["key", "alt", "focus", "kind"],
              "properties": {"key": {"type": "string", "pattern": "^commons:File:.+"},
                             "alt": {"type": "string", "minLength": 10, "maxLength": 300},
                             "focus": {"type": "array", "minItems": 2, "maxItems": 2,
                                       "items": {"type": "number", "minimum": 0, "maximum": 1}},
                             "kind": {"enum": ["photo", "historic"]},
                             "year": {"type": "integer", "minimum": 1826, "maximum": 2100},
                             "pair": {"type": "string", "pattern": "^it_"}}}
    return {"type": "object", "additionalProperties": False, "required": ["choices", "notes"],
            "properties": {"choices": {"type": "array", "maxItems": 6, "items": choice}, "notes": NOTE}}
