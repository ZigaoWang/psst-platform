"""Model providers for the harness (decision 28). A model is named `<provider>:<model id>`, such as
`openrouter:qwen/qwen3.8-flash` or `anthropic:claude-haiku-5-5`. Every provider takes the same request (messages in
the OpenAI shape, optional tools, a token limit) and gives back the same reply: text, tool calls, tokens, cost, and
latency. Keys come only from the environment."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# OpenAI-compatible endpoints, each with the environment variable that holds its key.
OPENAI_COMPATIBLE = {
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "qwen": ("https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY"),
    "glm": ("https://open.bigmodel.cn/api/paas/v4", "ZHIPU_API_KEY"),
    "kimi": ("https://api.moonshot.ai/v1", "MOONSHOT_API_KEY"),
    "minimax": ("https://api.minimax.io/v1", "MINIMAX_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
}
ANTHROPIC = ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY")


class ProviderError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Reply:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    raw: dict[str, Any] = field(default_factory=dict)
    cut_off: bool = False   # the answer stopped at the length limit
    reasoning_tokens: int = 0


def split(model: str) -> tuple[str, str]:
    provider, _, name = model.partition(":")
    if not name or (provider not in OPENAI_COMPATIBLE and provider != "anthropic"):
        raise ProviderError(f"a harness model is <provider>:<model>, with a known provider; got {model!r}")
    return provider, name


def check(model: str) -> None:
    """A harness model, or a group of them (vote:<model>+<model>... or rotate:...), with known providers."""
    group = model.startswith(("vote:", "rotate:"))
    for member in (model.partition(":")[2].split("+") if group else [model]):
        split(member)


def chat(model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
         max_tokens: int = 4000, json_only: bool = False, timeout: int = 300, reasoning: str | None = None) -> Reply:
    """`reasoning` sets how much a reasoning model thinks before it answers: "off", "low", or None for its default."""
    provider, name = split(model)
    if provider == "anthropic":
        return _anthropic(name, messages, tools, max_tokens, timeout)
    return _openai(provider, name, messages, tools, max_tokens, json_only, timeout, reasoning)


def _post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: int) -> tuple[dict[str, Any], int]:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **headers})
    started = time.monotonic()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read()), int((time.monotonic() - started) * 1000)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:500]
            if error.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** attempt * 5)
                continue
            raise ProviderError(f"{error.code} from {url}: {detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt < 3:
                time.sleep(2 ** attempt * 5)
                continue
            raise ProviderError(f"no answer from {url}: {error}") from error
    raise ProviderError(f"no answer from {url}")


def _key(variable: str) -> str:
    key = os.environ.get(variable)
    if not key:
        raise ProviderError(f"{variable} isn't set")
    return key


def _openai(provider: str, name: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None,
            max_tokens: int, json_only: bool, timeout: int, reasoning: str | None = None) -> Reply:
    base, variable = OPENAI_COMPATIBLE[provider]
    body: dict[str, Any] = {"model": name, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    elif json_only:
        body["response_format"] = {"type": "json_object"}
    if provider == "openrouter":
        # Only providers that neither keep nor train on what is sent, fastest first.
        body["provider"] = {"data_collection": "deny", "sort": "throughput"}
        body["usage"] = {"include": True}
        if reasoning:
            body["reasoning"] = {"enabled": False} if reasoning == "off" else {"effort": reasoning}
    raw, latency = _post(f"{base}/chat/completions", body, {"Authorization": f"Bearer {_key(variable)}"}, timeout)
    if "error" in raw:
        raise ProviderError(f"{provider}: {raw['error']}")
    choice = raw["choices"][0]
    message = choice["message"]
    usage = raw.get("usage") or {}
    calls = [ToolCall(c["id"], c["function"]["name"], _arguments(c["function"].get("arguments")))
             for c in message.get("tool_calls") or []]
    return Reply(text=message.get("content") or "", tool_calls=calls,
                 input_tokens=int(usage.get("prompt_tokens") or 0),
                 cached_tokens=int((usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
                 output_tokens=int(usage.get("completion_tokens") or 0),
                 cost_usd=float(usage.get("cost") or 0), latency_ms=latency, raw=raw,
                 cut_off=choice.get("finish_reason") == "length",
                 reasoning_tokens=int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0))


def _arguments(text: str | None) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {"_unparsed": text}
    return value if isinstance(value, dict) else {"_value": value}


def _anthropic(name: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, max_tokens: int,
               timeout: int) -> Reply:
    """Anthropic's Messages API. The system prompt is cached, since it is the same for every item of a step."""
    base, variable = ANTHROPIC
    system = [{"type": "text", "text": m["content"], "cache_control": {"type": "ephemeral"}}
              for m in messages if m["role"] == "system"]
    converted: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "tool":
            converted.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": m["tool_call_id"],
                                                           "content": m["content"]}]})
        elif m.get("tool_calls"):
            content: list[dict[str, Any]] = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            content += [{"type": "tool_use", "id": c["id"], "name": c["function"]["name"],
                         "input": _arguments(c["function"]["arguments"])} for c in m["tool_calls"]]
            converted.append({"role": "assistant", "content": content})
        else:
            converted.append({"role": m["role"], "content": m["content"]})
    body: dict[str, Any] = {"model": name, "max_tokens": max_tokens, "system": system, "messages": converted}
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                         for t in tools]
    raw, latency = _post(f"{base}/messages", body,
                         {"x-api-key": _key(variable), "anthropic-version": "2023-06-01"}, timeout)
    text = "".join(b.get("text", "") for b in raw.get("content", []) if b["type"] == "text")
    calls = [ToolCall(b["id"], b["name"], b.get("input") or {}) for b in raw.get("content", [])
             if b["type"] == "tool_use"]
    usage = raw.get("usage") or {}
    cached = int(usage.get("cache_read_input_tokens") or 0)
    return Reply(text=text, tool_calls=calls,
                 input_tokens=int(usage.get("input_tokens") or 0) + cached
                 + int(usage.get("cache_creation_input_tokens") or 0),
                 cached_tokens=cached, output_tokens=int(usage.get("output_tokens") or 0), latency_ms=latency,
                 raw=raw)


def credit() -> dict[str, float] | None:
    """What is left on the OpenRouter key and account, when the key is set: the key's own spend, and the account's
    remaining credit."""
    key = os.environ.get(OPENAI_COMPATIBLE["openrouter"][1])
    if not key:
        return None
    base = OPENAI_COMPATIBLE["openrouter"][0]
    headers = {"Authorization": f"Bearer {key}"}
    with urllib.request.urlopen(urllib.request.Request(f"{base}/credits", headers=headers), timeout=30) as r:
        account = json.loads(r.read())["data"]
    with urllib.request.urlopen(urllib.request.Request(f"{base}/key", headers=headers), timeout=30) as r:
        own = json.loads(r.read())["data"]
    return {"key_spent": float(own.get("usage") or 0),
            "account_remaining": float(account["total_credits"]) - float(account["total_usage"])}
