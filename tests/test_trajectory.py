# TrajectoryPolicy (the session-history layer) and Gateway.call's session_id integration,
# against the real opa binary. Skips cleanly when opa is not reachable, same convention as
# test_policy.py.
from __future__ import annotations

import pytest

from gateway.gateway_core import Gateway, TrajectoryPolicyError
from gateway.policy import opa_binary
from gateway.trajectory import TrajectoryPolicy

requires_opa = pytest.mark.skipif(opa_binary() is None, reason="opa binary not on PATH/OPA_BIN")


@requires_opa
def test_report_pin_denied_after_get_user_in_same_session(gateway: Gateway, issuer, registry):
    token = issuer.issue("trust-safety")
    gateway.call(token, "get_user", {"user_id": 1}, session_id="s1")
    with pytest.raises(TrajectoryPolicyError):
        gateway.call(token, "report_pin", {"pin_id": 2, "reason": "spam"}, session_id="s1")


@requires_opa
def test_report_pin_denied_after_search_users_in_same_session(gateway: Gateway, issuer):
    token = issuer.issue("trust-safety")
    gateway.call(token, "search_users", {"query": "user"}, session_id="s1")
    with pytest.raises(TrajectoryPolicyError):
        gateway.call(token, "report_pin", {"pin_id": 2, "reason": "spam"}, session_id="s1")


@requires_opa
def test_report_pin_denied_even_with_a_benign_call_in_between(gateway: Gateway, issuer):
    token = issuer.issue("trust-safety")
    gateway.call(token, "get_user", {"user_id": 1}, session_id="s1")
    gateway.call(token, "get_pin", {"pin_id": 3}, session_id="s1")
    with pytest.raises(TrajectoryPolicyError):
        gateway.call(token, "report_pin", {"pin_id": 2, "reason": "spam"}, session_id="s1")


@requires_opa
def test_report_pin_allowed_in_a_session_with_no_private_read(gateway: Gateway, issuer):
    token = issuer.issue("trust-safety")
    gateway.call(token, "get_pin", {"pin_id": 3}, session_id="s1")
    result = gateway.call(token, "report_pin", {"pin_id": 2, "reason": "spam"}, session_id="s1")
    assert result.tool == "report_pin"


@requires_opa
def test_sessions_are_isolated(gateway: Gateway, issuer):
    token = issuer.issue("trust-safety")
    gateway.call(token, "get_user", {"user_id": 1}, session_id="session-a")
    # A different session_id has never seen the private read, so it is unaffected.
    result = gateway.call(token, "report_pin", {"pin_id": 2, "reason": "spam"}, session_id="session-b")
    assert result.tool == "report_pin"


def test_no_session_id_skips_trajectory_policy_entirely(gateway: Gateway, issuer):
    # Every pre-extension benchmark calls Gateway.call without session_id; this is what
    # keeps their numbers (1,200/1,200, 0/4,000, 6.93%) unaffected by this layer existing.
    token = issuer.issue("trust-safety")
    gateway.call(token, "get_user", {"user_id": 1})
    result = gateway.call(token, "report_pin", {"pin_id": 2, "reason": "spam"})
    assert result.tool == "report_pin"


def test_trajectory_policy_records_only_tool_identity_and_annotations_never_params():
    policy = TrajectoryPolicy()
    from gateway.registry import Registry

    spec = Registry().resolve("get_user")
    policy.record("s1", spec)
    history = policy.history_for("s1")
    assert history == [("get_user", frozenset({"private_read"}))]
    # Nothing resembling a param value (a user id, an email) is reachable from the
    # recorded entry; it is exactly (tool name, registry annotation set).
