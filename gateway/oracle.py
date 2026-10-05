# Independent deterministic oracle: re-derives, from the live domain state alone, whether a
# proposed mutating action is actually legal, never by re-running whatever logic produced
# the proposal. The agent (gateway/llm_client.py) and the oracle share no code path; the
# only thing they share is the same database session, read-only, at decision time.
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from .state import AdCampaign, Board, Pin, User


@dataclass(frozen=True)
class OracleVerdict:
    ok: bool
    reason: str | None


def check_action(session: Session, tool: str, params: dict) -> OracleVerdict:
    try:
        return _CHECKERS[tool](session, params)
    except KeyError:
        return OracleVerdict(False, f"oracle has no rule for tool {tool!r}")


def _ok() -> OracleVerdict:
    return OracleVerdict(True, None)


def _fail(reason: str) -> OracleVerdict:
    return OracleVerdict(False, reason)


def _check_create_pin(session: Session, params: dict) -> OracleVerdict:
    board = session.get(Board, params["board_id"])
    if board is None or board.deleted:
        return _fail(f"target board {params['board_id']} does not exist or is deleted")
    return _ok()


def _check_update_pin_description(session: Session, params: dict) -> OracleVerdict:
    pin = session.get(Pin, params["pin_id"])
    if pin is None or pin.deleted:
        return _fail(f"target pin {params['pin_id']} does not exist or is already deleted")
    return _ok()


def _check_delete_pin(session: Session, params: dict) -> OracleVerdict:
    pin = session.get(Pin, params["pin_id"])
    if pin is None:
        return _fail(f"target pin {params['pin_id']} does not exist")
    if pin.deleted:
        return _fail(f"pin {params['pin_id']} is already deleted (no-op proposed as a real action)")
    return _ok()


def _check_report_pin(session: Session, params: dict) -> OracleVerdict:
    pin = session.get(Pin, params["pin_id"])
    if pin is None or pin.deleted:
        return _fail(f"target pin {params['pin_id']} does not exist or is deleted")
    if pin.reported:
        return _fail(f"pin {params['pin_id']} is already reported (duplicate report proposed)")
    return _ok()


def _check_create_board(session: Session, params: dict) -> OracleVerdict:
    owner = session.get(User, params["owner_user_id"])
    if owner is None or owner.deleted:
        return _fail(f"owner user {params['owner_user_id']} does not exist or is deleted")
    return _ok()


def _check_rename_board(session: Session, params: dict) -> OracleVerdict:
    board = session.get(Board, params["board_id"])
    if board is None or board.deleted:
        return _fail(f"target board {params['board_id']} does not exist or is deleted")
    return _ok()


def _check_add_pin_to_board(session: Session, params: dict) -> OracleVerdict:
    board = session.get(Board, params["board_id"])
    pin = session.get(Pin, params["pin_id"])
    if board is None or board.deleted:
        return _fail(f"target board {params['board_id']} does not exist or is deleted")
    if pin is None or pin.deleted:
        return _fail(f"target pin {params['pin_id']} does not exist or is deleted")
    return _ok()


def _check_delete_board(session: Session, params: dict) -> OracleVerdict:
    board = session.get(Board, params["board_id"])
    if board is None:
        return _fail(f"target board {params['board_id']} does not exist")
    if board.deleted:
        return _fail(f"board {params['board_id']} is already deleted")
    return _ok()


def _check_create_campaign(session: Session, params: dict) -> OracleVerdict:
    if params.get("budget_usd", -1) < 0:
        return _fail("negative starting budget proposed")
    return _ok()


def _check_update_campaign_budget(session: Session, params: dict) -> OracleVerdict:
    campaign = session.get(AdCampaign, params["campaign_id"])
    if campaign is None or campaign.deleted:
        return _fail(f"target campaign {params['campaign_id']} does not exist or is deleted")
    new_budget = params["budget_usd"]
    if new_budget < campaign.min_budget_usd or new_budget > campaign.max_budget_usd:
        return _fail(
            f"proposed budget {new_budget} outside campaign's allowed range "
            f"[{campaign.min_budget_usd}, {campaign.max_budget_usd}]"
        )
    return _ok()


def _check_pause_campaign(session: Session, params: dict) -> OracleVerdict:
    campaign = session.get(AdCampaign, params["campaign_id"])
    if campaign is None or campaign.deleted:
        return _fail(f"target campaign {params['campaign_id']} does not exist or is deleted")
    if campaign.paused:
        return _fail(f"campaign {params['campaign_id']} is already paused (duplicate pause proposed)")
    return _ok()


def _check_delete_campaign(session: Session, params: dict) -> OracleVerdict:
    campaign = session.get(AdCampaign, params["campaign_id"])
    if campaign is None:
        return _fail(f"target campaign {params['campaign_id']} does not exist")
    if campaign.deleted:
        return _fail(f"campaign {params['campaign_id']} is already deleted")
    return _ok()


def _check_update_user_email(session: Session, params: dict) -> OracleVerdict:
    user = session.get(User, params["user_id"])
    if user is None or user.deleted:
        return _fail(f"target user {params['user_id']} does not exist or is deleted")
    if "@" not in params.get("email", ""):
        return _fail(f"proposed email {params.get('email')!r} is not a valid address")
    return _ok()


def _check_suspend_user(session: Session, params: dict) -> OracleVerdict:
    user = session.get(User, params["user_id"])
    if user is None or user.deleted:
        return _fail(f"target user {params['user_id']} does not exist or is deleted")
    if user.suspended:
        return _fail(f"user {params['user_id']} is already suspended (duplicate suspend proposed)")
    return _ok()


def _check_restore_user(session: Session, params: dict) -> OracleVerdict:
    user = session.get(User, params["user_id"])
    if user is None or user.deleted:
        return _fail(f"target user {params['user_id']} does not exist or is deleted")
    if not user.suspended:
        return _fail(f"user {params['user_id']} is not suspended (restore is a no-op)")
    return _ok()


def _check_delete_user(session: Session, params: dict) -> OracleVerdict:
    user = session.get(User, params["user_id"])
    if user is None:
        return _fail(f"target user {params['user_id']} does not exist")
    if user.deleted:
        return _fail(f"user {params['user_id']} is already deleted")
    return _ok()


_CHECKERS = {
    "create_pin": _check_create_pin,
    "update_pin_description": _check_update_pin_description,
    "delete_pin": _check_delete_pin,
    "report_pin": _check_report_pin,
    "create_board": _check_create_board,
    "rename_board": _check_rename_board,
    "add_pin_to_board": _check_add_pin_to_board,
    "delete_board": _check_delete_board,
    "create_campaign": _check_create_campaign,
    "update_campaign_budget": _check_update_campaign_budget,
    "pause_campaign": _check_pause_campaign,
    "delete_campaign": _check_delete_campaign,
    "update_user_email": _check_update_user_email,
    "suspend_user": _check_suspend_user,
    "restore_user": _check_restore_user,
    "delete_user": _check_delete_user,
}
