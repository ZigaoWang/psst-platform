"""Running one task through a model (decision 28). The pipeline fixes the order of steps; inside a judgment step the
model may call typed tools, within limits, and its answer is checked exactly as a worker's submission is checked.
Problems go back to the model a limited number of times; then the task is given back with the reason. Every model
call and tool call is traced with its tokens, cost, and the prompt and tool versions that produced it."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst.cli import tasks as task_cli
from psst.core import db
from psst.tasks import files

from . import providers, tools

Connection = psycopg.Connection[dict[str, Any]]

# Task data every item of a step shares: it goes first and unchanged, so providers can cache it.
SHARED = ("golden_bar", "marked_examples", "reference_stories", "rules", "research_brief")

PREAMBLE = """You work inside an automated pipeline, not a terminal. Where the instructions below mention commands,
use the tools instead: fetch_source reads and saves a page (`psst fetch`), search_snapshot finds a passage in a saved
page, lookup_wikidata and find_osm identify a place (`psst place find`), nearby_places shows what the platform already
has nearby, and check_draft runs the tool checks on a draft. Quote only from snapshots you fetched or were given.
When you are done, reply with only the JSON result, in the shape `result_schema` gives, and nothing else. It is
checked exactly as a submission is; if anything must be fixed you will be told, and you fix it and answer again."""


@dataclass
class Limits:
    """What one item may use in a step."""
    tool_calls: int = 12
    fixes: int = 2
    tokens: int = 400_000          # input and output over every call for the item
    reply_tokens: int = 8000


STEP_LIMITS = {
    "calibrate": Limits(tool_calls=0, fixes=2, tokens=300_000, reply_tokens=8000),
    "review": Limits(tool_calls=6, fixes=2, tokens=500_000, reply_tokens=12000),
    "audit": Limits(tool_calls=4, fixes=2, tokens=500_000, reply_tokens=8000),
    "revise": Limits(tool_calls=10, fixes=3, tokens=400_000, reply_tokens=8000),
    "triage": Limits(tool_calls=0, fixes=2, tokens=300_000, reply_tokens=12000),
    "write": Limits(tool_calls=14, fixes=3, tokens=500_000, reply_tokens=8000),
}
STEP_TOOLS = {
    "calibrate": [],
    "review": ["search_snapshot", "fetch_source"],
    "audit": ["search_snapshot"],
    "revise": ["search_snapshot", "fetch_source", "check_draft"],
    "triage": [],
    "write": ["fetch_source", "search_snapshot", "lookup_wikidata", "find_osm", "nearby_places", "check_draft"],
}


class BudgetReached(RuntimeError):
    pass


class GaveUp(RuntimeError):
    pass


@dataclass
class Spend:
    calls: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    trace: list[int] = field(default_factory=list)


def version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def check_budget(conn: Connection, city_id: int | None) -> None:
    """Stop before spending past the total budget or a city's daily or monthly budget."""
    row = conn.execute("""SELECT psst.harness_spend(%s) AS s, psst.setting('harness.budget_usd') AS total,
                                 psst.setting('harness.city_daily_usd') AS daily,
                                 psst.setting('harness.city_monthly_usd') AS monthly,
                                 psst.setting('harness.paused') AS paused""", (city_id,)).fetchone()
    assert row
    spent = row["s"]
    if row["paused"] is True:
        raise BudgetReached("the harness is paused")
    if float(spent["total"]) >= float(row["total"]):
        raise BudgetReached(f"spent {float(spent['total']):.4f} of the {row['total']} USD budget")
    if city_id is not None and row["daily"] is not None and float(spent["city_today"]) >= float(row["daily"]):
        raise BudgetReached(f"the city's daily budget of {row['daily']} USD is spent")
    if city_id is not None and row["monthly"] is not None and float(spent["city_month"]) >= float(row["monthly"]):
        raise BudgetReached(f"the city's monthly budget of {row['monthly']} USD is spent")


