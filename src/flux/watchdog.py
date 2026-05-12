"""Flux Watchdog — Agent health monitoring + auto-recovery.

Independent supervisor that watches an agent daemon and restarts it
on failure with exponential backoff. Designed to run as a separate
process from the agent daemon itself.

Health signals (all must be OK):
1. Agent PID file exists AND process is alive
2. Heartbeat 'last_run_at' is within freshness window (relative to cron schedule)
3. Consecutive failure count below threshold

Restart policy (exponential backoff with 30 min ceiling):
    attempt 1: 30s   attempt 2: 60s   attempt 3: 300s
    attempt 4: 900s  attempt 5+: 1800s

Usage:
    from flux.watchdog import AgentWatchdog
    from flux.runner import AgentRunner

    runner = AgentRunner("agents/news-bot.yaml")
    watchdog = AgentWatchdog(runner, check_interval=60)
    watchdog.watch_forever()
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from flux.logging import get_logger

logger = get_logger("watchdog")


# Backoff schedule in seconds: attempt index 1..5+
BACKOFF_SECONDS = [30, 60, 300, 900, 1800]


@dataclass
class HealthCheck:
    """Result of a health check."""
    healthy: bool
    reason: str
    details: dict


class AgentWatchdog:
    """Supervises an agent daemon and restarts on failure.

    The watchdog is intended to run in its own process — separate from
    the agent daemon — so it survives crashes of the supervised process.
    """

    def __init__(
        self,
        runner,
        *,
        check_interval: int = 60,
        max_failures_before_restart: int = 3,
        stale_grace_seconds: int = 600,
    ):
        """
        Args:
            runner: AgentRunner instance for the supervised agent.
            check_interval: Seconds between health checks (default 60).
            max_failures_before_restart: Consecutive agent failures that
                trigger a restart even if the process is still alive.
            stale_grace_seconds: Extra time beyond the cron 'next_run_at'
                before a missed run is considered unhealthy.
        """
        self.runner = runner
        self.check_interval = check_interval
        self.max_failures_before_restart = max_failures_before_restart
        self.stale_grace_seconds = stale_grace_seconds

        self._restart_attempts = 0
        self._last_restart_at: Optional[float] = None
        self._stop_requested = False

    # ------------------------------------------------------------------
    # Watchdog state files
    # ------------------------------------------------------------------

    @property
    def watchdog_pid_file(self) -> str:
        return os.path.join(self.runner.data_dir, "watchdog.pid")

    @property
    def events_file(self) -> str:
        return self.runner.events_file

    # ------------------------------------------------------------------
    # Event logging
    # ------------------------------------------------------------------

    def emit_event(self, event_type: str, data: Optional[dict] = None) -> None:
        """Append a structured event to events.jsonl."""
        record = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.runner.name,
            "event": event_type,
            "data": data or {},
        }
        try:
            with open(self.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning("Failed to write watchdog event: %s", e)

        logger.info("watchdog.%s: %s", event_type, data or {})

    # ------------------------------------------------------------------
    # Health checks
    # ------------------------------------------------------------------

    def _process_alive(self) -> tuple[bool, Optional[int]]:
        """Return (is_alive, pid) for the supervised agent."""
        pid = self.runner.read_pid()
        if pid is None:
            return False, None
        return True, pid

    def _heartbeat_fresh(self, hb: dict) -> tuple[bool, str]:
        """Check that the heartbeat hasn't gone stale beyond next_run_at.

        Logic: if there's a scheduled next_run_at, the heartbeat is stale
        only if 'now > next_run_at + stale_grace_seconds'. This allows long
        idle gaps between cron firings without false alarms.
        """
        next_run_at = hb.get("next_run_at")
        if not next_run_at:
            # No next run scheduled yet (daemon just started) - not stale.
            return True, "no schedule yet"
        try:
            next_dt = datetime.fromisoformat(next_run_at)
        except (ValueError, TypeError):
            return True, "unparseable next_run_at"

        deadline = next_dt + timedelta(seconds=self.stale_grace_seconds)
        now = datetime.now(tz=next_dt.tzinfo) if next_dt.tzinfo else datetime.now()
        if now > deadline:
            return False, f"missed scheduled run (next_run_at={next_run_at}, now past +{self.stale_grace_seconds}s grace)"
        return True, "fresh"

    def is_healthy(self) -> HealthCheck:
        """Run all health checks. Returns first failure, or healthy."""
        # 1. Process alive
        alive, pid = self._process_alive()
        if not alive:
            return HealthCheck(
                healthy=False,
                reason="process_dead",
                details={"pid": None},
            )

        # 2. Read heartbeat
        hb = self.runner._load_heartbeat()

        # 3. Consecutive failure count
        consecutive = int(hb.get("consecutive_failures", 0))
        if consecutive >= self.max_failures_before_restart:
            return HealthCheck(
                healthy=False,
                reason="too_many_failures",
                details={
                    "consecutive_failures": consecutive,
                    "last_error": hb.get("last_error"),
                },
            )

        # 4. Stale heartbeat
        fresh, fresh_reason = self._heartbeat_fresh(hb)
        if not fresh:
            return HealthCheck(
                healthy=False,
                reason="stale_heartbeat",
                details={
                    "pid": pid,
                    "detail": fresh_reason,
                    "last_run_at": hb.get("last_run_at"),
                    "next_run_at": hb.get("next_run_at"),
                },
            )

        return HealthCheck(
            healthy=True,
            reason="ok",
            details={
                "pid": pid,
                "consecutive_failures": consecutive,
                "last_run_status": hb.get("last_run_status"),
            },
        )

    # ------------------------------------------------------------------
    # Restart logic
    # ------------------------------------------------------------------

    def _backoff_delay(self) -> int:
        """Return delay (seconds) for current restart attempt."""
        idx = min(self._restart_attempts, len(BACKOFF_SECONDS) - 1)
        return BACKOFF_SECONDS[idx]

    def _spawn_daemon(self) -> Optional[int]:
        """Spawn a detached `flux start <yaml> -d --now` subprocess.

        Returns the spawned PID, or None on failure.
        """
        cmd = [sys.executable, "-m", "flux.cli", "start", self.runner.yaml_path, "-d", "--now"]
        try:
            # start_new_session=True detaches from the watchdog process group
            proc = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            # Give it a moment to write its PID file
            time.sleep(2)
            return proc.pid
        except OSError as e:
            logger.error("Failed to spawn daemon for %s: %s", self.runner.name, e)
            return None

    def restart(self, reason: str) -> bool:
        """Attempt to restart the agent daemon.

        Applies exponential backoff based on consecutive restart attempts.
        Resets the counter only after a successful subsequent health check.

        Returns:
            True if a daemon process was spawned, False otherwise.
        """
        self._restart_attempts += 1
        delay = self._backoff_delay()

        self.emit_event("restart_pending", {
            "reason": reason,
            "attempt": self._restart_attempts,
            "delay_seconds": delay,
        })

        logger.warning(
            "Restart %d for %s in %ds (reason=%s)",
            self._restart_attempts, self.runner.name, delay, reason,
        )

        # Sleep with stop-aware polling so SIGTERM cancels promptly.
        end = time.time() + delay
        while time.time() < end:
            if self._stop_requested:
                return False
            time.sleep(min(2, end - time.time()))

        # Clean stale PID file before respawning.
        if self.runner.read_pid() is None:
            self.runner._cleanup_pid()

        spawned_pid = self._spawn_daemon()
        if spawned_pid is None:
            self.emit_event("restart_failed", {"attempt": self._restart_attempts})
            return False

        self._last_restart_at = time.time()
        self.emit_event("restart_spawned", {
            "attempt": self._restart_attempts,
            "subprocess_pid": spawned_pid,
        })
        return True

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def watch_forever(self) -> None:
        """Run the watchdog loop until SIGTERM/SIGINT."""
        self._write_watchdog_pid()
        self._setup_signal_handlers()

        self.emit_event("watchdog_started", {
            "check_interval": self.check_interval,
            "max_failures": self.max_failures_before_restart,
        })

        try:
            while not self._stop_requested:
                hc = self.is_healthy()

                if hc.healthy:
                    # Reset restart counter after one healthy tick post-restart.
                    if self._restart_attempts > 0:
                        self.emit_event("recovered", {
                            "attempts_used": self._restart_attempts,
                            "details": hc.details,
                        })
                        self._restart_attempts = 0
                else:
                    self.emit_event("unhealthy", {
                        "reason": hc.reason,
                        "details": hc.details,
                    })
                    self.restart(reason=hc.reason)
                    # After a restart, immediately loop into next check.
                    continue

                # Sleep with stop-aware polling.
                end = time.time() + self.check_interval
                while time.time() < end and not self._stop_requested:
                    time.sleep(min(2, end - time.time()))
        finally:
            self._cleanup_watchdog_pid()
            self.emit_event("watchdog_stopped", {})

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _setup_signal_handlers(self) -> None:
        def _stop(signum, frame):
            logger.info("Watchdog received signal %d, stopping", signum)
            self._stop_requested = True
        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

    def _write_watchdog_pid(self) -> None:
        try:
            with open(self.watchdog_pid_file, "w") as f:
                f.write(str(os.getpid()))
        except OSError as e:
            logger.warning("Failed to write watchdog pid: %s", e)

    def _cleanup_watchdog_pid(self) -> None:
        try:
            os.remove(self.watchdog_pid_file)
        except OSError:
            pass

    @staticmethod
    def watchdog_pid_for(agent_name: str) -> Optional[int]:
        """Return the PID of a running watchdog for the agent, or None."""
        path = os.path.join(
            os.path.expanduser("~"), ".flux", "agents", agent_name, "watchdog.pid"
        )
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return pid
        except (ValueError, OSError):
            try:
                os.remove(path)
            except OSError:
                pass
            return None
