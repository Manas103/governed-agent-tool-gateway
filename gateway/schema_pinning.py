# Fingerprints each tool's schema (name, domain, mutating flag, permitted groups,
# required params, annotations) the moment it is discovered, and flags any later
# discovery whose fingerprint for a previously-seen tool differs. This is deliberately
# structural, not semantic: it does not judge whether a changed schema is dangerous, only
# that an approved tool's shape silently moved since the caller last pinned it, which is
# the fact a human or a stricter downstream policy needs to react to a catalog change it
# never approved.
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .registry import ToolSpec


def fingerprint_tool(spec: ToolSpec) -> str:
    material = json.dumps(
        {
            "name": spec.name,
            "domain": spec.domain,
            "mutating": spec.mutating,
            "permitted_groups": sorted(spec.permitted_groups),
            "required_params": list(spec.required_params),
            "annotations": sorted(spec.annotations),
        },
        sort_keys=True,
    )
    return hashlib.sha256(material.encode()).hexdigest()


def fingerprint_mcp_tool(name: str, input_schema: dict, meta: dict | None) -> str:
    """Same idea, computed from what a real MCP `list_tools()` discovery actually returns
    (the tool's JSON input schema plus its `meta` dict) rather than from this project's own
    ToolSpec, so the fingerprint genuinely reflects what the transport told the caller, not
    what the caller already assumed."""
    material = json.dumps({"name": name, "input_schema": input_schema, "meta": meta or {}}, sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class DriftRecord:
    tool: str
    kind: str  # "schema_changed" | "new_since_pin" | "removed_since_pin"
    pinned_fingerprint: str | None
    current_fingerprint: str | None


class CatalogPin:
    """Pins a set of (name -> fingerprint) at discovery time; check_drift() takes the same
    shape again later and diffs it. Works the same whether the fingerprints come from
    fingerprint_tool() (in-process Registry) or fingerprint_mcp_tool() (a real MCP
    discovery); the class itself never knows which."""

    def __init__(self, fingerprints: dict[str, str]) -> None:
        self._pinned: dict[str, str] = dict(fingerprints)

    def check_drift(self, current_fingerprints: dict[str, str]) -> list[DriftRecord]:
        drift: list[DriftRecord] = []
        for name, pinned_fp in self._pinned.items():
            current_fp = current_fingerprints.get(name)
            if current_fp is None:
                drift.append(DriftRecord(name, "removed_since_pin", pinned_fp, None))
            elif current_fp != pinned_fp:
                drift.append(DriftRecord(name, "schema_changed", pinned_fp, current_fp))
        for name in current_fingerprints:
            if name not in self._pinned:
                drift.append(DriftRecord(name, "new_since_pin", None, current_fingerprints[name]))
        return drift
