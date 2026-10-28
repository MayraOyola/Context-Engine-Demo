"""RAG SSE stream contract tests."""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Tests old MCP-based RAG error handling; current impl uses direct redis search")
def test_rag_event_stream_emits_done_after_stream_answer_raises():
    pass
