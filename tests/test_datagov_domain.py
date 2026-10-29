from __future__ import annotations

import asyncio
from datetime import timedelta

from domains.datagov import memory_tools, native_ttl, retention
from domains.datagov.domain import DOMAIN


class FakeMemoryService:
    def __init__(self, memories=None):
        self.memories = list(memories or [])

    async def asearch_long_term_memory(self, *, text, owner_id, limit=None, **_):
        return [m for m in self.memories if m["ownerId"] == owner_id][: limit or 100]

    def delete_long_term_memory(self, *, owner_id, memory_id):
        self.memories = [m for m in self.memories if m["id"] != memory_id]


class FakeRedis:
    def __init__(self):
        self.events = []

    def xadd(self, stream, event, maxlen=None):
        self.events.append({"stream": stream, **event})


class FakeKeyspace:
    def __init__(self, ttls):
        self.ttls = dict(ttls)

    def ttl(self, key):
        return self.ttls.get(key, -2)

    def expire(self, key, seconds):
        self.ttls[key] = seconds


class FakeSettings:
    memory_store_id = "store1"


def _memory(mid, category, days_ago, status="active", products=("Company Fundamentals",)):
    event_date = retention.today() - timedelta(days=days_ago)
    attrs = retention.seed_attributes(category, event_date, f"{category} event", ["follow_up"], list(products))
    attrs["status"] = status
    return {"id": mid, "ownerId": "E1001", "text": category, "memoryType": retention.MEMORY_TYPE, "attributes": attrs}


def test_tiers_span_a_week_to_a_year():
    days = {c: t.days for c, t in retention.TIERS.items()}
    assert days == {
        "data_incident": 7,
        "access_request": 30,
        "project_work": 90,
        "migration_deprecation": 180,
        "regulatory_audit": 365,
    }


def test_three_users_have_separate_seed_sets_and_priya_has_an_expired_one():
    sets = DOMAIN.seed_memory_sets()
    assert set(sets) == {m["id"] for m in DOMAIN.demo_members} == {"E1001", "E1002", "E1003"}
    views = [retention.describe({"id": str(i), "attributes": s.attributes}) for i, s in enumerate(sets["E1001"])]
    assert [v["category"] for v in views] == ["data_incident", "project_work", "access_request"]
    assert [v["expired"] for v in views] == [False, False, True]
    assert all(not retention.is_inactive({"attributes": s.attributes}) for o in ("E1002", "E1003") for s in sets[o])


def test_filter_hides_expired_resolved_and_superseded():
    memories = [
        _memory("incident", "data_incident", 3),
        _memory("incident-resolved", "data_incident", 0, status="resolved"),
        _memory("old-access", "access_request", 40),
        _memory("project", "project_work", 20),
    ]
    kept, hidden = DOMAIN.filter_long_term_memories(memories)
    assert [m["id"] for m in kept] == ["project"]
    assert {h["id"]: h["reason"] for h in hidden} == {
        "incident": "superseded by a resolved memory",
        "incident-resolved": "resolved",
        "old-access": "expired",
    }


def test_sweep_deletes_expired_resolved_and_superseded(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(memory_tools, "create_redis_client", lambda s: redis)
    service = FakeMemoryService(
        [
            _memory("keep", "project_work", 20),
            _memory("old-access", "access_request", 40),
            _memory("inc", "data_incident", 3),
            _memory("inc-resolved", "data_incident", 0, status="resolved"),
        ]
    )
    out = asyncio.run(memory_tools.sweep_expired_memory(service, None, "E1001"))
    assert {d["id"] for d in out["deleted"]} == {"old-access", "inc", "inc-resolved"}
    assert {m["id"] for m in service.memories} == {"keep"}
    assert {e["action"] for e in redis.events} == {"expire", "superseded", "resolved"}


def test_reconcile_gives_each_memory_its_own_ttl(monkeypatch):
    incident = _memory("i", "data_incident", 3)  # 4 days left
    project = _memory("p", "project_work", 20)  # 70 days left
    year = 365 * 86400
    keyspace = FakeKeyspace({native_ttl.memory_key("store1", k): year for k in ("i", "p")})
    monkeypatch.setattr(native_ttl, "create_redis_client", lambda s: keyspace)
    report = native_ttl.reconcile_ttls(FakeSettings(), [incident, project])
    days = {c["id"]: c["ttl_days"] for c in report}
    assert 3 < days["i"] <= 5 and 69 < days["p"] <= 71
    assert all(c["set_now"] for c in report)


def test_card_keeps_only_the_fields_worth_showing():
    memory = {
        "id": "m1",
        "text": "User's model uses Company Fundamentals.",
        "memoryType": "context_event",
        "namespace": "demo",
        "ownerId": "E1001",
        "createdAt": "2026-10-01T00:00:00Z",
        "attributes": {
            "context_category": "project_work",
            "event_summary": "duplicate of text",
            "event_date": "2026-10-01",
            "retention_days": 90,
            "expires_on": "2026-12-30",
            "related_data_products": ["Company Fundamentals"],
            "likely_follow_ups": ["lineage_check"],
            "status": "active",
        },
    }
    card = retention.card(memory)
    assert set(card) == {
        "id", "text", "category", "status", "expires", "days_remaining", "likely_follow_ups", "related_data_products",
    }
    assert card["category"] == "project_work"
