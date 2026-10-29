"""Helpers for the activity-panel trace: SSE encoding, timing and compact payloads.

The agent and the LLM always see the full tool results. The functions here only shape what is
streamed to the UI, dropping bookkeeping fields so each trace row shows what matters.
"""

from __future__ import annotations

import json
import logging
from time import perf_counter
from typing import Any

log = logging.getLogger("iris")


def sse(event_type: str, **fields: Any) -> str:
    return f"data: {json.dumps({'type': event_type, **fields})}\n\n"


class Timer:
    """Elapsed milliseconds since the request started, for the trace timeline."""

    def __init__(self) -> None:
        self._start = perf_counter()

    def elapsed_ms(self) -> int:
        return round((perf_counter() - self._start) * 1000)


def ms_since(start: float) -> int:
    return max(round((perf_counter() - start) * 1000), 1)


# ── Tool output handling ──────────────────────────────────────────────────────────


def parse_tool_output(raw_output: Any) -> dict[str, Any]:
    """Normalize a tool's raw output into a JSON-serializable dict."""
    if raw_output is None or raw_output == "":
        return {}
    if isinstance(raw_output, dict):
        return raw_output
    text = raw_output.content if hasattr(raw_output, "content") and isinstance(raw_output.content, str) else str(raw_output)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {"result": text}
    return parsed if isinstance(parsed, dict) else {"result": parsed}


def error_payload(error: Any) -> dict[str, str]:
    return {"error": str(error) or "Tool failed.", "type": error.__class__.__name__}


def pop_pending_tool(pending: dict[str, dict[str, Any]], *, run_id: str, name: str) -> dict[str, Any] | None:
    """Match a tool end/error event back to its start.

    LangGraph normally gives a stable run_id; when it does not, fall back to the oldest pending
    call with the same name so the trace resolves instead of showing "Running" forever.
    """
    if run_id and run_id in pending:
        return pending.pop(run_id)
    for key, entry in list(pending.items()):
        if name and entry.get("name") != name:
            continue
        return pending.pop(key)
    return None


# ── Compact payloads for the UI ───────────────────────────────────────────────────

_MCP_PAGING_KEYS = {"effective_match_mode", "effective_term_count", "limit", "offset"}


def _drop_key(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return {k: _drop_key(v, key) for k, v in value.items() if k != key}
    if isinstance(value, list):
        return [_drop_key(v, key) for v in value]
    return value


def compact_mcp_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Context Retriever result without its per-record `_retrieval` stamp and paging echo."""
    slim = _drop_key(payload, "_retrieval")
    if not isinstance(slim, dict):
        return slim
    slim = {k: v for k, v in slim.items() if k not in _MCP_PAGING_KEYS}
    if slim.get("has_more") is False:
        slim.pop("has_more")
    return slim


def compact_session_events(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Session (short-term) events reduced to who said what."""
    out = []
    for event in events:
        content = event.get("content")
        parts = content if isinstance(content, list) else []
        text = " ".join(str(p["text"]) for p in parts if isinstance(p, dict) and p.get("text")).strip()
        if text:
            out.append({"role": str(event.get("role", "USER")).upper(), "text": text})
    return out
