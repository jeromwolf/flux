"""Flux Scheduler — APScheduler-based cron scheduler for agent daemon mode."""

from __future__ import annotations

import signal
import sys
import os
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from flux.logging import get_logger

logger = get_logger("scheduler")


class AgentScheduler:
    """Cron-based scheduler for running agents on a schedule.

    Usage:
        scheduler = AgentScheduler(runner, cron_expr="0 8 * * *")
        scheduler.start()  # Blocks until stopped
    """

    def __init__(self, runner, cron_expr: str):
        """
        Args:
            runner: AgentRunner instance
            cron_expr: Cron expression (5 fields: min hour day month weekday)
        """
        self.runner = runner
        self.cron_expr = cron_expr
        self.scheduler = BlockingScheduler()
        self._setup_signal_handlers()

    def _setup_signal_handlers(self):
        """Handle graceful shutdown on SIGTERM/SIGINT."""
        def _shutdown(signum, frame):
            logger.info("Received signal %d, shutting down scheduler...", signum)
            self.stop()
            sys.exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

    def _run_agent(self):
        """Execute the agent (called by scheduler)."""
        logger.info("Scheduled run triggered for: %s", self.runner.name)
        try:
            result = self.runner.run()
            if result.error:
                logger.error("Agent run completed with error: %s", result.error)
            else:
                logger.info(
                    "Agent run completed: tokens=%d/%d, cost=$%.4f, duration=%.1fs",
                    result.input_tokens, result.output_tokens,
                    result.cost_usd, result.duration_seconds,
                )
        except Exception:
            logger.exception("Scheduled agent run failed")

    def _parse_cron(self) -> dict:
        """Parse cron expression into APScheduler CronTrigger kwargs.

        Supports standard 5-field cron: minute hour day month day_of_week
        """
        parts = self.cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(
                f"Invalid cron expression: '{self.cron_expr}'. "
                "Expected 5 fields: minute hour day month day_of_week"
            )

        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }

    def start(self, run_immediately: bool = False):
        """Start the scheduler (blocks).

        Args:
            run_immediately: If True, run the agent once before starting schedule.
        """
        # Write PID file
        self.runner.write_pid()

        cron_kwargs = self._parse_cron()
        trigger = CronTrigger(**cron_kwargs)

        self.scheduler.add_job(
            self._run_agent,
            trigger=trigger,
            id=f"agent-{self.runner.name}",
            name=f"Agent: {self.runner.name}",
            replace_existing=True,
        )

        next_run = trigger.get_next_fire_time(None, datetime.now())
        logger.info(
            "Scheduler started for '%s' with cron '%s'. Next run: %s",
            self.runner.name, self.cron_expr,
            next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "unknown",
        )

        if run_immediately:
            logger.info("Running agent immediately before schedule starts...")
            self._run_agent()

        try:
            self.scheduler.start()
        finally:
            self.runner._cleanup_pid()

    def stop(self):
        """Stop the scheduler gracefully."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped for: %s", self.runner.name)
        self.runner._cleanup_pid()

    def get_next_run(self) -> str | None:
        """Get next scheduled run time as ISO string."""
        jobs = self.scheduler.get_jobs()
        if not jobs:
            return None
        next_run = jobs[0].next_run_time
        return next_run.isoformat() if next_run else None
