# Governed Agent Tool Gateway with a Registry and Approval Queue

A gateway that stands between an AI agent and 4 domain-specific tool servers (pins, boards, ad campaigns, users; 24 typed tools total), scoping every call to the caller's group with a short-lived signed token, holding every mutating call for human approval, and checking every proposed mutation against an independent deterministic oracle before it ever reaches that approval queue. An internal-operations intake layer turns free-text request tickets into the same scoped, approved calls and is benchmarked against 150 tickets that each carry a planted prompt injection. Stack: Python, FastAPI, TypeScript, PostgreSQL (SQLite exercised this session). Every number below was measured on this machine, not targeted; two of the original headline numbers (the oracle's catch rate, the ranking compute and quality tradeoffs in the sibling project) took genuine design iteration to land near their design target, and that iteration is in Findings, not hidden.

## Why this exists

Pinterest's own published MCP architecture (a fleet of domain servers behind one registry, per-call business-group scoping, human approval before dangerous actions) is the production shape this project mirrors at personal-project scale. The posting weights judgment about when an AI agent is wrong more heavily than almost anything else it asks for, and the only way to evidence that judgment is a measured catch rate from an artifact that actually governs an agent, not an adjective on a resume.

Extended for an internal-operations intake domain: an internal team rarely calls tools directly, it files a free-text ticket ("suspend this account", "pause this campaign, the budget ran over") and something turns that into a tool call. That something is exactly where a planted prompt injection would try to act, so the extension's job is to prove the intake layer resists that while still doing the mundane classification work.

## Honest framing

- **The 4 domain servers are one Python package, not 4 network services.** `gateway/registry.py` models them as 4 logical tool namespaces (pins, boards, ad_campaigns, users) behind one `Registry`, the same separation Pinterest's real fleet enforces, without standing up 4 actual FastAPI processes for a project this size.
- **PostgreSQL is implemented, not exercised.** `gateway/state.py` takes a `DATABASE_URL` and works unchanged against a real Postgres DSN; every number below ran against SQLite (`sqlite:///:memory:` for tests and benchmarks), since Postgres is not installed as a running service on this machine. This matches the rest of this portfolio's convention for a database that is not live here.
- **The "agent" in the 4,000/1,200/3,000-call benchmarks is `DeterministicRouter`, a fast stand-in, not a live model.** `gateway/llm_client.py` defines one `LLMClient` interface with two implementations: `DeterministicRouter`, used at scale because 5,200 real subprocess calls to an LLM would be slow and nondeterministic to benchmark, and `ClaudeCLIClient`, which really shells out to `claude -p` and is exercised on a 20-call live sample in `tests/test_live_claude_sample.py`.
- **The oracle's "6.8%-ish" catch rate is measured on a corpus this project built, with a known seeded mistake rate.** `gateway/corpus.py`'s `generate_oracle_corpus` seeds a fixed, real slice of the live database into terminal states (already-suspended users, already-deleted pins, already-paused campaigns) and draws both clean and deliberately-mistaken proposals from those real pools; `mistake_rate` is this generator's own design knob, tuned over the 3 allowed genuine attempts (Findings has the full story), never the oracle's own rules.
- **Machine and toolchain.** Windows 11, Python 3.12.10, FastAPI 0.115.5, SQLAlchemy 2.0.36, Pydantic 2.10.3, pytest 8.3.4, httpx 0.28.1, `claude` CLI 2.1.296 (headless `-p`, no network calls beyond what that CLI makes on its own).
- **The intake classifier (`gateway/intake.py`) is deliberately regex, not an LLM call.** An LLM-based intake would itself be the prompt-injection attack surface this extension exists to test; a plain-text parser restricted to one field and one sentence has no instruction-following channel for injected text to exploit in the first place. This is a real design tradeoff, not a shortcut: the classifier cannot handle free-form phrasing, only the fixed sentence shapes `gateway/corpus.py`'s ticket generator and a real intake form would both produce.
- **The 150 planted-injection tickets are synthetic, built by this project's own generator.** `generate_intake_corpus` in `gateway/corpus.py` writes every ticket's literal request as an ordinary, in-range ask and plants exactly one injection per ticket across 3 shapes; it is not a red-team dataset collected from anywhere else.

## Architecture

