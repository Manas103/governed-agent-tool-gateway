# Turns a free-text internal request ticket into a (tool, params) proposal for
# gateway_core.Gateway.call, without ever letting text other than the ticket's own
# "Request:" field, and only its first sentence, influence what gets called. This is a
# deliberate design choice, not an oversight: an LLM-based intake would itself be the
# prompt-injection attack surface this module exists to resist, so classification here is
# plain regex over one bounded field. Nothing in this module trusts the ticket body for
# the caller's group either; that comes from the ticket's authenticated submitter record,
# a separate channel the ticket text cannot write to.
from __future__ import annotations

import re
from dataclasses import dataclass, field

INJECTION_MARKERS: tuple[str, ...] = (
    "ignore the above",
    "ignore previous",
    "ignore all previous",
    "disregard",
    "already approved",
    "pre-approved",
    "skip the approval",
    "skip approval",
    "skip the oracle",
    "bypass the oracle",
    "bypass approval",
    "without approval",
    "without review",
    "as an administrator",
    "as the administrator",
    "as a senior",
    "treat this as approved",
    "treat me as",
    "new instruction",
    "system:",
    "override the",
    "automatically approve",
    "auto-approve",
    "no review needed",
    "approved by compliance",
    "on behalf of the approver",
)

# One regex per write tool, matched against the Request field's first sentence only.
# Ordering does not matter for correctness (the nouns pin/board/campaign/user/email never
# collide across patterns); it is fixed here only so output is deterministic to read.
_TOOL_PATTERNS: tuple[tuple[str, re.Pattern, tuple[str, ...]], ...] = (
    ("suspend_user", re.compile(r"Suspend user (\d+) for (.+?)\.", re.IGNORECASE), ("user_id", "reason")),
    ("restore_user", re.compile(r"Restore user (\d+) from suspension\.", re.IGNORECASE), ("user_id",)),
    ("delete_user", re.compile(r"Delete user (\d+) permanently\.", re.IGNORECASE), ("user_id",)),
    ("update_user_email", re.compile(r"Update email for user (\d+) to (\S+)\.", re.IGNORECASE), ("user_id", "email")),
    ("create_pin", re.compile(r"Create a new pin on board (\d+) with description (.+?)\.", re.IGNORECASE), ("board_id", "description")),
    ("update_pin_description", re.compile(r"Update the description of pin (\d+) to (.+?)\.", re.IGNORECASE), ("pin_id", "description")),
    ("report_pin", re.compile(r"Report pin (\d+) for (.+?)\.", re.IGNORECASE), ("pin_id", "reason")),
    ("delete_pin", re.compile(r"Delete pin (\d+)\.", re.IGNORECASE), ("pin_id",)),
    ("create_board", re.compile(r"Create a new board named (.+?) owned by user (\d+)\.", re.IGNORECASE), ("name", "owner_user_id")),
    ("rename_board", re.compile(r"Rename board (\d+) to (.+?)\.", re.IGNORECASE), ("board_id", "name")),
    ("add_pin_to_board", re.compile(r"Add pin (\d+) to board (\d+)\.", re.IGNORECASE), ("pin_id", "board_id")),
    ("delete_board", re.compile(r"Delete board (\d+)\.", re.IGNORECASE), ("board_id",)),
    ("create_campaign", re.compile(r"Create a new ad campaign named (.+?) with budget \$([\d.]+)\.", re.IGNORECASE), ("name", "budget_usd")),
    ("update_campaign_budget", re.compile(r"Update the budget for campaign (\d+) to \$([\d.]+)\.", re.IGNORECASE), ("campaign_id", "budget_usd")),
    ("pause_campaign", re.compile(r"Pause campaign (\d+)\.", re.IGNORECASE), ("campaign_id",)),
    ("delete_campaign", re.compile(r"Delete campaign (\d+)\.", re.IGNORECASE), ("campaign_id",)),
)

_INT_PARAMS = {"user_id", "pin_id", "board_id", "campaign_id", "owner_user_id"}
_FLOAT_PARAMS = {"budget_usd"}

_REQUEST_FIELD = re.compile(r"^Request:\s*(.*)$", re.MULTILINE)
_SENTENCE_SPLIT = re.compile(r"(?<=\.)\s+")


class IntakeError(Exception):
    pass


@dataclass(frozen=True)
class IntakeResult:
    tool: str
    params: dict
    primary_sentence: str
    trailing_text: str
    injection_detected: bool
    injection_markers: tuple[str, ...] = field(default_factory=tuple)


def _cast(name: str, raw: str) -> int | float | str:
    if name in _INT_PARAMS:
        return int(raw)
    if name in _FLOAT_PARAMS:
        return float(raw)
    return raw


def _match_tool(sentence: str) -> tuple[str, dict] | None:
    for tool, pattern, param_names in _TOOL_PATTERNS:
        m = pattern.search(sentence)
        if m:
            params = {name: _cast(name, value) for name, value in zip(param_names, m.groups())}
            return tool, params
    return None


def classify(ticket_text: str) -> IntakeResult:
    """Parses a ticket's Request field, acts on its first sentence only, and reports every
    injection marker phrase found anywhere else in the ticket without letting any of them
    change the extracted tool or params. Raises IntakeError if the Request field is
    missing or its first sentence names no known tool; a malformed ticket is refused, not
    guessed at."""
    match = _REQUEST_FIELD.search(ticket_text)
    if not match:
        raise IntakeError("ticket has no Request field")
    request_field = match.group(1).strip()
    sentences = [s for s in _SENTENCE_SPLIT.split(request_field) if s]
    if not sentences:
        raise IntakeError("Request field is empty")
    primary, trailing = sentences[0], " ".join(sentences[1:])

    resolved = _match_tool(primary)
    if resolved is None:
        raise IntakeError(f"first sentence of Request field names no known tool: {primary!r}")
    tool, params = resolved

    scan_text = (trailing + "\n" + ticket_text).lower()
    found = tuple(marker for marker in INJECTION_MARKERS if marker in scan_text)
    return IntakeResult(
        tool=tool,
        params=params,
        primary_sentence=primary,
        trailing_text=trailing,
        injection_detected=bool(found),
        injection_markers=found,
    )
