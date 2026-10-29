"""Agent-facing memory tools for user context, backed by real Agent Memory calls.

Every write and delete goes to the Redis Agent Memory service; each change is also
appended to a Redis stream so there is an audit trail of what the model stored and removed.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any

from backend.app.memory_service import MemoryService
from backend.app.redis_connection import create_redis_client
from domains.datagov import retention

MEMORY_TOOL_NAMES = {
    "search_user_memory",
    "retire_context_memory",
    "sweep_expired_memory",
}

_ALL_QUERY = "user context, projects, incidents and access"


async def _all_managed(service: MemoryService, owner_id: str) -> list[dict[str, Any]]:
    """Every memory for the owner that carries a retention window (context_event memories)."""
    items = await service.asearch_long_term_memory(
        text=_ALL_QUERY, owner_id=owner_id, limit=100, similarity_threshold=0.0
    )
    return [m for m in items if retention.is_managed(m)]


async def _audit(settings: Any, event: dict[str, str]) -> None:
    def _write() -> None:
        create_redis_client(settings).xadd(retention.AUDIT_STREAM, event, maxlen=1000)

    try:
        await asyncio.to_thread(_write)
    except Exception as exc:  # audit must not block the memory operation itself
        event["audit_error"] = str(exc)


async def search_user_memory(service: MemoryService, owner_id: str, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).strip()
    if not query:
        return {"error": "query is required"}
    limit = args.get("limit")
    memories = await service.asearch_long_term_memory(
        text=query, owner_id=owner_id, limit=int(limit) if limit is not None else None
    )
    stale = retention.superseded_ids(memories)
    live = [m for m in memories if not retention.is_inactive(m) and str(m.get("id")) not in stale]
    return {"memories": [retention.card(m) for m in live]}


async def retire_context_memory(
    service: MemoryService, settings: Any, owner_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    memory_id = str(args.get("memory_id", "")).strip()
    reason = str(args.get("reason", "")).strip() or "no longer relevant"
    if not memory_id:
        return {"error": "memory_id is required"}
    owned = {m.get("id"): m for m in await _all_managed(service, owner_id)}
    if memory_id not in owned:
        return {"error": "memory_id not found for this user"}
    await asyncio.to_thread(service.delete_long_term_memory, owner_id=owner_id, memory_id=memory_id)
    await _audit(settings, {
        "action": "retire", "memory_id": memory_id, "owner_id": owner_id, "reason": reason,
    })
    return {"retired": True, "memory": retention.card(owned[memory_id]), "reason": reason}


async def sweep_expired_memory(service: MemoryService, settings: Any, owner_id: str) -> dict[str, Any]:
    """Delete memories that Redis has not already expired: past window, resolved, or superseded."""
    managed = await _all_managed(service, owner_id)
    stale = retention.superseded_ids(managed)
    deleted: list[dict[str, Any]] = []
    kept: list[str] = []
    for memory in managed:
        view = retention.describe(memory)
        superseded = str(view["id"]) in stale
        if view["expired"] or view["resolved"] or superseded:
            await asyncio.to_thread(
                service.delete_long_term_memory, owner_id=owner_id, memory_id=str(view["id"])
            )
            action = "superseded" if superseded else ("resolved" if view["resolved"] and not view["expired"] else "expire")
            await _audit(settings, {
                "action": action, "memory_id": str(view["id"]), "owner_id": owner_id,
                "category": str(view["category"]), "expires": str(view["expires"]),
            })
            deleted.append({"id": view["id"], "text": view["text"], "category": view["category"], "reason": action})
        else:
            kept.append(str(view["id"]))
    return {"deleted": deleted, "kept": kept}
