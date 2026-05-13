"""Tests for flux.runner — model resolution, RunResult, and AgentRunner utilities."""

from __future__ import annotations

import os

import pytest

from flux.runner import (
    MODEL_ALIASES,
    AgentRunner,
    RunResult,
    resolve_model,
)

# ---------------------------------------------------------------------------
# resolve_model
# ---------------------------------------------------------------------------

def test_resolve_model_claude_haiku():
    provider, model_id = resolve_model("claude-haiku")
    assert provider == "anthropic"
    assert model_id == "claude-haiku-4-5-20251001"


def test_resolve_model_claude_sonnet():
    provider, model_id = resolve_model("claude-sonnet")
    assert provider == "anthropic"
    assert model_id == "claude-sonnet-4-6-20250514"


def test_resolve_model_gpt4o():
    provider, model_id = resolve_model("gpt-4o")
    assert provider == "openai"
    assert model_id == "gpt-4o"


def test_resolve_model_unknown():
    provider, model_id = resolve_model("some-unknown-model-xyz")
    assert provider == "anthropic"
    assert model_id == "some-unknown-model-xyz"


# ---------------------------------------------------------------------------
# RunResult
# ---------------------------------------------------------------------------

def test_run_result_to_dict():
    result = RunResult(
        agent_name="test-agent",
        text="Hello world",
        tool_rounds=2,
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0012,
        duration_seconds=1.5,
        error=None,
        timestamp="2024-01-01T00:00:00",
    )
    d = result.to_dict()

    assert d["agent_name"] == "test-agent"
    assert d["text"] == "Hello world"
    assert d["tool_rounds"] == 2
    assert d["input_tokens"] == 100
    assert d["output_tokens"] == 50
    assert d["cost_usd"] == 0.0012
    assert d["duration_seconds"] == 1.5
    assert d["error"] is None
    assert d["timestamp"] == "2024-01-01T00:00:00"


# ---------------------------------------------------------------------------
# AgentRunner — construction and property tests
# ---------------------------------------------------------------------------

YAML_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "agents",
    "examples",
    "news-summary.yaml",
)


@pytest.fixture()
def runner(tmp_path):
    """AgentRunner loaded from the real news-summary.yaml, with isolated data dir."""
    return AgentRunner(YAML_PATH, data_dir=str(tmp_path / "flux-data"))


def test_agent_runner_init(runner):
    assert runner.name == "news-summary-bot"
    assert runner.provider_name == "anthropic"
    # claude-haiku alias should resolve to the full model ID
    assert runner.model_id == "claude-haiku-4-5-20251001"


def test_agent_runner_properties(runner, tmp_path):
    data_dir = str(tmp_path / "flux-data")
    assert runner.pid_file == os.path.join(data_dir, "agent.pid")
    assert runner.cost_file == os.path.join(data_dir, "cost_history.jsonl")
    assert runner.log_file == os.path.join(data_dir, "agent.log")


def test_agent_runner_cost_summary_empty(runner):
    summary = runner.get_cost_summary()
    assert summary["total_runs"] == 0
    assert summary["total_cost"] == 0.0
    assert summary["today_cost"] == 0.0
    assert summary["today_runs"] == 0


def test_agent_runner_list_running_empty(tmp_path, monkeypatch):
    """list_running should return [] when the agents dir does not exist."""
    fake_home = str(tmp_path / "fake_home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    # Patch os.path.expanduser to return our fake home
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))
    result = AgentRunner.list_running()
    assert result == []


# ---------------------------------------------------------------------------
# MODEL_ALIASES completeness
# ---------------------------------------------------------------------------

def test_model_aliases_completeness():
    """Every alias in MODEL_ALIASES should resolve to a non-empty (provider, model_id)."""
    for alias, full_id in MODEL_ALIASES.items():
        provider, model_id = resolve_model(alias)
        assert provider, f"Empty provider for alias {alias!r}"
        assert model_id, f"Empty model_id for alias {alias!r}"
        # The returned model_id must equal the expanded full ID (not the alias)
        assert model_id == full_id, (
            f"resolve_model({alias!r}) returned model_id={model_id!r}, "
            f"expected {full_id!r}"
        )


# ---------------------------------------------------------------------------
# W2: Heartbeat lifecycle (no LLM call needed)
# ---------------------------------------------------------------------------

def test_runner_heartbeat_lifecycle(runner):
    """mark_started -> update_heartbeat tracks runs and failure streak."""
    runner.mark_started()
    hb = runner._load_heartbeat()
    assert hb["agent_name"] == runner.name
    assert hb["pid"] == os.getpid()
    assert hb["total_runs"] == 0
    assert hb["consecutive_failures"] == 0

    # One success
    runner.update_heartbeat(status="success")
    hb = runner._load_heartbeat()
    assert hb["total_runs"] == 1
    assert hb["last_run_status"] == "success"
    assert hb["consecutive_failures"] == 0

    # Two failures - streak grows
    runner.update_heartbeat(status="error", error="oops 1")
    runner.update_heartbeat(status="error", error="oops 2")
    hb = runner._load_heartbeat()
    assert hb["total_runs"] == 3
    assert hb["consecutive_failures"] == 2
    assert hb["last_error"] == "oops 2"
    assert hb["total_failures"] == 2

    # Success resets streak but not totals
    runner.update_heartbeat(status="success", next_run_at="2026-05-13T08:00:00")
    hb = runner._load_heartbeat()
    assert hb["consecutive_failures"] == 0
    assert hb["next_run_at"] == "2026-05-13T08:00:00"
    assert hb["total_runs"] == 4


def test_runner_heartbeat_corrupt_file_resets_safely(runner):
    """Corrupt heartbeat.json doesn't crash subsequent reads."""
    with open(runner.heartbeat_file, "w") as f:
        f.write("{not valid json")
    hb = runner._load_heartbeat()
    assert hb["agent_name"] == runner.name
    assert hb["consecutive_failures"] == 0
