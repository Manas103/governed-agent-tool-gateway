from gateway.oracle import check_action
from gateway.state import AdCampaign, Board, Pin, User


def test_create_pin_ok_on_live_board(session):
    assert check_action(session, "create_pin", {"board_id": 0, "description": "x"}).ok


def test_create_pin_flagged_on_deleted_board(session):
    session.get(Board, 0).deleted = True
    session.commit()
    v = check_action(session, "create_pin", {"board_id": 0, "description": "x"})
    assert not v.ok and "deleted" in v.reason


def test_delete_pin_flagged_when_already_deleted(session):
    session.get(Pin, 0).deleted = True
    session.commit()
    v = check_action(session, "delete_pin", {"pin_id": 0})
    assert not v.ok


def test_delete_pin_flagged_when_target_does_not_exist(session):
    v = check_action(session, "delete_pin", {"pin_id": 999_999})
    assert not v.ok


def test_report_pin_flagged_on_duplicate_report(session):
    session.get(Pin, 0).reported = True
    session.commit()
    v = check_action(session, "report_pin", {"pin_id": 0, "reason": "spam"})
    assert not v.ok


def test_update_campaign_budget_ok_within_range(session):
    c = session.get(AdCampaign, 0)
    v = check_action(session, "update_campaign_budget", {"campaign_id": 0, "budget_usd": (c.min_budget_usd + c.max_budget_usd) / 2})
    assert v.ok


def test_update_campaign_budget_flagged_above_max(session):
    c = session.get(AdCampaign, 0)
    v = check_action(session, "update_campaign_budget", {"campaign_id": 0, "budget_usd": c.max_budget_usd + 1})
    assert not v.ok


def test_update_campaign_budget_flagged_below_min(session):
    c = session.get(AdCampaign, 0)
    v = check_action(session, "update_campaign_budget", {"campaign_id": 0, "budget_usd": c.min_budget_usd - 1})
    assert not v.ok


def test_pause_campaign_flagged_when_already_paused(session):
    session.get(AdCampaign, 0).paused = True
    session.commit()
    v = check_action(session, "pause_campaign", {"campaign_id": 0})
    assert not v.ok


def test_suspend_user_flagged_when_already_suspended(session):
    session.get(User, 0).suspended = True
    session.commit()
    v = check_action(session, "suspend_user", {"user_id": 0, "reason": "x"})
    assert not v.ok


def test_restore_user_flagged_when_not_suspended(session):
    v = check_action(session, "restore_user", {"user_id": 0})
    assert not v.ok


def test_restore_user_ok_when_suspended(session):
    session.get(User, 0).suspended = True
    session.commit()
    v = check_action(session, "restore_user", {"user_id": 0})
    assert v.ok


def test_update_user_email_flagged_on_malformed_address(session):
    v = check_action(session, "update_user_email", {"user_id": 0, "email": "not-an-email"})
    assert not v.ok


def test_unregistered_tool_is_flagged_not_crashed(session):
    v = check_action(session, "not_a_real_tool", {})
    assert not v.ok
