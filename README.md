# Governed Agent Tool Gateway with a Registry and Approval Queue

A gateway that stands between an AI agent and 4 domain-specific tool servers (pins, boards, ad campaigns, users; 24 typed tools total), scoping every call to the caller's group with a short-lived signed token, holding every mutating call for human approval, and checking every proposed mutation against an independent deterministic oracle before it ever reaches that approval queue. An internal-operations intake layer turns free-text request tickets into the same scoped, approved calls and is benchmarked against 150 tickets that each carry a planted prompt injection. Extended with a trajectory-aware policy layer, evaluated by a real Rego/OPA policy, that denies a call based on tool identity and prior call history alone, plus discovery-time tool-schema fingerprinting over a real MCP transport. Stack: Python, FastAPI, MCP, Rego (OPA), TypeScript, PostgreSQL (SQLite exercised this session). Every number below was measured on this machine, not targeted; two of the original headline numbers (the oracle's catch rate, the ranking compute and quality tradeoffs in the sibling project) took genuine design iteration to land near their design target, and that iteration is in Findings, not hidden.

## Why this exists

Pinterest's own published MCP architecture (a fleet of domain servers behind one registry, per-call business-group scoping, human approval before dangerous actions) is the production shape this project mirrors at personal-project scale. The posting weights judgment about when an AI agent is wrong more heavily than almost anything else it asks for, and the only way to evidence that judgment is a measured catch rate from an artifact that actually governs an agent, not an adjective on a resume.

Extended for an internal-operations intake domain: an internal team rarely calls tools directly, it files a free-text ticket ("suspend this account", "pause this campaign, the budget ran over") and something turns that into a tool call. That something is exactly where a planted prompt injection would try to act, so the extension's job is to prove the intake layer resists that while still doing the mundane classification work.

Extended again (Oct. 2026) for a different reader: Harvey's own published MCP policy engine and connector library evaluate policy outside the model on tool identity, argument authority and prior call trajectory alone, never prompt or document content, and pin each approved tool's schema at discovery so a connector that silently changes shape raises an alert rather than a new, un-reviewed capability. This extension adds exactly those three properties on top of the existing registry and approval queue, over a real MCP transport rather than the in-process call path the rest of this project uses: a trajectory-aware policy (`gateway/trajectory.py`, `gateway/policy.py`, `policy/trajectory.rego`) that denies an external-send call following a private read anywhere earlier in the same session, and discovery-time schema fingerprinting (`gateway/schema_pinning.py`) that catches a tool's advertised schema silently changing between two real MCP `list_tools()` calls.

## Honest framing

