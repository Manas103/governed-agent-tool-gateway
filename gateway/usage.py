# Per-team token quotas and chargeback for the LLM call each agent turn makes through
# gateway/llm_client.py. No real metered LLM provider sits behind the 4,000+1,200+N-call
# benchmarks elsewhere in this repo (they run against DeterministicRouter, not a billed
# API), so "provider-reported usage" below is a simulated ground-truth token count,
# computed by a second, independent estimator, standing in for a real provider's billing
# export the same way DeterministicRouter stands in for a real model. The honest question
# this module answers is whether the gateway's own fast, synchronous estimate, the only
# number available on the hot call path before any real provider's async usage report
# would even exist, tracks that ground truth closely enough to charge a team against it.
from __future__ import annotations

import json
import re
from dataclasses import dataclass

# Calibrated once against this repo's own task-description corpus (see
# scripts/run_usage_reconciliation_benchmark.py's measured output); not re-tuned per run.
WORDS_TO_TOKEN_RATIO = 1.51
PRICE_PER_1K_TOKENS_USD = 0.0150

TEAM_MONTHLY_TOKEN_QUOTA: dict[str, int] = {
    "catalog-ops": 2_000_000,
    "ads-ops": 1_200_000,
    "trust-safety": 900_000,
    "growth-analytics": 600_000,
}


class QuotaExceededError(Exception):
    pass


def request_text(task_description: str, tool: str, params: dict) -> str:
    """The text whose length stands in for what would actually be sent to an LLM provider
    for this call: the task description plus the tool and params under consideration."""
    return f"{task_description} tool={tool} params={json.dumps(params, sort_keys=True, default=str)}"


_WORD_SPLIT_RE = re.compile(r"[\s_]+")


def fast_token_estimate(text: str) -> int:
    """The gateway's own live estimator: a word count times a calibrated ratio, cheap
    enough to run synchronously on every call. Splits on underscores as well as
    whitespace, since tool identifiers are snake_case and a real BPE tokenizer would split
    those into multiple subword tokens rather than counting one; a plain whitespace split
    undercounts exactly the longer tool names and was the first attempt's measured bias
    (see docs/usage_reconciliation_output.txt)."""
    words = [w for w in _WORD_SPLIT_RE.split(text) if w]
    return max(1, round(len(words) * WORDS_TO_TOKEN_RATIO))


def provider_token_estimate(text: str) -> int:
    """Stands in for a real provider's own reported token count (simulated; see module
    docstring). ~4 characters per token is the commonly cited average for English text
    under GPT-style BPE tokenizers, and is used here as the independent reference."""
    return max(1, round(len(text) / 4.0))


@dataclass(frozen=True)
class UsageEvent:
    group: str
    tool: str
    domain: str
    fast_tokens: int
    provider_tokens: int

    @property
    def fast_cost_usd(self) -> float:
        return self.fast_tokens / 1000.0 * PRICE_PER_1K_TOKENS_USD

    @property
    def provider_cost_usd(self) -> float:
        return self.provider_tokens / 1000.0 * PRICE_PER_1K_TOKENS_USD


@dataclass(frozen=True)
class ReconciliationRow:
    group: str
    fast_cost_usd: float
    provider_cost_usd: float
    relative_error: float
    n_events: int


class UsageMeter:
    """Enforces per-team token quotas against the fast estimate, the only number available
    at call time, and separately tracks the provider-reported estimate so chargeback can be
    reconciled against it after the fact."""

    def __init__(self, quotas: dict[str, int] | None = None) -> None:
        self._quotas = dict(quotas or TEAM_MONTHLY_TOKEN_QUOTA)
        self._fast_used: dict[str, int] = {g: 0 for g in self._quotas}
        self.events: list[UsageEvent] = []

    def quota(self, group: str) -> int:
        return self._quotas[group]

    def quota_remaining(self, group: str) -> int:
        return self._quotas[group] - self._fast_used.get(group, 0)

    def record(self, *, group: str, tool: str, domain: str, text: str) -> UsageEvent:
        if group not in self._quotas:
            raise KeyError(f"no quota configured for group: {group}")
        fast = fast_token_estimate(text)
        if self._fast_used[group] + fast > self._quotas[group]:
            raise QuotaExceededError(
                f"group {group!r} would exceed its {self._quotas[group]} token quota "
                f"({self._fast_used[group]} used, {fast} requested for this call)"
            )
        provider = provider_token_estimate(text)
        event = UsageEvent(group=group, tool=tool, domain=domain, fast_tokens=fast, provider_tokens=provider)
        self._fast_used[group] += fast
        self.events.append(event)
        return event

    def reconciliation(self) -> list[ReconciliationRow]:
        rows = []
        for group in self._quotas:
            group_events = [e for e in self.events if e.group == group]
            fast_cost = sum(e.fast_cost_usd for e in group_events)
            provider_cost = sum(e.provider_cost_usd for e in group_events)
            relative_error = abs(fast_cost - provider_cost) / provider_cost if provider_cost else 0.0
            rows.append(ReconciliationRow(group, fast_cost, provider_cost, relative_error, len(group_events)))
        return rows
