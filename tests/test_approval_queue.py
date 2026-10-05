import pytest

from gateway.state import Pin


def test_rejected_proposal_never_applies_its_effect(gateway, issuer, session):
    token = issuer.issue("catalog-ops")
    before = session.get(Pin, 2).deleted
    result = gateway.call(token, "delete_pin", {"pin_id": 2})
    gateway.queue.decide(result.approval_id, approve=False)
    assert session.get(Pin, 2).deleted == before


def test_approved_proposal_applies_its_effect_exactly_once(gateway, issuer, session):
    token = issuer.issue("catalog-ops")
    result = gateway.call(token, "delete_pin", {"pin_id": 3})
    assert session.get(Pin, 3).deleted is False
    gateway.queue.decide(result.approval_id, approve=True)
    assert session.get(Pin, 3).deleted is True


def test_a_decision_cannot_be_made_twice(gateway, issuer):
    token = issuer.issue("catalog-ops")
    result = gateway.call(token, "delete_pin", {"pin_id": 4})
    gateway.queue.decide(result.approval_id, approve=True)
    with pytest.raises(ValueError):
        gateway.queue.decide(result.approval_id, approve=True)


def test_pending_list_excludes_decided_entries(gateway, issuer):
    token = issuer.issue("catalog-ops")
    a = gateway.call(token, "delete_pin", {"pin_id": 5})
    b = gateway.call(token, "delete_pin", {"pin_id": 6})
    assert {e.approval_id for e in gateway.queue.pending()} == {a.approval_id, b.approval_id}
    gateway.queue.decide(a.approval_id, approve=True)
    assert {e.approval_id for e in gateway.queue.pending()} == {b.approval_id}


def test_every_decision_is_recorded_in_the_approval_log(gateway, issuer, session):
    from gateway.state import ApprovalRecord

    token = issuer.issue("catalog-ops")
    result = gateway.call(token, "delete_pin", {"pin_id": 7})
    gateway.queue.decide(result.approval_id, approve=True)
    record = session.query(ApprovalRecord).filter_by(approval_id=result.approval_id).one()
    assert record.decision == "approved"
    assert record.tool == "delete_pin"
