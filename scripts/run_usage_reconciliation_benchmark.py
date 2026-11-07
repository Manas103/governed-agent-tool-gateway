#!/usr/bin/env python
# Replays several thousand metered agent calls across all 4 caller groups, each carrying a
# natural-language task description of deliberately varying length, through the real
# Gateway with a UsageMeter attached, then reports the per-team chargeback reconciliation
# between the gateway's own fast token estimate (the number quotas are enforced against,
# live) and the simulated provider-reported estimate (an independent reference; see
# gateway/usage.py for why no real provider is actually billed here). A second section
# demonstrates quota enforcement directly: one team's quota is set low enough to be
# exhausted mid-run, and the run proves no accepted call ever pushes that team's recorded
# usage over its quota.
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.approval_queue import ApprovalQueue
from gateway.auth import TokenIssuer
from gateway.gateway_core import Gateway, QuotaExceededError
from gateway.registry import GROUPS, Registry
from gateway.state import make_session_factory, seed_fixture_state
from gateway.usage import TEAM_MONTHLY_TOKEN_QUOTA, UsageMeter

N_USERS, N_BOARDS, N_PINS, N_CAMPAIGNS = 200, 200, 2000, 100
N_CALLS = 4000
SEED = 20261030

_READ_TOOLS_BY_DOMAIN = {
    "pins": ("get_pin", "search_pins"),
    "boards": ("get_board", "list_boards_for_user"),
    "ad_campaigns": ("get_campaign", "list_campaigns"),
    "users": ("get_user", "search_users"),
}


def _task_description(rng: random.Random, tool: str) -> str:
    """Three deliberately different-length shapes: a short directive, a mid-length one with
    a stated reason, and a long one restating context an agent would plausibly carry
    forward from earlier in a session. The spread in character-per-word ratio across these
    three shapes is what makes the reconciliation below a genuine measurement rather than
    an artifact of one fixed sentence template."""
    shape = rng.randrange(3)
    if shape == 0:
        return f"Run {tool}."
    if shape == 1:
        return f"Please run {tool} now, it is needed for the current triage queue item."
    return (
        f"Continuing from the earlier part of this session, the next step is to run "
        f"{tool} so the analyst reviewing this ticket has the data needed to close it "
        f"out without having to ask a follow-up question."
    )


def _tools_for_group(group: str) -> list[str]:
    tools = []
    for domain in GROUPS[group]["domains"]:
        tools.extend(_READ_TOOLS_BY_DOMAIN[domain])
    return tools


def _params_for(tool: str, rng: random.Random) -> dict:
    if tool == "get_pin":
        return {"pin_id": rng.randrange(N_PINS)}
    if tool == "search_pins":
        return {"query": "pin"}
    if tool == "get_board":
        return {"board_id": rng.randrange(N_BOARDS)}
    if tool == "list_boards_for_user":
        return {"user_id": rng.randrange(N_USERS)}
    if tool == "get_campaign":
        return {"campaign_id": rng.randrange(N_CAMPAIGNS)}
    if tool == "list_campaigns":
        return {}
    if tool == "get_user":
        return {"user_id": rng.randrange(N_USERS)}
    if tool == "search_users":
        return {"query": "user"}
    raise ValueError(tool)


def main() -> None:
    session_factory = make_session_factory("sqlite:///:memory:")
    session = session_factory()
    seed_fixture_state(session, users=N_USERS, boards=N_BOARDS, pins=N_PINS, campaigns=N_CAMPAIGNS)

    registry = Registry()
    issuer = TokenIssuer(b"usage-benchmark-secret")
    queue = ApprovalQueue(session)
    meter = UsageMeter()
    gateway = Gateway(session, registry, issuer, queue, usage_meter=meter)

    rng = random.Random(SEED)
    groups = list(GROUPS)
    denied = 0
    served = 0
    for _ in range(N_CALLS):
        group = rng.choice(groups)
        tool = rng.choice(_tools_for_group(group))
        token = issuer.issue(group)
        params = _params_for(tool, rng)
        task_description = _task_description(rng, tool)
        try:
            gateway.call(token, tool, params, task_description=task_description)
            served += 1
        except QuotaExceededError:
            denied += 1

    reconciliation = meter.reconciliation()

    # Quota enforcement, demonstrated directly: a fresh meter with one team's quota set
    # deliberately low, driven past it.
    low_quota_group = "growth-analytics"
    tight_meter = UsageMeter(quotas={**TEAM_MONTHLY_TOKEN_QUOTA, low_quota_group: 500})
    tight_gateway = Gateway(session, registry, issuer, queue, usage_meter=tight_meter)
    quota_denials = 0
    quota_accepted = 0
    over_quota_ever = False
    for _ in range(200):
        tool = rng.choice(_tools_for_group(low_quota_group))
        token = issuer.issue(low_quota_group)
        params = _params_for(tool, rng)
        task_description = _task_description(rng, tool)
        try:
            tight_gateway.call(token, tool, params, task_description=task_description)
            quota_accepted += 1
        except QuotaExceededError:
            quota_denials += 1
        if tight_meter.quota_remaining(low_quota_group) < 0:
            over_quota_ever = True

    report = {
        "n_calls": N_CALLS,
        "served": served,
        "denied_over_quota": denied,
        "reconciliation": [
            {
                "group": row.group,
                "n_events": row.n_events,
                "fast_cost_usd": round(row.fast_cost_usd, 6),
                "provider_cost_usd": round(row.provider_cost_usd, 6),
                "relative_error": row.relative_error,
                "within_half_percent": row.relative_error <= 0.005,
            }
            for row in reconciliation
        ],
        "all_groups_within_half_percent": all(row.relative_error <= 0.005 for row in reconciliation),
        "quota_enforcement_demo": {
            "group": low_quota_group,
            "quota_tokens": 500,
            "accepted": quota_accepted,
            "denied": quota_denials,
            "usage_ever_exceeded_quota": over_quota_ever,
        },
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
