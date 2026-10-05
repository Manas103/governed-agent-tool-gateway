# The 4,000/1,200/3,000-item benchmarks all run DeterministicRouter, a fast stand-in
# measured at scale. This test is the live-model sanity check on the same LLMClient
# interface: 20 real `claude -p` subprocess calls (claude-haiku-4-5, headless CLI, no
# network call besides what that CLI makes on its own), each asked to choose between an
# oracle-clean candidate and an oracle-flagged one for the same task, and the test asserts
# the real gateway call path (authorization, oracle check, approval queue) behaves
# identically regardless of which client proposed the action. Skips cleanly if the `claude`
# binary is not on PATH, matching this portfolio's convention for a live external
# dependency that is not guaranteed to be present on every build machine.
from __future__ import annotations

import json
import shutil

import pytest

from gateway.corpus import seed_oracle_terminals
from gateway.gateway_core import ProposalResult
from gateway.llm_client import ClaudeCLIClient

N_USERS, N_BOARDS, N_PINS, N_CAMPAIGNS = 50, 50, 400, 30

pytestmark = pytest.mark.skipif(shutil.which("claude") is None, reason="claude CLI not on PATH")


def test_20_live_claude_proposals_each_match_their_intended_oracle_verdict(gateway, issuer, registry, session):
    pools = seed_oracle_terminals(session, n_users=N_USERS, n_boards=N_BOARDS, n_pins=N_PINS, n_campaigns=N_CAMPAIGNS)
    client = ClaudeCLIClient()

    cases = [
        ("delete_pin", {"pin_id": pools.unreported_live_pins[0]}, False),
        ("delete_pin", {"pin_id": pools.deleted_pins[0]}, True),
        ("report_pin", {"pin_id": pools.unreported_live_pins[1], "reason": "spam"}, False),
        ("report_pin", {"pin_id": pools.reported_pins[0], "reason": "spam"}, True),
        ("suspend_user", {"user_id": pools.active_users[0], "reason": "policy"}, False),
        ("suspend_user", {"user_id": pools.suspended_users[0], "reason": "policy"}, True),
        ("restore_user", {"user_id": pools.suspended_users[1]}, False),
        ("restore_user", {"user_id": pools.active_users[1]}, True),
        ("pause_campaign", {"campaign_id": pools.unpaused_live_campaigns[0]}, False),
        ("pause_campaign", {"campaign_id": pools.paused_campaigns[0]}, True),
        ("delete_campaign", {"campaign_id": pools.unpaused_live_campaigns[1]}, False),
        ("delete_campaign", {"campaign_id": pools.deleted_campaigns[0]}, True),
        ("delete_board", {"board_id": pools.live_boards[0]}, False),
        ("delete_board", {"board_id": pools.deleted_boards[0]}, True),
        ("rename_board", {"board_id": pools.live_boards[1], "name": "renamed"}, False),
        ("rename_board", {"board_id": pools.deleted_boards[0], "name": "renamed"}, True),
        ("update_campaign_budget", {"campaign_id": pools.unpaused_live_campaigns[2], "budget_usd": 500.0}, False),
        ("update_campaign_budget", {"campaign_id": pools.unpaused_live_campaigns[2], "budget_usd": 999_999.0}, True),
        ("update_user_email", {"user_id": pools.active_users[2], "email": "a@b.test"}, False),
        ("update_user_email", {"user_id": pools.active_users[2], "email": "not-an-email"}, True),
    ]
    assert len(cases) == 20

    correct = 0
    details = []
    for tool, params, expect_flagged in cases:
        proposed = client.propose(f"perform {tool}", tool, params)
        assert proposed.params == params, "claude -p must echo the candidate params verbatim, not invent new ones"
        # Route through the exact owning group the way the benchmark scripts do.
        from gateway.corpus import _owning_group

        token = issuer.issue(_owning_group(tool, registry))
        result = gateway.call(token, tool, proposed.params)
        assert isinstance(result, ProposalResult)
        matched = (not result.oracle_ok) == expect_flagged
        details.append({"tool": tool, "expect_flagged": expect_flagged, "oracle_ok": result.oracle_ok, "matched": matched})
        if matched:
            correct += 1

    assert correct == len(cases), json.dumps(details, indent=2)
