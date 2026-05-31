"""
Deterministic pre-trade guardrails.

These checks are enforced in *code*, never delegated to an LLM prompt. No order
reaches Alpaca unless every applicable check passes. `evaluate()` is a pure
function (the caller supplies account/positions/clock), so it is fully unit
-testable without network access; `gather_inputs()` does the live fetching.
"""
from typing import Optional

from pydantic import BaseModel

from src.core.config import CONFIG, Config


class GuardrailCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class GuardrailDecision(BaseModel):
    approved: bool
    side: Optional[str] = None          # "buy" | "sell" | None
    notional_usd: float = 0.0
    blocked_by: Optional[str] = None    # name of first failing check
    checks: list[GuardrailCheck] = []


_DIRECTION_TO_SIDE = {"BUY": "buy", "SELL": "sell"}


def evaluate(
    *,
    ticker: str,
    direction: str,                     # "BUY" | "SELL" | "HOLD"
    conviction: float,
    avg_confidence: float,
    proposed_notional: float,
    account: dict,
    positions: list,
    clock: dict,
    daily_trade_count: int,
    config: Config = CONFIG,
) -> GuardrailDecision:
    checks: list[GuardrailCheck] = []

    def add(name: str, passed: bool, detail: str) -> bool:
        checks.append(GuardrailCheck(name=name, passed=passed, detail=detail))
        return passed

    # 1. Actionable direction — HOLD never trades.
    actionable = add(
        "actionable_direction",
        direction in _DIRECTION_TO_SIDE,
        f"direction={direction}" + ("" if direction in _DIRECTION_TO_SIDE else " → no order"),
    )

    # 2. Confidence gate (the limit that was previously only advisory).
    add(
        "confidence_gate",
        conviction >= config.conviction_min and avg_confidence >= config.avg_conf_min,
        f"conviction={conviction:.2f} (≥{config.conviction_min}), "
        f"avg_conf={avg_confidence:.2f} (≥{config.avg_conf_min})",
    )

    # 3. Market hours.
    add(
        "market_open",
        bool(clock.get("is_open", False)),
        "market open" if clock.get("is_open") else "market closed",
    )

    # 4. Daily trade cap.
    add(
        "daily_trade_cap",
        daily_trade_count < config.max_daily_trades,
        f"{daily_trade_count}/{config.max_daily_trades} trades today",
    )

    # 5. No duplicate/conflicting open position in this symbol.
    held = next((p for p in positions if p.get("symbol") == ticker), None)
    add(
        "no_conflicting_position",
        held is None,
        "no open position" if held is None else f"already holding {held.get('qty')} {ticker}",
    )

    # 6. Sizing — clamp to the tightest of the position/portfolio/buying-power caps.
    equity = _to_float(account.get("equity"))
    buying_power = _to_float(account.get("buying_power"))
    portfolio_cap = config.max_portfolio_pct * equity
    notional = min(proposed_notional, config.max_position_usd, portfolio_cap, buying_power)
    notional = round(max(notional, 0.0), 2)
    add(
        "sufficient_sizing",
        notional > 0,
        f"sized ${notional:.2f} (cap ${config.max_position_usd:.0f}, "
        f"{config.max_portfolio_pct:.0%} equity=${portfolio_cap:.2f}, bp=${buying_power:.2f})",
    )

    failing = next((c for c in checks if not c.passed), None)
    approved = failing is None
    return GuardrailDecision(
        approved=approved,
        side=_DIRECTION_TO_SIDE.get(direction) if approved else None,
        notional_usd=notional if approved else 0.0,
        blocked_by=None if approved else failing.name,
        checks=checks,
    )


def gather_inputs() -> dict:
    """Fetch the live account/positions/clock/daily-count fed into evaluate()."""
    from src.tools.alpaca import get_account, get_positions, get_clock, count_orders_today
    return {
        "account": get_account(),
        "positions": get_positions(),
        "clock": get_clock(),
        "daily_trade_count": count_orders_today(),
    }


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
