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
    if task_type in ("check_claims_a", "check_claims_b", "escalate"):
        result = {"type": "object", "additionalProperties": False, "required": ["verdicts"],
                  "properties": {"verdicts": CLAIM_VERDICTS, "item": ITEM_VERDICT}}
        return result
    if task_type == "audit":
        return {"type": "object", "additionalProperties": False, "required": ["verdicts", "item"],
                "properties": {"verdicts": CLAIM_VERDICTS, "item": ITEM_VERDICT}}
    if task_type in ("check_item", "check_photo", "check_translation"):
        return {"type": "object", "additionalProperties": False, "required": ["verdict", "note", "untraced", "answers"],
                "properties": {
                    "verdict": {"enum": ["pass", "fail", "unclear"]}, "note": NOTE,
                    "untraced": {"type": "array", "items": {"type": "string"}},
                    "answers": {"type": "array", "items": {"type": "string"}},
                    "back_translation": {"type": "string"}}}
    if task_type in ("write_story", "write_guide", "write_trail"):
        return writing(task_type.removeprefix("write_"))
    if task_type == "revise":
        assert item_type
        if item_type == "translation":
            return translation()
        return writing(item_type)
    if task_type == "translate":
        return translation()
    raise KeyError(f"no result schema for {task_type}")


def translation() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["language", "body", "reason"],
            "properties": {"language": {"enum": rules.load().type("translation")["languages"]},
                           "body": {"type": "object"}, "translation_of": {"type": "string", "pattern": "^rv_"},
                           "reason": NOTE}}
