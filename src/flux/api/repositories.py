"""Repository layer — async CRUD primitives over the ORM models.

Routers depend on these instead of touching SQLAlchemy directly, so multi-tenant
filtering (``user_id == current_user.id``) is enforced in one place.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flux.api.models import Agent, Run, User


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, user_id: uuid.UUID) -> Optional[User]:
        return await self.session.get(User, user_id)

    async def get_by_github_id(self, github_id: int) -> Optional[User]:
        stmt = select(User).where(User.github_id == github_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def upsert_from_github(
        self,
        *,
        github_id: int,
        github_login: str,
        email: Optional[str],
        avatar_url: Optional[str],
    ) -> User:
        user = await self.get_by_github_id(github_id)
        if user is None:
            user = User(
                github_id=github_id,
                github_login=github_login,
                email=email,
                avatar_url=avatar_url,
            )
            self.session.add(user)
        else:
            user.github_login = github_login
            user.email = email
            user.avatar_url = avatar_url
        await self.session.flush()
        return user


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

class AgentRepository:
    """Multi-tenant agent CRUD. Every query filters by user_id."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[Agent]:
        stmt = select(Agent).where(Agent.user_id == user_id).order_by(Agent.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_for_user(self, agent_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Agent]:
        """Return the agent only if it belongs to ``user_id`` (otherwise None).

        Returning ``None`` for cross-tenant access prevents information leakage
        (routers translate this into 404, never 403).
        """
        stmt = select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name_for_user(self, name: str, user_id: uuid.UUID) -> Optional[Agent]:
        stmt = select(Agent).where(Agent.name == name, Agent.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        description: Optional[str],
        yaml_source: str,
    ) -> Agent:
        agent = Agent(
            user_id=user_id,
            name=name,
            description=description,
            yaml_source=yaml_source,
        )
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def update(self, agent: Agent, *, description: Optional[str] = None,
                     yaml_source: Optional[str] = None) -> Agent:
        if description is not None:
            agent.description = description
        if yaml_source is not None:
            agent.yaml_source = yaml_source
        await self.session.flush()
        return agent

    async def delete(self, agent: Agent) -> None:
        await self.session.delete(agent)
        await self.session.flush()


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------

class RunRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_for_agent(self, agent_id: uuid.UUID, *, limit: int = 50) -> list[Run]:
        stmt = (
            select(Run)
            .where(Run.agent_id == agent_id)
            .order_by(Run.started_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def record(
        self,
        *,
        agent_id: uuid.UUID,
        status: str,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_usd: Optional[float] = None,
        tool_rounds: Optional[int] = None,
        error: Optional[str] = None,
        finished_at=None,
    ) -> Run:
        run = Run(
            agent_id=agent_id,
            status=status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            tool_rounds=tool_rounds,
            error=error,
            finished_at=finished_at,
        )
        self.session.add(run)
        await self.session.flush()
        return run
