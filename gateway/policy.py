# A real `opa eval` subprocess against a real Rego file (policy/trajectory.rego), not a
# Python re-implementation of the rule. OPA is not installed as a persistent part of this
# machine's toolchain (see README "Honest framing"); set OPA_BIN to an absolute opa binary
# path, or put `opa` on PATH, to exercise this for real. decide_trajectory() fails closed
# in both documented ways: a tool with no registry annotation at all, and any error while
# invoking or parsing opa's own output (a non-zero exit, a timeout, malformed JSON).
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REGO_PATH = Path(__file__).resolve().parent.parent / "policy" / "trajectory.rego"
_QUERY = "data.gateway.trajectory.allow"


class PolicyUnavailableError(Exception):
    """Raised only by tests that need to tell "opa is not installed here" apart from a
    real policy decision; decide_trajectory() itself never raises this, it denies."""


@dataclass(frozen=True)
class PolicyDecision:
    allow: bool
    reason: str
    evaluated: bool  # False when fail-closed without ever reaching opa (missing annotation)


def opa_binary() -> str | None:
    env = os.environ.get("OPA_BIN")
    if env and Path(env).exists():
        return env
    return shutil.which("opa")


def _call_entry(tool: str, annotations: frozenset[str] | list[str]) -> dict[str, Any]:
    return {"tool": tool, "annotations": sorted(annotations)}


def decide_trajectory(
    current_tool: str,
    current_annotations: frozenset[str],
    history: list[tuple[str, frozenset[str]]],
) -> PolicyDecision:
    """input.current / input.history carry only tool identity and registry annotations,
    exactly the three inputs the resume claims: tool identity, argument authority (which
    is what an annotation like `private_read` or `external_send` means, derived once in
    registry.py from each tool's parameter and return shape, never from a call's actual
    argument values), and prior call trajectory. No params, prompt text, or document
    content are ever constructed into this payload, structurally, not just by convention."""
    if not current_annotations:
        return PolicyDecision(False, f"missing annotation for {current_tool!r}: deny by default", evaluated=False)
    for hist_tool, hist_annotations in history:
        if not hist_annotations:
            return PolicyDecision(False, f"missing annotation for {hist_tool!r} in trajectory: deny by default", evaluated=False)

    opa = opa_binary()
    if opa is None:
        return PolicyDecision(False, "policy evaluation error (opa binary not found): deny by default", evaluated=False)

    payload = {
        "current": _call_entry(current_tool, current_annotations),
        "history": [_call_entry(t, a) for t, a in history],
    }
    try:
        proc = subprocess.run(
            [opa, "eval", "-I", "-f", "json", "-d", str(_REGO_PATH), _QUERY],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return PolicyDecision(False, f"policy evaluation error (opa exit {proc.returncode}): deny by default", evaluated=True)
        parsed = json.loads(proc.stdout)
        allow = bool(parsed["result"][0]["expressions"][0]["value"])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, IndexError, ValueError) as exc:
        return PolicyDecision(False, f"policy evaluation error ({exc}): deny by default", evaluated=True)

    if allow:
        return PolicyDecision(True, "allowed", evaluated=True)
    return PolicyDecision(False, "denied: external_send follows private_read in trajectory", evaluated=True)
