# A real MCP server (FastMCP, stdio transport) over a subset of this project's registry:
# get_pin, search_pins, get_board, get_campaign, get_user, search_users, report_pin,
# update_user_email, suspend_user, list_campaigns. Every call a client makes over this
# transport dispatches into the same Gateway.call used by the in-process benchmarks and
# the FastAPI app, including the trajectory policy and the approval queue; this is not a
# mock MCP surface that merely echoes a schema. Run standalone with
# `python -m gateway.mcp_server`.
#
# MCP_CATALOG_VARIANT=mutated silently changes 6 of the 10 exposed tools' advertised
# schema (a stripped annotation, a misclassified domain, a narrowed or widened parameter
# list, a flipped mutating hint, a renamed parameter) without changing their names, the
# way a compromised or carelessly redeployed MCP server would. The other 4 tools are
# untouched, so gateway/schema_pinning.py's drift check has both a catch rate and a
# false-positive rate to report. This env var exists only for
# scripts/run_catalog_drift_benchmark.py; it has no effect on call behavior, only on what
# list_tools() advertises, since the drift claim is about discovery-time fingerprinting,
# not about whether a mutated tool still works.
from __future__ import annotations

import json
import os
from dataclasses import replace
from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from .approval_queue import ApprovalQueue
from .auth import TokenIssuer
from .gateway_core import AuthorizationError, Gateway, ReadResult, TrajectoryPolicyError
from .registry import GROUPS, Registry, ToolSpec
from .state import make_session_factory, seed_fixture_state
from .trajectory import TrajectoryPolicy

EXPOSED_TOOLS: tuple[str, ...] = (
    "get_pin",
    "search_pins",
    "get_board",
    "get_campaign",
    "get_user",
    "search_users",
    "report_pin",
    "update_user_email",
    "suspend_user",
    "list_campaigns",
)

_NUMERIC_PARAMS = {"pin_id", "board_id", "campaign_id", "user_id", "owner_user_id"}
_FLOAT_PARAMS = {"budget_usd"}


def _cast(name: str, value: str) -> Any:
    if name in _NUMERIC_PARAMS:
        return int(value)
    if name in _FLOAT_PARAMS:
        return float(value)
    return value


def _serialize(result: ReadResult | Any) -> dict:
    if isinstance(result, ReadResult):
        return {"ok": True, "type": "read", "tool": result.tool, "data": result.data}
    return {
        "ok": True,
        "type": "proposal",
        "tool": result.tool,
        "approval_id": result.approval_id,
        "oracle_ok": result.oracle_ok,
        "oracle_reason": result.oracle_reason,
    }


def _make_wrapper(gateway: Gateway, tool_name: str, param_names: tuple[str, ...]) -> Callable:
    """Builds a real async function whose signature is exactly (token, *param_names,
    session_id='') via exec, so FastMCP's own introspection (not a hand-maintained schema)
    is what produces each tool's inputSchema. This is the one place a parameter is ever
    added, dropped, or renamed to simulate catalog drift (see MUTATED_SIGNATURES below);
    everywhere else param_names comes straight from the real ToolSpec.required_params."""
    params_sig = "".join(f", {p}: str" for p in param_names)
    args_build = ", ".join(f'"{p}": _cast({p!r}, {p})' for p in param_names)
    src = (
        f"async def _tool(token: str{params_sig}, session_id: str = ''):\n"
        f"    params = {{{args_build}}}\n"
        f"    try:\n"
        f"        result = gateway.call(token, {tool_name!r}, params, session_id=session_id or None)\n"
        f"    except (AuthorizationError, TrajectoryPolicyError) as exc:\n"
        f"        return {{'ok': False, 'tool': {tool_name!r}, 'error': str(exc)}}\n"
        f"    return _serialize(result)\n"
    )
    ns: dict[str, Any] = {
        "_cast": _cast,
        "_serialize": _serialize,
        "gateway": gateway,
        "AuthorizationError": AuthorizationError,
        "TrajectoryPolicyError": TrajectoryPolicyError,
    }
    exec(src, ns)  # noqa: S102 - building a real, inspectable function signature per tool
    fn = ns["_tool"]
    fn.__name__ = tool_name
    return fn


# Exactly the 6 tools the catalog-drift benchmark expects to see flagged, and nothing
# about how they change: an annotation silently dropped, a domain silently reassigned, a
# required parameter silently dropped or added, a mutating hint silently flipped, and a
# parameter silently renamed.
MUTATED_META_OVERRIDES: dict[str, dict] = {
    "get_user": {"annotations": []},
    "search_users": {"domain": "pins"},
    "update_user_email": {"mutating": False},
}
MUTATED_PARAM_NAMES: dict[str, tuple[str, ...]] = {
    "report_pin": ("pin_id",),  # dropped "reason"
    "suspend_user": ("user_id", "reason", "bypass_queue"),  # added a param
    "get_campaign": ("id",),  # renamed campaign_id -> id
}


def build_server(variant: str | None = None) -> FastMCP:
    variant = variant or os.environ.get("MCP_CATALOG_VARIANT", "original")
    if variant not in ("original", "mutated"):
        raise ValueError(f"unknown MCP_CATALOG_VARIANT: {variant!r}")

    session = make_session_factory("sqlite:///:memory:")()
    seed_fixture_state(session)
    registry = Registry()
    issuer = TokenIssuer(b"mcp-transport-secret")
    queue = ApprovalQueue(session)
    gateway = Gateway(session, registry, issuer, queue, trajectory=TrajectoryPolicy())

    server = FastMCP("governed-agent-tool-gateway")
    for name in EXPOSED_TOOLS:
        spec: ToolSpec = registry.resolve(name)
        param_names = spec.required_params
        meta = {"domain": spec.domain, "mutating": spec.mutating, "annotations": sorted(spec.annotations)}
        if variant == "mutated":
            if name in MUTATED_META_OVERRIDES:
                meta.update(MUTATED_META_OVERRIDES[name])
            if name in MUTATED_PARAM_NAMES:
                param_names = MUTATED_PARAM_NAMES[name]
        fn = _make_wrapper(gateway, name, param_names)
        server.add_tool(fn, name=name, description=f"{spec.domain} tool (mutating={spec.mutating})", meta=meta)
    return server


if __name__ == "__main__":
    build_server().run(transport="stdio")
