"""Tests for flux.safety.shield module."""
from __future__ import annotations

import time
import pytest

from flux.safety.shield import (
    BudgetTracker,
    CircuitBreaker,
    CostResult,
    SafetyShield,
    calculate_cost,
)


# ---------------------------------------------------------------------------
# Test 1: calculate_cost with a known model (claude-haiku) returns correct CostResult
# ---------------------------------------------------------------------------

def test_calculate_cost_known_model():
    # claude-haiku-4-20250514 pricing: input $0.80 / 1M, output $4.0 / 1M
    result = calculate_cost("claude-haiku-4-20250514", input_tokens=1_000_000, output_tokens=1_000_000)

    assert isinstance(result, CostResult)
    assert result.model == "claude-haiku-4-20250514"
    assert result.input_tokens == 1_000_000
    assert result.output_tokens == 1_000_000
    assert pytest.approx(result.input_cost_usd, rel=1e-6) == 0.80
    assert pytest.approx(result.output_cost_usd, rel=1e-6) == 4.0
    assert pytest.approx(result.total_cost_usd, rel=1e-6) == 4.80


# ---------------------------------------------------------------------------
# Test 2: Unknown model returns zero costs
# ---------------------------------------------------------------------------

def test_calculate_cost_unknown_model():
    result = calculate_cost("totally-unknown-model-xyz", input_tokens=500, output_tokens=200)

    assert isinstance(result, CostResult)
    assert result.model == "totally-unknown-model-xyz"
    assert result.input_cost_usd == 0.0
    assert result.output_cost_usd == 0.0
    assert result.total_cost_usd == 0.0


# ---------------------------------------------------------------------------
# Test 3: BudgetTracker check_budget returns (True, "OK") when within limits
# ---------------------------------------------------------------------------

def test_budget_tracker_within_limits():
    tracker = BudgetTracker(per_run_limit=0.10, daily_limit=1.00, monthly_limit=10.00)
    ok, reason = tracker.check_budget(estimated_cost=0.01)

    assert ok is True
    assert reason == "OK"


# ---------------------------------------------------------------------------
# Test 4: Returns False when per_run limit exceeded
# ---------------------------------------------------------------------------

def test_budget_tracker_per_run_exceeded():
    tracker = BudgetTracker(per_run_limit=0.05, daily_limit=1.00, monthly_limit=10.00)
    # Record costs so current_run_cost is near the limit
    tracker.record_cost(0.04)

    ok, reason = tracker.check_budget(estimated_cost=0.02)  # 0.04 + 0.02 > 0.05

    assert ok is False
    assert "Per-run budget exceeded" in reason


# ---------------------------------------------------------------------------
# Test 5: Returns False when daily limit exceeded
# ---------------------------------------------------------------------------

def test_budget_tracker_daily_exceeded():
    tracker = BudgetTracker(per_run_limit=10.0, daily_limit=0.50, monthly_limit=10.00)
    tracker.record_cost(0.48)

    ok, reason = tracker.check_budget(estimated_cost=0.05)  # 0.48 + 0.05 > 0.50

    assert ok is False
    assert "Daily budget exceeded" in reason


# ---------------------------------------------------------------------------
# Test 6: Daily counter resets on new day
# ---------------------------------------------------------------------------

def test_budget_tracker_daily_reset():
    tracker = BudgetTracker(per_run_limit=10.0, daily_limit=0.50, monthly_limit=10.00)
    # Simulate having spent near limit yesterday
    tracker.daily_cost = 0.48
    tracker.daily_reset_date = "2000-01-01"  # far in the past — forces reset

    ok, reason = tracker.check_budget(estimated_cost=0.05)

    # After reset, daily_cost is 0.0 so 0.05 is within limit
    assert ok is True
    assert reason == "OK"
    assert tracker.daily_cost == 0.0


# ---------------------------------------------------------------------------
# Test 7: record_cost updates all levels
# ---------------------------------------------------------------------------

def test_budget_tracker_record_cost():
    tracker = BudgetTracker(per_run_limit=1.0, daily_limit=10.0, monthly_limit=100.0)
    tracker.check_budget()  # initialise reset dates

    tracker.record_cost(0.05)

    assert pytest.approx(tracker.current_run_cost) == 0.05
    assert pytest.approx(tracker.daily_cost) == 0.05
    assert pytest.approx(tracker.monthly_cost) == 0.05

    tracker.record_cost(0.10)

    assert pytest.approx(tracker.current_run_cost) == 0.15
    assert pytest.approx(tracker.daily_cost) == 0.15
    assert pytest.approx(tracker.monthly_cost) == 0.15


# ---------------------------------------------------------------------------
# Test 8: CircuitBreaker starts closed and allows calls
# ---------------------------------------------------------------------------

def test_circuit_breaker_closed():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

    assert cb.state == "closed"
    ok, reason = cb.can_proceed()
    assert ok is True
    assert reason == "OK"


# ---------------------------------------------------------------------------
# Test 9: CircuitBreaker opens after failure_threshold failures
# ---------------------------------------------------------------------------

def test_circuit_breaker_opens():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

    for _ in range(3):
        cb.record_failure()

    assert cb.state == "open"
    ok, reason = cb.can_proceed()
    assert ok is False
    assert "Circuit breaker open" in reason


# ---------------------------------------------------------------------------
# Test 10: CircuitBreaker transitions to half_open after recovery_timeout
# ---------------------------------------------------------------------------

