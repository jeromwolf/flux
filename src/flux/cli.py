"""Flux CLI — AI Agent Runtime."""

from __future__ import annotations

import os
import sys

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="flux")
def cli():
    """Flux — AI Agent Runtime Platform.

    Deploy, run, and manage AI agents 24/7.
    """
    pass


@cli.command()
@click.argument("name")
@click.option("-d", "--dir", "directory", default="agents", help="Output directory")
def init(name: str, directory: str):
    """Create a new agent from template."""
    import yaml

    template = {
        "name": name,
        "description": f"Agent: {name}",
        "schedule": "0 8 * * *",
        "model": "claude-haiku",
        "max_tokens": 4096,
        "budget": {
            "per_run": 0.10,
            "daily": 1.00,
            "monthly": 10.00,
        },
        "tools": ["web_search", "web_fetch"],
        "system_prompt": "You are a helpful AI assistant.\n",
        "user_prompt": "Hello! What can you help me with today?\n",
    }

    os.makedirs(directory, exist_ok=True)
    filepath = os.path.join(directory, f"{name}.yaml")

    if os.path.exists(filepath):
        console.print(f"[bold red]Error:[/] {filepath} already exists")
        raise SystemExit(1)

    with open(filepath, "w", encoding="utf-8") as f:
        yaml.dump(template, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    console.print(f"[bold green]Created:[/] {filepath}")
    console.print(f"[dim]Edit the file, then run: flux start {filepath}[/]")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
def validate(file: str):
    """Validate an agent YAML config."""
    from flux.config import load_agent_config, AgentConfig
    from pydantic import ValidationError

    try:
        data = load_agent_config(file)
        agent = AgentConfig(**data)

        console.print(f"[bold green]Valid ✓[/] {agent.name}")
        console.print(f"  Model: {agent.model}")
        console.print(f"  Schedule: {agent.schedule or 'none (manual)'}")
        console.print(f"  Budget: ${agent.budget.per_run}/run, ${agent.budget.daily}/day, ${agent.budget.monthly}/mo")
        console.print(f"  Tools: {', '.join(agent.tools) if agent.tools else 'none'}")
    except ValidationError as e:
        console.print("[bold red]Invalid ✗[/]")
        for err in e.errors():
            loc = " → ".join(str(x) for x in err["loc"])
            console.print(f"  {loc}: {err['msg']}")
        raise SystemExit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise SystemExit(1)


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-d", "--daemon", is_flag=True, help="Run as background daemon")
@click.option("--now", is_flag=True, help="Run immediately (daemon mode: before schedule starts)")
def start(file: str, daemon: bool, now: bool):
    """Start an agent from YAML config."""
    from flux.runner import AgentRunner

    try:
        runner = AgentRunner(file)
    except Exception as e:
        console.print(f"[bold red]Error loading config:[/] {e}")
        raise SystemExit(1)

    # Check if already running
    existing_pid = runner.read_pid()
    if existing_pid:
        console.print(f"[bold yellow]Agent '{runner.name}' already running (PID {existing_pid})[/]")
        raise SystemExit(1)

    if daemon:
        _start_daemon(runner, now)
    else:
        _start_foreground(runner)


def _start_foreground(runner):
    """Run agent once in foreground with Rich output."""
    config = runner.agent_config

    console.print(Panel(
        f"[bold]{config.name}[/]\n"
        f"Model: {runner.model_id} ({runner.provider_name})\n"
        f"Tools: {', '.join(config.tools) if config.tools else 'none'}\n"
        f"Budget: ${config.budget.per_run}/run",
        title="[bold cyan]Flux Agent[/]",
        border_style="cyan",
    ))

    console.print()

    with console.status("[bold green]Running agent...", spinner="dots"):
        result = runner.run()

    if result.error:
        console.print(f"\n[bold red]Error:[/] {result.error}")

    if result.text:
        console.print(Panel(result.text, title="[bold]Response[/]", border_style="green"))

    # Stats
    console.print()
    stats = Table(show_header=False, box=None, padding=(0, 2))
    stats.add_column(style="dim")
    stats.add_column()
    stats.add_row("Tokens", f"{result.input_tokens:,} in / {result.output_tokens:,} out")
    stats.add_row("Tool rounds", str(result.tool_rounds))
    stats.add_row("Cost", f"${result.cost_usd:.4f}")
    stats.add_row("Duration", f"{result.duration_seconds:.1f}s")
    console.print(stats)


def _start_daemon(runner, run_immediately: bool):
    """Start agent as a daemon with scheduled execution."""
    from flux.scheduler import AgentScheduler
    from flux.logging import setup_logging

    config = runner.agent_config

    if not config.schedule:
        console.print("[bold red]Error:[/] No schedule defined in agent config. Use 'flux start' without -d for one-time run.")
        raise SystemExit(1)

    # Setup file logging for daemon
    setup_logging(
        level="INFO",
        log_format="text",
        log_file=runner.log_file,
    )

    console.print(f"[bold green]Starting daemon:[/] {config.name}")
    console.print(f"  Schedule: {config.schedule}")
    console.print(f"  Log: {runner.log_file}")
    console.print(f"  PID file: {runner.pid_file}")
    if run_immediately:
        console.print("  [dim]Running immediately before schedule starts[/]")
    console.print()
    console.print("[dim]Press Ctrl+C to stop[/]")

    scheduler = AgentScheduler(runner, cron_expr=config.schedule)
    try:
        scheduler.start(run_immediately=run_immediately)
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Stopped.[/]")
    except SystemExit:
        pass


@cli.command()
@click.argument("name")
def stop(name: str):
    """Stop a running agent by name."""
    import signal as sig

    agents_dir = os.path.join(os.path.expanduser("~"), ".flux", "agents", name)
    pid_file = os.path.join(agents_dir, "agent.pid")

    if not os.path.exists(pid_file):
        console.print(f"[bold red]Agent '{name}' is not running[/]")
        raise SystemExit(1)

    try:
        with open(pid_file, "r") as f:
            pid = int(f.read().strip())

        os.kill(pid, sig.SIGTERM)
        console.print(f"[bold green]Stopped:[/] {name} (PID {pid})")

        # Clean up PID file
        try:
            os.remove(pid_file)
        except OSError:
            pass
    except ProcessLookupError:
        console.print(f"[bold yellow]Agent '{name}' was not running (stale PID file removed)[/]")
        try:
            os.remove(pid_file)
        except OSError:
            pass
    except ValueError:
        console.print(f"[bold red]Invalid PID file for '{name}'[/]")
        raise SystemExit(1)


@cli.command(name="list")
def list_agents():
    """List running agents."""
    from flux.runner import AgentRunner

    running = AgentRunner.list_running()

    if not running:
        console.print("[dim]No agents running.[/]")
        return

    table = Table(title="Running Agents")
    table.add_column("Name", style="cyan")
    table.add_column("PID", style="green")

    for agent in running:
        table.add_row(agent["name"], str(agent["pid"]))

    console.print(table)


@cli.command()
@click.argument("name")
@click.option("-n", "--lines", default=50, help="Number of lines to show")
@click.option("-f", "--follow", is_flag=True, help="Follow log output (tail -f)")
def logs(name: str, lines: int, follow: bool):
    """View agent logs."""
    log_file = os.path.join(os.path.expanduser("~"), ".flux", "agents", name, "agent.log")

    if not os.path.exists(log_file):
        console.print(f"[dim]No logs found for '{name}'[/]")
        return

    if follow:
        # Follow mode - read and then watch for changes
        console.print(f"[dim]Following {log_file} (Ctrl+C to stop)[/]")
        import time

        with open(log_file, "r", encoding="utf-8") as f:
            # Show last N lines first
            all_lines = f.readlines()
            for line in all_lines[-lines:]:
                console.print(line.rstrip())

            try:
                while True:
                    line = f.readline()
                    if line:
                        console.print(line.rstrip())
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                console.print("\n[dim]Stopped following.[/]")
    else:
        with open(log_file, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        for line in all_lines[-lines:]:
            console.print(line.rstrip())


@cli.command()
@click.argument("name")
def cost(name: str):
    """View agent cost summary."""
    cost_file = os.path.join(os.path.expanduser("~"), ".flux", "agents", name, "cost_history.jsonl")

    if not os.path.exists(cost_file):
        console.print(f"[dim]No cost data for '{name}'[/]")
        return

    import json
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    total_cost = 0.0
    total_runs = 0
    today_cost = 0.0
    today_runs = 0
    total_tokens_in = 0
    total_tokens_out = 0

    with open(cost_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                total_cost += record.get("cost_usd", 0.0)
                total_runs += 1
                total_tokens_in += record.get("input_tokens", 0)
                total_tokens_out += record.get("output_tokens", 0)
                if record.get("timestamp", "").startswith(today):
                    today_cost += record.get("cost_usd", 0.0)
                    today_runs += 1
            except json.JSONDecodeError:
                continue

    table = Table(title=f"Cost Summary: {name}", show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Today", f"${today_cost:.4f} ({today_runs} runs)")
    table.add_row("Total", f"${total_cost:.4f} ({total_runs} runs)")
    table.add_row("Tokens", f"{total_tokens_in:,} in / {total_tokens_out:,} out")

    console.print(table)


@cli.command()
@click.argument("name")
def halt(name: str):
    """Halt an agent immediately (emergency stop)."""
    data_dir = os.path.join(os.path.expanduser("~"), ".flux", "agents", name)
    if not os.path.exists(data_dir):
        console.print(f"[bold red]Unknown agent: {name}[/]")
        raise SystemExit(1)
    halt_file = os.path.join(data_dir, "emergency_stop")
    with open(halt_file, "w", encoding="utf-8") as f:
        from datetime import datetime as _dt
        f.write(_dt.now().isoformat())
    console.print(f"[bold red]Halted:[/] {name}")
    console.print("[dim]Next pre_check will block until 'flux resume'.[/]")


@cli.command()
@click.argument("name")
def resume(name: str):
    """Resume a halted agent (clears emergency stop)."""
    halt_file = os.path.join(
        os.path.expanduser("~"), ".flux", "agents", name, "emergency_stop"
    )
    if not os.path.exists(halt_file):
        console.print(f"[dim]Agent '{name}' is not halted[/]")
        return
    os.remove(halt_file)
    console.print(f"[bold green]Resumed:[/] {name}")


@cli.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("-d", "--daemon", is_flag=True, help="Run watchdog as background daemon")
@click.option("--interval", default=60, type=int, help="Health check interval in seconds")
def watch(file: str, daemon: bool, interval: int):
    """Watch an agent daemon and auto-restart on failure."""
    import subprocess
    from flux.runner import AgentRunner
    from flux.watchdog import AgentWatchdog
    from flux.logging import setup_logging

    try:
        runner = AgentRunner(file)
    except Exception as e:
        console.print(f"[bold red]Error loading config:[/] {e}")
        raise SystemExit(1)

    existing = AgentWatchdog.watchdog_pid_for(runner.name)
    if existing:
        console.print(f"[bold yellow]Watchdog for '{runner.name}' already running (PID {existing})[/]")
        raise SystemExit(1)

    if daemon:
        # Spawn detached subprocess running this same command without -d
        cmd = [sys.executable, "-m", "flux.cli", "watch", file, "--interval", str(interval)]
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        import time as _t
        _t.sleep(1)
        console.print(f"[bold green]Watchdog started:[/] {runner.name} (PID {proc.pid})")
        console.print(f"  Check interval: {interval}s")
        console.print(f"  Events: {runner.events_file}")
        return

    # Foreground mode
    watchdog_log = os.path.join(runner.data_dir, "watchdog.log")
    setup_logging(level="INFO", log_format="text", log_file=watchdog_log)

    console.print(f"[bold green]Watching:[/] {runner.name}")
    console.print(f"  Check interval: {interval}s")
    console.print(f"  Events: {runner.events_file}")
    console.print("[dim]Press Ctrl+C to stop[/]")

    wd = AgentWatchdog(runner, check_interval=interval)
    try:
        wd.watch_forever()
    except KeyboardInterrupt:
        console.print("\n[bold yellow]Watchdog stopped.[/]")


@cli.command()
@click.argument("name")
def unwatch(name: str):
    """Stop the watchdog for an agent."""
    import signal as sig
    from flux.watchdog import AgentWatchdog

    pid = AgentWatchdog.watchdog_pid_for(name)
    if pid is None:
        console.print(f"[bold red]No watchdog running for '{name}'[/]")
        raise SystemExit(1)

    try:
        os.kill(pid, sig.SIGTERM)
        console.print(f"[bold green]Watchdog stopped:[/] {name} (PID {pid})")
    except ProcessLookupError:
        console.print(f"[bold yellow]Watchdog for '{name}' was not running[/]")


@cli.command()
@click.argument("name")
def status(name: str):
    """Show agent + watchdog health status."""
    import json
    from flux.watchdog import AgentWatchdog

    data_dir = os.path.join(os.path.expanduser("~"), ".flux", "agents", name)
    pid_file = os.path.join(data_dir, "agent.pid")
    heartbeat_file = os.path.join(data_dir, "heartbeat.json")

    if not os.path.exists(data_dir):
        console.print(f"[dim]Unknown agent: {name}[/]")
        raise SystemExit(1)

    # Agent process status
    agent_pid = None
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                agent_pid = int(f.read().strip())
            os.kill(agent_pid, 0)
        except (ValueError, OSError):
            agent_pid = None

    # Watchdog status
    watchdog_pid = AgentWatchdog.watchdog_pid_for(name)

    # Heartbeat
    hb = {}
    if os.path.exists(heartbeat_file):
        try:
            with open(heartbeat_file, "r", encoding="utf-8") as f:
                hb = json.load(f)
        except (OSError, json.JSONDecodeError):
            pass

    table = Table(title=f"Status: {name}", show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(style="bold")
    table.add_row("Agent process", f"[green]running (PID {agent_pid})[/]" if agent_pid else "[red]stopped[/]")
    table.add_row("Watchdog", f"[green]running (PID {watchdog_pid})[/]" if watchdog_pid else "[dim]none[/]")
    table.add_row("Last run", str(hb.get("last_run_at") or "-"))
    table.add_row("Last status", str(hb.get("last_run_status") or "-"))
    table.add_row("Next run", str(hb.get("next_run_at") or "-"))
    table.add_row("Consecutive failures", str(hb.get("consecutive_failures", 0)))
    table.add_row("Total runs", str(hb.get("total_runs", 0)))
    last_error = hb.get("last_error")
    if last_error:
        table.add_row("Last error", f"[red]{last_error}[/]")

    console.print(table)


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
@click.option("--port", default=8000, type=int, help="Bind port (default 8000)")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev only)")
def serve(host: str, port: int, reload: bool):
    """Start the Flux web API (FastAPI + SQLAlchemy)."""
    try:
        import uvicorn
    except ImportError:
        console.print("[bold red]Missing dependency:[/] install with [cyan]pip install 'flux-agent[api]'[/]")
        raise SystemExit(1)

    console.print(f"[bold green]Starting Flux API:[/] http://{host}:{port}")
    console.print("[dim]Press Ctrl+C to stop[/]")
    uvicorn.run("flux.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
