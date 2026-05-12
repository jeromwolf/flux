"""Flux AgentRunner -- Orchestrates agent lifecycle from YAML config to execution.

Ties together config loading, LLM provider creation, tool management,
safety shields, and the AgentEngine into a single run() call.

Usage:
    from flux.runner import AgentRunner

    runner = AgentRunner("agents/news-bot.yaml")
    result = runner.run()       # Single execution
    print(result.text)
    print(f"Cost: ${result.cost_usd:.4f}")

    # Streaming:
    for event in runner.run_stream():
        if event.type == "text_delta":
            print(event.data, end="", flush=True)
"""

from __future__ import annotations

import os
import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from flux.config import load_agent_config, AgentConfig, get_config
from flux.llm import get_provider, StreamEvent
from flux.tools.manager import ToolManager
from flux.safety.shield import SafetyShield
from flux.engine import AgentEngine, TurnResult, BudgetExceededError
from flux.logging import get_logger

logger = get_logger("runner")

# ---------------------------------------------------------------------------
# Model alias mapping: short names -> full model IDs
# ---------------------------------------------------------------------------

MODEL_ALIASES: dict[str, str] = {
    "claude-haiku": "claude-haiku-4-5-20251001",
    "claude-sonnet": "claude-sonnet-4-6-20250514",
    "claude-opus": "claude-opus-4-6-20250514",
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gemini-flash": "gemini-2.5-flash",
    "gemini-pro": "gemini-2.5-pro",
}


def resolve_model(model_name: str) -> tuple[str, str]:
    """Resolve a model alias to (provider_name, full_model_id).

    Args:
        model_name: Short alias (e.g. "claude-haiku") or full model ID.

    Returns:
        Tuple of (provider_name, model_id).
    """
    full_model = MODEL_ALIASES.get(model_name, model_name)

    if "claude" in full_model:
        return "anthropic", full_model
    elif "gpt" in full_model:
        return "openai", full_model
    elif "gemini" in full_model:
        return "google", full_model
    elif "llama" in full_model or "mistral" in full_model:
        return "ollama", full_model
    else:
        return "anthropic", full_model


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    """Result of an agent run."""

    agent_name: str
    text: str = ""
    tool_rounds: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "text": self.text,
            "tool_rounds": self.tool_rounds,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# AgentRunner
# ---------------------------------------------------------------------------

