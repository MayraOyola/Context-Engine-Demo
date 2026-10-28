from __future__ import annotations

import json
import logging
from typing import Any

from context_surfaces import UnifiedClient

from backend.app.settings import Settings

log = logging.getLogger("iris.mcp")


def _default_array_items_schema(*, field_name: str | None = None, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    description = ""
    if isinstance(schema, dict):
        description = str(schema.get("description", ""))
    hint = " ".join(part for part in (field_name or "", description) if part).lower()
    if any(token in hint for token in ("embedding", "vector")):
        return {"type": "number"}
    return {}


def _sanitize_property_schema(name: str, schema: Any) -> Any:
    if isinstance(schema, list):
        return [_sanitize_property_schema(name, item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    sanitized = dict(schema)
    schema_type = sanitized.get("type")

    if schema_type == "array":
        items = sanitized.get("items")
        if isinstance(items, dict):
            sanitized["items"] = _sanitize_property_schema(f"{name}_item", items)
        elif items is None:
            sanitized["items"] = _default_array_items_schema(field_name=name, schema=sanitized)

    properties = sanitized.get("properties")
    if isinstance(properties, dict):
        sanitized["properties"] = {
            prop_name: _sanitize_property_schema(prop_name, prop_schema)
            for prop_name, prop_schema in properties.items()
        }

    additional_properties = sanitized.get("additionalProperties")
    if isinstance(additional_properties, (dict, list)):
        sanitized["additionalProperties"] = _sanitize_property_schema(
            f"{name}_value",
            additional_properties,
        )

    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        value = sanitized.get(key)
        if isinstance(value, list):
            sanitized[key] = [_sanitize_property_schema(name, item) for item in value]

    negated = sanitized.get("not")
    if isinstance(negated, dict):
        sanitized["not"] = _sanitize_property_schema(name, negated)

    return sanitized


def _sanitize_tool_definition(tool_def: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(tool_def)
    input_schema = sanitized.get("inputSchema")
    if isinstance(input_schema, dict):
        sanitized["inputSchema"] = _sanitize_property_schema("input", input_schema)
    return sanitized


class ContextSurfaceService:
    """Wraps the context-surfaces SDK to list and call MCP tools.

    Uses a persistent UnifiedClient to reuse HTTP/TLS connections across
    tool calls, avoiding ~100ms connection setup overhead per call.
    Automatically reconnects on stale connection errors.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._tool_cache: list[dict[str, Any]] | None = None
        self._client: UnifiedClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.mcp_agent_key)

    async def _get_client(self) -> UnifiedClient:
        if self._client is None:
            self._client = UnifiedClient()
            await self._client.__aenter__()
        return self._client

    async def _reset_client(self) -> UnifiedClient:
        log.warning("Resetting MCP client connection")
        try:
            if self._client is not None:
                await self._client.__aexit__(None, None, None)
        except Exception:
            pass
        self._client = None
        return await self._get_client()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        if self._tool_cache is not None:
            return self._tool_cache
        client = await self._get_client()
        tools = await client.list_tools(self.settings.mcp_agent_key)
        self._tool_cache = [t if isinstance(t, dict) else t.model_dump() for t in tools]
        return self._tool_cache or []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                client = await self._get_client()
                result = await client.query_tool(
                    agent_key=self.settings.mcp_agent_key,
                    tool_name=tool_name,
                    arguments=arguments,
                )
                if isinstance(result, dict):
                    content = result.get("content", [])
                    if content and isinstance(content, list) and content[0].get("type") == "text":
                        text = content[0].get("text", "")
                        try:
                            return json.loads(text)
                        except json.JSONDecodeError:
                            return {"raw_text": text}
                return result if isinstance(result, dict) else {"result": result}
            except Exception as exc:
                last_exc = exc
                if attempt == 0:
                    log.warning("MCP call_tool %s failed (attempt 1), reconnecting: %s", tool_name, exc)
                    await self._reset_client()
                else:
                    raise
        raise last_exc  # type: ignore[misc]

