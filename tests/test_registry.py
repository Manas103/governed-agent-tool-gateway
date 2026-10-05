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
