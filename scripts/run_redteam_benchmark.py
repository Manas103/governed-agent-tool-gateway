"""Red-team benchmark: 640 payloads across 8 technique families through
the deterministic agent, with and without the guardrail, plus the 250-
benign-request false-refusal check. Writes docs/redteam_benchmark_output.txt
and docs/redteam_summary.json.

Usage: python scripts/run_redteam_benchmark.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from redteam.agent import DeterministicAgent
from redteam.corpus import build_benign_requests, run_benign_requests, run_payloads
from redteam.payloads import FAMILIES, build_payloads


def main() -> None:
    out: list[str] = []

    def log(msg):
        print(msg)
        out.append(msg)

    payloads = build_payloads()
    log(f"payloads: {len(payloads)} across {len(FAMILIES)} families")

    agent = DeterministicAgent()
    outcomes = run_payloads(payloads, agent)

    n_total = len(outcomes)
    n_success_before = sum(1 for o in outcomes if o.attack_success)
    n_success_after = sum(1 for o in outcomes if o.attack_success and not o.blocked_by_guardrail)
    log(f"\n== attack success ==\nbefore guardrail: {n_success_before} / {n_total} ({n_success_before / n_total * 100:.2f}%)")
    log(f"after guardrail:  {n_success_after} / {n_total} ({n_success_after / n_total * 100:.2f}%)")

    by_family = Counter()
    by_family_total = Counter()
    for o in outcomes:
        by_family_total[o.payload.family_id] += 1
        if o.attack_success:
            by_family[o.payload.family_id] += 1
    log("\nbefore-guardrail success by family:")
    for f in FAMILIES:
        log(f"  {f.id} [{f.owasp_category} {f.owasp_name}]: {by_family[f.id]} / {by_family_total[f.id]}")

    residual = [o for o in outcomes if o.attack_success and not o.blocked_by_guardrail]
    log(f"\nresidual (still succeeded after guardrail): {len(residual)}")
    for o in residual[:20]:
        log(f"  family={o.payload.family_id} template={o.payload.template_id} delivery={o.payload.delivery} "
            f"cross_tool={o.payload.cross_tool} reason={o.guardrail.reason}")

    benign = build_benign_requests(250)
    benign_outcomes = run_benign_requests(benign, agent)
    n_refused = sum(1 for b in benign_outcomes if b.refused)
    log(f"\n== benign control set ==\nrefused: {n_refused} / {len(benign_outcomes)} ({n_refused / len(benign_outcomes) * 100:.2f}%)")

    owasp_map = {f.id: {"category": f.owasp_category, "name": f.owasp_name} for f in FAMILIES}
    log(f"\n== OWASP LLM Top 10 mapping ==\n{json.dumps(owasp_map, indent=2)}")

    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "redteam_benchmark_output.txt").write_text("\n".join(out), encoding="utf-8")

    summary = {
        "n_payloads": n_total,
        "n_families": len(FAMILIES),
        "attack_success_before_guardrail": n_success_before,
        "attack_success_before_guardrail_pct": n_success_before / n_total * 100,
        "attack_success_after_guardrail": n_success_after,
        "attack_success_after_guardrail_pct": n_success_after / n_total * 100,
        "by_family_before_guardrail": dict(by_family),
        "n_benign": len(benign_outcomes),
        "n_benign_refused": n_refused,
        "benign_refusal_rate_pct": n_refused / len(benign_outcomes) * 100,
        "owasp_mapping": owasp_map,
    }
    (docs / "redteam_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\nwrote docs/redteam_benchmark_output.txt and docs/redteam_summary.json")


if __name__ == "__main__":
    main()
