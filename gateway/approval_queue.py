# Every mutating call lands here first and stops: nothing in this module ever runs
# effects.apply_action except decide(approve=True). A rejected or still-pending entry has
# touched the domain tables zero times, which is the property the replay harness in
# tests/test_replay_harness.py checks by reconstructing expected state from
# ApprovalRecord rows alone.
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from enum import Enum

from sqlalchemy.orm import Session

from .effects import apply_action
from .oracle import OracleVerdict
from .state import ApprovalRecord


class Decision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass
class ApprovalEntry:
    approval_id: str
    tool: str
    domain: str
    caller_group: str
    params: dict
    oracle_verdict: OracleVerdict
    decision: Decision = Decision.PENDING


class ApprovalQueue:
    """Holds every mutating proposal pending a human decision. In-memory queue of pending
    entries; the durable record of what was ever actually approved lives in
    ApprovalRecord, written only at decide() time."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._pending: dict[str, ApprovalEntry] = {}

    def submit(self, *, tool: str, domain: str, caller_group: str, params: dict, oracle_verdict: OracleVerdict) -> ApprovalEntry:
        entry = ApprovalEntry(
            approval_id=str(uuid.uuid4()),
            tool=tool,
            domain=domain,
            caller_group=caller_group,
            params=params,
            oracle_verdict=oracle_verdict,
        )
        self._pending[entry.approval_id] = entry
        return entry

    def pending(self) -> list[ApprovalEntry]:
        return [e for e in self._pending.values() if e.decision == Decision.PENDING]

    def get(self, approval_id: str) -> ApprovalEntry:
        return self._pending[approval_id]

    def decide(self, approval_id: str, *, approve: bool) -> ApprovalEntry:
        entry = self._pending[approval_id]
        if entry.decision != Decision.PENDING:
            raise ValueError(f"approval {approval_id} already decided: {entry.decision}")
        entry.decision = Decision.APPROVED if approve else Decision.REJECTED
        if approve:
            apply_action(self._session, entry.tool, entry.params)
        self._session.add(
            ApprovalRecord(
                approval_id=entry.approval_id,
                tool=entry.tool,
                domain=entry.domain,
                caller_group=entry.caller_group,
                params_json=json.dumps(entry.params, sort_keys=True),
                oracle_ok=entry.oracle_verdict.ok,
                oracle_reason=entry.oracle_verdict.reason,
                decision=entry.decision.value,
            )
        )
        self._session.commit()
        return entry
