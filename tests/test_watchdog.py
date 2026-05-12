"""Tests for flux.watchdog — AgentWatchdog health checks + restart policy."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta

import pytest

from flux.runner import AgentRunner
from flux.watchdog import AgentWatchdog, BACKOFF_SECONDS, HealthCheck

YAML_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "agents",
    "examples",
    "news-summary.yaml",
)


@pytest.fixture()
def runner(tmp_path):
    return AgentRunner(YAML_PATH, data_dir=str(tmp_path / "flux-data"))


@pytest.fixture()
def watchdog(runner):
    return AgentWatchdog(runner, check_interval=5, max_failures_before_restart=3)


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def test_is_healthy_process_dead(watchdog):
    """No PID file -> unhealthy with process_dead reason."""
    hc = watchdog.is_healthy()
    assert isinstance(hc, HealthCheck)
    assert hc.healthy is False
    assert hc.reason == "process_dead"


def test_is_healthy_running_and_fresh(watchdog, runner):
    """Live PID + fresh heartbeat -> healthy."""
    # Use this test process as the "agent" PID
    with open(runner.pid_file, "w") as f:
        f.write(str(os.getpid()))

    # Heartbeat with future next_run_at
    hb = runner._empty_heartbeat()
    future = (datetime.now() + timedelta(minutes=30)).isoformat()
    hb["next_run_at"] = future
    hb["last_run_at"] = datetime.now().isoformat()
    hb["last_run_status"] = "success"
    runner._save_heartbeat(hb)

    hc = watchdog.is_healthy()
    assert hc.healthy is True
    assert hc.reason == "ok"


def test_is_healthy_too_many_failures(watchdog, runner):
    """consecutive_failures >= threshold triggers too_many_failures."""
    with open(runner.pid_file, "w") as f:
        f.write(str(os.getpid()))

    hb = runner._empty_heartbeat()
    hb["consecutive_failures"] = 5
    hb["last_error"] = "boom"
    hb["next_run_at"] = (datetime.now() + timedelta(hours=1)).isoformat()
    runner._save_heartbeat(hb)

    hc = watchdog.is_healthy()
    assert hc.healthy is False
    assert hc.reason == "too_many_failures"
    assert hc.details["consecutive_failures"] == 5
    assert hc.details["last_error"] == "boom"


def test_is_healthy_stale_heartbeat(watchdog, runner):
    """Past next_run_at + grace -> stale_heartbeat."""
    with open(runner.pid_file, "w") as f:
        f.write(str(os.getpid()))

    hb = runner._empty_heartbeat()
    # Pretend the next run was an hour ago, well past 600s grace.
    past = (datetime.now() - timedelta(hours=1)).isoformat()
    hb["next_run_at"] = past
    runner._save_heartbeat(hb)

    hc = watchdog.is_healthy()
    assert hc.healthy is False
    assert hc.reason == "stale_heartbeat"


# ---------------------------------------------------------------------------
# Backoff schedule
# ---------------------------------------------------------------------------

def test_backoff_schedule_matches_constant(watchdog):
    """_backoff_delay walks BACKOFF_SECONDS and clamps to the last entry."""
    for attempt_idx, expected in enumerate(BACKOFF_SECONDS):
        watchdog._restart_attempts = attempt_idx
        assert watchdog._backoff_delay() == expected

    # Beyond the list: clamp at last value (30 min)
    watchdog._restart_attempts = 99
    assert watchdog._backoff_delay() == BACKOFF_SECONDS[-1]


# ---------------------------------------------------------------------------
# Event logging
# ---------------------------------------------------------------------------

def test_emit_event_appends_jsonl(watchdog, runner):
    """emit_event writes a structured JSON line to events.jsonl."""
    watchdog.emit_event("test_event", {"k": 1, "msg": "hello"})
    watchdog.emit_event("another", {})

    assert os.path.exists(runner.events_file)
    with open(runner.events_file, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2

    rec1 = json.loads(lines[0])
    assert rec1["event"] == "test_event"
    assert rec1["agent"] == runner.name
    assert rec1["data"] == {"k": 1, "msg": "hello"}
    assert "timestamp" in rec1
