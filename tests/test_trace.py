from backend.app.trace import compact_mcp_result, compact_session_events


def test_compact_mcp_result_drops_bookkeeping_but_keeps_data():
    raw = {
        "count": 1,
        "effective_match_mode": "any",
        "effective_term_count": 2,
        "has_more": False,
        "limit": 10,
        "offset": 0,
        "results": [{"_retrieval": {"source": "x"}, "id": "INC-1", "status": "open"}],
    }
    assert compact_mcp_result(raw) == {"count": 1, "results": [{"id": "INC-1", "status": "open"}]}


def test_compact_mcp_result_keeps_has_more_when_true():
    assert compact_mcp_result({"count": 10, "has_more": True})["has_more"] is True


def test_compact_session_events_keeps_role_and_text():
    events = [
        {"role": "user", "eventId": "a", "content": [{"text": "hi"}, {"text": "there"}]},
        {"role": "ASSISTANT", "content": []},
    ]
    assert compact_session_events(events) == [{"role": "USER", "text": "hi there"}]
