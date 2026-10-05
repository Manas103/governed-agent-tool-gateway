# Short-lived, HMAC-signed scoped tokens: the gateway's stand-in for Pinterest's published
# end-user JWT plus business-group gating. A token names a group and an expiry; nothing
# else. The gateway never trusts a caller's self-declared group, only a signature it can
# verify against a server-held secret.
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from .registry import GROUPS


class TokenError(Exception):
    pass


@dataclass(frozen=True)
class TokenPayload:
    group: str
    issued_at: float
    expires_at: float


class TokenIssuer:
    def __init__(self, secret: bytes, ttl_seconds: float = 300.0) -> None:
        self._secret = secret
        self._ttl = ttl_seconds

    def issue(self, group: str, *, now: float | None = None) -> str:
        if group not in GROUPS:
            raise TokenError(f"unknown group: {group}")
        now = time.time() if now is None else now
        payload = {"group": group, "iat": now, "exp": now + self._ttl}
        body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        sig = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        return f"{body}.{sig}"

    def issue_expired(self, group: str) -> str:
        """Test/benchmark helper only: mints a token that is already past its expiry, to
        exercise the adversarial-case rejection path without waiting out a real TTL."""
        return self.issue(group, now=time.time() - self._ttl - 1.0)

    def verify(self, token: str, *, now: float | None = None) -> TokenPayload:
        try:
            body, sig = token.split(".", 1)
        except ValueError as exc:
            raise TokenError("malformed token") from exc
        expected_sig = hmac.new(self._secret, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise TokenError("invalid signature")
        payload = json.loads(base64.urlsafe_b64decode(body.encode()))
        now = time.time() if now is None else now
        if now >= payload["exp"]:
            raise TokenError("token expired")
        if payload["group"] not in GROUPS:
            raise TokenError(f"unknown group: {payload['group']}")
        return TokenPayload(group=payload["group"], issued_at=payload["iat"], expires_at=payload["exp"])
