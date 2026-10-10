"""Running one task through a model (decision 28). The pipeline fixes the order of steps; inside a judgment step the
model may call typed tools, within limits, and its answer is checked exactly as a worker's submission is checked.
Problems go back to the model a limited number of times; then the task is given back with the reason. Every model
call and tool call is traced with its tokens, cost, and the prompt and tool versions that produced it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from psst.cli import tasks as task_cli
from psst.core import db
from psst.tasks import files, prompts

from . import providers, quotes, tools

Connection = psycopg.Connection[dict[str, Any]]

# Task data every item of a step shares: it goes first and unchanged, so providers can cache it.
SHARED = ("golden_bar", "marked_examples", "reference_stories", "rules")

PREAMBLE = """You work inside an automated pipeline, not a terminal. Where the instructions below mention commands,
use the tools instead: fetch_source reads and saves a page (`psst fetch`), search_snapshot finds a passage in a saved
page, lookup_wikidata and find_osm identify a place (`psst place find`), nearby_places shows what the platform already
has nearby, and check_draft runs the tool checks on a draft. Quote only from snapshots you fetched or were given.
Never guess a web address: read the pages you were given and follow the links they list, such as an article's
references to heritage listings, archives, and histories.
When you are done, reply with only the JSON result, in the shape `result_schema` gives, and nothing else. It is
checked exactly as a submission is; if anything must be fixed you will be told, and you fix it and answer again."""


@dataclass
class Limits:
    """What one item may use in a step."""
    tool_calls: int = 12
    fixes: int = 2
    tokens: int = 400_000          # input and output over every call for the item
    reply_tokens: int = 8000
    reasoning: str | None = None   # "off" or "low" for a step that needs craft more than deliberation


STEP_LIMITS = {
    "tier_check": Limits(tool_calls=0, fixes=1, tokens=60_000, reply_tokens=600),
    "calibrate": Limits(tool_calls=0, fixes=2, tokens=400_000, reply_tokens=16000),
    "review": Limits(tool_calls=6, fixes=2, tokens=500_000, reply_tokens=12000),
    "audit": Limits(tool_calls=4, fixes=2, tokens=500_000, reply_tokens=8000),
    "revise": Limits(tool_calls=10, fixes=3, tokens=400_000, reply_tokens=8000),
    "triage": Limits(tool_calls=0, fixes=1, tokens=200_000, reply_tokens=32000, reasoning="off"),
    "evidence": Limits(tool_calls=0, fixes=1, tokens=60_000, reply_tokens=8000, reasoning="off"),
    "write": Limits(tool_calls=0, fixes=1, tokens=40_000, reply_tokens=4000, reasoning="off"),
}
STEP_TOOLS = {
    "tier_check": [],
    "calibrate": [],
    "review": ["search_snapshot", "fetch_source"],
    "audit": ["search_snapshot"],
    "revise": ["search_snapshot", "fetch_source", "check_draft"],
    "triage": [],
    "evidence": [],
    "write": [],
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


CREDIT_SECONDS = 300
_credit_checked = 0.0


def check_credit(conn: Connection, token: str) -> None:
    """Every few minutes, ask the provider what the key has spent and the account has left, record it for the console,
    and stop when the key has reached the budget by the provider's own count or the account is nearly empty."""
    global _credit_checked
    import time
    if time.monotonic() - _credit_checked < CREDIT_SECONDS:
        return
    _credit_checked = time.monotonic()
    try:
        credit = providers.credit()
    except OSError:
        return
    if credit is None:
        return
    conn.execute("SELECT psst.record_harness_credit(%s, %s)", (token, Jsonb(credit)))
    budget = conn.execute("SELECT psst.setting('harness.budget_usd') AS b").fetchone()
    if budget and credit["key_spent"] >= float(budget["b"]):
        raise BudgetReached(f"the provider counts {credit['key_spent']:.4f} USD spent on this key")
    if credit["account_remaining"] < ACCOUNT_RESERVE_USD:
        raise BudgetReached(f"only {credit['account_remaining']:.2f} USD of credit is left on the account")


