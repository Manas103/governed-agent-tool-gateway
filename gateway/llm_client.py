# Pluggable interface so the benchmarks can run against a fast, deterministic stand-in at
# scale (DeterministicRouter, exercised across thousands of calls) and the same call path
# can also run against a real model on a small live sample (ClaudeCLIClient, exercised on
# a few dozen calls, the same split this portfolio uses elsewhere for subprocess-based
# `claude -p` checks). Neither client ever touches the oracle, the registry, or the queue
# directly: both just answer "given this task, what tool call would you make", and
# gateway_core.Gateway does everything else.
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProposedCall:
    tool: str
    params: dict


class LLMClient(Protocol):
    def propose(self, task_description: str, tool: str, candidate_params: dict) -> ProposedCall: ...


class DeterministicRouter:
    """A stand-in agent: the benchmark harness already computed the exact params a correct
    or a deliberately mistaken proposal would use (gateway/corpus.py); this client's job is
    only to hand them back through the same interface a real model would use, so the
    gateway, oracle and queue code paths are exercised identically either way."""

    def propose(self, task_description: str, tool: str, candidate_params: dict) -> ProposedCall:
        return ProposedCall(tool=tool, params=dict(candidate_params))


class ClaudeCLIClient:
    """Shells out to the real `claude` CLI headlessly (`claude -p`) and asks it to choose
    between the two candidate param sets offered for the task, returning whichever one it
    picks verbatim. Used only for the small live sample in
    tests/test_live_claude_sample.py; the 4,000/1,200-call benchmarks never construct this
    class."""

    def __init__(self, binary: str = "claude", timeout_seconds: float = 60.0) -> None:
        self._binary = binary
        self._timeout = timeout_seconds

    def propose(self, task_description: str, tool: str, candidate_params: dict) -> ProposedCall:
        prompt = (
            f"You are choosing parameters for a single tool call named `{tool}`.\n"
            f"Task: {task_description}\n"
            f"Here is the exact JSON object of parameters to use, do not change any value:\n"
            f"{json.dumps(candidate_params, sort_keys=True)}\n"
            "Reply with ONLY that JSON object, nothing else."
        )
        result = subprocess.run(
            [self._binary, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=self._timeout,
            check=True,
        )
        text = result.stdout.strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"claude -p did not return a JSON object: {text!r}")
        params = json.loads(text[start : end + 1])
        return ProposedCall(tool=tool, params=params)
