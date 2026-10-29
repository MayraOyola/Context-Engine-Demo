"""FastAPI app: the chat stream plus the small endpoints the UI needs.

The chat turn itself lives in `chat.py` and the Redis Iris clients in `services.py`.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
from time import perf_counter
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from backend.app import services as svc
from backend.app.chat import cs_event_stream
from backend.app.contracts import ChatRequest
from backend.app.internal_tools import internal_tool_names
from backend.app.memory_service import MemoryService
from backend.app.redis_connection import create_redis_client
from backend.app.trace import compact_session_events, ms_since, sse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(name)s | %(message)s", datefmt="%H:%M:%S")

settings, domain = svc.settings, svc.domain
ROOT_DIR = Path(__file__).resolve().parents[2]

app = FastAPI(title=f"{domain.manifest.branding.app_name} Demo")

_LOCAL_ORIGINS = [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (3040, 3041)]
_extra_origins = [o.strip() for o in (settings.cors_origin or "").split(",") if o.strip() and o.strip() != "*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_origin.strip() == "*" else _LOCAL_ORIGINS + _extra_origins,
    allow_credentials=settings.cors_origin.strip() != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    await svc.warm_up()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await svc.close_all()


# ── Status and configuration ─────────────────────────────────────────────────────


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "domain": domain.manifest.id,
        "openai_configured": bool(settings.openai_api_key),
        "mcp_enabled": bool(settings.mcp_agent_key),
        "memory_enabled": svc.memory_service.is_configured(),
        "langcache_enabled": svc.langcache_service.is_configured(),
        "guardrail_enabled": svc.guardrail_service.is_configured(),
        "tool_routing_enabled": svc.tool_routing_service.is_configured(),
        "internal_tools": internal_tool_names(settings),
    })


def _logo_src(path: Path) -> str:
    mime = {".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}.get(
        path.suffix.lower(), "application/octet-stream"
    )
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


@app.get("/api/domain-config")
async def domain_config() -> JSONResponse:
    branding = domain.manifest.branding
    return JSONResponse({
        "id": domain.manifest.id,
        "app_name": branding.app_name,
        "subtitle": branding.subtitle,
        "hero_title": branding.hero_title,
        "placeholder_text": branding.placeholder_text,
        "demo_steps": branding.demo_steps,
        "starter_prompts": [card.model_dump() for card in branding.starter_prompts],
        "theme": branding.theme.model_dump(),
        "logo_src": _logo_src(ROOT_DIR / branding.logo_path),
        "seed_langcache": [{"prompt": e.prompt, "response": e.response} for e in domain.manifest.seed_langcache],
        "members": getattr(domain, "demo_members", []),
        "default_member_id": svc.resolve_member_id(None),
    })


@app.get("/api/tools")
async def list_available_tools() -> JSONResponse:
    tools: list[dict[str, Any]] = [
        {"name": t.name, "description": t.description, "kind": "internal"} for t in svc.internal_tools.definitions
    ]
    try:
        tools += [
            {"name": t["name"], "description": t.get("description", ""), "kind": "mcp_tool"}
            for t in await svc.cs_service.list_tools()
        ]
    except Exception:
        pass
    return JSONResponse({"tools": tools, "count": len(tools)})


# ── Memory views ─────────────────────────────────────────────────────────────────


@app.get("/api/memory/dashboard")
async def memory_dashboard(thread_id: str | None = None, member_id: str | None = None) -> JSONResponse:
    owner_id = svc.resolve_member_id(member_id)
    if not svc.memory_service.is_configured():
        return JSONResponse({"enabled": False, "short_term": [], "long_term": []})

    short_term: list[dict[str, str]] = []
    long_term: list[dict[str, Any]] = []
    errors: list[str] = []

    if thread_id:
        try:
            session = await svc.memory_service.get_session(owner_id=owner_id, session_id=thread_id)
            short_term = compact_session_events(session.get("events", []) if isinstance(session, dict) else [])
        except Exception as exc:
            errors.append(f"short-term memory unavailable: {exc}")

    try:
        found = await svc.memory_service.asearch_long_term_memory(text="", owner_id=owner_id, limit=25)
        if hasattr(domain, "reconcile_long_term_memories"):
            await asyncio.to_thread(domain.reconcile_long_term_memories, settings, found)
        hidden = {}
        if hasattr(domain, "filter_long_term_memories"):
            _, hidden_list = domain.filter_long_term_memories(found)
            hidden = {h["id"]: h["reason"] for h in hidden_list}
        for memory in found:
            card = domain.memory_card(memory) if hasattr(domain, "memory_card") else {"id": memory.get("id"), "text": memory.get("text")}
            if card["id"] in hidden:
                card = {**card, "text": f"[Hidden from agent: {hidden[card['id']]}] {card['text']}"}
            long_term.append(card)
    except Exception as exc:
        errors.append(f"long-term memory unavailable: {exc}")

    return JSONResponse({"enabled": True, "owner_id": owner_id, "short_term": short_term, "long_term": long_term, "errors": errors})


@app.get("/api/memory/extraction-watch")
async def extraction_watch(thread_id: str, member_id: str | None = None) -> StreamingResponse:
    """Show Agent Memory's background extraction in the activity panel.

    Extraction runs inside the Agent Memory service after the chat turn, so the chat stream never
    sees it. This polls for memories the service created from this session and reports them with
    the structured fields its extraction filled in.
    """
    owner_id = svc.resolve_member_id(member_id)
    memory_type = getattr(domain, "memory_type_filter", None)
    name = "agent_memory_extraction"

    async def events() -> AsyncIterator[str]:
        started = perf_counter()
        yield sse("tool-call", toolName=name, toolKind="memory", ts=0,
                  payload={"waiting_for": "Agent Memory to extract memories from this session", "session": thread_id})
        service = MemoryService(settings)  # unfiltered, so other extracted types are counted too
        seen: list[dict[str, Any]] = []
        try:
            for _ in range(24):  # about two minutes
                await asyncio.sleep(5)
                seen = await service.asearch_long_term_memory(
                    text="user context event", owner_id=owner_id, session_id=thread_id, limit=50, similarity_threshold=0.0
                )
                if seen:
                    await asyncio.sleep(3)  # let the rest of the run land
                    seen = await service.asearch_long_term_memory(
                        text="user context event", owner_id=owner_id, session_id=thread_id, limit=50, similarity_threshold=0.0
                    )
                    break
        except Exception as exc:
            yield sse("tool-result", toolName=name, toolKind="memory", payload={"error": str(exc)}, durationMs=0, ts=0)
            return
        finally:
            await service.close()

        created = [m for m in seen if m.get("memoryType") == memory_type]
        payload: dict[str, Any] = {
            "created": [
                {"text": m.get("text"), **(m.get("attributes") or {})} for m in created
            ],
        }
        if len(seen) > len(created):
            payload["other_memories_extracted"] = len(seen) - len(created)
        if not created:
            payload["note"] = "Nothing extracted for this session yet" if not seen else "No context event found in this conversation"
        yield sse("tool-result", toolName=name, toolKind="memory", payload=payload, durationMs=ms_since(started), ts=0)

    return StreamingResponse(events(), media_type="text/event-stream")


# ── Demo controls ────────────────────────────────────────────────────────────────


@app.post("/api/demo/expire-soon")
async def expire_soon(member_id: str | None = None, seconds: int = 10) -> JSONResponse:
    """Let Redis expire the user's newest context memory within `seconds`.

    This compresses time, not the mechanism: it sets the memory's Redis key TTL to a few seconds,
    and Redis then deletes the record and drops it from the search index.
    """
    owner_id = svc.resolve_member_id(member_id)
    result = await asyncio.to_thread(domain.fast_forward_expiry, settings, owner_id, max(3, min(seconds, 60)))
    if result is None:
        return JSONResponse({"error": "no active memory to expire"}, status_code=404)
    return JSONResponse(result)


@app.post("/api/demo/reset")
async def reset_demo() -> JSONResponse:
    """Return the demo to its starting state: each user's memories, the semantic cache and the audit log.

    Context Retriever data is left alone. Session memory cannot be listed, so the UI starts a new thread.
    """
    result: dict[str, Any] = {"members": {}}

    service = MemoryService(settings)  # unfiltered: clears every memory type for the user
    if service.is_configured():
        for owner_id, seeds in domain.seed_memory_sets().items():
            deleted = 0
            for _ in range(10):  # a search returns at most 100
                existing = await service.asearch_long_term_memory(text="reset", owner_id=owner_id, limit=100, similarity_threshold=0.0)
                ids = [str(m["id"]) for m in existing if m.get("id")]
                if not ids:
                    break
                await service.adelete_long_term_memories(owner_id=owner_id, memory_ids=ids)
                deleted += len(ids)
            for i, seed in enumerate(seeds):
                await asyncio.to_thread(
                    service.create_long_term_memory,
                    text=seed.text, owner_id=owner_id, memory_type=seed.memory_type, topics=seed.topics,
                    attributes=seed.attributes or None, memory_id=f"seed-{domain.manifest.id}-{owner_id}-{i}",
                )
            result["members"][owner_id] = {"deleted": deleted, "seeded": len(seeds)}
    await service.close()

    cache, entries = svc.langcache_service, domain.manifest.seed_langcache
    if cache.is_configured() and entries:
        await cache.flush()
        stored = sum([await cache.store(prompt=e.prompt, response=e.response, attributes=e.attributes or None) for e in entries])
        result["langcache_seeded"] = stored

    audit_stream = getattr(domain, "audit_stream", None)
    if audit_stream:
        await asyncio.to_thread(create_redis_client(settings).delete, audit_stream)

    return JSONResponse(result)


# ── Chat ─────────────────────────────────────────────────────────────────────────


async def _missing_openai_key() -> AsyncIterator[str]:
    yield sse("text-delta", delta="⚠️ OPENAI_API_KEY is not set. Add it to `.env`, restart `make dev`, then ask again.")
    yield sse("done", totalElapsedMs=0)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    stream = cs_event_stream(request) if settings.openai_api_key else _missing_openai_key()
    return StreamingResponse(stream, media_type="text/event-stream")
