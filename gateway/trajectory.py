# Per-session call history and the trajectory-aware policy decision built on top of it.
# A session here is just a caller-chosen session_id string; the gateway never issues or
# verifies it the way it does an auth token, since the point of this layer is to see
# structural call shape across calls already made for other reasons, not to be a second
# authorization mechanism. TrajectoryPolicy.record() is only ever called on a call that
# already passed Gateway.authorize(), so this history is "things the caller was legitimately
# allowed to do," not a replay buffer of refused attempts.
from __future__ import annotations

from dataclasses import dataclass, field

from .policy import PolicyDecision, decide_trajectory
from .registry import ToolSpec


@dataclass
class TrajectoryPolicy:
    _sessions: dict[str, list[tuple[str, frozenset[str]]]] = field(default_factory=dict)

    def check(self, session_id: str, spec: ToolSpec) -> PolicyDecision:
        history = self._sessions.get(session_id, [])
        return decide_trajectory(spec.name, spec.annotations, history)

    def record(self, session_id: str, spec: ToolSpec) -> None:
        self._sessions.setdefault(session_id, []).append((spec.name, spec.annotations))

    def history_for(self, session_id: str) -> list[tuple[str, frozenset[str]]]:
        return list(self._sessions.get(session_id, []))

    def reset(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