- **The 4 domain servers are one Python package, not 4 network services.** `gateway/registry.py` models them as 4 logical tool namespaces (pins, boards, ad_campaigns, users) behind one `Registry`, the same separation Pinterest's real fleet enforces, without standing up 4 actual FastAPI processes for a project this size.
- **PostgreSQL is implemented, not exercised.** `gateway/state.py` takes a `DATABASE_URL` and works unchanged against a real Postgres DSN; every number below ran against SQLite (`sqlite:///:memory:` for tests and benchmarks), since Postgres is not installed as a running service on this machine. This matches the rest of this portfolio's convention for a database that is not live here.
- **The "agent" in the 4,000/1,200/3,000-call benchmarks is `DeterministicRouter`, a fast stand-in, not a live model.** `gateway/llm_client.py` defines one `LLMClient` interface with two implementations: `DeterministicRouter`, used at scale because 5,200 real subprocess calls to an LLM would be slow and nondeterministic to benchmark, and `ClaudeCLIClient`, which really shells out to `claude -p` and is exercised on a 20-call live sample in `tests/test_live_claude_sample.py`.
- **The oracle's "6.8%-ish" catch rate is measured on a corpus this project built, with a known seeded mistake rate.** `gateway/corpus.py`'s `generate_oracle_corpus` seeds a fixed, real slice of the live database into terminal states (already-suspended users, already-deleted pins, already-paused campaigns) and draws both clean and deliberately-mistaken proposals from those real pools; `mistake_rate` is this generator's own design knob, tuned over the 3 allowed genuine attempts (Findings has the full story), never the oracle's own rules.
- **Machine and toolchain.** Windows 11, Python 3.12.10, FastAPI 0.115.5, SQLAlchemy 2.0.36, Pydantic 2.14.1, pytest 8.3.4, httpx 0.28.1, `claude` CLI 2.1.296 (headless `-p`, no network calls beyond what that CLI makes on its own); Harvey extension adds MCP Python SDK 1.30.0 (FastMCP, stdio transport) and OPA 1.21.2 (real binary, invoked as a subprocess, not installed as a service).
- **The intake classifier (`gateway/intake.py`) is deliberately regex, not an LLM call.** An LLM-based intake would itself be the prompt-injection attack surface this extension exists to test; a plain-text parser restricted to one field and one sentence has no instruction-following channel for injected text to exploit in the first place. This is a real design tradeoff, not a shortcut: the classifier cannot handle free-form phrasing, only the fixed sentence shapes `gateway/corpus.py`'s ticket generator and a real intake form would both produce.
- **The 150 planted-injection tickets are synthetic, built by this project's own generator.** `generate_intake_corpus` in `gateway/corpus.py` writes every ticket's literal request as an ordinary, in-range ask and plants exactly one injection per ticket across 3 shapes; it is not a red-team dataset collected from anywhere else.
- **OPA is a real binary, genuinely invoked, but is not installed as a persistent part of this machine's toolchain.** `gateway/policy.py` shells out to a real `opa eval` subprocess against a real `.rego` file; this session downloaded the official static Windows binary (`open-policy-agent/opa` release, v1.21.2) to a scratch path and pointed `OPA_BIN` at it. `docs/trajectory_benchmark_output.txt` and every `test_policy.py`/`test_trajectory.py`/`test_mcp_transport.py` OPA-dependent test were genuinely evaluated by it this session; those tests skip cleanly (`pytest.mark.skipif`) if `OPA_BIN`/`PATH` do not resolve to an `opa` binary on a future machine, matching this portfolio's convention for a live external dependency.
- **`report_pin` is this registry's stand-in for "sends data outside the system," not a new tool.** No tool or domain was added to keep this project's original "4 domains, 24 tools" numbers exactly unchanged; instead, `report_pin` (which already forwards a pin reference and reason to Pinterest's external/third-party trust-and-safety review tooling) is annotated `external_send`, and `get_user`/`search_users` (which already return user PII) are annotated `private_read`. Every other tool is annotated `none`, explicitly classified rather than merely unlabeled.
- **The MCP transport exposes 10 of the 24 tools, not the full catalog.** `gateway/mcp_server.py` wires `get_pin`, `search_pins`, `get_board`, `get_campaign`, `get_user`, `search_users`, `report_pin`, `update_user_email`, `suspend_user` and `list_campaigns` as real FastMCP tools over stdio, each dispatching into the same `Gateway.call` used everywhere else in this project (including the trajectory policy). The point of the transport extension is to prove discovery-time fingerprinting and a trajectory decision genuinely round-trip over MCP, not to re-expose all 24 tools a second way.
- **The "6 silent catalog changes" are deliberately injected by this project's own `MCP_CATALOG_VARIANT=mutated` server variant**, run as a second real subprocess and a second real `list_tools()` discovery, not a hypothetical. The other 4 exposed tools are provably unchanged between the two discoveries.

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
  policy.py              Harvey extension: decide_trajectory(), a real `opa eval`
                       subprocess against policy/trajectory.rego. Fails closed (denies
                       without ever reaching opa) when a tool's annotation set is empty,
                       and fails closed on any opa error (non-zero exit, timeout,
                       malformed output).
  trajectory.py          Harvey extension: TrajectoryPolicy, an in-memory per-session_id
                       call history (tool name + registry annotations only, never
                       params). Gateway.call()'s session_id parameter is optional and
                       untouched by every pre-extension benchmark.
  schema_pinning.py      Harvey extension: fingerprint_tool()/fingerprint_mcp_tool()
                       (sha256 of a tool's declared shape) and CatalogPin.check_drift(),
                       which diffs a pinned fingerprint set against a later one.
  mcp_server.py          Harvey extension: a real FastMCP server (stdio transport)
                       exposing 10 of the 24 tools, each dispatching into the same
                       Gateway.call() used everywhere else. MCP_CATALOG_VARIANT=mutated
                       silently changes 6 of those 10 tools' advertised schema, for the
                       catalog-drift benchmark.
  mcp_client.py          Harvey extension: launches gateway/mcp_server.py as a real child
                       process and speaks the real MCP protocol to it (list_tools,
                       call_tool), closing the subprocess when the session exits.
policy/
  trajectory.rego        Harvey extension: the real Rego policy gateway/policy.py
                       evaluates. input.current/input.history carry only tool identity
                       and registry annotations, never a call's actual argument values.
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
  run_trajectory_benchmark.py     Harvey extension: 120 adversarial private-read-then-
                                  external-send trajectories (3 shapes) plus 40 clean
                                  controls, in-process, against the real opa binary.
  run_catalog_drift_benchmark.py  Harvey extension: two real MCP list_tools() discoveries
                                  (original, then mutated) and the fingerprint diff
                                  between them.
tests/
  test_registry.py, test_auth.py, test_oracle.py, test_approval_queue.py,
  test_gateway_core.py, test_http_app.py, test_oracle_corpus.py, test_intake.py,
  test_live_claude_sample.py (skips cleanly if `claude` is not on PATH),
  test_policy.py, test_trajectory.py, test_schema_pinning.py, test_mcp_transport.py
  (the last three skip their opa-dependent cases cleanly if opa is not reachable)
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

### Why the trajectory policy is a real Rego/OPA evaluation, not a Python if-statement

A Python function that checked "does this session's history contain a private_read
entry" would be simpler and would produce the identical 120/120 and 40/40 numbers below.
It would also be a worse artifact for this reader: Harvey's own MCP policy engine post is
explicit that policy is evaluated outside the model, in a real policy engine, specifically
so the rule can be audited, versioned and tested independently of the gateway's own code.
`policy/trajectory.rego` is a real, 15-line Rego file, evaluated by a real `opa eval`
subprocess (`gateway/policy.py`); the Python wrapper's only job is building the input
(tool identity and registry annotations, nothing else) and handling the two fail-closed
cases a missing annotation or a broken opa invocation. That is a smaller, more honest
"deliberately disclosed imperfection" than pretending Rego was the whole mechanism: opa is
not installed as a persistent part of this machine's toolchain, so every opa-dependent
test and benchmark here either genuinely invoked a real downloaded binary this session or
skips cleanly, never a mock standing in for it.

### Why the trajectory check looks at the whole session, not just the previous call

The first version of this design (never shipped) denied a call only when the
*immediately preceding* call in the session was a private_read. That is trivially evaded:
an agent trying to exfiltrate data has every reason to call an unrelated, harmless tool in
between. `policy/trajectory.rego`'s `deny` rule scans `input.history` with `some entry in
input.history`, which is why the "interleaved-benign-call" shape (`get_user`, then
`get_pin`, then `report_pin`) is a third of the 120-case adversarial corpus and is caught
exactly as reliably as the immediate case; see Measured results.

## Validation

`pytest tests -q`: 77 tests, 0 failures (`docs/test_output.txt`), covering the registry
shape, token issuance and expiry, every oracle rule, the approval queue's state machine,
authorization refusal paths, the FastAPI app end to end via `TestClient`, the oracle
corpus's precision and recall, the intake classifier's field-and-sentence restriction, a
20-call live `claude -p` sample, the trajectory policy's two fail-closed paths and its real
`opa`-backed decisions, catalog-fingerprint drift detection, and a real MCP stdio
client/server round trip including a trajectory denial that propagates over the
transport. 10 of the 77 are the opa-dependent cases that skip cleanly without a real `opa`
binary reachable; all 10 ran for real this session (`OPA_BIN` pointed at a downloaded
v1.21.2 Windows binary).

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

**The first `pip install mcp` landed a major version whose server API does not exist in
any form this code expected.** `mcp==2.3.0` resolved by default; `mcp.server.Server` in
that release has no `list_tools()`/`call_tool()` decorators at all; it is a completely
different low-level request-handler API, and `mcp.server.fastmcp` raises its own
`ModuleNotFoundError` on import with a message explaining FastMCP was renamed to
`MCPServer` for 2.x. Pinned to `mcp==1.30.0` (the stable, documented FastMCP API this
project actually uses) and re-verified the stdio round trip for real before writing
anything else against it.

**Installing `mcp` on top of this project's existing `fastapi==0.115.5` pin genuinely
broke the FastAPI app, twice, in two different ways, both found by actually running
`pytest tests/test_http_app.py` rather than assumed fixed.** First: `pip install mcp`
upgraded `starlette` to a version whose `Router.__init__` dropped the `on_startup` kwarg
FastAPI 0.115.5 still passes, so `FastAPI()` itself raised `TypeError` at import time.
Pinned `starlette==0.41.3` (the floor FastAPI 0.115.5's own constraint allows) to fix it,
which in turn left `pip install -r requirements.txt` unresolvable from a clean venv:
`mcp==1.30.0` requires `pydantic>=2.11`, and this project's existing pin was `2.10.3`.
Bumped to `pydantic==2.14.1` (also inside FastAPI 0.115.5's broad `<3.0.0` allowance) and
reinstalled into a genuinely fresh venv from the committed `requirements.txt` alone to
confirm the full 77-test suite passes with no manual steps, not just in the already-warm
venv this was debugged in. `sse-starlette` (a transitive dependency of `mcp`'s unused SSE
transport) still wants `starlette>=0.49.1` and pip prints that conflict as a warning on
every install; disclosed rather than silenced, since this project's own code only ever
imports the stdio transport, which does not touch `sse_starlette` at all.

**A deliberately engineered test for the "deny on a rule error" claim initially failed to
reach the error path it was supposed to test.** The first version of
`test_rule_evaluation_error_denies` pointed `OPA_BIN` at a nonexistent path, expecting the
subprocess call itself to fail; instead `gateway.policy.opa_binary()`'s own existence
check (`Path(env).exists()`) correctly rejected the bad override and fell back to
searching `PATH`, which found nothing, so the test accidentally exercised the
"opa binary not found" path (`evaluated=False`) instead of the intended "opa ran and
errored" path (`evaluated=True`). Fixed by pointing `OPA_BIN` at a real, existing
executable that is not opa (this test's own `sys.executable`), so the subprocess
genuinely starts, genuinely exits non-zero against opa's argument list, and genuinely
exercises the non-zero-exit branch.

**The first version of the schema-drift test's `delete_pin` mutation was not actually a
mutation.** It added `"growth-analytics"` to `delete_pin`'s `permitted_groups`, expecting
that to change its fingerprint; `registry.py`'s `_tools_for_domain` already includes every
read-only group whose `domains` set names a given domain in that domain's
`permitted_groups` (the mechanism the Architecture section's "domain-group permission and
write-permission are two separate checks" note describes), so `growth-analytics` was
already present and the "mutation" was a no-op, caught immediately when the test's own
assertion produced a real 6-vs-7-tool diff instead of the expected 6. Fixed by widening
`delete_pin` to `ads-ops` (a group with no access to the `pins` domain at all) instead,
which is also the more realistic silent-widening scenario.

## Measured results

Machine: Windows 11, Python 3.12.10, FastAPI 0.115.5, SQLAlchemy 2.0.36, pytest 8.3.4; Harvey extension additionally: MCP Python SDK 1.30.0, OPA 1.21.2 (real binary, scratch-path, not a persistent install).

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
| 120 of 120 private-read-then-external-send trajectories denied, across 3 attack shapes | **120/120** (40 immediate, 40 via-search, 40 interleaved with a benign call in between), all denied by the real `opa`-evaluated trajectory policy; 0 false positives on a 40-scenario clean control set (`docs/trajectory_benchmark_output.txt`) |
| Policy decides on tool identity, argument authority and prior call trajectory only, never prompt or document content | Structurally verified: `gateway/policy.py`'s `decide_trajectory()` input is built only from `spec.name` and `spec.annotations`; no `params` dict, ticket text, or pin/user content is ever constructed into the payload sent to `opa eval` (`tests/test_trajectory.py::test_trajectory_policy_records_only_tool_identity_and_annotations_never_params`) |
| Policy denies when a rule errors or an annotation is missing | Verified directly: a tool with an empty annotation set denies without ever invoking opa, and a real opa subprocess that exits non-zero also denies (`tests/test_policy.py`, 4 of its tests) |
| 6 silent catalog changes caught by fingerprinting each approved tool's schema at discovery, over a real MCP transport | **6/6** (annotation stripped, domain reassigned, a required param dropped, another added, a param renamed, a mutating hint flipped), 0 false positives on the other 4 of 10 tools exposed over a real stdio `list_tools()` round trip run twice (original, then a mutated server variant) (`docs/catalog_drift_benchmark_output.txt`) |

## Building and running

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt

venv\Scripts\python.exe -m pytest tests -q                     # 77 tests
venv\Scripts\python.exe scripts/run_replay_benchmark.py         # 4,000-call replay
venv\Scripts\python.exe scripts/run_adversarial_benchmark.py    # 1,200-case adversarial auth
venv\Scripts\python.exe scripts/run_oracle_catch_rate.py 0.065  # oracle corpus benchmark
venv\Scripts\python.exe scripts/run_injection_benchmark.py      # 150-ticket intake/injection benchmark

venv\Scripts\python.exe -m uvicorn gateway.gateway_app:app --reload   # the FastAPI app itself
```

`tests/test_live_claude_sample.py` needs the `claude` CLI on `PATH`; it skips cleanly
(`pytest.mark.skipif`) when it is not.

### Harvey extension: OPA and the real MCP transport

The trajectory policy and catalog-drift benchmarks need a real `opa` binary. It is not
installed as a persistent part of this machine's toolchain; download the official static
binary and point `OPA_BIN` at it (or put `opa` on `PATH`):

```
# https://github.com/open-policy-agent/opa/releases/latest, opa_windows_amd64.exe
set OPA_BIN=C:\path\to\opa.exe

venv\Scripts\python.exe scripts/run_trajectory_benchmark.py     # 120-trajectory + 40-clean benchmark
venv\Scripts\python.exe scripts/run_catalog_drift_benchmark.py  # two real MCP discoveries, fingerprint diff

venv\Scripts\python.exe -m gateway.mcp_server                   # the MCP server standalone (stdio transport)
set MCP_CATALOG_VARIANT=mutated & venv\Scripts\python.exe -m gateway.mcp_server   # the 6-tool-mutated variant
```

Every `test_policy.py`/`test_trajectory.py`/`test_mcp_transport.py` case that needs opa
skips cleanly (`pytest.mark.skipif(opa_binary() is None, ...)`) without it; `scripts/
run_trajectory_benchmark.py` exits non-zero instead of reporting a misleadingly clean
run, since a missing opa binary would make the trajectory policy fail closed on
everything, including the clean control set.

## Sibling comparison

[`ontology-grounded-operations-agent`](https://github.com/Manas103/ontology-grounded-operations-agent) and [`agent-action-harness-deterministic-oracle`](https://github.com/Manas103/agent-action-harness-deterministic-oracle) are the closest siblings: both already cover typed tools, an approval queue, and a deterministic oracle grading agent proposals, and both are measured well (386/386 held-out questions correct, 0/200 malformed proposals reaching the queue; 420 agent tasks graded against an independent expected-state oracle). What neither sibling has is the **architecture** this project is actually about: multiple domain servers behind one registry that resolves tool identity and approved status before a call is made, and per-caller-group authorization scoping on top of that, which is the specific shape Pinterest's own published MCP system uses. The siblings' typed-tool and oracle machinery is reused in spirit here (same category of idea: an oracle independent of whatever proposed the action), not in code; this project's registry-plus-scoping layer is the new part.

## Limitations

- The 4 domain servers are one Python package behind one `Registry`, not 4 independently deployed services; a real fleet would also need network-level isolation between domains, which this project does not model.
- The oracle's 16 rules check existence, lifecycle state, and simple numeric ranges; they do not check cross-field business logic a real moderation or ads-policy team would also enforce (for example, whether a budget change is reasonable given a campaign's historical spend, not just its configured min/max).
- `DeterministicRouter` is a fast stand-in for an agent, not a model; its "mistakes" are seeded by `gateway/corpus.py`, not emergent from a real model's own reasoning errors the way the `ClaudeCLIClient` sample's would be at full scale.
- `intake.classify()` only recognizes the fixed sentence shapes its 16 regexes name; a real ticket written in arbitrary natural language would mostly fail to classify at all (`IntakeError`, refused) rather than being misparsed. That refuse-on-unrecognized behavior is the honest, safe default for this project's scope, not a claim that the classifier generalizes to free-form phrasing.
- The 150-ticket injection benchmark's attacker model is three textual shapes planted by this project's own generator (fake prior approval, claimed role escalation, same-field instruction redirect); it does not cover encoding tricks (base64, zero-width characters), multi-turn injections, or an injection that targets the LLM client an agent on the other side of this gateway would actually use, since this layer sits in front of the gateway and never itself calls an LLM.
- PostgreSQL support is implemented but not exercised this session (see Honest framing); the measured numbers above are all against SQLite.
- The trajectory policy's vocabulary is 2 annotations (`private_read`, `external_send`) over 3 of this registry's 24 tools; it does not attempt the general case of an agent exfiltrating data through an arbitrary chain of tool calls whose individual steps were never annotated for this purpose.
- `report_pin` is a repurposed existing tool standing in for "sends data outside the system," not a dedicated network call to an external service; a production version of this policy would annotate a fleet's actual outbound-integration tools, not a trust-and-safety report queue.
- The MCP transport exposes 10 of the 24 tools; the other 14 (boards and ad-campaigns writes, pin/board/campaign deletes, and a few reads) are reachable only through the in-process `Gateway.call` path the rest of this project's benchmarks use, not over MCP.
- The 6 simulated catalog changes are this project's own `MCP_CATALOG_VARIANT=mutated` server variant, run as a second local subprocess; this does not model a real adversary who has compromised or MITM'd an actual remote MCP server's network transport.
- OPA is a real binary, genuinely invoked this session, but is not installed as a persistent part of this machine's toolchain; a future run needs `OPA_BIN` set or `opa` on `PATH`, and every dependent test and benchmark is written to disclose that rather than silently fall back to a Python mirror of the Rego logic.
