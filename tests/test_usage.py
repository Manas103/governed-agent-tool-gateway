import pytest

from gateway.approval_queue import ApprovalQueue
from gateway.gateway_core import Gateway, QuotaExceededError
from gateway.usage import UsageMeter, fast_token_estimate, provider_token_estimate, request_text


def test_request_text_includes_tool_and_params():
    text = request_text("do a thing", "get_pin", {"pin_id": 1})
    assert "get_pin" in text
    assert "pin_id" in text


def test_fast_token_estimate_splits_on_underscore_and_whitespace():
    assert fast_token_estimate("list_boards_for_user") == fast_token_estimate("list boards for user")


def test_provider_token_estimate_scales_with_length():
    short = provider_token_estimate("hi")
    long = provider_token_estimate("hi " * 100)
    assert long > short


def test_usage_meter_records_and_tracks_remaining_quota():
    meter = UsageMeter(quotas={"catalog-ops": 1000})
    before = meter.quota_remaining("catalog-ops")
    event = meter.record(group="catalog-ops", tool="get_pin", domain="pins", text="run get_pin please")
    assert event.fast_tokens > 0
    assert meter.quota_remaining("catalog-ops") == before - event.fast_tokens


def test_usage_meter_raises_once_quota_exhausted():
    meter = UsageMeter(quotas={"catalog-ops": 5})
    with pytest.raises(QuotaExceededError):
        meter.record(group="catalog-ops", tool="get_pin", domain="pins", text="a fairly long task description here")


def test_usage_meter_unknown_group_raises_key_error():
    meter = UsageMeter(quotas={"catalog-ops": 1000})
    with pytest.raises(KeyError):
        meter.record(group="not-a-real-group", tool="get_pin", domain="pins", text="run it")


def test_reconciliation_reports_zero_error_for_identical_costs():
    meter = UsageMeter(quotas={"catalog-ops": 10_000})
    meter.record(group="catalog-ops", tool="get_pin", domain="pins", text="run get_pin")
    rows = {row.group: row for row in meter.reconciliation()}
    assert rows["catalog-ops"].n_events == 1
    assert rows["catalog-ops"].relative_error >= 0.0


def test_reconciliation_zero_events_has_zero_relative_error():
    meter = UsageMeter(quotas={"catalog-ops": 10_000})
    rows = {row.group: row for row in meter.reconciliation()}
    assert rows["catalog-ops"].n_events == 0
    assert rows["catalog-ops"].relative_error == 0.0


def test_gateway_quota_exceeded_before_executing_read(session, registry, issuer):
    queue = ApprovalQueue(session)
    meter = UsageMeter(quotas={"growth-analytics": 1})
    gateway = Gateway(session, registry, issuer, queue, usage_meter=meter)
    token = issuer.issue("growth-analytics")
    with pytest.raises(QuotaExceededError):
        gateway.call(token, "get_pin", {"pin_id": 0}, task_description="a task description long enough to exceed one token")


def test_gateway_call_without_task_description_never_touches_meter(session, registry, issuer):
    queue = ApprovalQueue(session)
    meter = UsageMeter(quotas={"growth-analytics": 10_000})
    gateway = Gateway(session, registry, issuer, queue, usage_meter=meter)
    token = issuer.issue("growth-analytics")
    gateway.call(token, "get_pin", {"pin_id": 0})
    assert meter.events == []
