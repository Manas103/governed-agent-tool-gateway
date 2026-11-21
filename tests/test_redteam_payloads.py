"""Claims: 24 typed tools behind one registry (unchanged, verified here
against the real Registry); 8 prompt-injection technique families
expanded into 640 payloads; each finding filed under an OWASP LLM Top 10
category; payloads delivered through tool outputs and request fields."""
from gateway.registry import Registry
from redteam.payloads import FAMILIES, build_payloads


def test_registry_still_has_24_tools_in_4_domains_unchanged():
    registry = Registry()
    assert registry.tool_count() == 24
    assert registry.domain_count() == 4


def test_exactly_8_families_expanded_into_640_payloads():
    assert len(FAMILIES) == 8
    payloads = build_payloads()
    assert len(payloads) == 640
    for family in FAMILIES:
        count = sum(1 for p in payloads if p.family_id == family.id)
        assert count == 80


def test_every_family_has_an_owasp_llm_top_10_category():
    valid_categories = {"LLM01", "LLM02", "LLM03", "LLM04", "LLM05", "LLM06", "LLM07", "LLM08", "LLM09", "LLM10"}
    for family in FAMILIES:
        assert family.owasp_category in valid_categories
        assert family.owasp_name


def test_payloads_split_evenly_between_delivery_modes_per_family():
    payloads = build_payloads()
    for family in FAMILIES:
        family_payloads = [p for p in payloads if p.family_id == family.id]
        request_field = sum(1 for p in family_payloads if p.delivery == "request_field")
        tool_output = sum(1 for p in family_payloads if p.delivery == "tool_output")
        assert request_field == 40
        assert tool_output == 40


def test_cross_tool_alt_action_always_differs_from_base_task_tool():
    payloads = build_payloads()
    for p in payloads:
        if p.cross_tool:
            assert p.alt_tool != p.base_task["tool"]


def test_same_tool_alt_action_keeps_the_tool_but_changes_the_target():
    payloads = build_payloads()
    for p in payloads:
        if not p.cross_tool:
            assert p.alt_tool == p.base_task["tool"]
            assert p.alt_params != p.base_task["params"]


def test_encoded_family_payload_text_contains_no_plaintext_action_words():
    payloads = build_payloads()
    encoded = [p for p in payloads if p.family_id == "encoded_obfuscated"]
    assert len(encoded) == 80
    for p in encoded:
        assert p.alt_tool not in p.text  # the tool name only exists inside the base64 blob
        for key in p.alt_params:
            assert key not in p.text  # param names are likewise only inside the blob