def test_circuit_breaker_recovery():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)  # 50 ms

    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"

    # Wait for recovery timeout to elapse
    time.sleep(0.1)

    ok, reason = cb.can_proceed()
    assert ok is True
    assert cb.state == "half_open"


# ---------------------------------------------------------------------------
# Test 11: SafetyShield pre_check works (budget + circuit breaker combined)
# ---------------------------------------------------------------------------

def test_safety_shield_pre_check():
    shield = SafetyShield(per_run=0.10, daily=1.00, monthly=10.00)
    shield.start_run()

    ok, reason = shield.pre_check(estimated_cost=0.01)

    assert ok is True
    assert reason == "OK"


def test_safety_shield_pre_check_budget_exceeded():
    shield = SafetyShield(per_run=0.05, daily=1.00, monthly=10.00)
    shield.start_run()
    shield.record_success(0.04)  # push run cost near limit

    ok, reason = shield.pre_check(estimated_cost=0.02)  # would exceed per_run

    assert ok is False
    assert "budget exceeded" in reason.lower()


# ---------------------------------------------------------------------------
# Test 12: SafetyShield record_success updates both budget and circuit breaker
# ---------------------------------------------------------------------------

def test_safety_shield_record_success():
    shield = SafetyShield(per_run=1.0, daily=10.0, monthly=100.0)
    shield.start_run()

    # Force the circuit breaker into a non-zero failure state first
    shield.record_failure()
    assert shield.circuit_breaker.failure_count == 1

    shield.record_success(0.03)

    # Budget updated
    assert pytest.approx(shield.budget.current_run_cost) == 0.03
    assert pytest.approx(shield.budget.daily_cost) == 0.03

    # Circuit breaker reset to closed
    assert shield.circuit_breaker.state == "closed"
    assert shield.circuit_breaker.failure_count == 0


# ---------------------------------------------------------------------------
# W2: Disk persistence
# ---------------------------------------------------------------------------

def test_budget_tracker_from_disk_missing_file(tmp_path):
    """from_disk returns a fresh tracker (with the given limits) when the file is absent."""
    path = str(tmp_path / "no-such-state.json")
    tracker = BudgetTracker.from_disk(path, per_run=0.1, daily=2.0, monthly=15.0)
    assert tracker.daily_cost == 0.0
    assert tracker.monthly_cost == 0.0
    assert tracker.per_run_limit == 0.1
    assert tracker.daily_limit == 2.0
    assert tracker.monthly_limit == 15.0


def test_budget_tracker_save_and_reload(tmp_path):
    """save_to_disk -> from_disk round-trips daily and monthly cost."""
    path = str(tmp_path / "state.json")
    a = BudgetTracker(per_run_limit=0.5, daily_limit=2.0, monthly_limit=20.0)
    a.record_cost(0.25)
    a.record_cost(0.10)
    a.save_to_disk(path)

    b = BudgetTracker.from_disk(path, per_run=0.5, daily=2.0, monthly=20.0)
    assert pytest.approx(b.daily_cost) == 0.35
    assert pytest.approx(b.monthly_cost) == 0.35
    # per-run is volatile - not persisted
    assert b.current_run_cost == 0.0
    # reset markers persisted
    assert b.daily_reset_date == a.daily_reset_date
    assert b.monthly_reset_month == a.monthly_reset_month


def test_safety_shield_auto_persists(tmp_path):
    """SafetyShield.record_success writes state to disk when state_path is set."""
    state_path = str(tmp_path / "budget.json")
    shield = SafetyShield(
        per_run=1.0, daily=10.0, monthly=100.0,
        state_path=state_path,
    )
    shield.start_run()
    shield.record_success(0.07)

    # A second shield loaded from the same path picks up the accumulated daily.
    fresh = SafetyShield(
        per_run=1.0, daily=10.0, monthly=100.0,
        state_path=state_path,
    )
    assert pytest.approx(fresh.budget.daily_cost) == 0.07


# ---------------------------------------------------------------------------
# W2: Emergency stop (halt switch)
# ---------------------------------------------------------------------------

def test_safety_shield_halt_blocks_pre_check(tmp_path):
    """When the halt file is present, pre_check fails fast."""
    halt = tmp_path / "emergency_stop"
    halt.write_text("halted by test")

    shield = SafetyShield(
        per_run=10.0, daily=10.0, monthly=100.0,
        halt_path=str(halt),
    )
    shield.start_run()
    ok, reason = shield.pre_check(estimated_cost=0.0001)
    assert ok is False
    assert "Emergency stop" in reason

    # Removing the halt file restores normal flow.
    halt.unlink()
    ok, reason = shield.pre_check(estimated_cost=0.0001)
    assert ok is True


# ---------------------------------------------------------------------------
# W2: Soft threshold warnings (80% / 95%)
# ---------------------------------------------------------------------------

def test_safety_shield_warning_80_percent():
    """get_warnings returns a warning once daily usage crosses 80%."""
    shield = SafetyShield(per_run=10.0, daily=1.0, monthly=100.0)
    shield.start_run()
    # 80% of daily
    shield.budget.record_cost(0.85)

    warnings = shield.get_warnings()
    assert any("Daily budget" in w for w in warnings)


def test_safety_shield_warning_95_percent_monthly():
    """get_warnings flags monthly usage when it crosses 95%."""
    shield = SafetyShield(per_run=10.0, daily=10.0, monthly=10.0)
    shield.start_run()
    shield.budget.record_cost(9.6)

    warnings = shield.get_warnings()
    assert any("Monthly budget" in w and "9" in w for w in warnings)
