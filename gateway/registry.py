# The registry: the one source of truth for which domain servers exist, which tools each
# exposes, and which caller group may invoke each tool. A fleet of domain-specific servers
# (pins, boards, ads_campaigns, users) rather than one monolith limits what a single caller
# group's blast radius looks like and keeps each domain's tool surface small enough to
# reason about on its own, the same reason Pinterest's published MCP architecture gives for
# splitting its own tool servers by domain.
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    mutating: bool
    permitted_groups: frozenset[str]
    required_params: tuple[str, ...]


# Every group that can hold a short-lived token, the domains it may call into, and whether
# it is allowed to call a mutating tool at all (growth-analytics is read-only by design: it
# exists to answer "how many X" questions, never to change anything).
GROUPS: dict[str, dict] = {
    "catalog-ops": {"domains": frozenset({"pins", "boards"}), "can_write": True},
    "ads-ops": {"domains": frozenset({"ad_campaigns"}), "can_write": True},
    "trust-safety": {"domains": frozenset({"users", "pins"}), "can_write": True},
    "growth-analytics": {"domains": frozenset({"pins", "boards", "ad_campaigns", "users"}), "can_write": False},
}

DOMAIN_SERVERS: tuple[str, ...] = ("pins", "boards", "ad_campaigns", "users")


def _tools_for_domain(domain: str, write_groups: frozenset[str]) -> list[ToolSpec]:
    # A domain's read-only groups are permitted to call into that domain at all (they show
    # up in permitted_groups for every tool in it, read or write); whether a specific call
    # is actually allowed to mutate is a second, independent check in Gateway.authorize
    # (GROUPS[group]["can_write"]). Splitting it this way is what makes "wrong domain for
    # my group" and "my group can only read" two genuinely distinct, separately testable
    # refusal reasons instead of the second one being unreachable dead code.
    domain_groups = write_groups | frozenset(
        g for g, spec in GROUPS.items() if not spec["can_write"] and domain in spec["domains"]
    )
    if domain == "pins":
        return [
            ToolSpec("get_pin", domain, False, domain_groups, ("pin_id",)),
            ToolSpec("search_pins", domain, False, domain_groups, ("query",)),
            ToolSpec("create_pin", domain, True, domain_groups, ("board_id", "description")),
            ToolSpec("update_pin_description", domain, True, domain_groups, ("pin_id", "description")),
            ToolSpec("delete_pin", domain, True, domain_groups, ("pin_id",)),
            ToolSpec("report_pin", domain, True, domain_groups, ("pin_id", "reason")),
        ]
    if domain == "boards":
        return [
            ToolSpec("get_board", domain, False, domain_groups, ("board_id",)),
            ToolSpec("list_boards_for_user", domain, False, domain_groups, ("user_id",)),
            ToolSpec("create_board", domain, True, domain_groups, ("owner_user_id", "name")),
            ToolSpec("rename_board", domain, True, domain_groups, ("board_id", "name")),
            ToolSpec("add_pin_to_board", domain, True, domain_groups, ("board_id", "pin_id")),
            ToolSpec("delete_board", domain, True, domain_groups, ("board_id",)),
        ]
    if domain == "ad_campaigns":
        return [
            ToolSpec("get_campaign", domain, False, domain_groups, ("campaign_id",)),
            ToolSpec("list_campaigns", domain, False, domain_groups, ()),
            ToolSpec("create_campaign", domain, True, domain_groups, ("name", "budget_usd")),
            ToolSpec("update_campaign_budget", domain, True, domain_groups, ("campaign_id", "budget_usd")),
            ToolSpec("pause_campaign", domain, True, domain_groups, ("campaign_id",)),
            ToolSpec("delete_campaign", domain, True, domain_groups, ("campaign_id",)),
        ]
    if domain == "users":
        return [
            ToolSpec("get_user", domain, False, domain_groups, ("user_id",)),
            ToolSpec("search_users", domain, False, domain_groups, ("query",)),
            ToolSpec("update_user_email", domain, True, domain_groups, ("user_id", "email")),
            ToolSpec("suspend_user", domain, True, domain_groups, ("user_id", "reason")),
            ToolSpec("restore_user", domain, True, domain_groups, ("user_id",)),
            ToolSpec("delete_user", domain, True, domain_groups, ("user_id",)),
        ]
    raise ValueError(f"unknown domain: {domain}")


def _write_groups_for_domain(domain: str) -> frozenset[str]:
    return frozenset(g for g, spec in GROUPS.items() if spec["can_write"] and domain in spec["domains"])


class Registry:
    """The approved-server-and-tool source of truth the gateway consults on every call."""

    def __init__(self) -> None:
        self.tools: dict[str, ToolSpec] = {}
        for domain in DOMAIN_SERVERS:
            for spec in _tools_for_domain(domain, _write_groups_for_domain(domain)):
                self.tools[spec.name] = spec

    def resolve(self, tool_name: str) -> ToolSpec:
        spec = self.tools.get(tool_name)
        if spec is None:
            raise KeyError(f"tool not registered: {tool_name}")
        return spec

    def tool_count(self) -> int:
        return len(self.tools)

    def domain_count(self) -> int:
        return len(DOMAIN_SERVERS)
