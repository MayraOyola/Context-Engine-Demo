"""Context-aware retention for user context stored in Redis Agent Memory.

Agent Memory's own extraction (the `context_event` custom memory type) creates each memory with
structured attributes: context_category, event_date, retention_days, expires_on,
related_data_products, likely_follow_ups and status. The service applies one long-term TTL to every memory, so the
per-context window is enforced here: expired or resolved memories are hidden when read, and the
sweep deletes them from Agent Memory with an audit entry. Set the service's long-term TTL above the
longest window so these windows govern.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

AUDIT_STREAM = "datagov:memory_audit"
MEMORY_TYPE = "context_event"


@dataclass(frozen=True)
class RetentionTier:
    category: str
    days: int
    description: str


TIERS: dict[str, RetentionTier] = {
    t.category: t
    for t in (
        RetentionTier("data_incident", 7, "A data quality incident or outage affecting the user's current work"),
        RetentionTier("access_request", 30, "A new or pending data access request, or time-boxed access"),
        RetentionTier("project_work", 90, "An active analysis, model or pipeline project using specific data products"),
        RetentionTier("migration_deprecation", 180, "A data product deprecation or a migration the user must complete"),
        RetentionTier("regulatory_audit", 365, "Audit, compliance or licensing obligations that follow the user for a year"),
    )
}


def today() -> date:
    return datetime.now(timezone.utc).date()


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def seed_attributes(category: str, event_date: date, summary: str, follow_ups: list[str], products: list[str]) -> dict[str, Any]:
    """Attributes in the same shape Agent Memory's extraction produces for context_event."""
    tier = TIERS[category]
    return {
        "context_category": category,
        "event_summary": summary,
        "event_date": event_date.isoformat(),
        "retention_days": tier.days,
        "expires_on": (event_date + timedelta(days=tier.days)).isoformat(),
        "related_data_products": products,
        "likely_follow_ups": follow_ups,
        "status": "active",
    }


def is_managed(memory: dict[str, Any]) -> bool:
    """True for memories that carry a retention window (context_event memories)."""
    return _parse_date((memory.get("attributes") or {}).get("expires_on")) is not None


def describe(memory: dict[str, Any], *, as_of: date | None = None) -> dict[str, Any]:
    """Memory record plus parsed retention fields and days remaining."""
    as_of = as_of or today()
    attrs = memory.get("attributes") or {}
    expires = _parse_date(attrs.get("expires_on"))
    days_left = (expires - as_of).days if expires else None
    resolved = str(attrs.get("status", "active")).lower() == "resolved"
    reasons = attrs.get("likely_follow_ups") or []
    products = attrs.get("related_data_products") or []
    return {
        "id": memory.get("id"),
        "text": memory.get("text"),
        "category": attrs.get("context_category"),
        "retention_days": attrs.get("retention_days"),
        "event_date": attrs.get("event_date"),
        "expires": expires.isoformat() if expires else None,
        "days_remaining": days_left,
        "likely_follow_ups": list(reasons) if isinstance(reasons, list) else [str(reasons)],
        "status": attrs.get("status", "active"),
        "expired": days_left is not None and days_left < 0,
        "resolved": resolved,
    }


def superseded_ids(memories: list[dict[str, Any]]) -> set[str]:
    """Active memories replaced by a newer resolved memory in the same context category.

    Agent Memory updates only change a memory's text, never its attributes, so a recovery arrives
    as a new `resolved` context_event. The older active memory for that context is then stale.
    """
    resolved: list[tuple[str, date]] = []
    for m in memories:
        attrs = m.get("attributes") or {}
        if str(attrs.get("status", "")).lower() == "resolved" and attrs.get("context_category"):
            when = _parse_date(attrs.get("event_date"))
            if when:
                resolved.append((str(attrs["context_category"]), when))
    stale: set[str] = set()
    for m in memories:
        attrs = m.get("attributes") or {}
        if str(attrs.get("status", "active")).lower() == "resolved" or not m.get("id"):
            continue
        started = _parse_date(attrs.get("event_date"))
        category = attrs.get("context_category")
        if started and any(c == category and when >= started for c, when in resolved):
            stale.add(str(m["id"]))
    return stale


def is_inactive(memory: dict[str, Any], *, as_of: date | None = None) -> bool:
    """Past its retention window, or marked resolved: not served to the agent, deleted by the sweep."""
    view = describe(memory, as_of=as_of)
    return bool(view["expired"] or view["resolved"])
