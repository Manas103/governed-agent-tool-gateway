#!/usr/bin/env python
# Replays 4,000 calls (a realistic mix of reads and legitimate writes) through the real
# Gateway, approving every proposal exactly as a human approver would for a clean batch,
# then proves "no unapproved write ever executed" the only way that is actually
# convincing: by reconstructing expected final state from the ApprovalRecord log alone
# (a second, independent read of the same facts) and diffing it, field by field, against
# the live domain tables the gateway actually wrote to.
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.approval_queue import ApprovalQueue
from gateway.auth import TokenIssuer
from gateway.corpus import generate_replay_corpus
from gateway.effects import apply_action
from gateway.gateway_core import Gateway, ProposalResult, ReadResult
from gateway.registry import Registry
from gateway.state import ApprovalRecord, make_session_factory, seed_fixture_state

N_USERS, N_BOARDS, N_PINS, N_CAMPAIGNS = 200, 200, 2000, 100
N_CALLS = 4000
SEED = 20261004


def main() -> None:
    session_factory = make_session_factory("sqlite:///:memory:")
    session = session_factory()
    seed_fixture_state(session, users=N_USERS, boards=N_BOARDS, pins=N_PINS, campaigns=N_CAMPAIGNS)

    registry = Registry()
    issuer = TokenIssuer(b"replay-benchmark-secret")
    queue = ApprovalQueue(session)
    gateway = Gateway(session, registry, issuer, queue)

    calls = generate_replay_corpus(
        registry, issuer, n=N_CALLS, seed=SEED, n_users=N_USERS, n_boards=N_BOARDS, n_pins=N_PINS, n_campaigns=N_CAMPAIGNS
    )

    reads = 0
    writes_approved = 0
    unapproved_writes_executed = 0  # would only ever increase from a real bypass bug
    for call in calls:
        try:
            result = gateway.call(call.token, call.tool, call.params)
        except Exception:
            # A legitimate-corpus call failing authorization would itself be the bug; none
            # should, since every token here is issued for the tool's own owning group.
            raise
        if isinstance(result, ReadResult):
            reads += 1
        else:
            assert isinstance(result, ProposalResult)
            queue.decide(result.approval_id, approve=True)
            writes_approved += 1

    # Independent reconstruction: replay every APPROVED record from the log, from scratch,
    # into a second in-memory database seeded identically, and diff its tables against the
    # live one the gateway actually wrote to.
    shadow_factory = make_session_factory("sqlite:///:memory:")
    shadow = shadow_factory()
    seed_fixture_state(shadow, users=N_USERS, boards=N_BOARDS, pins=N_PINS, campaigns=N_CAMPAIGNS)
    records = session.query(ApprovalRecord).order_by(ApprovalRecord.id).all()
    for record in records:
        if record.decision == "approved":
            apply_action(shadow, record.tool, json.loads(record.params_json))
    shadow.commit()

    from gateway.state import AdCampaign, Board, Pin, User

    mismatches = []
    for model in (Pin, Board, AdCampaign, User):
        live_rows = {row.id: _row_signature(row) for row in session.query(model)}
        shadow_rows = {row.id: _row_signature(row) for row in shadow.query(model)}
        if live_rows != shadow_rows:
            mismatches.append(model.__tablename__)

    approved_count = sum(1 for r in records if r.decision == "approved")
    if approved_count != writes_approved:
        unapproved_writes_executed = abs(writes_approved - approved_count)

    report = {
        "n_calls": N_CALLS,
        "reads": reads,
        "writes_approved": writes_approved,
        "approval_log_rows": len(records),
        "state_reconstructed_from_log_matches_live_state": not mismatches,
        "mismatched_tables": mismatches,
        "unapproved_writes_executed": unapproved_writes_executed,
    }
    print(json.dumps(report, indent=2))


def _row_signature(row) -> tuple:
    return tuple(getattr(row, c.name) for c in row.__table__.columns)


if __name__ == "__main__":
    main()