def parse_json(text: str) -> dict[str, Any] | None:
    """The JSON answer, with or without a code fence around it."""
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.S)
    if fenced:
        stripped = fenced.group(1).strip()
    start = stripped.find("{")
    if start < 0:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class Executor:
    def __init__(self, token: str, model: str) -> None:
        self.token, self.model = token, model
        self.provider = providers.split(model)[0]
        os.environ["PSST_RUN_TOKEN"] = token  # the command-line helpers the harness shares read it

    # Model calls ---------------------------------------------------------------------------------------------

    def converse(self, step: str, system: str, user: str, task: dict[str, Any], prompt_version: str,
                 accept: Any, ctx: tools.Context, spend: Spend) -> Any:
        """One judgment step: call the model, run the tools it asks for, and hand its answer to `accept`, which
        returns the outcome or raises task_cli.NotSubmitted with the problems to send back."""
        limits, names = STEP_LIMITS[step], STEP_TOOLS[step]
        definitions = tools.definitions(names)
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tool_calls = fixes = 0
        while True:
            with db.connect("worker") as conn:
                check_budget(conn, task.get("city_id"))
            if spend.tokens >= limits.tokens:
                raise GaveUp(f"used {spend.tokens} tokens, over the step's limit of {limits.tokens}")
            offer = definitions if tool_calls < limits.tool_calls else None
            error: str | None = None
            try:
                reply = providers.chat(self.model, messages, offer, limits.reply_tokens, json_only=not offer)
            except providers.ProviderError as failure:
                error, reply = str(failure), None
            ran: list[dict[str, Any]] = []
            if reply is not None and reply.tool_calls:
                assistant = {"role": "assistant", "content": reply.text or None,
                             "tool_calls": [{"id": c.id, "type": "function",
                                             "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                            for c in reply.tool_calls]}
                messages.append(assistant)
                for c in reply.tool_calls:
                    output = tools.call(ctx, c.name, c.arguments)
                    ran.append({"tool": c.name, "input": c.arguments, "output": output, "error": output.get("error")})
                    messages.append({"role": "tool", "tool_call_id": c.id,
                                     "content": json.dumps(output, ensure_ascii=False)[:40000]})
                    tool_calls += 1
            self.record(step, task, prompt_version, messages, reply, error, ran, spend)
            if reply is None:
                raise GaveUp(f"the model didn't answer: {error}")
            if reply.tool_calls:
                continue
            messages.append({"role": "assistant", "content": reply.text})
            answer = parse_json(reply.text)
            try:
                if answer is None:
                    raise task_cli.NotSubmitted(["reply with only the JSON result, in the shape result_schema gives"])
                return accept(answer)
            except task_cli.NotSubmitted as problems:
                fixes += 1
                if fixes > limits.fixes:
                    raise GaveUp("still not right after the fixes allowed: "
                                 + "; ".join(problems.found)[:900]) from None
                messages.append({"role": "user", "content": "Not submitted. Fix these and answer again with the "
                                 "whole JSON result:\n" + "\n".join(f"- {p}" for p in problems.found)})

    def record(self, step: str, task: dict[str, Any], prompt_version: str, messages: list[dict[str, Any]],
               reply: providers.Reply | None, error: str | None, ran: list[dict[str, Any]], spend: Spend) -> None:
        spent_now = reply.input_tokens + reply.output_tokens if reply else 0
        spend.calls += 1
        spend.tokens += spent_now
        spend.cost_usd += reply.cost_usd if reply else 0
        call = {"task": task.get("id"), "city": task.get("city_id"), "step": step, "provider": self.provider,
                "model": self.model, "prompt_version": prompt_version, "tools_version": tools.VERSION,
                "request": {"messages": [m for m in messages if m["role"] != "system"][-6:]},
                "response": {"text": reply.text, "tool_calls": [c.__dict__ for c in reply.tool_calls]}
                if reply else None,
                "error": error, "tools": ran,
                "input_tokens": reply.input_tokens if reply else 0,
                "cached_tokens": reply.cached_tokens if reply else 0,
                "output_tokens": reply.output_tokens if reply else 0, "cost_usd": reply.cost_usd if reply else 0,
                "latency_ms": reply.latency_ms if reply else 0}
        with db.connect("worker") as conn:
            row = conn.execute("SELECT psst.record_harness_call(%s, %s) AS id", (self.token, Jsonb(call))).fetchone()
        if row:
            spend.trace.append(int(row["id"]))

    # Tasks ---------------------------------------------------------------------------------------------------

    def messages_for(self, document: dict[str, Any]) -> tuple[str, str, str]:
        """The system prompt (instructions and shared data, the same for every item of the step) and the item."""
        data = document["data"]
        shared = {k: data[k] for k in SHARED if k in data}
        system = PREAMBLE + "\n\n" + document["prompt"] + "\n\n## Shared data\n\n" + json.dumps(
            shared, ensure_ascii=False, sort_keys=True, default=str)
        item = {"task": document["task"], "type": document["type"],
                "data": {k: v for k, v in data.items() if k not in SHARED},
                "result_schema": document["result_schema"]}
        return system, json.dumps(item, ensure_ascii=False, default=str), version(PREAMBLE + document["prompt"])

    def run(self, task: dict[str, Any]) -> dict[str, Any]:
        """Do one leased task end to end and submit it, or give it back with the reason."""
        with db.connect("worker") as conn:
            document = files.build(conn, task, files.Lookups(task_cli._lead, task_cli._key_facts,
                                                             task_cli._photo_candidates, task_cli._photo_file))
        document = json.loads(json.dumps(document, default=str))
        spend = Spend()
        step = document["type"]
        try:
            if step == "research_cell":
                from .research import research_cell
                outcome = research_cell(self, task, document, spend)
            else:
                system, user, prompt_version = self.messages_for(document)
                ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=self.token,
                                    place_id=task.get("place_id"),
                                    item_id=task.get("item_id"))
                try:
                    outcome = self.converse(step, system, user, task, prompt_version,
                                            lambda answer: task_cli.submit(document, answer), ctx, spend)
                finally:
                    ctx.conn.close()
        except GaveUp as reason:
            self.give_back(document, str(reason))
            return {"task": task["id"], "outcome": "returned", "reason": str(reason), "cost_usd": spend.cost_usd}
        return {"task": task["id"], "outcome": outcome, "calls": spend.calls, "tokens": spend.tokens,
                "cost_usd": round(spend.cost_usd, 6)}

    def give_back(self, document: dict[str, Any], reason: str) -> None:
        with db.connect("worker") as conn:
            conn.execute("SELECT psst.return_task(%s, %s, %s)", (self.token, document["task"], reason[:1000]))
