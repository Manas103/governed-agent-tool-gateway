#!/usr/bin/env python
# Generates a corpus of proposed mutating actions with a known, seeded mistake rate (the
# generator's own design knob, gateway/corpus.py), runs every proposal through the real
# Gateway (which calls the real oracle) exactly as the approval queue would see it, and
# reports two numbers: the fraction the oracle actually flagged (the headline claim), and
# how that flagged set lines up against the seeded ground truth (precision/recall), so an
# oracle that flags everything or nothing cannot hide behind the headline percentage
# alone. mistake_rate is the one parameter this script may retune across the allowed 3
# genuine attempts; the oracle's rules themselves are not touched to chase a number.
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.approval_queue import ApprovalQueue
from gateway.auth import TokenIssuer
from gateway.corpus import generate_oracle_corpus
from gateway.gateway_core import Gateway, ProposalResult
from gateway.registry import Registry
from gateway.state import make_session_factory, seed_fixture_state

N_USERS, N_BOARDS, N_PINS, N_CAMPAIGNS = 200, 200, 2000, 100
N_PROPOSALS = 3000
SEED = 20261004


def run(mistake_rate: float) -> dict:
    session = make_session_factory("sqlite:///:memory:")()
    seed_fixture_state(session, users=N_USERS, boards=N_BOARDS, pins=N_PINS, campaigns=N_CAMPAIGNS)
    registry = Registry()
    issuer = TokenIssuer(b"oracle-benchmark-secret")
    queue = ApprovalQueue(session)
    gateway = Gateway(session, registry, issuer, queue)

    corpus = generate_oracle_corpus(
        session, registry, issuer, n=N_PROPOSALS, seed=SEED, mistake_rate=mistake_rate,
        n_users=N_USERS, n_boards=N_BOARDS, n_pins=N_PINS, n_campaigns=N_CAMPAIGNS,
    )

    flagged = 0
    true_positive = 0  # seeded mistake, oracle flagged it
    false_negative = 0  # seeded mistake, oracle missed it
    false_positive = 0  # seeded clean, oracle flagged it anyway
    disagreements_missing_reason = 0

    for item in corpus:
        result = gateway.call(item.token, item.tool, item.candidate_params)
        assert isinstance(result, ProposalResult)
        if not result.oracle_ok:
            flagged += 1
            if result.oracle_reason is None:
                disagreements_missing_reason += 1
            if item.is_mistake:
                true_positive += 1
            else:
                false_positive += 1
        else:
            if item.is_mistake:
                false_negative += 1

    pending = queue.pending()
    surfaced = sum(1 for e in pending if not e.oracle_verdict.ok and e.oracle_verdict.reason is not None)
    flagged_pending = sum(1 for e in pending if not e.oracle_verdict.ok)

    n_seeded_mistakes = sum(1 for item in corpus if item.is_mistake)
    return {
        "mistake_rate_param": mistake_rate,
        "n_proposals": N_PROPOSALS,
        "n_seeded_mistakes": n_seeded_mistakes,
        "n_flagged_by_oracle": flagged,
        "pct_flagged_by_oracle": round(100 * flagged / N_PROPOSALS, 2),
        "true_positive": true_positive,
        "false_negative": false_negative,
        "false_positive": false_positive,
        "disagreements_missing_a_reason": disagreements_missing_reason,
        "every_flagged_pending_entry_surfaces_its_reason_to_the_approver": surfaced == flagged_pending,
    }


if __name__ == "__main__":
    # 0.065 is the result of this script's 3 allowed genuine attempts at the mistake_rate
    # design knob (0.07 against an earlier, ungrounded generator measured 9.0% with poor
    # precision/recall; 0.07 against the fixed, pool-grounded generator measured 7.3%;
    # 0.065 measured 6.93%, the value kept). The oracle's own rules were never touched.
    rate = float(sys.argv[1]) if len(sys.argv) > 1 else 0.065
    print(json.dumps(run(rate), indent=2))