ACCOUNT_RESERVE_USD = 2.0  # never run the provider account dry mid-task


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
    window = conn.execute("SELECT psst.harness_window() AS w").fetchone()
    if window and window["w"] and float(window["w"]["spent"]) >= float(window["w"]["usd"]):
        raise BudgetReached(f"spent {float(window['w']['spent']):.4f} of the window's {window['w']['usd']} USD")
    if city_id is not None and float(spent["city_total"]) >= float(spent["city_budget"] or 0):
        raise BudgetReached(f"the city's budget of {spent['city_budget'] or 0} USD is spent")
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
    def __init__(self, token: str, model: str, max_places: int = 12) -> None:
        self.token, self.model, self.max_places = token, model, max_places
        # A panel (vote:) marks together; a rotation (rotate:) takes turns writing, one model per place.
        self.mode = model.partition(":")[0] if model.startswith(("vote:", "rotate:")) else "one"
        self.members = model.partition(":")[2].split("+") if self.mode != "one" else []
        providers.check(model)
        self.provider = self.mode if self.members else providers.split(model)[0]
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
                check_credit(conn, self.token)
            if spend.tokens >= limits.tokens:
                raise GaveUp(f"used {spend.tokens} tokens, over the step's limit of {limits.tokens}")
            offer = definitions if tool_calls < limits.tool_calls else None
            error: str | None = None
            try:
                reply = providers.chat(self.model, messages, offer, limits.reply_tokens, json_only=not offer,
                                       reasoning=limits.reasoning)
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
                    started = time.monotonic()
                    output = tools.call(ctx, c.name, c.arguments)
                    ran.append({"tool": c.name, "input": c.arguments, "output": output, "error": output.get("error"),
                                "latency_ms": int((time.monotonic() - started) * 1000)})
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
            if answer is None and step in PROSE_IS_SKIP and reply.text.strip() and not reply.cut_off \
                    and not TOOL_MARKUP.search(reply.text):  # words that imitate a tool call are no answer
                answer = {"skip": reply.text.strip()[:300]}  # a model declining in words is declining
            try:
                if reply.cut_off:
                    raise task_cli.NotSubmitted(["your answer was cut off at the length limit; answer again more "
                                                 "briefly (short reasons, nothing the result doesn't need)"])
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
                "output_tokens": reply.output_tokens if reply else 0,
                "reasoning_tokens": reply.reasoning_tokens if reply else 0, "cost_usd": reply.cost_usd if reply else 0,
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
            if step == "research_cell" and self.mode == "vote":
                raise GaveUp("research is written by one model or a rotation, not a panel")
            if step == "research_cell":
                from .research import research_cell
                outcome = research_cell(self, task, document, spend)
            elif self.mode == "vote":
                outcome = self.vote(task, document, spend)
            elif self.mode == "rotate":
                raise GaveUp(f"{step} is done by one model or a panel, not a rotation")
            else:
                system, user, prompt_version = self.messages_for(document)
                ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=self.token,
                                    place_id=task.get("place_id"),
                                    item_id=task.get("item_id"))
                def accept(answer: dict[str, Any]) -> Any:
                    if step == "review":
                        self.confirm_featured(task, document, answer, spend)
                    if step == "revise":
                        stats, repairs = quotes.repair(ctx.conn, answer, ctx.read | _snapshots_in(document))
                        ctx.conn.execute("SELECT psst.record_quote_repairs(%s, %s, %s, %s, %s, %s, %s)",
                                         (self.token, task["id"], task.get("place_id"), self.model,
                                          spend.trace[-1], Jsonb(stats), Jsonb(repairs)))
                    return task_cli.submit(document, answer)
                try:
                    outcome = self.converse(step, system, user, task, prompt_version, accept, ctx, spend)
                finally:
                    ctx.conn.close()
        except GaveUp as reason:
            self.give_back(document, str(reason))
            return {"task": task["id"], "outcome": "returned", "reason": str(reason), "cost_usd": spend.cost_usd}
        return {"task": task["id"], "outcome": outcome, "calls": spend.calls, "tokens": spend.tokens,
                "cost_usd": round(spend.cost_usd, 6)}

    def vote(self, task: dict[str, Any], document: dict[str, Any], spend: Spend) -> Any:
        """A panel of models marks the same items; each item takes the majority's mark and tier, and the combined
        answer is checked and submitted like any other (decision 29). Only review and calibration vote."""
        step = document["type"]
        if step not in VOTING:
            raise GaveUp(f"{step} is done by one model, not a panel")
        system, user, prompt_version = self.messages_for(document)
        answers = []
        for member in self.members:
            ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=self.token,
                                place_id=task.get("place_id"), item_id=task.get("item_id"))
            try:
                answers.append(Executor(self.token, member).converse(
                    step, system, user, task, prompt_version, lambda a: _checked(document, a), ctx, spend))
            except GaveUp:
                continue  # a member that can't answer properly doesn't vote
            finally:
                ctx.conn.close()
        if len(answers) * 2 <= len(self.members):
            raise GaveUp(f"only {len(answers)} of {len(self.members)} models gave a usable answer")
        combined = combine(step, answers)
        if step == "review":
            self.confirm_featured(task, document, combined, spend)
        return task_cli.submit(document, combined)

    def confirm_featured(self, task: dict[str, Any], document: dict[str, Any], answer: dict[str, Any],
                         spend: Spend) -> None:
        """A story tiered featured leads the feed only when a second model agrees; otherwise it publishes as a map
        story (decision 30). The second model is routing.tier_check, never the reviewer itself."""
        featured = [d for d in answer.get("decisions", []) if d.get("mark") == "good" and d.get("tier") == "featured"]
        if not featured:
            return
        with db.connect("worker") as conn:
            # A featured story keeps two independent sources (decision 35); one resting on its record alone is a map
            # story, whatever its surprise.
            sources = {r["revision_id"]: r["n"] for r in conn.execute("""
                SELECT c.revision_id, count(DISTINCT n.source_id) AS n FROM psst.claims c
                JOIN psst.evidence e ON e.claim_id = c.id JOIN psst.snapshots n ON n.id = e.snapshot_id
                WHERE c.revision_id = ANY(%s) GROUP BY 1""", ([d["revision"] for d in featured],))}
            for d in featured:
                if sources.get(d["revision"], 0) < 2:
                    d["tier"] = "map"
            featured = [d for d in featured if d["tier"] == "featured"]
            if not featured:
                return
            row = conn.execute("SELECT psst.setting('routing.tier_check') #>> '{}' AS m").fetchone()
        second = row["m"] if row else None
        if not second or second == self.model or second in self.members:
            for d in featured:
                d["tier"] = "map"  # no independent second reader: it doesn't lead the feed
            return
        prompt = prompts.load("tier_check").text
        examples = [{k: e.get(k) for k in ("headline", "short", "tier")}
                    for e in document["data"].get("marked_examples", []) if e.get("tier")]
        system = prompt + "\n\n## Shared data\n\n" + json.dumps({"marked_examples": examples}, ensure_ascii=False)
        items = {i["revision"]: i for i in document["data"]["items"]}
        checker = Executor(self.token, second)
        for d in featured:
            body = items.get(d["revision"], {}).get("body", {})
            user = json.dumps({"story": {k: body.get(k) for k in ("headline", "short", "long", "look")}},
                              ensure_ascii=False)
            ctx = tools.Context(conn=db.open_connection(db.conninfo("worker"), autocommit=True), token=self.token)
            try:
                verdict = checker.converse("tier_check", system, user, task, version(prompt),
                                           _tier_answer, ctx, spend)
            except GaveUp:
                verdict = {"tier": "map"}
            finally:
                ctx.conn.close()
            if verdict["tier"] != "featured":
                d["tier"] = "map"

    def give_back(self, document: dict[str, Any], reason: str) -> None:
        with db.connect("worker") as conn:
            conn.execute("SELECT psst.return_task(%s, %s, %s)", (self.token, document["task"], reason[:1000]))


