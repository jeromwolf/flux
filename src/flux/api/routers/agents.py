"""Agent CRUD + halt/resume/status/runs routes.

All endpoints require the JWT cookie. Cross-tenant access returns 404 (not 403)
to avoid leaking the existence of other users' agents.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import yaml
from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import ValidationError

from flux.api.deps import CurrentUserDep, SessionDep
from flux.api.db import get_sessionmaker
from flux.api.models import Run
from flux.api.repositories import AgentRepository, RunRepository
from flux.api.schemas import AgentCreate, AgentOut, AgentUpdate, RunOut
from flux.api.services.event_bus import EventBus
from flux.api.services.runner_proxy import execute_agent
from flux.config import AgentConfig

router = APIRouter(prefix="/agents", tags=["agents"])


def _validate_yaml_source(yaml_source: str) -> None:
    """Run yaml_source through AgentConfig so callers see structural errors early."""
    try:
        data = yaml.safe_load(yaml_source)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=422, detail=f"invalid YAML: {e}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="YAML must be a mapping")
    try:
        AgentConfig(**data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())


def _agent_data_dir(user_id: uuid.UUID, agent_name: str) -> str:
    return os.path.join(
        os.path.expanduser("~"), ".flux", "users", str(user_id), "agents", agent_name
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[AgentOut])
async def list_agents(current_user: CurrentUserDep, session: SessionDep) -> list[AgentOut]:
    repo = AgentRepository(session)
    rows = await repo.list_for_user(current_user.id)
    return [AgentOut.model_validate(a) for a in rows]


@router.post("", response_model=AgentOut, status_code=201)
async def create_agent(
    payload: AgentCreate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> AgentOut:
    _validate_yaml_source(payload.yaml_source)
    repo = AgentRepository(session)
    existing = await repo.get_by_name_for_user(payload.name, current_user.id)
    if existing is not None:
        raise HTTPException(status_code=409, detail="agent name already taken")
    agent = await repo.create(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        yaml_source=payload.yaml_source,
    )
    await session.commit()
    await session.refresh(agent)
    return AgentOut.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(
    agent_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> AgentOut:
    repo = AgentRepository(session)
    agent = await repo.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return AgentOut.model_validate(agent)


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(
    agent_id: uuid.UUID,
    payload: AgentUpdate,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> AgentOut:
    repo = AgentRepository(session)
    agent = await repo.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    if payload.yaml_source is not None:
        _validate_yaml_source(payload.yaml_source)
    await repo.update(agent, description=payload.description, yaml_source=payload.yaml_source)
    await session.commit()
    await session.refresh(agent)
    return AgentOut.model_validate(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> None:
    repo = AgentRepository(session)
    agent = await repo.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    await repo.delete(agent)
    await session.commit()


# ---------------------------------------------------------------------------
# Runs (history)
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/runs", response_model=list[RunOut])
async def list_runs(
    agent_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> list[RunOut]:
    agents = AgentRepository(session)
    agent = await agents.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    runs = await RunRepository(session).list_for_agent(agent.id)
    return [RunOut.model_validate(r) for r in runs]


# ---------------------------------------------------------------------------
# Run trigger ("Run Now")
# ---------------------------------------------------------------------------

async def _execute_and_record(
    *,
    run_id: uuid.UUID,
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    agent_name: str,
    yaml_source: str,
) -> None:
    """Background task: invoke runner, update the queued Run row."""
    try:
        result = await execute_agent(
            user_id=user_id, agent_name=agent_name, yaml_source=yaml_source,
        )
    except Exception as e:
        # Persist failure as 'error' status; never let the task explode silently.
        result = None
        error_text = f"runner crashed: {type(e).__name__}: {e}"
    else:
        error_text = None

    sm = get_sessionmaker()
    async with sm() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        if result is None:
            run.status = "error"
            run.error = error_text
        elif result.error:
            run.status = "budget_exceeded" if "Budget exceeded" in result.error else "error"
            run.error = result.error
            run.input_tokens = result.input_tokens
            run.output_tokens = result.output_tokens
            run.cost_usd = result.cost_usd
            run.tool_rounds = result.tool_rounds
        else:
            run.status = "success"
            run.input_tokens = result.input_tokens
            run.output_tokens = result.output_tokens
            run.cost_usd = result.cost_usd
            run.tool_rounds = result.tool_rounds
        run.finished_at = datetime.now(timezone.utc)
        await session.commit()
        # Notify WebSocket subscribers (best-effort; failures are not fatal).
        try:
            await EventBus.publish(agent_id, {
                "type": "run_complete",
                "run_id": str(run.id),
                "status": run.status,
                "cost_usd": float(run.cost_usd) if run.cost_usd is not None else None,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "error": run.error,
            })
        except Exception:
            pass


@router.post("/{agent_id}/run", response_model=RunOut, status_code=202)
async def run_agent_now(
    agent_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
    background_tasks: BackgroundTasks,
) -> RunOut:
    """Trigger an immediate run. Returns the queued Run row; execution is async."""
    agents = AgentRepository(session)
    agent = await agents.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    run = await RunRepository(session).record(agent_id=agent.id, status="queued")
    await session.commit()
    await session.refresh(run)

    background_tasks.add_task(
        _execute_and_record,
        run_id=run.id,
        agent_id=agent.id,
        user_id=current_user.id,
        agent_name=agent.name,
        yaml_source=agent.yaml_source,
    )
    return RunOut.model_validate(run)


# ---------------------------------------------------------------------------
# Halt / Resume (emergency stop)
# ---------------------------------------------------------------------------

@router.post("/{agent_id}/halt")
async def halt_agent(
    agent_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    agents = AgentRepository(session)
    agent = await agents.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    data_dir = _agent_data_dir(current_user.id, agent.name)
    os.makedirs(data_dir, exist_ok=True)
    halt_file = os.path.join(data_dir, "emergency_stop")
    with open(halt_file, "w", encoding="utf-8") as f:
        from datetime import datetime as _dt, timezone as _tz
        f.write(_dt.now(_tz.utc).isoformat())
    agent.status = "halted"
    await session.commit()
    return {"agent_id": str(agent.id), "halted": True}


@router.post("/{agent_id}/resume")
async def resume_agent(
    agent_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    agents = AgentRepository(session)
    agent = await agents.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")
    halt_file = os.path.join(_agent_data_dir(current_user.id, agent.name), "emergency_stop")
    if os.path.exists(halt_file):
        os.remove(halt_file)
    agent.status = "idle"
    await session.commit()
    return {"agent_id": str(agent.id), "halted": False}


# ---------------------------------------------------------------------------
# Status (heartbeat + cost summary on disk)
# ---------------------------------------------------------------------------

@router.get("/{agent_id}/status")
async def agent_status(
    agent_id: uuid.UUID,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> dict:
    import json as _json

    agents = AgentRepository(session)
    agent = await agents.get_for_user(agent_id, current_user.id)
    if agent is None:
        raise HTTPException(status_code=404, detail="agent not found")

    data_dir = _agent_data_dir(current_user.id, agent.name)
    heartbeat: dict = {}
    hb_path = os.path.join(data_dir, "heartbeat.json")
    if os.path.exists(hb_path):
        try:
            with open(hb_path, "r", encoding="utf-8") as f:
                heartbeat = _json.load(f)
        except (OSError, _json.JSONDecodeError):
            heartbeat = {}

    budget: dict = {}
    budget_path = os.path.join(data_dir, "budget_state.json")
    if os.path.exists(budget_path):
        try:
            with open(budget_path, "r", encoding="utf-8") as f:
                budget = _json.load(f)
        except (OSError, _json.JSONDecodeError):
            budget = {}

    return {
        "agent_id": str(agent.id),
        "name": agent.name,
        "status": agent.status,
        "heartbeat": heartbeat,
        "budget": budget,
        "halted": os.path.exists(os.path.join(data_dir, "emergency_stop")),
    }
