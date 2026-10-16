from gateway.registry import Registry


def test_four_domain_servers(registry: Registry):
    assert registry.domain_count() == 4


def test_twenty_four_typed_tools(registry: Registry):
    assert registry.tool_count() == 24


def test_every_tool_has_at_least_one_permitted_group(registry: Registry):
    for spec in registry.tools.values():
        assert len(spec.permitted_groups) > 0, spec.name


def test_every_tool_declares_its_required_params(registry: Registry):
    for spec in registry.tools.values():
        assert isinstance(spec.required_params, tuple)


def test_every_real_tool_carries_at_least_one_annotation(registry: Registry):
    # The registry itself never produces a tool with an empty annotation set; "missing
    # annotation" (tested directly in test_policy.py) is reachable only via a ToolSpec
    # built outside this map, never a real catalog entry.
    for spec in registry.tools.values():
        assert len(spec.annotations) > 0, spec.name


def test_exactly_one_private_read_and_one_external_send_tool(registry: Registry):
    private_read = [s.name for s in registry.tools.values() if "private_read" in s.annotations]
    external_send = [s.name for s in registry.tools.values() if "external_send" in s.annotations]
    assert set(private_read) == {"get_user", "search_users"}
    assert set(external_send) == {"report_pin"}
