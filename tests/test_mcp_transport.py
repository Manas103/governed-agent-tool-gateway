# A real MCP stdio client/server round trip: these tests launch `python -m
# gateway.mcp_server` as a genuine child process (gateway/mcp_client.py) and speak the
# real MCP protocol to it, they do not call gateway.mcp_server's functions in-process.
# Each test opens and closes its own session, so nothing is left running once this module
# finishes.
from __future__ import annotations

import asyncio

import pytest

from gateway.auth import TokenIssuer
from gateway.mcp_client import discover_tools, mcp_session
from gateway.mcp_server import EXPOSED_TOOLS, MUTATED_META_OVERRIDES, MUTATED_PARAM_NAMES
from gateway.policy import opa_binary

requires_opa = pytest.mark.skipif(opa_binary() is None, reason="opa binary not on PATH/OPA_BIN")


def test_original_catalog_discovery_matches_exposed_tools():
    tools = asyncio.run(discover_tools("original"))
    assert {t.name for t in tools} == set(EXPOSED_TOOLS)
    get_user = next(t for t in tools if t.name == "get_user")
    assert get_user.meta["annotations"] == ["private_read"]
    report_pin = next(t for t in tools if t.name == "report_pin")
    assert "reason" in report_pin.input_schema["required"]


def test_mutated_catalog_only_changes_the_six_named_tools():
    original = {t.name: (t.input_schema, t.meta) for t in asyncio.run(discover_tools("original"))}
    mutated = {t.name: (t.input_schema, t.meta) for t in asyncio.run(discover_tools("mutated"))}
    changed = {name for name in original if original[name] != mutated[name]}
    assert changed == set(MUTATED_META_OVERRIDES) | set(MUTATED_PARAM_NAMES)


def test_real_call_tool_executes_a_read_through_the_gateway():
    async def run():
        issuer = TokenIssuer(b"mcp-transport-secret")
        token = issuer.issue("trust-safety")
        async with mcp_session("original") as session:
            result = await session.call_tool("get_user", {"token": token, "user_id": "1"})
            assert result.isError is False
            text = "".join(getattr(b, "text", "") for b in result.content)
            assert '"ok": true' in text
            assert '"email"' in text

    asyncio.run(run())


@requires_opa
def test_real_call_tool_trajectory_denial_round_trips_over_mcp():
    async def run():
        issuer = TokenIssuer(b"mcp-transport-secret")
        token = issuer.issue("trust-safety")
        async with mcp_session("original") as session:
            r1 = await session.call_tool("get_user", {"token": token, "user_id": "1", "session_id": "mcp-s1"})
            assert '"ok": true' in "".join(getattr(b, "text", "") for b in r1.content)

            r2 = await session.call_tool(
                "report_pin", {"token": token, "pin_id": "2", "reason": "spam", "session_id": "mcp-s1"}
            )
            text2 = "".join(getattr(b, "text", "") for b in r2.content)
            assert '"ok": false' in text2
            assert "external_send follows private_read" in text2

            r3 = await session.call_tool(
                "report_pin", {"token": token, "pin_id": "3", "reason": "spam", "session_id": "mcp-s2"}
            )
            text3 = "".join(getattr(b, "text", "") for b in r3.content)
            assert '"ok": true' in text3

    asyncio.run(run())
