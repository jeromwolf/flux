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


DEFAULT_MISFIRE_GRACE_SECONDS = 300  # 5 minutes
DEFAULT_MAX_INSTANCES = 1            # one run at a time per agent


class AgentScheduler:
    """Cron-based scheduler for running agents on a schedule.

    Hardened (W2):
        - ``misfire_grace_time`` so a missed run within 5 minutes still fires
        - ``max_instances=1`` so a long-running call never overlaps itself
        - ``coalesce=True`` so multiple missed runs collapse into one catch-up

    Failure backoff is delegated to :class:`flux.watchdog.AgentWatchdog`.

    Usage::

        scheduler = AgentScheduler(runner, cron_expr="0 8 * * *")
        scheduler.start()  # Blocks until stopped
    """

    def __init__(
        self,
        runner,
        cron_expr: str,
        *,
        misfire_grace_time: int = DEFAULT_MISFIRE_GRACE_SECONDS,
        max_instances: int = DEFAULT_MAX_INSTANCES,
        coalesce: bool = True,
    ):
        """
        Args:
            runner: AgentRunner instance.
            cron_expr: Cron expression (5 fields: min hour day month weekday).
            misfire_grace_time: Seconds within which a missed run still fires.
            max_instances: Concurrent run limit per agent (default 1).
            coalesce: If True, multiple missed runs collapse into one.
        """
        self.runner = runner
        self.cron_expr = cron_expr
        self.misfire_grace_time = misfire_grace_time
        self.max_instances = max_instances
        self.coalesce = coalesce
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
                    "Agent run completed: tokens=%s/%s, cost=$%s, duration=%ss",
                    result.input_tokens, result.output_tokens,
                    result.cost_usd, result.duration_seconds,
                )
        except Exception:
            logger.exception("Scheduled agent run failed")
        finally:
            # Refresh heartbeat with next scheduled fire time so Watchdog
            # can tell whether the daemon is still ticking.
            try:
                next_iso = self.get_next_run()
                if next_iso:
                    hb = self.runner._load_heartbeat()
                    hb["next_run_at"] = next_iso
                    self.runner._save_heartbeat(hb)
            except Exception:
                logger.debug("Failed to update next_run heartbeat", exc_info=True)

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
        # Write PID file + bootstrap heartbeat for Watchdog
        self.runner.write_pid()
        self.runner.mark_started()

        cron_kwargs = self._parse_cron()
        trigger = CronTrigger(**cron_kwargs)

        self.scheduler.add_job(
            self._run_agent,
            trigger=trigger,
            id=f"agent-{self.runner.name}",
            name=f"Agent: {self.runner.name}",
            replace_existing=True,
            misfire_grace_time=self.misfire_grace_time,
            max_instances=self.max_instances,
            coalesce=self.coalesce,
        )

        next_run = trigger.get_next_fire_time(None, datetime.now())
        logger.info(
            "Scheduler started for '%s' with cron '%s'. Next run: %s",
            self.runner.name, self.cron_expr,
            next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "unknown",
        )

        # Persist initial next_run so the Watchdog has a freshness anchor.
        if next_run is not None:
            try:
                hb = self.runner._load_heartbeat()
                hb["next_run_at"] = next_run.isoformat()
                self.runner._save_heartbeat(hb)
            except Exception:
                logger.debug("Failed to seed next_run_at heartbeat", exc_info=True)

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
