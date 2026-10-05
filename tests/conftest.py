import pytest

from gateway.approval_queue import ApprovalQueue
from gateway.auth import TokenIssuer
from gateway.gateway_core import Gateway
from gateway.registry import Registry
from gateway.state import make_session_factory, seed_fixture_state

N_USERS, N_BOARDS, N_PINS, N_CAMPAIGNS = 50, 50, 400, 30


@pytest.fixture
def session():
    factory = make_session_factory("sqlite:///:memory:")
    s = factory()
    seed_fixture_state(s, users=N_USERS, boards=N_BOARDS, pins=N_PINS, campaigns=N_CAMPAIGNS)
    yield s
    s.close()


@pytest.fixture
def registry():
    return Registry()


@pytest.fixture
def issuer():
    return TokenIssuer(b"test-secret", ttl_seconds=300.0)


@pytest.fixture
def gateway(session, registry, issuer):
    queue = ApprovalQueue(session)
    return Gateway(session, registry, issuer, queue)
