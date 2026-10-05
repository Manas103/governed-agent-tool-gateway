# Builds the three measured corpora from the seeded fixture state. Every corpus is a
# plain, re-generatable Python list (no external data file), so a benchmark run is
# reproducible from the seed alone.
from __future__ import annotations

import random
from dataclasses import dataclass

from .auth import TokenIssuer
from .registry import GROUPS, Registry

READ_TOOLS = ("get_pin", "search_pins", "get_board", "list_boards_for_user", "get_campaign", "list_campaigns", "get_user", "search_users")
WRITE_TOOLS = (
    "create_pin", "update_pin_description", "delete_pin", "report_pin",
    "create_board", "rename_board", "add_pin_to_board", "delete_board",
    "create_campaign", "update_campaign_budget", "pause_campaign", "delete_campaign",
    "update_user_email", "suspend_user", "restore_user", "delete_user",
)


@dataclass(frozen=True)
class CallSpec:
    tool: str
    group: str
    token: str
    params: dict
    label: str  # free-form, e.g. "legitimate", "mistake:stale-target", "adversarial:wrong-group"


def _owning_group(tool_name: str, registry: Registry) -> str:
    spec = registry.resolve(tool_name)
    for group in spec.permitted_groups:
        if GROUPS[group]["can_write"] or not spec.mutating:
            return group
    raise ValueError(f"no owning group for {tool_name}")


def _correct_params(tool: str, rng: random.Random, n_users: int, n_boards: int, n_pins: int, n_campaigns: int) -> dict:
    if tool == "get_pin":
        return {"pin_id": rng.randrange(n_pins)}
    if tool == "search_pins":
        return {"query": "pin"}
    if tool == "get_board":
        return {"board_id": rng.randrange(n_boards)}
    if tool == "list_boards_for_user":
        return {"user_id": rng.randrange(n_users)}
    if tool == "get_campaign":
        return {"campaign_id": rng.randrange(n_campaigns)}
    if tool == "list_campaigns":
        return {}
    if tool == "get_user":
        return {"user_id": rng.randrange(n_users)}
    if tool == "search_users":
        return {"query": "user"}
    if tool == "create_pin":
        return {"board_id": rng.randrange(n_boards), "description": f"new pin {rng.random():.4f}"}
    if tool == "update_pin_description":
        return {"pin_id": rng.randrange(n_pins), "description": f"updated {rng.random():.4f}"}
    if tool == "delete_pin":
        return {"pin_id": rng.randrange(n_pins)}
    if tool == "report_pin":
        return {"pin_id": rng.randrange(n_pins), "reason": "spam"}
    if tool == "create_board":
        return {"owner_user_id": rng.randrange(n_users), "name": f"board {rng.random():.4f}"}
    if tool == "rename_board":
        return {"board_id": rng.randrange(n_boards), "name": f"renamed {rng.random():.4f}"}
    if tool == "add_pin_to_board":
        return {"board_id": rng.randrange(n_boards), "pin_id": rng.randrange(n_pins)}
    if tool == "delete_board":
        return {"board_id": rng.randrange(n_boards)}
    if tool == "create_campaign":
        return {"name": f"campaign {rng.random():.4f}", "budget_usd": round(rng.uniform(100, 5000), 2)}
    if tool == "update_campaign_budget":
        return {"campaign_id": rng.randrange(n_campaigns), "budget_usd": round(rng.uniform(50, 50_000), 2)}
    if tool == "pause_campaign":
        return {"campaign_id": rng.randrange(n_campaigns)}
    if tool == "delete_campaign":
        return {"campaign_id": rng.randrange(n_campaigns)}
    if tool == "update_user_email":
        return {"user_id": rng.randrange(n_users), "email": f"user{rng.randrange(n_users)}@updated.test"}
    if tool == "suspend_user":
        return {"user_id": rng.randrange(n_users), "reason": "policy violation"}
    if tool == "restore_user":
        return {"user_id": rng.randrange(n_users)}
    if tool == "delete_user":
        return {"user_id": rng.randrange(n_users)}
    raise ValueError(f"no generator for {tool}")