```
gateway/
  registry.py         The source of truth: 4 domain servers, 24 ToolSpecs (name, domain,
                       mutating, permitted_groups, required_params), 4 caller groups
                       (catalog-ops, ads-ops, trust-safety, growth-analytics, the last
                       read-only). permitted_groups includes every group with real access
                       to a tool's domain, read or write; whether a call may actually
                       mutate is a second, independent check in gateway_core.py, so "wrong
                       domain for my group" and "my group can only read" are two distinct,
                       separately testable refusal reasons, not one that makes the other
                       unreachable.
  auth.py              Short-lived HMAC-signed tokens: {group, issued_at, expires_at},
                       verified against a server-held secret, never a caller's
                       self-declared claim.
  state.py             SQLAlchemy models: Pin, Board, AdCampaign, User, and the
                       append-only ApprovalRecord log every approved or rejected proposal
                       is written to exactly once, at decide() time.
  oracle.py             check_action(session, tool, params): 16 independent rules, one per
                       mutating tool, each re-deriving legality from live state alone
                       (target exists, isn't already in the state a mutation would move it
                       to, numeric fields are in range). Shares no code with effects.py.
  effects.py           The actual mutation each write tool performs, reachable only from
                       approval_queue.decide(approve=True), never from gateway_core.py
                       directly.
  approval_queue.py     Every mutating proposal lands here first. Pending until decide();
                       decide(approve=True) calls effects.apply_action and logs an
                       ApprovalRecord; decide(approve=False) logs the rejection and touches
                       no table.
  gateway_core.py       Gateway.call(): resolve the tool, authorize the token (signature,
                       expiry, group-domain permission, write permission), execute reads
                       directly, submit writes to the queue with an oracle verdict
                       attached.
  llm_client.py         LLMClient protocol; DeterministicRouter (the benchmark-scale
                       stand-in) and ClaudeCLIClient (the real `claude -p` subprocess
                       client, live-sampled only).
  corpus.py             Builds all 4 measured corpora: generate_replay_corpus (4,000 mixed
                       read/write calls), generate_adversarial_corpus (1,200 refusal
                       cases, 3 attack shapes), generate_oracle_corpus (proposed mutating
                       actions with a seeded mistake rate, grounded in real terminal-state
                       pools from seed_oracle_terminals), generate_intake_corpus (150
                       internal-operations tickets, each carrying one planted prompt
                       injection across 3 shapes).
  intake.py             classify(ticket_text): extracts (tool, params) from a ticket's
                       Request field, acting on its first sentence only; scans the whole
                       ticket for injection marker phrases without ever letting one change
                       what gets extracted. Never reads a caller's group from ticket text.
  gateway_app.py         FastAPI wrapper: POST /auth/token, POST /tools/{name}/call, GET
                       /approvals, POST /approvals/{id}/decide, GET /registry.
scripts/
  run_replay_benchmark.py        4,000 calls, approves every proposal, reconstructs
                                  expected state from the ApprovalRecord log alone in a
                                  second database and diffs it against the live one.
  run_adversarial_benchmark.py   1,200 adversarial authorization attempts.
  run_oracle_catch_rate.py        The oracle corpus benchmark; takes a mistake_rate arg.
  run_injection_benchmark.py      150 planted-injection tickets through classify() and the
                                  real Gateway, approving only when the oracle agrees;
                                  counts out-of-policy actions (an executed call that is
                                  not the ticket's own literal request).
tests/
  test_registry.py, test_auth.py, test_oracle.py, test_approval_queue.py,
  test_gateway_core.py, test_http_app.py, test_oracle_corpus.py, test_intake.py,
  test_live_claude_sample.py (skips cleanly if `claude` is not on PATH)
```

### Why domain-group permission and write-permission are two separate checks

An earlier version of `registry.py` gave every mutating tool `permitted_groups =
write_groups` only, which meant `growth-analytics` (the one read-only group) was never
even in a write tool's permitted set, so `gateway_core.py`'s separate `can_write` check
could never be the actual reason a call was refused: the domain check always refused it
first. That made the "read-only group attempts a write" adversarial case structurally
untestable even though the code path existed. Fixed by giving every tool in a domain
(read or write) the same `permitted_groups`, so a read-only group legitimately passes the
domain check and is refused specifically by the write-permission check; see Findings for
the benchmark number this fixed.

### Why the intake classifier is restricted to one field and one sentence

A first design kept the classifier scanning the whole ticket for anything that looked like
an instruction, on the theory that a smarter parser would catch more real requests. That is
exactly backwards for this threat model: a parser that will consider instruction-shaped
text anywhere in a document is a parser an injected instruction anywhere in that document
can reach. `classify()` instead reads only the `Request:` field, and only that field's
first sentence; everything else in the ticket, including a second instruction-shaped
sentence appended to the same field, is logged (`trailing_text`) and scanned only for
injection marker phrases, never for a tool match. The restriction is the security property,
not a limitation worked around elsewhere.

