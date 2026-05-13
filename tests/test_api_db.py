"""Tests for the W3 DB layer — models + repository CRUD + tenant isolation."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from flux.api.db import Base
from flux.api.repositories import AgentRepository, RunRepository, UserRepository


@pytest_asyncio.fixture
async def session():
    """In-memory SQLite session with the full schema created.

    StaticPool keeps the connection across the session so :memory: is shared.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        yield s
    await engine.dispose()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

async def test_user_insert_and_unique_github_id(session):
    repo = UserRepository(session)
    await repo.upsert_from_github(
        github_id=42, github_login="kelly", email="k@flux.ai.kr", avatar_url=None,
    )
    await session.commit()

    fetched = await repo.get_by_github_id(42)
    assert fetched is not None
    assert fetched.github_login == "kelly"
    assert isinstance(fetched.id, uuid.UUID)


async def test_user_upsert_overwrites_login(session):
    repo = UserRepository(session)
    await repo.upsert_from_github(github_id=7, github_login="old", email=None, avatar_url=None)
    await session.commit()

    await repo.upsert_from_github(github_id=7, github_login="new", email="x@y.z", avatar_url="http://a")
    await session.commit()

    fetched = await repo.get_by_github_id(7)
    assert fetched.github_login == "new"
    assert fetched.email == "x@y.z"
    assert fetched.avatar_url == "http://a"


async def test_agent_unique_name_per_user(session):
    users = UserRepository(session)
    u1 = await users.upsert_from_github(github_id=1, github_login="a", email=None, avatar_url=None)
    u2 = await users.upsert_from_github(github_id=2, github_login="b", email=None, avatar_url=None)
    await session.commit()

    repo = AgentRepository(session)
    await repo.create(user_id=u1.id, name="news-bot", description=None, yaml_source="x: 1\n" * 5)
    await session.commit()

    # Same user can't reuse name. Wrap the duplicate in a SAVEPOINT so the
    # IntegrityError only rolls back that nested transaction.
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await repo.create(user_id=u1.id, name="news-bot", description=None, yaml_source="x: 2\n" * 5)

    # Different user CAN reuse the same name
    other = await repo.create(user_id=u2.id, name="news-bot", description=None, yaml_source="x: 3\n" * 5)
    await session.commit()
    assert other.user_id == u2.id


# ---------------------------------------------------------------------------
# Repository: tenant isolation
# ---------------------------------------------------------------------------

async def test_list_for_user_only_returns_own_agents(session):
    users = UserRepository(session)
    u1 = await users.upsert_from_github(github_id=11, github_login="alice", email=None, avatar_url=None)
    u2 = await users.upsert_from_github(github_id=22, github_login="bob", email=None, avatar_url=None)
    await session.commit()

    repo = AgentRepository(session)
    await repo.create(user_id=u1.id, name="alice-agent-1", description=None, yaml_source="a" * 20)
    await repo.create(user_id=u1.id, name="alice-agent-2", description=None, yaml_source="a" * 20)
    await repo.create(user_id=u2.id, name="bob-agent", description=None, yaml_source="b" * 20)
    await session.commit()

    alice_list = await repo.list_for_user(u1.id)
    bob_list = await repo.list_for_user(u2.id)

    assert {a.name for a in alice_list} == {"alice-agent-1", "alice-agent-2"}
    assert {a.name for a in bob_list} == {"bob-agent"}


async def test_get_for_user_returns_none_on_cross_tenant(session):
    """Cross-tenant access yields None (router will turn into 404)."""
    users = UserRepository(session)
    owner = await users.upsert_from_github(github_id=100, github_login="owner", email=None, avatar_url=None)
    intruder = await users.upsert_from_github(github_id=101, github_login="intruder", email=None, avatar_url=None)
    await session.commit()

    repo = AgentRepository(session)
    agent = await repo.create(user_id=owner.id, name="secret", description=None, yaml_source="s" * 20)
    await session.commit()

    own = await repo.get_for_user(agent.id, owner.id)
    nope = await repo.get_for_user(agent.id, intruder.id)
    assert own is not None
    assert nope is None


async def test_get_by_name_for_user(session):
    users = UserRepository(session)
    u = await users.upsert_from_github(github_id=200, github_login="u", email=None, avatar_url=None)
    await session.commit()
    repo = AgentRepository(session)
    await repo.create(user_id=u.id, name="lookup-bot", description=None, yaml_source="x" * 20)
    await session.commit()

    hit = await repo.get_by_name_for_user("lookup-bot", u.id)
    miss = await repo.get_by_name_for_user("not-here", u.id)
    assert hit is not None
    assert miss is None


# ---------------------------------------------------------------------------
# Repository: update + delete
# ---------------------------------------------------------------------------

async def test_agent_update_and_delete(session):
    users = UserRepository(session)
    u = await users.upsert_from_github(github_id=300, github_login="u", email=None, avatar_url=None)
    await session.commit()
    repo = AgentRepository(session)
    agent = await repo.create(user_id=u.id, name="bot", description="v1", yaml_source="x" * 20)
    await session.commit()

    await repo.update(agent, description="v2", yaml_source="y" * 20)
    await session.commit()
    refetched = await repo.get_for_user(agent.id, u.id)
    assert refetched.description == "v2"
    assert refetched.yaml_source == "y" * 20

    await repo.delete(refetched)
    await session.commit()
    assert await repo.get_for_user(agent.id, u.id) is None


# ---------------------------------------------------------------------------
# Run history
# ---------------------------------------------------------------------------

async def test_run_record_and_list(session):
    users = UserRepository(session)
    u = await users.upsert_from_github(github_id=400, github_login="u", email=None, avatar_url=None)
    await session.commit()
    agents = AgentRepository(session)
    agent = await agents.create(user_id=u.id, name="r", description=None, yaml_source="x" * 20)
    await session.commit()

    runs = RunRepository(session)
    await runs.record(agent_id=agent.id, status="success", cost_usd=0.014, input_tokens=120, output_tokens=80, tool_rounds=2)
    await runs.record(agent_id=agent.id, status="error", error="boom")
    await session.commit()

    history = await runs.list_for_agent(agent.id)
    assert len(history) == 2
    statuses = {r.status for r in history}
    assert statuses == {"success", "error"}


async def test_run_cascade_delete_with_agent(session):
    users = UserRepository(session)
    u = await users.upsert_from_github(github_id=500, github_login="u", email=None, avatar_url=None)
    await session.commit()
    agents = AgentRepository(session)
    agent = await agents.create(user_id=u.id, name="c", description=None, yaml_source="x" * 20)
    await session.commit()
    runs = RunRepository(session)
    await runs.record(agent_id=agent.id, status="success", cost_usd=0.01)
    await session.commit()

    await agents.delete(agent)
    await session.commit()

    leftover = await runs.list_for_agent(agent.id)
    assert leftover == []