class AgentRunner:
    """Orchestrates the complete agent lifecycle.

    Loads an agent YAML config, resolves the model to a provider,
    sets up tools and safety shields, then runs the agent engine.

    Usage::

        runner = AgentRunner("agents/news-bot.yaml")
        result = runner.run()
        print(result.text)
    """

    def __init__(self, yaml_path: str, *, data_dir: Optional[str] = None):
        self.yaml_path = os.path.abspath(yaml_path)

        # Load and validate config
        raw = load_agent_config(self.yaml_path)
        self.agent_config = AgentConfig(**raw)

        # Data directory for this agent (logs, cost history, PID files)
        self.data_dir = data_dir or os.path.join(
            os.path.expanduser("~"), ".flux", "agents", self.agent_config.name
        )
        os.makedirs(self.data_dir, exist_ok=True)

        # Resolve model alias to provider + full model ID
        provider_name, model_id = resolve_model(self.agent_config.model)
        self.provider_name = provider_name
        self.model_id = model_id

        logger.info(
            "AgentRunner initialized: %s (model=%s, provider=%s)",
            self.agent_config.name,
            self.model_id,
            self.provider_name,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self.agent_config.name

    @property
    def pid_file(self) -> str:
        return os.path.join(self.data_dir, "agent.pid")

    @property
    def cost_file(self) -> str:
        return os.path.join(self.data_dir, "cost_history.jsonl")

    @property
    def log_file(self) -> str:
        return os.path.join(self.data_dir, "agent.log")

    @property
    def heartbeat_file(self) -> str:
        return os.path.join(self.data_dir, "heartbeat.json")

    @property
    def events_file(self) -> str:
        return os.path.join(self.data_dir, "events.jsonl")

    @property
    def emergency_stop_file(self) -> str:
        return os.path.join(self.data_dir, "emergency_stop")

    @property
    def budget_state_file(self) -> str:
        return os.path.join(self.data_dir, "budget_state.json")

    # ------------------------------------------------------------------
    # Component factories
    # ------------------------------------------------------------------

    def _create_provider(self):
        """Create LLM provider from resolved model config."""
        return get_provider(
            provider_name=self.provider_name,
            model=self.model_id,
        )

    def _create_tool_manager(self) -> ToolManager:
        """Create and configure ToolManager with the agent's tool whitelist.

        ToolManager loads all builtin tools on construction.
        If the agent config specifies a tools list, we filter down to that whitelist.
        """
        tool_mgr = ToolManager()

        # Filter to only agent's allowed tools
        if self.agent_config.tools:
            tool_mgr.load_only(self.agent_config.tools)

        return tool_mgr

    def _create_safety_shield(self) -> SafetyShield:
        """Create SafetyShield from the agent's budget config.

        State is loaded from / persisted to ``budget_state_file`` so that
        daily/monthly counters survive daemon restarts. The ``emergency_stop``
        file acts as a hard kill switch (``flux halt`` / ``flux resume``).
        """
        budget = self.agent_config.budget
        return SafetyShield(
            per_run=budget.per_run,
            daily=budget.daily,
            monthly=budget.monthly,
            state_path=self.budget_state_file,
            halt_path=self.emergency_stop_file,
        )

    # ------------------------------------------------------------------
    # Cost tracking
    # ------------------------------------------------------------------

    def _save_cost_record(self, result: RunResult) -> None:
        """Append cost record to JSONL file."""
        record = {
            "timestamp": result.timestamp,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
            "duration_seconds": result.duration_seconds,
            "tool_rounds": result.tool_rounds,
            "error": result.error,
        }
        with open(self.cost_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    # ------------------------------------------------------------------
    # Heartbeat (used by Watchdog)
    # ------------------------------------------------------------------

    def _empty_heartbeat(self) -> dict:
        return {
            "agent_name": self.name,
            "pid": None,
            "started_at": None,
            "last_run_at": None,
            "last_run_status": None,
            "last_error": None,
            "next_run_at": None,
            "consecutive_failures": 0,
            "total_runs": 0,
            "total_failures": 0,
        }

    def _load_heartbeat(self) -> dict:
        """Read heartbeat.json or return empty default."""
        if not os.path.exists(self.heartbeat_file):
            return self._empty_heartbeat()
        try:
            with open(self.heartbeat_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            logger.warning("Corrupt heartbeat file for %s, resetting", self.name)
            return self._empty_heartbeat()

    def _save_heartbeat(self, hb: dict) -> None:
        """Atomically write heartbeat.json (tmp -> rename)."""
        tmp = self.heartbeat_file + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(hb, f, indent=2)
            os.replace(tmp, self.heartbeat_file)
        except OSError as e:
            logger.warning("Failed to save heartbeat for %s: %s", self.name, e)

    def mark_started(self) -> None:
        """Record daemon start in heartbeat."""
        hb = self._load_heartbeat()
        hb["pid"] = os.getpid()
        hb["started_at"] = datetime.now().isoformat()
        self._save_heartbeat(hb)

    def update_heartbeat(
        self,
        *,
        status: str,
        error: Optional[str] = None,
        next_run_at: Optional[str] = None,
    ) -> None:
        """Update heartbeat after a run.

        Args:
            status: "success", "error", or "budget_exceeded"
            error: Error message if status != success
            next_run_at: ISO timestamp of next scheduled run (from scheduler)
        """
        hb = self._load_heartbeat()
        hb["agent_name"] = self.name
        hb["last_run_at"] = datetime.now().isoformat()
        hb["last_run_status"] = status
        hb["last_error"] = error
        hb["total_runs"] = int(hb.get("total_runs", 0)) + 1
        if status == "success":
            hb["consecutive_failures"] = 0
        else:
            hb["consecutive_failures"] = int(hb.get("consecutive_failures", 0)) + 1
            hb["total_failures"] = int(hb.get("total_failures", 0)) + 1
        if next_run_at is not None:
            hb["next_run_at"] = next_run_at
        self._save_heartbeat(hb)

    def get_cost_summary(self) -> dict:
        """Read cost history and return aggregated summary.

        Returns:
            Dict with total_runs, total_cost, today_cost, today_runs.
        """
        if not os.path.exists(self.cost_file):
            return {
                "total_runs": 0,
                "total_cost": 0.0,
                "today_cost": 0.0,
                "today_runs": 0,
            }

        today = datetime.now().strftime("%Y-%m-%d")
        total_cost = 0.0
        total_runs = 0
        today_cost = 0.0
        today_runs = 0

        with open(self.cost_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    total_cost += record.get("cost_usd", 0.0)
                    total_runs += 1
                    if record.get("timestamp", "").startswith(today):
                        today_cost += record.get("cost_usd", 0.0)
                        today_runs += 1
                except json.JSONDecodeError:
                    continue

        return {
            "total_runs": total_runs,
            "total_cost": total_cost,
            "today_cost": today_cost,
            "today_runs": today_runs,
        }

    # ------------------------------------------------------------------
    # Execution: single run
    # ------------------------------------------------------------------

    def run(self, *, callbacks: Optional[dict] = None) -> RunResult:
        """Execute the agent once (single run).

        Args:
            callbacks: Optional dict with keys:
                on_llm_start, on_tool_start, on_tool_end, on_llm_response

        Returns:
            RunResult with response text, token usage, and cost metrics.
        """
        callbacks = callbacks or {}
        start_time = time.time()

        run_result = RunResult(
            agent_name=self.name,
            timestamp=datetime.now().isoformat(),
        )

        try:
            # Setup components
            provider = self._create_provider()
            tool_mgr = self._create_tool_manager()
            safety = self._create_safety_shield()
            safety.start_run()

            # Create engine
            engine = AgentEngine(
                provider=provider,
                client=None,
                tool_mgr=tool_mgr,
                system_prompt=self.agent_config.system_prompt,
                safety=safety,
                on_llm_start=callbacks.get("on_llm_start"),
                on_tool_start=callbacks.get("on_tool_start"),
                on_tool_end=callbacks.get("on_tool_end"),
                on_llm_response=callbacks.get("on_llm_response"),
            )

            # Build initial messages
            messages: list[dict] = [
                {"role": "user", "content": self.agent_config.user_prompt},
            ]

            # Run the agent turn
            logger.info("Running agent: %s", self.name)
            turn_result = engine.run_turn(messages)

            # Map TurnResult fields to RunResult
            run_result.text = turn_result.text
            run_result.tool_rounds = turn_result.tool_rounds
            run_result.input_tokens = turn_result.input_tokens
            run_result.output_tokens = turn_result.output_tokens
            run_result.cost_usd = turn_result.cost_usd
            run_result.error = turn_result.error

        except BudgetExceededError as e:
            run_result.error = f"Budget exceeded: {e}"
            logger.warning("Budget exceeded for %s: %s", self.name, e)
        except Exception as e:
            run_result.error = str(e)
            logger.exception("Agent run failed: %s", self.name)

        run_result.duration_seconds = round(time.time() - start_time, 2)

        # Persist cost record
        try:
            self._save_cost_record(run_result)
        except OSError:
            logger.warning("Failed to save cost record")

        # Update heartbeat for Watchdog
        if run_result.error is None:
            self.update_heartbeat(status="success")
        elif "Budget exceeded" in (run_result.error or ""):
            self.update_heartbeat(status="budget_exceeded", error=run_result.error)
        else:
            self.update_heartbeat(status="error", error=run_result.error)

        return run_result

    # ------------------------------------------------------------------
    # Execution: streaming
    # ------------------------------------------------------------------

    def run_stream(self, *, callbacks: Optional[dict] = None):
        """Execute the agent with streaming output.

        Yields StreamEvent objects from the engine. The final event
        has type="turn_complete" with data=TurnResult.

        Args:
            callbacks: Optional dict with keys: on_tool_start, on_tool_end
        """
        callbacks = callbacks or {}

        provider = self._create_provider()
        tool_mgr = self._create_tool_manager()
        safety = self._create_safety_shield()
        safety.start_run()

        engine = AgentEngine(
            provider=provider,
            client=None,
            tool_mgr=tool_mgr,
            system_prompt=self.agent_config.system_prompt,
            safety=safety,
            on_tool_start=callbacks.get("on_tool_start"),
            on_tool_end=callbacks.get("on_tool_end"),
        )

        messages: list[dict] = [
            {"role": "user", "content": self.agent_config.user_prompt},
        ]

        start_time = time.time()
        last_result: Optional[TurnResult] = None

        for event in engine.run_turn_stream(messages):
            if event.type == "turn_complete" and isinstance(event.data, TurnResult):
                last_result = event.data
            yield event

        # Save cost if we got a completed result
        if last_result is not None:
            run_result = RunResult(
                agent_name=self.name,
                text=last_result.text,
                tool_rounds=last_result.tool_rounds,
                input_tokens=last_result.input_tokens,
                output_tokens=last_result.output_tokens,
                cost_usd=last_result.cost_usd,
                error=last_result.error,
                duration_seconds=round(time.time() - start_time, 2),
                timestamp=datetime.now().isoformat(),
            )
            try:
                self._save_cost_record(run_result)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # PID management (for daemon mode)
    # ------------------------------------------------------------------

    def write_pid(self) -> None:
        """Write current process PID to pid file."""
        with open(self.pid_file, "w") as f:
            f.write(str(os.getpid()))

    def read_pid(self) -> Optional[int]:
        """Read PID from pid file. Returns None if not running."""
        if not os.path.exists(self.pid_file):
            return None
        try:
            with open(self.pid_file, "r") as f:
                pid = int(f.read().strip())
            # Signal 0 checks process existence without sending a signal
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            self._cleanup_pid()
            return None

    def _cleanup_pid(self) -> None:
        """Remove stale PID file."""
        try:
            os.remove(self.pid_file)
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Class-level utilities
    # ------------------------------------------------------------------

    @staticmethod
    def list_running() -> list[dict]:
        """List all running agents from ~/.flux/agents/*/agent.pid.

        Returns:
            List of dicts with 'name' and 'pid' keys.
        """
        agents_dir = os.path.join(os.path.expanduser("~"), ".flux", "agents")
        if not os.path.exists(agents_dir):
            return []

        running = []
        for name in sorted(os.listdir(agents_dir)):
            pid_file = os.path.join(agents_dir, name, "agent.pid")
            if not os.path.exists(pid_file):
                continue
            try:
                with open(pid_file, "r") as f:
                    pid = int(f.read().strip())
                os.kill(pid, 0)  # Check if process is alive
                running.append({"name": name, "pid": pid})
            except (ValueError, OSError):
                # Stale PID file -- clean up
                try:
                    os.remove(pid_file)
                except OSError:
                    pass

        return running
