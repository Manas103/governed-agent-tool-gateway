# gateway.policy.decide_trajectory wraps a real `opa eval` subprocess against a real
# Rego file. OPA is not installed as a persistent part of this machine's toolchain (see
# README); the two fail-closed paths that never need to reach opa at all are tested
# unconditionally, and the tests that need a real decision from opa itself skip cleanly
# when OPA_BIN/PATH does not resolve to a binary, matching this portfolio's convention for
# a live external dependency that is not guaranteed present on every build machine.
from __future__ import annotations

import pytest

from gateway.policy import decide_trajectory, opa_binary

requires_opa = pytest.mark.skipif(opa_binary() is None, reason="opa binary not on PATH/OPA_BIN")


def test_missing_annotation_on_current_call_denies_without_reaching_opa():
    decision = decide_trajectory("mystery_tool", frozenset(), [])
    assert decision.allow is False
    assert decision.evaluated is False
    assert "missing annotation" in decision.reason


def test_missing_annotation_in_history_denies_without_reaching_opa():
    decision = decide_trajectory("report_pin", frozenset({"external_send"}), [("mystery_tool", frozenset())])
    assert decision.allow is False
    assert decision.evaluated is False
    assert "missing annotation" in decision.reason


def test_rule_evaluation_error_denies(monkeypatch):
    # Points opa_binary() at a real, existing executable that is not opa (this test's own
    # Python interpreter): the subprocess genuinely runs and genuinely exits non-zero
    # against opa's argument list, so this exercises the real "opa exit nonzero" except
    # branch in decide_trajectory, not a mocked one.
    import sys

    monkeypatch.setattr("gateway.policy.opa_binary", lambda: sys.executable)
    decision = decide_trajectory("report_pin", frozenset({"external_send"}), [("get_user", frozenset({"private_read"}))])
    assert decision.allow is False
    assert decision.evaluated is True
    assert "policy evaluation error" in decision.reason


def test_no_opa_binary_anywhere_denies(monkeypatch):
    monkeypatch.delenv("OPA_BIN", raising=False)
    monkeypatch.setattr("gateway.policy.shutil.which", lambda name: None)
    decision = decide_trajectory("report_pin", frozenset({"external_send"}), [])
    assert decision.allow is False
    assert decision.evaluated is False
    assert "opa binary not found" in decision.reason


@requires_opa
def test_real_opa_denies_external_send_after_private_read():
    decision = decide_trajectory("report_pin", frozenset({"external_send"}), [("get_user", frozenset({"private_read"}))])
    assert decision.allow is False
    assert decision.evaluated is True
    assert decision.reason == "denied: external_send follows private_read in trajectory"


@requires_opa
def test_real_opa_allows_external_send_with_no_private_read_in_history():
    decision = decide_trajectory("report_pin", frozenset({"external_send"}), [("get_pin", frozenset({"none"}))])
    assert decision.allow is True
    assert decision.evaluated is True


@requires_opa
def test_real_opa_allows_private_read_itself():
    decision = decide_trajectory("get_user", frozenset({"private_read"}), [])
    assert decision.allow is True


@requires_opa
def test_real_opa_denies_regardless_of_how_many_benign_calls_intervene():
    history = [("get_user", frozenset({"private_read"})), ("get_pin", frozenset({"none"})), ("get_board", frozenset({"none"}))]
    decision = decide_trajectory("report_pin", frozenset({"external_send"}), history)
    assert decision.allow is False
