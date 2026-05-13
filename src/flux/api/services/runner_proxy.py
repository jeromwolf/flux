"""Bridge: materialise an agent's YAML to a per-user data directory and run it.

The web API never holds an :class:`AgentRunner` instance in DB; instead, the
YAML stored in the ``agents.yaml_source`` column is the canonical source. When
the user clicks "Run Now", we write that YAML into the per-user data dir and
spin up an ``AgentRunner`` against it, exactly the same way the CLI does.

This keeps W1/W2 invariants intact:
- Path traversal protection (already enforced by AgentRunner).
- Budget state (``budget_state.json``) persists across runs.
- Heartbeat + log files remain compatible with the CLI Watchdog.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from flux.runner import AgentRunner, RunResult


def user_agent_data_dir(user_id: uuid.UUID, agent_name: str) -> str:
    """Return per-user, per-agent data dir under ``~/.flux/users/<id>/agents/<name>``."""
    return os.path.join(
        os.path.expanduser("~"),
        ".flux",
        "users",
        str(user_id),
        "agents",
        agent_name,
    )


def _materialise_yaml(yaml_source: str, data_dir: str) -> str:
    os.makedirs(data_dir, exist_ok=True)
    yaml_path = os.path.join(data_dir, "agent.yaml")
    with open(yaml_path, "w", encoding="utf-8") as f:
        f.write(yaml_source)
    return yaml_path


async def execute_agent(
    *,
    user_id: uuid.UUID,
    agent_name: str,
    yaml_source: str,
) -> RunResult:
    """Write YAML to disk and run :class:`AgentRunner` in a worker thread."""
    data_dir = user_agent_data_dir(user_id, agent_name)
    yaml_path = _materialise_yaml(yaml_source, data_dir)

    def _run() -> RunResult:
        runner = AgentRunner(yaml_path, data_dir=data_dir)
        return runner.run()

    return await asyncio.to_thread(_run)
