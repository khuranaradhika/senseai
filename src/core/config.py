"""
Central configuration — single source of truth for every threshold and model tier.

Nothing in the pipeline should hardcode a limit; import from here. Values can be
overridden by environment variables (so a demo can be tuned without code edits),
but all guardrail thresholds are *enforced in code* (see src/core/guardrails.py),
never merely suggested to an LLM in a prompt.
"""
import os
from dataclasses import dataclass


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


# ── Model tiers (W&B Inference DeepSeek IDs; verified against /v1/models) ──────
FAST_MODEL = os.getenv("FAST_MODEL", "deepseek-ai/DeepSeek-V4-Flash")   # specialists
SMART_MODEL = os.getenv("SMART_MODEL", "deepseek-ai/DeepSeek-V4-Pro")    # critic/arbiter/conviction


@dataclass(frozen=True)
class Config:
    # ── Execution gate (conservative; see plan.md) ────────────────────────────
    conviction_min: float = _env_float("CONVICTION_MIN", 0.70)
    avg_conf_min: float = _env_float("AVG_CONF_MIN", 0.60)

    # ── Critic feedback loop ──────────────────────────────────────────────────
    max_critic_rounds: int = _env_int("MAX_CRITIC_ROUNDS", 2)

    # ── Position / risk limits ────────────────────────────────────────────────
    max_position_usd: float = _env_float("MAX_POSITION_USD", 1000.0)
    max_portfolio_pct: float = _env_float("MAX_PORTFOLIO_PCT", 0.10)  # frac of equity
    max_daily_trades: int = _env_int("MAX_DAILY_TRADES", 5)

    # ── Tool use ──────────────────────────────────────────────────────────────
    max_tool_calls: int = _env_int("MAX_TOOL_CALLS", 3)  # per specialist

    # ── LLM resilience ────────────────────────────────────────────────────────
    llm_timeout_s: int = _env_int("LLM_TIMEOUT_S", 60)
    llm_max_retries: int = _env_int("LLM_MAX_RETRIES", 3)


# Importable singleton — `from src.core.config import CONFIG`
CONFIG = Config()
