"""Semantic tool routing: choose which tools the LLM sees for each question.

The agent has dozens of tools, and every model call re-sends all of their definitions (~15k
tokens for Reddash). Here a second SemanticRouter (RedisVL) classifies the question against
groups of example questions, and only the tools in the matching groups are attached to the
model call. It reuses the embedding the guardrail already computed, so routing adds one Redis
vector search and no extra OpenAI call.

If nothing matches, every tool is attached, so routing can only save tokens, never remove
the agent's ability to answer.
"""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any

from redisvl.extensions.router import Route, SemanticRouter
from redisvl.extensions.router.schema import RoutingConfig
from redisvl.utils.vectorize import OpenAITextVectorizer

from backend.app.core.domain_contract import ToolRoutingConfig
from backend.app.redis_connection import build_redis_url
from backend.app.settings import Settings

log = logging.getLogger("iris.toolrouting")


@dataclass
class ToolSelection:
    tools: list[str]
    routes: list[dict[str, Any]] = field(default_factory=list)
    fallback: bool = False


def expand_patterns(patterns: list[str], all_tools: list[str]) -> set[str]:
    """Resolve tool names / fnmatch patterns against the tools that actually exist."""
    selected: set[str] = set()
    for pattern in patterns:
        selected.update(name for name in all_tools if fnmatch.fnmatchcase(name, pattern))
    return selected


def resolve_selection(
    config: ToolRoutingConfig,
    matched_routes: list[dict[str, Any]],
    all_tools: list[str],
) -> ToolSelection:
    """Combine always-on tools with the tools of every matched route (all tools if none match)."""
    if not matched_routes:
        return ToolSelection(tools=list(all_tools), routes=[], fallback=True)
    by_name = {route.name: route for route in config.routes}
    patterns = list(config.always_on)
    for match in matched_routes:
        route = by_name.get(match["name"])
        if route:
            patterns.extend(route.tools)
    chosen = expand_patterns(patterns, all_tools)
    # Keep the original tool order so the prompt stays stable.
    return ToolSelection(tools=[name for name in all_tools if name in chosen], routes=matched_routes)


class ToolRoutingService:
    def __init__(self, settings: Settings, config: ToolRoutingConfig | None):
        self._config = config
        self._enabled = settings.tool_routing_enabled
        self._openai_api_key = settings.openai_api_key
        self._embedding_model = settings.openai_embedding_model
        self._redis_url = build_redis_url(settings)
        self._router: SemanticRouter | None = None
        self._lock = asyncio.Lock()

    def is_configured(self) -> bool:
        return bool(
            self._enabled and self._config and self._config.routes
            and self._openai_api_key and self._redis_url
        )

    async def _ensure_router(self) -> SemanticRouter:
        if self._router is not None:
            return self._router
        async with self._lock:
            if self._router is not None:
                return self._router
            assert self._config is not None
            vectorizer = OpenAITextVectorizer(
                model=self._embedding_model,
                api_config={"api_key": self._openai_api_key},
            )
            routes = [
                Route(
                    name=route.name,
                    references=route.references,
                    distance_threshold=route.distance_threshold,
                )
                for route in self._config.routes
            ]
            config = self._config

            def _build() -> SemanticRouter:
                return SemanticRouter(
                    name=config.router_name,
                    vectorizer=vectorizer,
                    routes=routes,
                    # One strong match on a single example is enough to select a route.
                    routing_config=RoutingConfig(aggregation_method="min", max_k=config.max_routes),
                    redis_url=self._redis_url,
                    overwrite=True,
                )

            self._router = await asyncio.to_thread(_build)
            log.info("Tool router '%s' initialized (%d routes)", config.router_name, len(routes))
            return self._router

    async def warm_up(self) -> None:
        if self.is_configured():
            await self._ensure_router()

    async def select(self, vector: list[float], all_tools: list[str]) -> ToolSelection:
        """Pick the tools for one question. Any failure falls back to every tool."""
        assert self._config is not None
        try:
            router = await self._ensure_router()
            matches = await asyncio.to_thread(
                lambda: router.route_many(vector=vector, max_k=self._config.max_routes)
            )
            matched = [
                {"name": m.name, "distance": round(float(m.distance), 3)}
                for m in (matches or [])
                if m.name
            ]
            return resolve_selection(self._config, matched, all_tools)
        except Exception:
            log.warning("Tool routing failed, attaching every tool", exc_info=True)
            return ToolSelection(tools=list(all_tools), routes=[], fallback=True)
