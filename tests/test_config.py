"""Tests for flux.config module."""
from __future__ import annotations

import pytest

from flux.config import (
    AgentConfig,
    BudgetConfig,
    Config,
    load_agent_config,
    load_config,
    reset_config,
    get_config,
)
from pydantic import ValidationError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """Always reset the config singleton before and after each test."""
    reset_config()
    yield
    reset_config()


# ---------------------------------------------------------------------------
# Test 1: Config() has correct defaults
# ---------------------------------------------------------------------------

def test_default_config():
    cfg = Config()
    assert cfg.default_model == "claude-sonnet-4-20250514"
    assert cfg.max_tokens == 4096
    assert cfg.max_tool_rounds == 10
    assert cfg.max_daily_calls == 100
    assert cfg.max_history == 50
    assert cfg.llm_retry_count == 3
    assert cfg.llm_retry_base_delay == 1.0
    assert cfg.llm_retry_max_delay == 16.0
    assert cfg.tool_timeout_seconds == 30.0
    assert cfg.max_message_length == 10000
    assert cfg.streaming_enabled is True
    assert cfg.weekly_budget_usd == 10.0
    assert cfg.log_level == "INFO"
    assert cfg.log_format == "text"


# ---------------------------------------------------------------------------
# Test 2: load_config() returns Config with defaults when no file/env
# ---------------------------------------------------------------------------

def test_load_config_defaults(tmp_path, monkeypatch):
    # Ensure none of the env overrides are set
    env_keys = [
        "LLM_MODEL", "MAX_TOKENS", "MAX_TOOL_ROUNDS", "MAX_DAILY_CALLS",
        "MAX_HISTORY", "LLM_RETRY_COUNT", "LLM_RETRY_BASE_DELAY",
        "TOOL_TIMEOUT", "DAEMON_MAX_RESTARTS", "DAEMON_RESTART_DELAY",
        "LOG_LEVEL", "LOG_FORMAT", "LOG_FILE", "LOG_MAX_BYTES",
        "LOG_BACKUP_COUNT", "STREAMING_ENABLED", "WEEKLY_BUDGET_USD",
        "MAX_WEEKLY_CALLS", "BACKUP_DIR",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)

    nonexistent_path = str(tmp_path / "no_config.json")
    cfg = load_config(nonexistent_path)

    assert isinstance(cfg, Config)
    assert cfg.default_model == "claude-sonnet-4-20250514"
    assert cfg.max_tokens == 4096
    assert cfg.max_tool_rounds == 10


# ---------------------------------------------------------------------------
# Test 3: Env vars override defaults
# ---------------------------------------------------------------------------

def test_config_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-20250514")
    monkeypatch.setenv("MAX_TOKENS", "2048")

    nonexistent_path = str(tmp_path / "no_config.json")
    cfg = load_config(nonexistent_path)

    assert cfg.default_model == "claude-haiku-4-20250514"
    assert cfg.max_tokens == 2048


# ---------------------------------------------------------------------------
# Test 4: Values outside bounds get clamped
# ---------------------------------------------------------------------------

def test_config_field_clamping(tmp_path, monkeypatch):
    # max_tool_rounds upper bound is 50
    monkeypatch.setenv("MAX_TOOL_ROUNDS", "999")
    # max_tokens lower bound is 100
    monkeypatch.setenv("MAX_TOKENS", "1")

    nonexistent_path = str(tmp_path / "no_config.json")
    cfg = load_config(nonexistent_path)

    assert cfg.max_tool_rounds == 50   # clamped from 999 to 50
    assert cfg.max_tokens == 100       # clamped from 1 to 100


# ---------------------------------------------------------------------------
# Test 5: BudgetConfig defaults and custom values
# ---------------------------------------------------------------------------

def test_budget_config():
    # Defaults
    b = BudgetConfig()
    assert b.per_run == 0.10
    assert b.daily == 1.00
    assert b.monthly == 10.00

    # Custom values
    b2 = BudgetConfig(per_run=0.05, daily=0.50, monthly=5.00)
    assert b2.per_run == 0.05
    assert b2.daily == 0.50
    assert b2.monthly == 5.00


# ---------------------------------------------------------------------------
# Test 6: AgentConfig validates a correct agent dict
# ---------------------------------------------------------------------------

def test_agent_config_valid():
    data = {
        "name": "test-agent",
        "description": "A test agent",
        "model": "claude-haiku",
        "max_tokens": 2048,
        "tools": ["web_search"],
        "system_prompt": "You are helpful.",
        "user_prompt": "Do something.",
        "budget": {"per_run": 0.05, "daily": 0.50, "monthly": 5.00},
    }
    agent = AgentConfig(**data)
    assert agent.name == "test-agent"
    assert agent.description == "A test agent"
    assert agent.model == "claude-haiku"
    assert agent.max_tokens == 2048
    assert agent.tools == ["web_search"]
    assert agent.budget.per_run == 0.05


# ---------------------------------------------------------------------------
# Test 7: AgentConfig raises ValidationError without name
# ---------------------------------------------------------------------------

def test_agent_config_missing_name():
    with pytest.raises(ValidationError):
        AgentConfig(description="no name here")


# ---------------------------------------------------------------------------
# Test 8: load_agent_config() loads the example YAML correctly
# ---------------------------------------------------------------------------

def test_load_agent_config():
    import os
    yaml_path = os.path.join(
        os.path.dirname(__file__), "..", "agents", "examples", "news-summary.yaml"
    )
    data = load_agent_config(yaml_path)

    assert isinstance(data, dict)
    assert data["name"] == "news-summary-bot"
    assert data["model"] == "claude-haiku"
    assert data["max_tokens"] == 4096
    assert "budget" in data
    assert data["budget"]["per_run"] == 0.10

    # Also validate through AgentConfig
    agent = AgentConfig(**data)
    assert agent.name == "news-summary-bot"
    assert "web_search" in agent.tools


# ---------------------------------------------------------------------------
# Test 9: Raises FileNotFoundError for missing file
# ---------------------------------------------------------------------------

def test_load_agent_config_nonexistent(tmp_path):
    missing = str(tmp_path / "ghost.yaml")
    with pytest.raises(FileNotFoundError):
        load_agent_config(missing)


# ---------------------------------------------------------------------------
# Test 10: reset_config() clears singleton cache
# ---------------------------------------------------------------------------

def test_reset_config(tmp_path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    nonexistent_path = str(tmp_path / "no_config.json")

    # Prime the singleton with default model
    cfg1 = get_config(nonexistent_path)
    assert cfg1.default_model == "claude-sonnet-4-20250514"

    # Reset, then set env override
    reset_config()
    monkeypatch.setenv("LLM_MODEL", "gpt-4o")

    cfg2 = get_config(nonexistent_path)
    assert cfg2.default_model == "gpt-4o"

    # The two configs are different objects
    assert cfg1 is not cfg2