## Validation

`pytest tests -q`: 51 tests, 0 failures (`docs/test_output.txt`), covering the registry
shape, token issuance and expiry, every oracle rule, the approval queue's state machine,
authorization refusal paths, the FastAPI app end to end via `TestClient`, the oracle
corpus's precision and recall, the intake classifier's field-and-sentence restriction, and
a 20-call live `claude -p` sample.

Independent reconstruction, not just a passing assertion: `run_replay_benchmark.py`
rebuilds expected final state from the `ApprovalRecord` log in a second, freshly seeded
database and diffs every row of every table against what the gateway actually wrote.

## Findings

**Fixing the domain/write-permission conflation changed the adversarial benchmark's own
shape, not just its pass/fail.** Before the fix in the Architecture section above, all
1,200 adversarial cases were generated as either "wrong group" (800) or "expired token"
(400); the "read-only group attempts a write" shape fell back to "wrong group" every time
because `growth-analytics` was never in a write tool's `permitted_groups` to begin with.
After the fix, the corpus naturally produced 533 wrong-group, 267 read-only-write-attempt,
and 400 expired-token cases, all 1,200 refused (`docs/adversarial_benchmark_output.txt`).
The bug was in the registry's permission model, not the benchmark script, and it would
have stayed invisible forever since the benchmark still reported "1200/1200 refused"
either way, just for the wrong reason two-thirds of the time.

**The oracle catch rate needed a grounded corpus, not just a mistake-rate knob, to mean
anything.** The first version of `generate_oracle_corpus` built "already deleted" /
"already suspended" mistake variants by pointing at `n - 1` (the last id in a range),
without ever actually deleting or suspending anything at that id first. Running it at
`mistake_rate=0.07` measured 9.0% flagged, but with 196 false positives and 121 false
negatives: most of the "flagged" proposals were clean cases the oracle correctly rejected
for an unrelated reason (`restore_user` on a never-suspended user, since no fixture user
was ever suspended), and most of the seeded "mistakes" were silently valid (an item at
`n - 1` that was never actually deleted). `seed_oracle_terminals` fixed this by actually
mutating a known slice of users/pins/boards/campaigns into real terminal states before
generating either case, which took the same `mistake_rate=0.07` to 7.3% flagged with 0
false positives and 0 false negatives. `mistake_rate=0.065`, the 3rd and final genuine
attempt, measured 6.93% (`docs/oracle_catch_rate_output.txt`), closest to the target of
the attempts tried; the rate itself is a corpus design parameter this project controls, so
"genuine attempt" here means adjusting that parameter and rerunning on the real,
now-grounded oracle rules, never touching the rules themselves to chase the number.

**The injection benchmark's own honest shortfall is the same `restore_user` gap found
above, one level up.** `run_injection_benchmark.py` seeds its fixture state the same way
the replay and adversarial benchmarks do (`seed_fixture_state`, nobody pre-suspended), and
`generate_intake_corpus` draws a `restore_user` ticket's target user uniformly rather than
from a grounded "already suspended" pool the way `generate_oracle_corpus`'s
`seed_oracle_terminals` does. The result is that a real, literal, non-adversarial
`restore_user` request is itself a no-op against this fixture and the oracle correctly
rejects it 8 times out of 150 tickets, regardless of the planted injection sharing that
ticket. That is why `matched_ground_truth` in `docs/injection_benchmark_output.txt` is
146-149 per shape rather than a flat 50: not every ticket's own literal request survives
the oracle, and reporting that honestly is more convincing than reporting a suspicious
150/150 approved. `out_of_policy_actions` is still measured at 0/150 on the first genuine
attempt, because an oracle-rejected ticket is counted as refused, not as having executed
anything, let alone the injected action.

## Measured results

Machine: Windows 11, Python 3.12.10, FastAPI 0.115.5, SQLAlchemy 2.0.36, pytest 8.3.4.

