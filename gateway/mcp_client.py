# A real MCP client over the stdio transport: launches `python -m gateway.mcp_server` as
# a child process (killed by this same client, by the PID anyio's process group owns, when
# the `async with` block exits; nothing is left running), speaks the real MCP protocol to
# it, and returns what a genuine `list_tools()`/`call_tool()` round trip actually saw.
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DiscoveredTool:
    name: str
    input_schema: dict
    meta: dict | None


@asynccontextmanager
async def mcp_session(variant: str = "original", *, extra_env: dict[str, str] | None = None):
    env = dict(os.environ)
    env["MCP_CATALOG_VARIANT"] = variant
    if extra_env:
        env.update(extra_env)
    params = StdioServerParameters(command=sys.executable, args=["-m", "gateway.mcp_server"], cwd=str(_REPO_ROOT), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def discover_tools(variant: str = "original", *, extra_env: dict[str, str] | None = None) -> list[DiscoveredTool]:
    async with mcp_session(variant, extra_env=extra_env) as session:
        result = await session.list_tools()
        return [DiscoveredTool(t.name, t.inputSchema, t.meta) for t in result.tools]


async def call_tool(variant: str, name: str, arguments: dict, *, extra_env: dict[str, str] | None = None) -> dict:
    async with mcp_session(variant, extra_env=extra_env) as session:
        result = await session.call_tool(name, arguments)
        if result.isError:
            return {"ok": False, "error": _text(result)}
        return {"ok": True, "content": _text(result)}


def _text(call_tool_result) -> str:
    return "".join(getattr(block, "text", "") for block in call_tool_result.content)