@dataclass(frozen=True)
class OraclePools:
    active_users: list[int]
    suspended_users: list[int]
    live_boards: list[int]
    deleted_boards: list[int]
    unreported_live_pins: list[int]
    reported_pins: list[int]
    deleted_pins: list[int]
    unpaused_live_campaigns: list[int]
    paused_campaigns: list[int]
    deleted_campaigns: list[int]


def seed_oracle_terminals(session, *, n_users: int, n_boards: int, n_pins: int, n_campaigns: int) -> OraclePools:
    """Marks a known, fixed slice of each entity type into a real terminal state (already
    suspended/deleted/reported/paused) in the live session, and returns the exact id pools
    that state corresponds to. Every "correct" and "mistake" proposal in
    generate_oracle_corpus is drawn from one of these pools, so both are grounded in a
    before-state that genuinely exists rather than guessed from an index like `n - 1`."""
    from .state import AdCampaign, Board, Pin, User

    suspended_users = list(range(0, n_users // 5))
    for uid in suspended_users:
        session.get(User, uid).suspended = True

    deleted_boards = list(range(0, n_boards // 10))
    for bid in deleted_boards:
        session.get(Board, bid).deleted = True

    deleted_pins = list(range(0, n_pins // 10))
    reported_pins = list(range(n_pins // 10, n_pins // 10 + n_pins // 10))
    for pid in deleted_pins:
        session.get(Pin, pid).deleted = True
    for pid in reported_pins:
        session.get(Pin, pid).reported = True

    deleted_campaigns = list(range(0, n_campaigns // 10))
    paused_campaigns = list(range(n_campaigns // 10, n_campaigns // 10 + n_campaigns // 10))
    for cid in deleted_campaigns:
        session.get(AdCampaign, cid).deleted = True
    for cid in paused_campaigns:
        session.get(AdCampaign, cid).paused = True
    session.commit()

    return OraclePools(
        active_users=list(range(n_users // 5, n_users)),
        suspended_users=suspended_users,
        live_boards=list(range(n_boards // 10, n_boards)),
        deleted_boards=deleted_boards,
        unreported_live_pins=list(range(n_pins // 10 + n_pins // 10, n_pins)),
        reported_pins=reported_pins,
        deleted_pins=deleted_pins,
        unpaused_live_campaigns=list(range(n_campaigns // 10 + n_campaigns // 10, n_campaigns)),
        paused_campaigns=paused_campaigns,
        deleted_campaigns=deleted_campaigns,
    )


def _oracle_correct_params(tool: str, pools: OraclePools, rng: random.Random) -> dict:
    if tool == "create_pin":
        return {"board_id": rng.choice(pools.live_boards), "description": f"new pin {rng.random():.4f}"}
    if tool == "update_pin_description":
        return {"pin_id": rng.choice(pools.unreported_live_pins), "description": f"updated {rng.random():.4f}"}
    if tool == "delete_pin":
        return {"pin_id": rng.choice(pools.unreported_live_pins)}
    if tool == "report_pin":
        return {"pin_id": rng.choice(pools.unreported_live_pins), "reason": "spam"}
    if tool == "create_board":
        return {"owner_user_id": rng.choice(pools.active_users), "name": f"board {rng.random():.4f}"}
    if tool == "rename_board":
        return {"board_id": rng.choice(pools.live_boards), "name": f"renamed {rng.random():.4f}"}
    if tool == "add_pin_to_board":
        return {"board_id": rng.choice(pools.live_boards), "pin_id": rng.choice(pools.unreported_live_pins)}
    if tool == "delete_board":
        return {"board_id": rng.choice(pools.live_boards)}
    if tool == "create_campaign":
        return {"name": f"campaign {rng.random():.4f}", "budget_usd": round(rng.uniform(100, 5000), 2)}
    if tool == "update_campaign_budget":
        campaign_id = rng.choice(pools.unpaused_live_campaigns + pools.paused_campaigns)
        return {"campaign_id": campaign_id, "budget_usd": round(rng.uniform(50, 50_000), 2)}
    if tool == "pause_campaign":
        return {"campaign_id": rng.choice(pools.unpaused_live_campaigns)}
    if tool == "delete_campaign":
        return {"campaign_id": rng.choice(pools.unpaused_live_campaigns + pools.paused_campaigns)}
    if tool == "update_user_email":
        uid = rng.choice(pools.active_users + pools.suspended_users)
        return {"user_id": uid, "email": f"user{uid}@updated.test"}
    if tool == "suspend_user":
        return {"user_id": rng.choice(pools.active_users), "reason": "policy violation"}
    if tool == "restore_user":
        return {"user_id": rng.choice(pools.suspended_users)}
    if tool == "delete_user":
        return {"user_id": rng.choice(pools.active_users + pools.suspended_users)}
    raise ValueError(f"no correct-case generator for {tool}")


def _oracle_mistake_params(tool: str, correct: dict, pools: OraclePools, rng: random.Random, n_boards: int, n_users: int) -> tuple[dict, str]:
    """A plausible real mistake, grounded in a before-state that genuinely holds in the
    live session: a target that is in range but already in a terminal lifecycle state
    (OraclePools), a target that was never seeded at all (a hallucinated id past the end
    of a real pool), or a value a careless agent could type (an out-of-range budget, a
    malformed email)."""
    if tool in ("delete_pin", "update_pin_description"):
        return {**correct, "pin_id": rng.choice(pools.deleted_pins)}, "stale-target:pin-already-deleted"
    if tool == "report_pin":
        return {**correct, "pin_id": rng.choice(pools.reported_pins)}, "stale-target:pin-already-reported"
    if tool == "create_pin":
        return {**correct, "board_id": rng.choice(pools.deleted_boards)}, "stale-target:board-already-deleted"
    if tool in ("delete_board", "rename_board"):
        return {**correct, "board_id": rng.choice(pools.deleted_boards)}, "stale-target:board-already-deleted"
    if tool == "add_pin_to_board":
        return {**correct, "pin_id": rng.choice(pools.deleted_pins)}, "stale-target:pin-already-deleted"
    if tool == "create_board":
        return {**correct, "owner_user_id": n_users + 50}, "hallucinated-target:user-does-not-exist"
    if tool == "delete_campaign":
        return {**correct, "campaign_id": rng.choice(pools.deleted_campaigns)}, "stale-target:campaign-already-deleted"
    if tool == "pause_campaign":
        return {**correct, "campaign_id": rng.choice(pools.paused_campaigns)}, "stale-target:campaign-already-paused"
    if tool == "update_campaign_budget":
        return {**correct, "budget_usd": 999_999.0}, "out-of-range:budget-exceeds-campaign-max"
    if tool == "create_campaign":
        return {**correct, "budget_usd": -1.0}, "invalid:negative-starting-budget"
    if tool == "update_user_email":
        return {**correct, "email": "not-an-email"}, "malformed:invalid-email"
    if tool == "suspend_user":
        return {**correct, "user_id": rng.choice(pools.suspended_users)}, "stale-target:user-already-suspended"
    if tool == "delete_user":
        return {**correct, "user_id": n_users + 50}, "hallucinated-target:user-does-not-exist"
    if tool == "restore_user":
        return {**correct, "user_id": rng.choice(pools.active_users)}, "stale-target:user-not-suspended"
    raise ValueError(f"no mistake variant for {tool}")


def generate_replay_corpus(registry: Registry, issuer: TokenIssuer, *, n: int, seed: int, n_users: int, n_boards: int, n_pins: int, n_campaigns: int) -> list[CallSpec]:
    """A realistic mix of reads and legitimate writes, for the structural "no unapproved
    write ever executed" check. Every call here is authorized and uses in-range,
    currently-valid targets; the point of this corpus is the plumbing, not correctness."""
    rng = random.Random(seed)
    tools = READ_TOOLS + WRITE_TOOLS
    calls = []
    for _ in range(n):
        tool = rng.choice(tools)
        group = _owning_group(tool, registry)
        token = issuer.issue(group)
        params = _correct_params(tool, rng, n_users, n_boards, n_pins, n_campaigns)
        calls.append(CallSpec(tool=tool, group=group, token=token, params=params, label="legitimate"))
    return calls


def generate_adversarial_corpus(registry: Registry, issuer: TokenIssuer, *, n: int, seed: int) -> list[CallSpec]:
    """Every entry here is authorized-as-attempted but must be refused: wrong group for the
    tool's domain, a read-only group attempting a write, or an expired token. Split roughly
    evenly across the three attack shapes."""
    rng = random.Random(seed)
    tools = READ_TOOLS + WRITE_TOOLS
    all_groups = list(GROUPS)
    calls = []
    for i in range(n):
        tool = rng.choice(tools)
        spec = registry.resolve(tool)
        shape = i % 3
        if shape == 0:
            # Wrong group entirely: pick a group not permitted for this tool.
            wrong_groups = [g for g in all_groups if g not in spec.permitted_groups]
            group = rng.choice(wrong_groups) if wrong_groups else rng.choice(all_groups)
            token = issuer.issue(group)
            label = "adversarial:wrong-group"
        elif shape == 1:
            # Read-only group attempting a write tool whose domain it CAN read.
            readonly_groups = [g for g, s in GROUPS.items() if not s["can_write"] and g in spec.permitted_groups]
            if not readonly_groups or not spec.mutating:
                # Fall back to a wrong-group case if this tool has no read-only reader.
                wrong_groups = [g for g in all_groups if g not in spec.permitted_groups] or all_groups
                group = rng.choice(wrong_groups)
                token = issuer.issue(group)
                label = "adversarial:wrong-group"
            else:
                group = rng.choice(readonly_groups)
                token = issuer.issue(group)
                label = "adversarial:read-only-group-write-attempt"
        else:
            group = rng.choice(list(spec.permitted_groups)) if spec.permitted_groups else rng.choice(all_groups)
            token = issuer.issue_expired(group)
            label = "adversarial:expired-token"
        calls.append(CallSpec(tool=tool, group=group, token=token, params={}, label=label))
    return calls


@dataclass(frozen=True)
class OracleCorpusItem:
    tool: str
    group: str
    token: str
    task_description: str
    candidate_params: dict
    is_mistake: bool
    mistake_kind: str | None


def generate_oracle_corpus(session, registry: Registry, issuer: TokenIssuer, *, n: int, seed: int, mistake_rate: float, n_users: int, n_boards: int, n_pins: int, n_campaigns: int) -> list[OracleCorpusItem]:
    """Proposed mutating actions only (reads are never "proposed", they execute directly).
    Seeds a fixed slice of the live session into real terminal states first
    (seed_oracle_terminals) so both the "correct" and "mistake" proposals below are
    grounded in a before-state that actually exists. `mistake_rate` is this generator's
    own design knob, not a target being fit to the oracle's output: it decides what
    fraction of proposals are seeded to be genuinely wrong before the oracle ever looks at
    them. The oracle's measured catch rate, computed in
    scripts/run_oracle_catch_rate.py, is what actually gets reported."""
    pools = seed_oracle_terminals(session, n_users=n_users, n_boards=n_boards, n_pins=n_pins, n_campaigns=n_campaigns)
    rng = random.Random(seed)
    items = []
    for _ in range(n):
        tool = rng.choice(WRITE_TOOLS)
        group = _owning_group(tool, registry)
        token = issuer.issue(group)
        correct = _oracle_correct_params(tool, pools, rng)
        if rng.random() < mistake_rate:
            params, kind = _oracle_mistake_params(tool, correct, pools, rng, n_boards, n_users)
            items.append(OracleCorpusItem(tool, group, token, f"perform {tool}", params, True, kind))
        else:
            items.append(OracleCorpusItem(tool, group, token, f"perform {tool}", correct, False, None))
    return items