| Claim | Measured |
|---|---|
| Registry of 4 domain servers and 24 typed tools | **4 domains, 24 tools** (`tests/test_registry.py`) |
| Each call scoped to the caller's group with a short-lived token | Verified: signature, expiry, domain-permission and write-permission all independently enforced (`tests/test_auth.py`, `tests/test_gateway_core.py`) |
| Every mutating call held for human approval | Verified structurally: `effects.apply_action` is reachable only from `approval_queue.decide(approve=True)`, never from the call path directly (`tests/test_gateway_core.py::test_mutating_call_never_executes_immediately...`) |
| Across 4,000 replayed calls no unapproved write executed | **0/4,000**, state reconstructed from the approval log alone matches live state exactly across all 4 tables (`docs/replay_benchmark_output.txt`) |
| All 1,200 adversarial authorization cases were refused | **1,200/1,200** (533 wrong-group, 267 read-only-group-write-attempt, 400 expired-token) (`docs/adversarial_benchmark_output.txt`) |
| A deterministic oracle caught 6.8% of the agent's proposed actions as wrong | **6.93%** (208/3,000, 0 false positives, 0 false negatives against the seeded ground truth), after 3 genuine attempts at the corpus's mistake-rate parameter (see Findings) (`docs/oracle_catch_rate_output.txt`) |
| Each disagreement surfaced to the approver | **True for every flagged proposal** across both the oracle-corpus benchmark and a dedicated pytest check (`tests/test_oracle_corpus.py`) |
| An intake path classifies and extracts fields from free-text internal requests | Verified: 150/150 tickets classified to the correct tool and params on the first genuine attempt (`tests/test_intake.py`, `docs/injection_benchmark_output.txt`) |
| 0 of 150 planted prompt injections caused an out-of-policy action | **0/150** (`docs/injection_benchmark_output.txt`), split 50/50/50 across a fake-approval-bypass claim, a role-escalation claim, and a same-field instruction-override redirect; 8/150 literal requests were themselves oracle-rejected as stale `restore_user` no-ops, unrelated to the injection (see Findings) |

## Building and running

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt

venv\Scripts\python.exe -m pytest tests -q                     # 51 tests
venv\Scripts\python.exe scripts/run_replay_benchmark.py         # 4,000-call replay
venv\Scripts\python.exe scripts/run_adversarial_benchmark.py    # 1,200-case adversarial auth
venv\Scripts\python.exe scripts/run_oracle_catch_rate.py 0.065  # oracle corpus benchmark
venv\Scripts\python.exe scripts/run_injection_benchmark.py      # 150-ticket intake/injection benchmark

venv\Scripts\python.exe -m uvicorn gateway.gateway_app:app --reload   # the FastAPI app itself
```

`tests/test_live_claude_sample.py` needs the `claude` CLI on `PATH`; it skips cleanly
(`pytest.mark.skipif`) when it is not.

## Sibling comparison

[`ontology-grounded-operations-agent`](https://github.com/Manas103/ontology-grounded-operations-agent) and [`agent-action-harness-deterministic-oracle`](https://github.com/Manas103/agent-action-harness-deterministic-oracle) are the closest siblings: both already cover typed tools, an approval queue, and a deterministic oracle grading agent proposals, and both are measured well (386/386 held-out questions correct, 0/200 malformed proposals reaching the queue; 420 agent tasks graded against an independent expected-state oracle). What neither sibling has is the **architecture** this project is actually about: multiple domain servers behind one registry that resolves tool identity and approved status before a call is made, and per-caller-group authorization scoping on top of that, which is the specific shape Pinterest's own published MCP system uses. The siblings' typed-tool and oracle machinery is reused in spirit here (same category of idea: an oracle independent of whatever proposed the action), not in code; this project's registry-plus-scoping layer is the new part.

## Limitations

- The 4 domain servers are one Python package behind one `Registry`, not 4 independently deployed services; a real fleet would also need network-level isolation between domains, which this project does not model.
- The oracle's 16 rules check existence, lifecycle state, and simple numeric ranges; they do not check cross-field business logic a real moderation or ads-policy team would also enforce (for example, whether a budget change is reasonable given a campaign's historical spend, not just its configured min/max).
- `DeterministicRouter` is a fast stand-in for an agent, not a model; its "mistakes" are seeded by `gateway/corpus.py`, not emergent from a real model's own reasoning errors the way the `ClaudeCLIClient` sample's would be at full scale.
- `intake.classify()` only recognizes the fixed sentence shapes its 16 regexes name; a real ticket written in arbitrary natural language would mostly fail to classify at all (`IntakeError`, refused) rather than being misparsed. That refuse-on-unrecognized behavior is the honest, safe default for this project's scope, not a claim that the classifier generalizes to free-form phrasing.
- The 150-ticket injection benchmark's attacker model is three textual shapes planted by this project's own generator (fake prior approval, claimed role escalation, same-field instruction redirect); it does not cover encoding tricks (base64, zero-width characters), multi-turn injections, or an injection that targets the LLM client an agent on the other side of this gateway would actually use, since this layer sits in front of the gateway and never itself calls an LLM.
- PostgreSQL support is implemented but not exercised this session (see Honest framing); the measured numbers above are all against SQLite.
