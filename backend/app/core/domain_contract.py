from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, Sequence

from pydantic import BaseModel, Field

from backend.app.core.domain_schema import EntitySpec


class PromptCard(BaseModel):
    eyebrow: str
    title: str
    prompt: str


class ThemeConfig(BaseModel):
    bg: str
    bg_accent_a: str
    bg_accent_b: str
    panel: str
    panel_strong: str
    panel_elevated: str
    line: str
    line_strong: str
    text: str
    muted: str
    soft: str
    accent: str
    user: str
    landing_bg: str = ""


class BrandingConfig(BaseModel):
    app_name: str
    subtitle: str
    hero_title: str
    placeholder_text: str
    logo_path: str
    demo_steps: list[str] = Field(default_factory=list)
    starter_prompts: list[PromptCard]
    theme: ThemeConfig


class NamespaceConfig(BaseModel):
    redis_prefix: str
    checkpoint_prefix: str
    checkpoint_write_prefix: str
    redis_instance_name: str
    surface_name: str
    agent_name: str


class IdentityConfig(BaseModel):
    tool_name: str = "get_current_user_profile"
    id_env_var: str = "DEMO_USER_ID"
    name_env_var: str = "DEMO_USER_NAME"
    email_env_var: str = "DEMO_USER_EMAIL"
    id_field: str = "user_id"
    default_id: str
    default_name: str
    default_email: str
    description: str


class GuardrailRouteConfig(BaseModel):
    name: str
    references: list[str]
    distance_threshold: float = 0.7
    block_message: str | None = None


class GuardrailConfig(BaseModel):
    router_name: str
    allowed_route_name: str
    routes: list[GuardrailRouteConfig]


class ToolRouteConfig(BaseModel):
    """One group of tools the agent may use for a kind of question."""

    name: str
    references: list[str]
    # Tool names or fnmatch patterns (e.g. "filter_order*", "get_order_by_id").
    tools: list[str]
    # Max cosine distance to the closest reference for the route to match (lower = stricter).
    distance_threshold: float = 0.5


class ToolRoutingConfig(BaseModel):
    """Semantic tool routing: pick which tools to send to the LLM for each question."""

    router_name: str
    # Tools sent with every call (identity, time, memory...).
    always_on: list[str] = Field(default_factory=list)
    routes: list[ToolRouteConfig]
    # Maximum number of matching routes to combine for one question.
    max_routes: int = 3


class SeedMemory(BaseModel):
    text: str
    topics: list[str] = Field(default_factory=list)
    memory_type: str = "semantic"
    attributes: dict[str, Any] = Field(default_factory=dict)


class SeedLangCacheEntry(BaseModel):
    prompt: str
    response: str
    attributes: dict[str, str] = Field(default_factory=dict)


class DomainManifest(BaseModel):
    id: str
    version: str = "1"
    description: str
    generated_models_module: str
    generated_models_path: str
    output_dir: str
    branding: BrandingConfig
    namespace: NamespaceConfig
    identity: IdentityConfig
    guardrail: GuardrailConfig | None = None
    tool_routing: ToolRoutingConfig | None = None
    seed_memories: list[SeedMemory] = Field(default_factory=list)
    seed_langcache: list[SeedLangCacheEntry] = Field(default_factory=list)


class InternalToolDefinition(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}, "required": []})


class GeneratedDataset(BaseModel):
    output_dir: str
    env_updates: dict[str, str]
    summary: dict[str, int]


class DomainPack(Protocol):
    manifest: DomainManifest

    def get_entity_specs(self) -> tuple[EntitySpec, ...]:
        ...

    def build_system_prompt(
        self,
        *,
        mcp_tools: Sequence[dict[str, Any]],
        runtime_config: dict[str, Any] | None = None,
    ) -> str:
        ...

    def get_internal_tool_definitions(
        self,
        *,
        runtime_config: dict[str, Any] | None = None,
    ) -> Sequence[InternalToolDefinition]:
        ...

    def execute_internal_tool(self, tool_name: str, arguments: dict[str, Any], settings: Any) -> dict[str, Any]:
        ...

    def generate_demo_data(
        self,
        *,
        output_dir: Path,
        seed: int | None = None,
        update_env_file: bool = False,
    ) -> GeneratedDataset:
        ...

    def validate(self) -> list[str]:
        ...
