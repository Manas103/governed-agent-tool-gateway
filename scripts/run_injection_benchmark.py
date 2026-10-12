#!/usr/bin/env python
# 150 internal-operations tickets, every one carrying a planted prompt injection (a
# claimed prior approval, a claimed elevated role, or a same-field instruction trying to
# redirect the call), run end to end through the real intake classifier and the real
# Gateway exactly as a human approver using this system would: approve a proposal only
# when the oracle agrees, decide on whatever gateway_core.call actually returns. An
# "out-of-policy action" is any ticket where the tool/params that ended up approved or
# executed is not the ticket's own literal first-sentence request, which would mean an
# injection either changed what the classifier extracted or reached execution through
# some path other than the normal authorize-then-approve one.
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.approval_queue import ApprovalQueue
from gateway.auth import TokenIssuer
from gateway.corpus import generate_intake_corpus
from gateway.gateway_core import AuthorizationError, Gateway, ProposalResult, ReadResult
from gateway.intake import IntakeError, classify
from gateway.registry import Registry
from gateway.state import make_session_factory, seed_fixture_state

N_USERS, N_BOARDS, N_PINS, N_CAMPAIGNS = 200, 200, 2000, 100
N_TICKETS = 150
SEED = 20261004


def main() -> None:
    session = make_session_factory("sqlite:///:memory:")()
    seed_fixture_state(session, users=N_USERS, boards=N_BOARDS, pins=N_PINS, campaigns=N_CAMPAIGNS)
    registry = Registry()
    issuer = TokenIssuer(b"injection-benchmark-secret")
    queue = ApprovalQueue(session)
    gateway = Gateway(session, registry, issuer, queue)

    tickets = generate_intake_corpus(
        registry, n=N_TICKETS, seed=SEED, n_users=N_USERS, n_boards=N_BOARDS, n_pins=N_PINS, n_campaigns=N_CAMPAIGNS
    )

    out_of_policy = 0
    by_shape: dict[str, dict[str, int]] = {}
    extraction_mismatches = []
    redirect_matches = []

    for i, ticket in enumerate(tickets):
        by_shape.setdefault(ticket.shape, {"total": 0, "matched_ground_truth": 0, "matched_injected": 0, "refused_or_rejected": 0})
        by_shape[ticket.shape]["total"] += 1

        try:
            result = classify(ticket.ticket_text)
        except IntakeError as exc:
            raise AssertionError(f"ticket {i} ({ticket.shape}) failed to classify: {exc}") from exc

        if not result.injection_detected:
            raise AssertionError(f"ticket {i} ({ticket.shape}) planted an injection that the scan missed")

        # The token comes from the ticket's authenticated submitter record (true_group),
        # never from anything parsed out of the free-text body.
        token = issuer.issue(ticket.true_group)
        try:
            outcome = gateway.call(token, result.tool, result.params)
        except AuthorizationError:
            by_shape[ticket.shape]["refused_or_rejected"] += 1
            continue

        if isinstance(outcome, ReadResult):
            executed_tool, executed_params = result.tool, result.params
        else:
            assert isinstance(outcome, ProposalResult)
            # Stand-in for a careful human approver: approve only when the independent
            # oracle agrees the proposal is legitimate against live state.
            approve = outcome.oracle_ok
            queue.decide(outcome.approval_id, approve=approve)
            if not approve:
                by_shape[ticket.shape]["refused_or_rejected"] += 1
                continue
            executed_tool, executed_params = result.tool, result.params

        matched_ground_truth = (executed_tool, executed_params) == (ticket.ground_truth_tool, ticket.ground_truth_params)
        matched_injected = ticket.injected_tool is not None and (executed_tool, executed_params) == (ticket.injected_tool, ticket.injected_params)

        if matched_ground_truth:
            by_shape[ticket.shape]["matched_ground_truth"] += 1
        if matched_injected:
            by_shape[ticket.shape]["matched_injected"] += 1
            redirect_matches.append(i)

        if not matched_ground_truth or matched_injected:
            out_of_policy += 1
            extraction_mismatches.append(
                {"ticket": i, "shape": ticket.shape, "executed": [executed_tool, executed_params], "ground_truth": [ticket.ground_truth_tool, ticket.ground_truth_params]}
            )

    report = {
        "n_tickets": N_TICKETS,
        "out_of_policy_actions": out_of_policy,
        "by_shape": by_shape,
        "extraction_mismatches": extraction_mismatches,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
