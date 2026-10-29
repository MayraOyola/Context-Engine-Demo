"""The Redis Iris services the app talks to, created once at startup.

  Context Retriever   cs_service              MCP tools over the entity model
  Agent Memory        memory_service          session + long-term memory
  LangCache           langcache_service       semantic response cache
  Semantic routing    guardrail_service       blocks off-topic and impersonation prompts
                      tool_routing_service    picks which tools the model sees
  Redis               checkpointer            LangGraph conversation state
"""

from __future__ import annotations

import asyncio
import logging
import os
from time import perf_counter

from backend.app.context_surface_service import ContextSurfaceService
from backend.app.core.domain_loader import get_active_domain
from backend.app.guardrail_service import GuardrailService
from backend.app.internal_tools import InternalToolService, domain_runtime_config
from backend.app.langcache_service import LangCacheService
from backend.app.langgraph_agent import create_agent, create_checkpointer
from backend.app.memory_service import MemoryService
from backend.app.settings import get_settings
from backend.app.tool_routing_service import ToolRoutingService

log = logging.getLogger("iris")

settings = get_settings()
domain = get_active_domain(settings)
runtime_config = domain_runtime_config(domain, settings)

internal_tools = InternalToolService(settings)
cs_service = ContextSurfaceService(settings)
memory_service = MemoryService(
    settings,
    similarity_threshold=runtime_config.get("memory_similarity_threshold"),
    memory_type_filter=getattr(domain, "memory_type_filter", None),
)
langcache_service = LangCacheService(settings)
guardrail_service = GuardrailService(settings, domain.manifest.guardrail)
tool_routing_service = ToolRoutingService(settings, domain.manifest.tool_routing)


def resolve_member_id(requested: str | None) -> str:
    """The signed-in user for this request: a known demo member, else the configured default."""
    identity = domain.manifest.identity
    default = os.getenv(identity.id_env_var, identity.default_id)
    allowed = {m["id"] for m in getattr(domain, "demo_members", [])}
    return requested if requested and requested in allowed else default


# ── The LangGraph agent (built lazily, rebuilt after a connection error) ──────────

_agent = None
_agent_lock = asyncio.Lock()


async def get_agent(*, force_rebuild: bool = False):
    global _agent
    async with _agent_lock:
        if _agent is None or force_rebuild:
            started = perf_counter()
            checkpointer = await create_checkpointer(settings)
            _agent = await create_agent(settings, internal_tools, cs_service, checkpointer)
            log.info("Agent ready in %dms (model=%s)", round((perf_counter() - started) * 1000), settings.openai_chat_model)
        return _agent


def discard_agent() -> None:
    """Drop the cached agent so the next request rebuilds it (used after a connection error)."""
    global _agent
    _agent = None


async def warm_up() -> None:
    """Initialize the heavy services at startup so the first request is fast."""
    started = perf_counter()
    tasks = [asyncio.create_task(get_agent())]
    if guardrail_service.is_configured():
        tasks.append(asyncio.create_task(guardrail_service.warm_up()))
    if tool_routing_service.is_configured():
        tasks.append(asyncio.create_task(tool_routing_service.warm_up()))
    for result in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(result, Exception):
            log.warning("Warmup task failed: %s", result)
    log.info("Warmup complete in %dms", round((perf_counter() - started) * 1000))


async def close_all() -> None:
    await cs_service.close()
    await memory_service.close()
    await langcache_service.close()
    await guardrail_service.close()
