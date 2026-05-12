"""Tests for flux CLI using click.testing.CliRunner."""

from __future__ import annotations

import os

import pytest
from click.testing import CliRunner

from flux.cli import cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Global flags
# ---------------------------------------------------------------------------

def test_cli_version(runner):
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_help(runner):
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    # Core commands should all appear in help output
    for cmd in ("init", "validate", "start", "stop", "list", "logs", "cost"):
        assert cmd in result.output


# ---------------------------------------------------------------------------
# flux init
# ---------------------------------------------------------------------------

def test_cli_init(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli, ["init", "test-bot"])
    assert result.exit_code == 0
    assert "Created" in result.output
    yaml_file = tmp_path / "agents" / "test-bot.yaml"
    assert yaml_file.exists()


def test_cli_init_duplicate(runner, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # First creation should succeed
    first = runner.invoke(cli, ["init", "test-bot"])
    assert first.exit_code == 0
    # Second creation should fail with exit code 1
    second = runner.invoke(cli, ["init", "test-bot"])
    assert second.exit_code != 0
    assert "already exists" in second.output


# ---------------------------------------------------------------------------
# flux validate
# ---------------------------------------------------------------------------

VALID_YAML = """\
name: my-agent
description: Test agent
model: claude-haiku
budget:
  per_run: 0.10
  daily: 1.00
  monthly: 10.00
tools:
  - web_search
system_prompt: "You are a helpful assistant."
user_prompt: "Hello!"
"""

INVALID_YAML = """\
description: Missing name field
model: claude-haiku
"""


def test_cli_validate_valid(runner, tmp_path):
    yaml_file = tmp_path / "valid.yaml"
    yaml_file.write_text(VALID_YAML, encoding="utf-8")
    result = runner.invoke(cli, ["validate", str(yaml_file)])
    assert result.exit_code == 0
    assert "Valid" in result.output


def test_cli_validate_invalid(runner, tmp_path):
    yaml_file = tmp_path / "invalid.yaml"
    yaml_file.write_text(INVALID_YAML, encoding="utf-8")
    result = runner.invoke(cli, ["validate", str(yaml_file)])
    assert result.exit_code != 0
    # Either "Invalid" indicator or a field error message should appear
    assert "Invalid" in result.output or "Error" in result.output or "name" in result.output


# ---------------------------------------------------------------------------
# flux list
# ---------------------------------------------------------------------------

def test_cli_list_empty(runner, tmp_path, monkeypatch):
    """When no agents are running, 'flux list' shows 'No agents running'."""
    fake_home = str(tmp_path / "fake_home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "No agents running" in result.output


# ---------------------------------------------------------------------------
# flux cost
# ---------------------------------------------------------------------------

def test_cli_cost_no_data(runner, tmp_path, monkeypatch):
    """When no cost history exists, 'flux cost <name>' says 'No cost data'."""
    fake_home = str(tmp_path / "fake_home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))
    result = runner.invoke(cli, ["cost", "nonexistent-agent"])
    assert result.exit_code == 0
    assert "No cost data" in result.output


# ---------------------------------------------------------------------------
# W2: flux halt / resume / status
# ---------------------------------------------------------------------------

def _fake_home(tmp_path, monkeypatch):
    fake_home = str(tmp_path / "fake_home")
    os.makedirs(fake_home)
    monkeypatch.setenv("HOME", fake_home)
    monkeypatch.setattr(os.path, "expanduser", lambda p: p.replace("~", fake_home))
    return fake_home


def test_cli_halt_creates_emergency_stop(runner, tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    agent_dir = os.path.join(home, ".flux", "agents", "bot-a")
    os.makedirs(agent_dir, exist_ok=True)

    result = runner.invoke(cli, ["halt", "bot-a"])
    assert result.exit_code == 0
    assert "Halted" in result.output
    assert os.path.exists(os.path.join(agent_dir, "emergency_stop"))


def test_cli_resume_removes_emergency_stop(runner, tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    agent_dir = os.path.join(home, ".flux", "agents", "bot-b")
    os.makedirs(agent_dir, exist_ok=True)
    halt_file = os.path.join(agent_dir, "emergency_stop")
    open(halt_file, "w").close()

    result = runner.invoke(cli, ["resume", "bot-b"])
    assert result.exit_code == 0
    assert "Resumed" in result.output
    assert not os.path.exists(halt_file)


def test_cli_resume_when_not_halted(runner, tmp_path, monkeypatch):
    home = _fake_home(tmp_path, monkeypatch)
    os.makedirs(os.path.join(home, ".flux", "agents", "bot-c"), exist_ok=True)

    result = runner.invoke(cli, ["resume", "bot-c"])
    assert result.exit_code == 0
    assert "not halted" in result.output


def test_cli_status_reads_heartbeat(runner, tmp_path, monkeypatch):
    """flux status shows the values from heartbeat.json."""
    import json
    home = _fake_home(tmp_path, monkeypatch)
    agent_dir = os.path.join(home, ".flux", "agents", "bot-d")
    os.makedirs(agent_dir, exist_ok=True)
    hb = {
        "agent_name": "bot-d",
        "pid": None,
        "started_at": "2026-05-12T08:00:00",
        "last_run_at": "2026-05-12T08:05:00",
        "last_run_status": "success",
        "last_error": None,
        "next_run_at": "2026-05-13T08:00:00",
        "consecutive_failures": 0,
        "total_runs": 3,
        "total_failures": 0,
    }
    with open(os.path.join(agent_dir, "heartbeat.json"), "w") as f:
        json.dump(hb, f)

    result = runner.invoke(cli, ["status", "bot-d"])
    assert result.exit_code == 0
    assert "bot-d" in result.output
    # The 'Last status' row should reflect heartbeat value
    assert "success" in result.output
    # And total_runs surfaces too
    assert "3" in result.output


def test_cli_help_lists_new_commands(runner):
    """W2 commands appear in --help output."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    for cmd in ("halt", "resume", "status", "watch", "unwatch"):
        assert cmd in result.output
