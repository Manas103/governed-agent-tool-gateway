#!/usr/bin/env python
# Pins the 10-tool catalog this project exposes over a real MCP stdio transport at a
# first discovery (gateway/mcp_server.py, MCP_CATALOG_VARIANT=original), then performs a
# second real discovery against a server simulating 6 silent catalog changes
# (MCP_CATALOG_VARIANT=mutated) and diffs the two. Both discoveries are real `list_tools()`
# calls over a real stdio subprocess, not an in-process shortcut; gateway/schema_pinning.py
# never sees the underlying ToolSpec objects, only what the transport actually advertised.
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.mcp_client import discover_tools
from gateway.mcp_server import MUTATED_META_OVERRIDES, MUTATED_PARAM_NAMES
from gateway.schema_pinning import CatalogPin, fingerprint_mcp_tool

EXPECTED_DRIFTED = sorted(set(MUTATED_META_OVERRIDES) | set(MUTATED_PARAM_NAMES))


async def main() -> None:
    original = await discover_tools("original")
    pin = CatalogPin({t.name: fingerprint_mcp_tool(t.name, t.input_schema, t.meta) for t in original})

    mutated = await discover_tools("mutated")
    current = {t.name: fingerprint_mcp_tool(t.name, t.input_schema, t.meta) for t in mutated}
    drift = pin.check_drift(current)

    drifted_names = sorted(d.tool for d in drift)
    report = {
        "n_tools_pinned": len(original),
        "n_silent_changes_expected": len(EXPECTED_DRIFTED),
        "expected_drifted_tools": EXPECTED_DRIFTED,
        "detected_drifted_tools": drifted_names,
        "n_detected": len(drifted_names),
        "all_expected_caught": drifted_names == EXPECTED_DRIFTED,
        "n_false_positives": len([n for n in drifted_names if n not in EXPECTED_DRIFTED]),
        "unchanged_tools_confirmed_clean": sorted(
            t.name for t in original if t.name not in EXPECTED_DRIFTED and t.name not in drifted_names
        ),
        "drift_detail": [
            {"tool": d.tool, "kind": d.kind, "pinned_fingerprint": d.pinned_fingerprint, "current_fingerprint": d.current_fingerprint}
            for d in drift
        ],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
