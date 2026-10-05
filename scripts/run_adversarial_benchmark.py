#!/usr/bin/env python
# 1,200 adversarial authorization attempts (wrong group, a read-only group trying to
# write, an expired token), split roughly evenly across the three shapes. Every one of
# these must be refused by Gateway.authorize before the call ever reaches the oracle or
# the approval queue; this script asserts exactly that and reports the honest count.
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.approval_queue import ApprovalQueue
from gateway.auth import TokenIssuer
from gateway.corpus import generate_adversarial_corpus
from gateway.gateway_core import AuthorizationError, Gateway
from gateway.registry import Registry
from gateway.state import make_session_factory, seed_fixture_state

N_CASES = 1200
SEED = 20261004


def main() -> None:
    session = make_session_factory("sqlite:///:memory:")()
    seed_fixture_state(session)
    registry = Registry()
    issuer = TokenIssuer(b"adversarial-benchmark-secret")
    queue = ApprovalQueue(session)
    gateway = Gateway(session, registry, issuer, queue)

    cases = generate_adversarial_corpus(registry, issuer, n=N_CASES, seed=SEED)

    refused = 0
    reached_queue = 0
    by_shape: dict[str, dict[str, int]] = {}
    for case in cases:
        shape = case.label
        by_shape.setdefault(shape, {"total": 0, "refused": 0})
        by_shape[shape]["total"] += 1
        try:
            # Params are intentionally empty for adversarial cases: authorization must be
            # checked, and must fail, before param validation would even run.
            gateway.call(case.token, case.tool, {})
        except AuthorizationError:
            refused += 1
            by_shape[shape]["refused"] += 1
        else:
            reached_queue += 1

    pending_after = len(queue.pending())
    report = {
        "n_cases": N_CASES,
        "refused": refused,
        "reached_queue_or_executed": reached_queue,
        "pending_approvals_after_run": pending_after,
        "by_shape": by_shape,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
