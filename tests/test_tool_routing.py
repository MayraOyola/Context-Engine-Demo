from backend.app.core.domain_contract import ToolRouteConfig, ToolRoutingConfig
from backend.app.core.domain_loader import load_domain
from backend.app.tool_routing_service import expand_patterns, resolve_selection

ALL_TOOLS = [
    "get_current_user_profile",
    "get_current_time",
    "filter_order",
    "get_order_by_id",
    "count_order",
    "filter_payment",
    "search_policy_by_text",
    "union_results",
]


def _config() -> ToolRoutingConfig:
    return ToolRoutingConfig(
        router_name="test-tool-routes",
        always_on=["get_current_user_profile", "get_current_time"],
        routes=[
            ToolRouteConfig(name="orders", references=["Where is my order?"], tools=["filter_order", "get_order_by_id"]),
            ToolRouteConfig(name="payments", references=["How much was I charged?"], tools=["filter_payment", "search_policy_*"]),
            ToolRouteConfig(name="counts", references=["How many orders?"], tools=["count_*"]),
        ],
    )


def test_expand_patterns_matches_names_and_globs_and_ignores_unknown_tools():
    assert expand_patterns(["filter_order", "count_*", "does_not_exist"], ALL_TOOLS) == {"filter_order", "count_order"}


def test_selection_combines_always_on_with_matched_routes_in_original_order():
    selection = resolve_selection(
        _config(),
        [{"name": "payments", "distance": 0.2}, {"name": "orders", "distance": 0.3}],
        ALL_TOOLS,
    )
    assert selection.fallback is False
    assert selection.tools == [
        "get_current_user_profile",
        "get_current_time",
        "filter_order",
        "get_order_by_id",
        "filter_payment",
        "search_policy_by_text",
    ]
    assert "union_results" not in selection.tools


def test_selection_falls_back_to_every_tool_when_nothing_matches():
    selection = resolve_selection(_config(), [], ALL_TOOLS)
    assert selection.fallback is True
    assert selection.tools == ALL_TOOLS


def test_selection_ignores_unknown_route_names():
    selection = resolve_selection(_config(), [{"name": "nope", "distance": 0.1}], ALL_TOOLS)
    assert selection.tools == ["get_current_user_profile", "get_current_time"]


def test_reddash_tool_routing_config_is_well_formed():
    config = load_domain("reddash").manifest.tool_routing
    assert config is not None
    names = [route.name for route in config.routes]
    assert len(names) == len(set(names))
    for route in config.routes:
        assert route.references, f"{route.name} needs example questions"
        assert route.tools, f"{route.name} needs tools"
        assert 0 < route.distance_threshold <= 1
    assert "get_current_user_profile" in config.always_on
