# FastAPI wrapper around gateway_core.Gateway. The benchmarks in scripts/ and the tests in
# tests/ call Gateway directly, in-process, because 4,000+1,200+N calls over real HTTP would
# spend most of their wall clock on the HTTP stack rather than the thing being measured;
# this app is what a real caller (an agent process, or the TypeScript console) would
# actually speak to, and tests/test_http_app.py exercises it end to end over a real
# Starlette TestClient (no live socket, no port to pick or leak).
from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .approval_queue import ApprovalQueue
from .auth import TokenIssuer
from .gateway_core import AuthorizationError, Gateway, ProposalResult, ReadResult
from .registry import GROUPS, Registry
from .state import make_session_factory, seed_fixture_state


class TokenRequest(BaseModel):
    group: str


class CallRequest(BaseModel):
    token: str
    params: dict[str, Any] = {}


class DecideRequest(BaseModel):
    approve: bool


def build_app(*, database_url: str | None = None, secret: bytes = b"dev-secret-change-me", seed_demo_data: bool = True) -> FastAPI:
    session_factory = make_session_factory(database_url)
    session = session_factory()
    if seed_demo_data:
        seed_fixture_state(session)
    registry = Registry()
    issuer = TokenIssuer(secret)
    queue = ApprovalQueue(session)
    gateway = Gateway(session, registry, issuer, queue)

    app = FastAPI(title="Governed Agent Tool Gateway")

    @app.get("/registry")
    def get_registry() -> dict:
        return {
            "domain_count": registry.domain_count(),
            "tool_count": registry.tool_count(),
            "groups": {g: {"domains": sorted(spec["domains"]), "can_write": spec["can_write"]} for g, spec in GROUPS.items()},
        }

    @app.post("/auth/token")
    def issue_token(req: TokenRequest) -> dict:
        if req.group not in GROUPS:
            raise HTTPException(status_code=400, detail=f"unknown group: {req.group}")
        return {"token": issuer.issue(req.group)}

    @app.post("/tools/{tool_name}/call")
    def call_tool(tool_name: str, req: CallRequest) -> dict:
        try:
            result = gateway.call(req.token, tool_name, req.params)
        except AuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(result, ReadResult):
            return {"status": "ok", "tool": result.tool, "data": result.data}
        assert isinstance(result, ProposalResult)
        return {
            "status": "pending_approval",
            "tool": result.tool,
            "approval_id": result.approval_id,
            "oracle_ok": result.oracle_ok,
            "oracle_reason": result.oracle_reason,
        }

    @app.get("/approvals")
    def list_approvals() -> dict:
        return {
            "pending": [
                {
                    "approval_id": e.approval_id,
                    "tool": e.tool,
                    "domain": e.domain,
                    "caller_group": e.caller_group,
                    "params": e.params,
                    "oracle_ok": e.oracle_verdict.ok,
                    "oracle_reason": e.oracle_verdict.reason,
                }
                for e in queue.pending()
            ]
        }

    @app.post("/approvals/{approval_id}/decide")
    def decide(approval_id: str, req: DecideRequest) -> dict:
        try:
            entry = queue.decide(approval_id, approve=req.approve)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"approval_id": entry.approval_id, "decision": entry.decision.value}

    return app


app = build_app(database_url=os.environ.get("DATABASE_URL"))
