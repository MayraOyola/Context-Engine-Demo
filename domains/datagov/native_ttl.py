"""Per-record Redis expiry for context_event memories.

Agent Memory stores every long-term memory as its own Redis hash and gives all of them the store's
long-term TTL. A context_event carries its own window in `expires_on`, so this sets the Redis
key's TTL to match and Redis deletes the record, and its search index entry, when the window ends.

This writes to the service's own keys, which are not a documented API, and an Agent Memory update
re-applies the store TTL. It is therefore re-applied whenever memories are read.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.app.redis_connection import create_redis_client
from domains.datagov import retention

# Ignore differences under an hour so reads do not rewrite a TTL that is already right.
_TOLERANCE_SECONDS = 3600


def memory_key(store_id: str, memory_id: str) -> str:
    return f"memory:{store_id}:ltm:{memory_id}"


def seconds_until_end_of(day: date, *, now: datetime | None = None) -> int:
    """Seconds from now until the end of `day` (UTC), the last day the memory is valid."""
    now = now or datetime.now(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    return int((end - now).total_seconds())


def fast_forward(settings: Any, memory_id: str, seconds: int) -> bool:
    """Demo only: shrink one memory's key TTL so Redis expires it in `seconds`. Same EXPIRE, less time."""
    client = create_redis_client(settings)
    return bool(client.expire(memory_key(settings.memory_store_id, memory_id), seconds))


def reconcile_ttls(settings: Any, memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Set each active context_event's Redis key TTL to its expiry.

    Returns one entry per memory with the key's TTL in days, and `set_now` when this call had to
    change it (on later reads the TTL is already right, so `set_now` is false).
    """
    store_id = getattr(settings, "memory_store_id", "")
    if not store_id:
        return []
    client = None
    report: list[dict[str, Any]] = []
    for memory in memories:
        view = retention.describe(memory)
        if not view["expires"] or view["expired"] or not view["id"]:
            continue
        desired = seconds_until_end_of(date.fromisoformat(view["expires"]))
        if desired <= 0:
            continue
        client = client or create_redis_client(settings)
        key = memory_key(store_id, str(view["id"]))
        current = client.ttl(key)
        if current == -2:  # key not found
            continue
        # A key already inside its last hour is left alone, so a demo fast-forward is not undone.
        about_to_expire = 0 <= current < _TOLERANCE_SECONDS
        set_now = not about_to_expire and (current == -1 or abs(current - desired) > _TOLERANCE_SECONDS)
        if set_now:
            client.expire(key, desired)
        report.append(
            {
                "id": view["id"],
                "category": view["category"],
                "ttl_days": round((desired if set_now else current) / 86400, 1),
                "expires": view["expires"],
                "set_now": set_now,
            }
        )
    return report
