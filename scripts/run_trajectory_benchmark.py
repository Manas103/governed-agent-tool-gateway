#!/usr/bin/env python
# 120 adversarial private-read-then-external-send trajectories, every one authorized at
# every individual step (same caller group, trust-safety, legitimately permitted both
# get_user/search_users and report_pin), that must still be denied at the final step by
# the trajectory policy alone. Paired with a clean control set (no resume claim; reported
# for the same reason every other benchmark in this project pairs a catch rate with a
# false-positive rate). Fails loudly, rather than reporting a misleadingly clean 120/120,
# if the real `opa` binary this benchmark depends on is not reachable: without it, every
# call would be denied fail-closed, including the clean control set, which would be an
# honest signal, not a passing one.
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gateway.approval_queue import ApprovalQueue
from gateway.auth import TokenIssuer
from gateway.corpus import generate_trajectory_corpus
from gateway.gateway_core import AuthorizationError, Gateway, TrajectoryPolicyError
from gateway.policy import opa_binary
from gateway.registry import Registry
from gateway.state import make_session_factory, seed_fixture_state
from gateway.trajectory import TrajectoryPolicy

N_ADVERSARIAL = 120
N_CLEAN = 40
SEED = 20260930
N_USERS = 50
N_PINS = 400


def main() -> None:
    if opa_binary() is None:
        print(
            "FATAL: no opa binary found (set OPA_BIN to an absolute path or put opa on "
            "PATH). This benchmark requires the real OPA evaluator; it will not report a "
            "fail-closed-everything run as a pass.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    session = make_session_factory("sqlite:///:memory:")()
    seed_fixture_state(session, users=N_USERS, pins=N_PINS)
    registry = Registry()
    issuer = TokenIssuer(b"trajectory-benchmark-secret")
    queue = ApprovalQueue(session)
    trajectory = TrajectoryPolicy()
    gateway = Gateway(session, registry, issuer, queue, trajectory=trajectory)

    scenarios = generate_trajectory_corpus(
        registry, issuer, n_adversarial=N_ADVERSARIAL, n_clean=N_CLEAN, seed=SEED, n_users=N_USERS, n_pins=N_PINS
    )

    adversarial_denied = 0
    adversarial_allowed_wrongly = 0
    clean_allowed = 0
    clean_denied_wrongly = 0
    by_shape: dict[str, dict[str, int]] = {}
    deny_reasons: list[str] = []

    for scenario in scenarios:
        final_denied = False
        final_reason = ""
        for step in scenario.steps:
            try:
                gateway.call(scenario.token, step.tool, step.params, session_id=scenario.session_id)
            except TrajectoryPolicyError as exc:
                final_denied = True
                final_reason = str(exc)
                break
            except AuthorizationError as exc:  # pragma: no cover - would indicate a corpus bug
                raise AssertionError(f"unexpected authorization failure in {scenario.label}: {exc}") from exc

        if scenario.expect_final_denied:
            by_shape.setdefault(scenario.label, {"total": 0, "denied": 0})
            by_shape[scenario.label]["total"] += 1
            if final_denied:
                adversarial_denied += 1
                by_shape[scenario.label]["denied"] += 1
                deny_reasons.append(final_reason)
            else:
                adversarial_allowed_wrongly += 1
        else:
            if final_denied:
                clean_denied_wrongly += 1
            else:
                clean_allowed += 1

    report = {
        "opa_binary": opa_binary(),
        "n_adversarial": N_ADVERSARIAL,
        "adversarial_denied": adversarial_denied,
        "adversarial_allowed_wrongly": adversarial_allowed_wrongly,
        "by_shape": by_shape,
        "n_clean": N_CLEAN,
        "clean_allowed": clean_allowed,
        "clean_denied_wrongly": clean_denied_wrongly,
        "sample_deny_reasons": sorted(set(deny_reasons))[:5],
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
