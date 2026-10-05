# Domain object store: 4 tables, one per domain server, plus an append-only approval log.
# SQLite is what this session actually exercises (DATABASE_URL defaults to a file-backed
# sqlite db); the models are plain SQLAlchemy so a real PostgreSQL DSN works unchanged, but
# that path is not live here, matching this portfolio's convention for a DB that is not
# installed as a running service on this machine.
from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class Pin(Base):
    __tablename__ = "pins"
    id = Column(Integer, primary_key=True)
    board_id = Column(Integer, ForeignKey("boards.id"), nullable=True)
    description = Column(Text, default="")
    deleted = Column(Boolean, default=False)
    reported = Column(Boolean, default=False)


class Board(Base):
    __tablename__ = "boards"
    id = Column(Integer, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String, nullable=False)
    deleted = Column(Boolean, default=False)


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    budget_usd = Column(Float, default=0.0)
    min_budget_usd = Column(Float, default=0.0)
    max_budget_usd = Column(Float, default=100_000.0)
    paused = Column(Boolean, default=False)
    deleted = Column(Boolean, default=False)


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, nullable=False)
    suspended = Column(Boolean, default=False)
    deleted = Column(Boolean, default=False)


# Append-only: the one and only place a mutating action is ever recorded as having taken
# effect. The replay harness reconstructs expected post-state from this table alone and
# diffs it against the live tables, which is what proves no write reached the tables
# through any path other than an approved queue decision.
class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    id = Column(Integer, primary_key=True)
    approval_id = Column(String, nullable=False, unique=True)
    tool = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    caller_group = Column(String, nullable=False)
    params_json = Column(Text, nullable=False)
    oracle_ok = Column(Boolean, nullable=False)
    oracle_reason = Column(Text, nullable=True)
    decision = Column(String, nullable=False)  # 'approved' | 'rejected'
    applied_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


def make_session_factory(database_url: str | None = None) -> sessionmaker:
    url = database_url or os.environ.get("DATABASE_URL", "sqlite:///:memory:")
    if url == "sqlite:///:memory:":
        # The default pool opens a fresh, empty in-memory database per checked-out
        # connection; StaticPool keeps every session on the one connection that actually
        # has the tables this call just created.
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    else:
        engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def seed_fixture_state(session: Session, *, users: int = 50, boards: int = 50, pins: int = 400, campaigns: int = 30) -> None:
    for i in range(users):
        session.add(User(id=i, email=f"user{i}@example.test"))
    for i in range(boards):
        session.add(Board(id=i, owner_user_id=i % users, name=f"board-{i}"))
    for i in range(pins):
        session.add(Pin(id=i, board_id=i % boards, description=f"pin {i}"))
    for i in range(campaigns):
        session.add(
            AdCampaign(id=i, name=f"campaign-{i}", budget_usd=1000.0, min_budget_usd=50.0, max_budget_usd=50_000.0)
        )
    session.commit()
