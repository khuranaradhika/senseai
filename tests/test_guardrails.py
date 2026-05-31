from src.core.config import CONFIG
from src.core.guardrails import evaluate


def _account(equity=100_000.0, buying_power=100_000.0):
    return {"equity": str(equity), "buying_power": str(buying_power)}


OPEN = {"is_open": True}
CLOSED = {"is_open": False}


def _eval(**overrides):
    base = dict(
        ticker="NVDA",
        direction="BUY",
        conviction=0.8,
        avg_confidence=0.7,
        proposed_notional=500.0,
        account=_account(),
        positions=[],
        clock=OPEN,
        daily_trade_count=0,
    )
    base.update(overrides)
    return evaluate(**base)


def test_happy_path_approved():
    d = _eval()
    assert d.approved is True
    assert d.side == "buy"
    assert d.notional_usd == 500.0
    assert d.blocked_by is None


def test_hold_is_not_actionable():
    d = _eval(direction="HOLD")
    assert d.approved is False
    assert d.blocked_by == "actionable_direction"


def test_low_conviction_blocked():
    d = _eval(conviction=0.5)  # below 0.70
    assert d.approved is False
    assert d.blocked_by == "confidence_gate"


def test_low_avg_confidence_blocked():
    d = _eval(avg_confidence=0.4)  # below 0.60
    assert d.approved is False
    assert d.blocked_by == "confidence_gate"


def test_market_closed_blocked():
    d = _eval(clock=CLOSED)
    assert d.approved is False
    assert d.blocked_by == "market_open"


def test_daily_cap_blocked():
    d = _eval(daily_trade_count=CONFIG.max_daily_trades)
    assert d.approved is False
    assert d.blocked_by == "daily_trade_cap"


def test_conflicting_position_blocked():
    d = _eval(positions=[{"symbol": "NVDA", "qty": "10", "side": "long"}])
    assert d.approved is False
    assert d.blocked_by == "no_conflicting_position"


def test_position_clamped_to_max_position_usd():
    d = _eval(proposed_notional=999_999.0)
    assert d.approved is True
    assert d.notional_usd == CONFIG.max_position_usd


def test_position_clamped_to_portfolio_pct():
    # 10% of $5,000 equity = $500, tighter than the $1,000 hard cap
    d = _eval(proposed_notional=999_999.0, account=_account(equity=5_000.0))
    assert d.notional_usd == 500.0


def test_zero_buying_power_blocks_sizing():
    d = _eval(account=_account(buying_power=0.0))
    assert d.approved is False
    assert d.blocked_by == "sufficient_sizing"
