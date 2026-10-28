from backend.app.memory_service import extract_memory_items, sanitize_actor_id, utc_now_iso


def test_sanitize_actor_id_replaces_underscores() -> None:
    assert sanitize_actor_id("CUST_DEMO_001") == "CUST-DEMO-001"


def test_sanitize_actor_id_collapses_invalid_characters() -> None:
    assert sanitize_actor_id(" user@demo / agent ") == "user-demo-agent"


def test_sanitize_actor_id_uses_fallback_when_empty() -> None:
    assert sanitize_actor_id("__", fallback="reddash-agent") == "reddash-agent"


def test_utc_now_iso_returns_utc_timestamp() -> None:
    assert utc_now_iso().endswith("Z")


def test_extract_memory_items_prefers_items() -> None:
    assert extract_memory_items({"items": [{"id": "1"}], "memories": [{"id": "legacy"}]}) == [{"id": "1"}]


def test_extract_memory_items_falls_back_to_memories() -> None:
    assert extract_memory_items({"memories": [{"id": "legacy"}]}) == [{"id": "legacy"}]


def test_extract_memory_items_handles_non_dict_payload() -> None:
    assert extract_memory_items(None) == []
