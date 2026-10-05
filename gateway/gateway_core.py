# The gateway call path every tool invocation goes through, independent of any HTTP
# framing (gateway_app.py is a thin FastAPI wrapper around this). authorize() is checked
# before the oracle or the queue ever sees a call: an unauthorized caller never reaches
# either, which is why the adversarial-authorization benchmark can assert refusal without
# touching the approval queue at all.
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .approval_queue import ApprovalEntry, ApprovalQueue
from .auth import TokenError, TokenIssuer, TokenPayload
from .oracle import check_action
from .registry import GROUPS, Registry
from .state import AdCampaign, Board, Pin, User


class AuthorizationError(Exception):
    pass


@dataclass(frozen=True)
class ReadResult:
    tool: str
    data: Any


@dataclass(frozen=True)
class ProposalResult:
    tool: str
    approval_id: str
    oracle_ok: bool
    oracle_reason: str | None


_READERS = {
    "get_pin": lambda s, p: _row_to_dict(s.get(Pin, p["pin_id"])),
    "search_pins": lambda s, p: [
        _row_to_dict(row) for row in s.query(Pin).filter(Pin.description.contains(p["query"])).limit(50)
    ],
    "get_board": lambda s, p: _row_to_dict(s.get(Board, p["board_id"])),
    "list_boards_for_user": lambda s, p: [
        _row_to_dict(row) for row in s.query(Board).filter(Board.owner_user_id == p["user_id"])
    ],
    "get_campaign": lambda s, p: _row_to_dict(s.get(AdCampaign, p["campaign_id"])),
    "list_campaigns": lambda s, p: [_row_to_dict(row) for row in s.query(AdCampaign)],
    "get_user": lambda s, p: _row_to_dict(s.get(User, p["user_id"])),
    "search_users": lambda s, p: [
        _row_to_dict(row) for row in s.query(User).filter(User.email.contains(p["query"])).limit(50)
    ],
}


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return {c.name: getattr(row, c.name) for c in row.__table__.columns}


class Gateway:
    def __init__(self, session: Session, registry: Registry, issuer: TokenIssuer, queue: ApprovalQueue) -> None:
        self.session = session
        self.registry = registry
        self.issuer = issuer
        self.queue = queue

    def authorize(self, token: str, tool_name: str) -> TokenPayload:
        try:
            payload = self.issuer.verify(token)
        except TokenError as exc:
            raise AuthorizationError(str(exc)) from exc
        spec = self.registry.resolve(tool_name)
        if payload.group not in spec.permitted_groups:
            raise AuthorizationError(f"group {payload.group!r} may not call {tool_name!r}")
        if spec.mutating and not GROUPS[payload.group]["can_write"]:
            raise AuthorizationError(f"group {payload.group!r} is read-only, cannot call mutating tool {tool_name!r}")
        return payload

    def call(self, token: str, tool_name: str, params: dict) -> ReadResult | ProposalResult:
        spec = self.registry.resolve(tool_name)
        payload = self.authorize(token, tool_name)
        missing = [p for p in spec.required_params if p not in params]
        if missing:
            raise AuthorizationError(f"missing required params for {tool_name!r}: {missing}")

        if not spec.mutating:
            return ReadResult(tool=tool_name, data=_READERS[tool_name](self.session, params))

        verdict = check_action(self.session, tool_name, params)
        entry: ApprovalEntry = self.queue.submit(
            tool=tool_name, domain=spec.domain, caller_group=payload.group, params=params, oracle_verdict=verdict
        )
        return ProposalResult(tool=tool_name, approval_id=entry.approval_id, oracle_ok=verdict.ok, oracle_reason=verdict.reason)
