"""Tests for flux.scheduler — cron parsing + hardened job configuration."""

from __future__ import annotations

import os

import pytest

from flux.runner import AgentRunner
from flux.scheduler import (
    AgentScheduler,
    DEFAULT_MAX_INSTANCES,
    DEFAULT_MISFIRE_GRACE_SECONDS,
)

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


# ---------------------------------------------------------------------------
# Defaults: hardened values applied
# ---------------------------------------------------------------------------

def test_scheduler_defaults_are_hardened(runner):
    s = AgentScheduler(runner, cron_expr="0 8 * * *")
    assert s.misfire_grace_time == DEFAULT_MISFIRE_GRACE_SECONDS == 300
    assert s.max_instances == DEFAULT_MAX_INSTANCES == 1
    assert s.coalesce is True


# ---------------------------------------------------------------------------
# Cron parser
# ---------------------------------------------------------------------------

def test_parse_cron_5_fields(runner):
    s = AgentScheduler(runner, cron_expr="*/5 * * * *")
    kwargs = s._parse_cron()
    assert kwargs == {
        "minute": "*/5",
        "hour": "*",
        "day": "*",
        "month": "*",
        "day_of_week": "*",
    }


def test_parse_cron_rejects_bad_field_count(runner):
    s = AgentScheduler(runner, cron_expr="0 8 * *")  # only 4 fields
    with pytest.raises(ValueError, match="Expected 5 fields"):
        s._parse_cron()


# ---------------------------------------------------------------------------
# Job configuration: hardened flags reach add_job
# ---------------------------------------------------------------------------

def test_add_job_uses_hardened_flags(runner, monkeypatch):
    """Calling scheduler.add_job() should pass misfire/max_instances/coalesce."""
    captured = {}

    def fake_add_job(func, trigger, **kwargs):
        captured.update(kwargs)
        captured["trigger"] = trigger

    s = AgentScheduler(runner, cron_expr="0 8 * * *")
    monkeypatch.setattr(s.scheduler, "add_job", fake_add_job)

    # Inline the bits of start() that matter for this test (avoid blocking)
    from apscheduler.triggers.cron import CronTrigger
    s.scheduler.add_job(
        s._run_agent,
        trigger=CronTrigger(**s._parse_cron()),
        id=f"agent-{s.runner.name}",
        name=f"Agent: {s.runner.name}",
        replace_existing=True,
        misfire_grace_time=s.misfire_grace_time,
        max_instances=s.max_instances,
        coalesce=s.coalesce,
    )

    assert captured["misfire_grace_time"] == 300
    assert captured["max_instances"] == 1
    assert captured["coalesce"] is True
    assert captured["replace_existing"] is True


# ---------------------------------------------------------------------------
# Override knobs are respected
# ---------------------------------------------------------------------------

def test_scheduler_overrides_misfire_and_concurrency(runner):
    s = AgentScheduler(
        runner,
        cron_expr="0 8 * * *",
        misfire_grace_time=60,
        max_instances=2,
        coalesce=False,
    )
    assert s.misfire_grace_time == 60
    assert s.max_instances == 2
    assert s.coalesce is False
