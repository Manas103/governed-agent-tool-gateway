from __future__ import annotations

from dataclasses import replace

from gateway.registry import Registry
from gateway.schema_pinning import CatalogPin, fingerprint_mcp_tool, fingerprint_tool


def test_identical_registry_shows_no_drift():
    registry = Registry()
    pin = CatalogPin({name: fingerprint_tool(spec) for name, spec in registry.tools.items()})
    current = {name: fingerprint_tool(spec) for name, spec in registry.tools.items()}
    assert pin.check_drift(current) == []


def test_six_mutated_tools_are_caught_with_zero_false_positives():
    registry = Registry()
    pin = CatalogPin({name: fingerprint_tool(spec) for name, spec in registry.tools.items()})

    mutated = dict(registry.tools)
    mutated["get_pin"] = replace(mutated["get_pin"], required_params=())
    mutated["delete_pin"] = replace(mutated["delete_pin"], permitted_groups=mutated["delete_pin"].permitted_groups | frozenset({"ads-ops"}))
    mutated["get_user"] = replace(mutated["get_user"], annotations=frozenset({"none"}))
    mutated["pause_campaign"] = replace(mutated["pause_campaign"], mutating=False)
    mutated["report_pin"] = replace(mutated["report_pin"], required_params=("pin_id",))
    mutated["update_user_email"] = replace(mutated["update_user_email"], domain="boards")
    expected_drifted = {"get_pin", "delete_pin", "get_user", "pause_campaign", "report_pin", "update_user_email"}

    current = {name: fingerprint_tool(spec) for name, spec in mutated.items()}
    drift = pin.check_drift(current)
    drifted_names = {d.tool for d in drift}

    assert drifted_names == expected_drifted
    unchanged = set(registry.tools) - expected_drifted
    assert all(d.tool not in unchanged for d in drift)


def test_removed_tool_is_flagged():
    registry = Registry()
    pin = CatalogPin({name: fingerprint_tool(spec) for name, spec in registry.tools.items()})
    current = {name: fp for name, fp in {n: fingerprint_tool(s) for n, s in registry.tools.items()}.items() if name != "delete_user"}
    drift = pin.check_drift(current)
    assert any(d.tool == "delete_user" and d.kind == "removed_since_pin" for d in drift)


def test_new_tool_since_pin_is_flagged():
    registry = Registry()
    pin = CatalogPin({name: fingerprint_tool(spec) for name, spec in registry.tools.items() if name != "get_board"})
    current = {name: fingerprint_tool(spec) for name, spec in registry.tools.items()}
    drift = pin.check_drift(current)
    assert any(d.tool == "get_board" and d.kind == "new_since_pin" for d in drift)


def test_mcp_fingerprint_is_sensitive_to_schema_and_meta():
    fp1 = fingerprint_mcp_tool("get_user", {"required": ["token", "user_id"]}, {"annotations": ["private_read"]})
    fp2 = fingerprint_mcp_tool("get_user", {"required": ["token", "user_id"]}, {"annotations": []})
    fp3 = fingerprint_mcp_tool("get_user", {"required": ["token", "user_id"]}, {"annotations": ["private_read"]})
    assert fp1 != fp2
    assert fp1 == fp3
