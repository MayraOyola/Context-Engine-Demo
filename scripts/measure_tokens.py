"""Measure OpenAI token usage for demo questions, one model call at a time.

Run it with semantic tool routing off and on to see how many tokens routing saves:

    TOOL_ROUTING_ENABLED=false uv run python scripts/measure_tokens.py "Why is my order running late?"
    TOOL_ROUTING_ENABLED=true  uv run python scripts/measure_tokens.py "Why is my order running late?"

LangCache is disabled for the run so answers are never served from (or written to) the cache.
Each question starts a new conversation.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from contextvars import ContextVar
from pathlib import Path

os.environ["LANGCACHE_HOST"] = ""  # measure the agent, not the cache

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from langchain_core.callbacks import BaseCallbackHandler  # noqa: E402
from langchain_core.tracers.context import register_configure_hook  # noqa: E402


class UsageCollector(BaseCallbackHandler):
    """Records (input_tokens, output_tokens) for every model call."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    def on_llm_end(self, response, **kwargs) -> None:  # type: ignore[override]
        for generations in response.generations:
            for generation in generations:
                usage = getattr(getattr(generation, "message", None), "usage_metadata", None)
                if usage:
                    self.calls.append((usage.get("input_tokens", 0), usage.get("output_tokens", 0)))


collector = UsageCollector()
_hook = ContextVar("usage_collector", default=None)
register_configure_hook(_hook, True)
_hook.set(collector)

from backend.app import main  # noqa: E402
from backend.app.contracts import ChatRequest  # noqa: E402


async def measure(question: str) -> dict:
    collector.calls.clear()
    request = ChatRequest(
        messages=[{"role": "user", "content": question}],
        mode="context_surfaces",
        thread_id=f"measure-{time.time_ns()}",
    )
    routing, error, started = None, None, time.time()
    async for chunk in main.cs_event_stream(request):
        if not chunk.startswith("data:"):
            continue
        event = json.loads(chunk[5:])
        if event.get("type") == "tool-result" and event.get("toolName") == "tool_routing":
            routing = event.get("payload")
        elif event.get("type") == "error":
            error = event.get("message", "")[:120]
    inputs = [i for i, _ in collector.calls]
    return {
        "question": question,
        "model_calls": len(inputs),
        "input_per_call": inputs,
        "total_tokens": sum(inputs) + sum(o for _, o in collector.calls),
        "routing": routing,
        "seconds": round(time.time() - started, 1),
        "error": error,
    }


async def run(questions: list[str]) -> None:
    routing_on = main.tool_routing_service.is_configured()
    print(f"Tool routing: {'ON' if routing_on else 'OFF'}   model: {main.settings.openai_chat_model}")
    grand_total = 0
    for question in questions:
        result = await measure(question)
        grand_total += result["total_tokens"]
        print(f"\nQ: {question}")
        if result["routing"]:
            r = result["routing"]
            names = [route["name"] for route in r["routes"]] or ["(no match: all tools)"]
            print(f"  routes: {names}  tools: {r['tools_selected']}/{r['tools_total']}")
        print(f"  model calls: {result['model_calls']}  input tokens per call: {result['input_per_call']}")
        print(f"  TOTAL tokens: {result['total_tokens']}   ({result['seconds']}s)")
        if result["error"]:
            print(f"  ERROR: {result['error']}")
    print(f"\nAll questions: {grand_total} tokens")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    asyncio.run(run(sys.argv[1:]))
