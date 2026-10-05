import time

import pytest

from gateway.auth import TokenError, TokenIssuer


def test_issued_token_verifies_to_its_own_group():
    issuer = TokenIssuer(b"secret", ttl_seconds=60)
    token = issuer.issue("catalog-ops")
    payload = issuer.verify(token)
    assert payload.group == "catalog-ops"


def test_token_rejected_once_past_expiry():
    issuer = TokenIssuer(b"secret", ttl_seconds=10)
    token = issuer.issue("catalog-ops", now=1_000_000.0)
    with pytest.raises(TokenError):
        issuer.verify(token, now=1_000_000.0 + 11)


def test_token_accepted_just_before_expiry():
    issuer = TokenIssuer(b"secret", ttl_seconds=10)
    token = issuer.issue("catalog-ops", now=1_000_000.0)
    issuer.verify(token, now=1_000_000.0 + 9)


def test_tampered_signature_rejected():
    issuer = TokenIssuer(b"secret", ttl_seconds=60)
    token = issuer.issue("catalog-ops")
    body, sig = token.split(".", 1)
    tampered = f"{body}.{'0' * len(sig)}"
    with pytest.raises(TokenError):
        issuer.verify(tampered)


def test_wrong_secret_cannot_forge_a_token():
    issuer_a = TokenIssuer(b"secret-a", ttl_seconds=60)
    issuer_b = TokenIssuer(b"secret-b", ttl_seconds=60)
    token = issuer_a.issue("catalog-ops")
    with pytest.raises(TokenError):
        issuer_b.verify(token)


def test_unknown_group_cannot_be_issued_a_token():
    issuer = TokenIssuer(b"secret", ttl_seconds=60)
    with pytest.raises(TokenError):
        issuer.issue("not-a-real-group")


def test_issue_expired_helper_actually_produces_an_expired_token():
    issuer = TokenIssuer(b"secret", ttl_seconds=60)
    token = issuer.issue_expired("catalog-ops")
    with pytest.raises(TokenError):
        issuer.verify(token)