TOOL_MARKUP = re.compile(r"<(?:invoke|parameter|function_calls|tool_call)\b")
PROSE_IS_SKIP = {"evidence"}  # steps where an answer in words instead of JSON means the place has no story
VOTING = {"review": ("decisions", "revision"), "calibrate": ("marks", "golden")}


def _checked(document: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    found = task_cli.problems(document, answer)
    if found:
        raise task_cli.NotSubmitted(found)
    return answer


def combine(step: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Each item gets the mark most of the panel gave and, among them, the tier most gave; its reason and cut come
    from the first member in that majority. A tie on the mark goes to the stricter mark."""
    listing, key = VOTING[step]
    strictness = {"bad": 0, "weak": 1, "good": 2}
    by_item: dict[str, list[dict[str, Any]]] = {}
    for answer in answers:
        for entry in answer[listing]:
            by_item.setdefault(entry[key], []).append(entry)
    combined = []
    for entries in by_item.values():
        marks = [e["mark"] for e in entries]
        mark = min(set(marks), key=lambda m: (-marks.count(m), strictness[m]))
        agreeing = [e for e in entries if e["mark"] == mark]
        tiers = [e.get("tier") for e in agreeing]
        tier = max(set(tiers), key=lambda x: (tiers.count(x), x == "featured"))
        chosen = next(e for e in agreeing if e.get("tier") == tier)
        combined.append(chosen | {"mark": mark, "tier": tier})
    notes = " / ".join(a.get("notes", "") for a in answers if a.get("notes"))[:600] or "Marked by a panel."
    return {listing: combined, "notes": notes}


def _snapshots_in(document: dict[str, Any]) -> set[str]:
    """Snapshot ids a task file gives (a revision's sources), so a revision can quote them exactly."""
    return set(re.findall(r"\bsn_[0-9a-hjkmnp-tv-z]{10}\b", json.dumps(document["data"])))


def _tier_answer(answer: dict[str, Any]) -> dict[str, Any]:
    if answer.get("tier") not in ("featured", "map"):
        raise task_cli.NotSubmitted(['answer {"tier": "featured" or "map", "reason": ...}'])
    return answer

