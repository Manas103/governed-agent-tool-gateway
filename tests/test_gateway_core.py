import pytest

from gateway.gateway_core import AuthorizationError, ProposalResult, ReadResult


def test_read_tool_executes_immediately_without_approval(gateway, issuer):
    token = issuer.issue("catalog-ops")
    result = gateway.call(token, "get_pin", {"pin_id": 0})
    assert isinstance(result, ReadResult)
    assert result.data["id"] == 0


def test_mutating_call_never_executes_immediately_it_is_only_proposed(gateway, issuer, session):
    token = issuer.issue("catalog-ops")
    from gateway.state import Pin

    before = session.get(Pin, 0).description
    result = gateway.call(token, "update_pin_description", {"pin_id": 0, "description": "changed"})
    assert isinstance(result, ProposalResult)
    assert session.get(Pin, 0).description == before, "a mutating call must not touch state before approval"


def test_wrong_group_for_domain_is_refused(gateway, issuer):
    token = issuer.issue("ads-ops")
    with pytest.raises(AuthorizationError):
        gateway.call(token, "delete_pin", {"pin_id": 0})


def test_read_only_group_cannot_call_a_write_tool_in_its_own_domain(gateway, issuer):
    token = issuer.issue("growth-analytics")
    with pytest.raises(AuthorizationError):
        gateway.call(token, "delete_pin", {"pin_id": 0})


def test_read_only_group_can_still_read(gateway, issuer):
    token = issuer.issue("growth-analytics")
    result = gateway.call(token, "get_pin", {"pin_id": 0})
    assert isinstance(result, ReadResult)


def test_missing_required_param_is_rejected_before_reaching_the_queue(gateway, issuer):
    token = issuer.issue("catalog-ops")
    with pytest.raises(AuthorizationError):
        gateway.call(token, "delete_pin", {})


def test_oracle_flags_a_delete_of_an_already_deleted_pin(gateway, issuer, session):
    token = issuer.issue("catalog-ops")
    first = gateway.call(token, "delete_pin", {"pin_id": 1})
    gateway.queue.decide(first.approval_id, approve=True)
    second = gateway.call(token, "delete_pin", {"pin_id": 1})
    assert isinstance(second, ProposalResult)
    assert second.oracle_ok is False
    assert "already deleted" in second.oracle_reason
