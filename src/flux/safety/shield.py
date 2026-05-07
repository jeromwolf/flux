"""Flux Safety Shield - Budget tracking, circuit breaker, and cost calculation.

Combines cost calculation (from model pricing data) with runtime safety:
- BudgetTracker: per-run, daily, and monthly spending limits
- CircuitBreaker: trips on repeated LLM call failures
- SafetyShield: unified pre-check before every LLM call

Usage:
    from flux.safety.shield import SafetyShield, calculate_cost

    shield = SafetyShield(per_run=0.10, daily=1.00, monthly=10.00)
    shield.start_run()

    ok, reason = shield.pre_check(estimated_cost=0.003)
    if ok:
        # make LLM call
        result = calculate_cost("claude-sonnet-4-20250514", 1000, 500)
        shield.record_success(result.total_cost_usd)
    else:
        shield.record_failure()
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from flux.logging import get_logger

logger = get_logger("safety.shield")


# ============================================================
# Model Pricing & Cost Calculation
# ============================================================

# Pricing: USD per 1M tokens
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic (Claude 4.5/4.6)
    "claude-sonnet-4-6-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.0},
    "claude-opus-4-6-20250514": {"input": 15.0, "output": 75.0},
    # Anthropic (legacy aliases)
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-20250514": {"input": 0.80, "output": 4.0},
    "claude-opus-4-20250514": {"input": 15.0, "output": 75.0},
    # OpenAI
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.6},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    # Google
    "gemini-2.5-flash": {"input": 0.15, "output": 0.6},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
}


@dataclass
class CostResult:
    """Cost calculation result"""

    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float


def get_model_pricing(model: str) -> Optional[dict[str, float]]:
    """Return pricing info for a model. Returns None if not found."""
    # Exact match
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]

    # Partial match (model_key in input or input in model_key)
    model_lower = model.lower()
    for model_key, pricing in MODEL_PRICING.items():
        key_lower = model_key.lower()
        if key_lower in model_lower or model_lower in key_lower:
            logger.debug("Partial match: '%s' -> '%s'", model, model_key)
            return pricing

    return None


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> CostResult:
    """Calculate USD cost from model name and token counts.

    Exact model name match -> partial match -> returns 0.0 on failure.

    Args:
        model: Model name
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        CostResult instance
    """
    pricing = get_model_pricing(model)

    if pricing is None:
        logger.warning("Unregistered model: '%s' - treating cost as 0.0", model)
        return CostResult(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    input_cost = input_tokens * pricing["input"] / 1_000_000
    output_cost = output_tokens * pricing["output"] / 1_000_000

    return CostResult(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=input_cost + output_cost,
    )


def list_supported_models() -> list[str]:
    """Return sorted list of models in the pricing table."""
    return sorted(MODEL_PRICING.keys())


# ============================================================
# Budget Tracker
# ============================================================

@dataclass
class BudgetTracker:
    """Tracks spending against budget limits."""
    per_run_limit: float = 0.10
    daily_limit: float = 1.00
    monthly_limit: float = 10.00

    # Running totals
    current_run_cost: float = 0.0
    daily_cost: float = 0.0
    monthly_cost: float = 0.0

    # Timestamps
    daily_reset_date: str = ""
    monthly_reset_month: str = ""

    def __post_init__(self):
        from datetime import datetime
        now = datetime.now()
        if not self.daily_reset_date:
            self.daily_reset_date = now.strftime("%Y-%m-%d")
        if not self.monthly_reset_month:
            self.monthly_reset_month = now.strftime("%Y-%m")

    def check_budget(self, estimated_cost: float = 0.0) -> tuple[bool, str]:
        """Check if spending is within budget. Returns (allowed, reason)."""
        from datetime import datetime
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        month = now.strftime("%Y-%m")

        # Reset daily counter if new day
        if self.daily_reset_date != today:
            self.daily_cost = 0.0
            self.daily_reset_date = today

        # Reset monthly counter if new month
        if self.monthly_reset_month != month:
            self.monthly_cost = 0.0
            self.monthly_reset_month = month

        # Check limits
        if self.current_run_cost + estimated_cost > self.per_run_limit:
            return False, f"Per-run budget exceeded: ${self.current_run_cost:.4f} / ${self.per_run_limit:.2f}"
        if self.daily_cost + estimated_cost > self.daily_limit:
            return False, f"Daily budget exceeded: ${self.daily_cost:.4f} / ${self.daily_limit:.2f}"
        if self.monthly_cost + estimated_cost > self.monthly_limit:
            return False, f"Monthly budget exceeded: ${self.monthly_cost:.4f} / ${self.monthly_limit:.2f}"

        return True, "OK"

    def record_cost(self, cost: float):
        """Record a cost against all budget levels."""
        self.current_run_cost += cost
        self.daily_cost += cost
        self.monthly_cost += cost

    def reset_run(self):
        """Reset per-run counter (called at start of each agent run)."""
        self.current_run_cost = 0.0


# ============================================================
# Circuit Breaker
# ============================================================

class CircuitBreaker:
    """Circuit breaker for LLM calls - trips on repeated failures."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failure_count = 0
        self.last_failure_time: float = 0.0
        self.state: str = "closed"  # closed=normal, open=blocking, half_open=testing

    def record_success(self):
        """Record a successful call."""
        self.failure_count = 0
        self.state = "closed"

    def record_failure(self):
        """Record a failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"Circuit breaker OPEN after {self.failure_count} failures")

    def can_proceed(self) -> tuple[bool, str]:
        """Check if a call is allowed."""
        if self.state == "closed":
            return True, "OK"

        if self.state == "open":
            elapsed = time.time() - self.last_failure_time
            if elapsed >= self.recovery_timeout:
                self.state = "half_open"
                return True, "Testing recovery"
            return False, f"Circuit breaker open. Recovery in {self.recovery_timeout - elapsed:.0f}s"

        # half_open - allow one test call
        return True, "Half-open test"


# ============================================================
# Safety Shield (Unified)
# ============================================================

class SafetyShield:
    """Combined safety layer: budget tracking + circuit breaker."""

    def __init__(self, per_run: float = 0.10, daily: float = 1.00, monthly: float = 10.00):
        self.budget = BudgetTracker(
            per_run_limit=per_run,
            daily_limit=daily,
            monthly_limit=monthly,
        )
        self.circuit_breaker = CircuitBreaker()

    def pre_check(self, estimated_cost: float = 0.0) -> tuple[bool, str]:
        """Check both budget and circuit breaker before an LLM call."""
        cb_ok, cb_reason = self.circuit_breaker.can_proceed()
        if not cb_ok:
            return False, cb_reason

        budget_ok, budget_reason = self.budget.check_budget(estimated_cost)
        if not budget_ok:
            return False, budget_reason

        return True, "OK"

    def record_success(self, cost: float):
        """Record successful LLM call with cost."""
        self.budget.record_cost(cost)
        self.circuit_breaker.record_success()

    def record_failure(self):
        """Record failed LLM call."""
        self.circuit_breaker.record_failure()

    def start_run(self):
        """Reset per-run budget at start of agent run."""
        self.budget.reset_run()

    def get_status(self) -> dict:
        """Get current safety status."""
        return {
            "budget": {
                "current_run": f"${self.budget.current_run_cost:.4f} / ${self.budget.per_run_limit:.2f}",
                "daily": f"${self.budget.daily_cost:.4f} / ${self.budget.daily_limit:.2f}",
                "monthly": f"${self.budget.monthly_cost:.4f} / ${self.budget.monthly_limit:.2f}",
            },
            "circuit_breaker": {
                "state": self.circuit_breaker.state,
                "failures": self.circuit_breaker.failure_count,
            }
        }
