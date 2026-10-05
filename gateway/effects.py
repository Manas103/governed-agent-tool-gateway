# The actual mutation each write tool performs, applied only from approval_queue.decide()
# after a human approval. This module is never reachable from gateway_app's call path
# directly; a mutating tool call always stops at the queue first. Read tools are served
# straight out of these same tables from gateway_app without going through here.
from __future__ import annotations

from sqlalchemy.orm import Session

from .state import AdCampaign, Board, Pin, User


def apply_action(session: Session, tool: str, params: dict) -> None:
    _APPLIERS[tool](session, params)


def _next_id(session: Session, model) -> int:
    existing = session.query(model.id).order_by(model.id.desc()).first()
    return (existing[0] + 1) if existing else 0


def _apply_create_pin(session: Session, params: dict) -> None:
    pin = Pin(id=_next_id(session, Pin), board_id=params["board_id"], description=params["description"])
    session.add(pin)


def _apply_update_pin_description(session: Session, params: dict) -> None:
    session.get(Pin, params["pin_id"]).description = params["description"]


def _apply_delete_pin(session: Session, params: dict) -> None:
    session.get(Pin, params["pin_id"]).deleted = True


def _apply_report_pin(session: Session, params: dict) -> None:
    session.get(Pin, params["pin_id"]).reported = True


def _apply_create_board(session: Session, params: dict) -> None:
    board = Board(id=_next_id(session, Board), owner_user_id=params["owner_user_id"], name=params["name"])
    session.add(board)


def _apply_rename_board(session: Session, params: dict) -> None:
    session.get(Board, params["board_id"]).name = params["name"]


def _apply_add_pin_to_board(session: Session, params: dict) -> None:
    session.get(Pin, params["pin_id"]).board_id = params["board_id"]


def _apply_delete_board(session: Session, params: dict) -> None:
    session.get(Board, params["board_id"]).deleted = True


def _apply_create_campaign(session: Session, params: dict) -> None:
    campaign = AdCampaign(id=_next_id(session, AdCampaign), name=params["name"], budget_usd=params["budget_usd"])
    session.add(campaign)


def _apply_update_campaign_budget(session: Session, params: dict) -> None:
    session.get(AdCampaign, params["campaign_id"]).budget_usd = params["budget_usd"]


def _apply_pause_campaign(session: Session, params: dict) -> None:
    session.get(AdCampaign, params["campaign_id"]).paused = True


def _apply_delete_campaign(session: Session, params: dict) -> None:
    session.get(AdCampaign, params["campaign_id"]).deleted = True


def _apply_update_user_email(session: Session, params: dict) -> None:
    session.get(User, params["user_id"]).email = params["email"]


def _apply_suspend_user(session: Session, params: dict) -> None:
    session.get(User, params["user_id"]).suspended = True


def _apply_restore_user(session: Session, params: dict) -> None:
    session.get(User, params["user_id"]).suspended = False


def _apply_delete_user(session: Session, params: dict) -> None:
    session.get(User, params["user_id"]).deleted = True


_APPLIERS = {
    "create_pin": _apply_create_pin,
    "update_pin_description": _apply_update_pin_description,
    "delete_pin": _apply_delete_pin,
    "report_pin": _apply_report_pin,
    "create_board": _apply_create_board,
    "rename_board": _apply_rename_board,
    "add_pin_to_board": _apply_add_pin_to_board,
    "delete_board": _apply_delete_board,
    "create_campaign": _apply_create_campaign,
    "update_campaign_budget": _apply_update_campaign_budget,
    "pause_campaign": _apply_pause_campaign,
    "delete_campaign": _apply_delete_campaign,
    "update_user_email": _apply_update_user_email,
    "suspend_user": _apply_suspend_user,
    "restore_user": _apply_restore_user,
    "delete_user": _apply_delete_user,
}
