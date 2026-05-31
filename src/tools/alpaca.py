import os
from dotenv import load_dotenv
import weave
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

load_dotenv()

ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")


def _alpaca_client() -> TradingClient:
    return TradingClient(
        ALPACA_API_KEY,
        ALPACA_SECRET_KEY,
        base_url=ALPACA_BASE_URL,
    )


def _to_dict(obj):
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return obj.__dict__
    return obj


@weave.op()
def get_account() -> dict:
    """Get Alpaca paper account info."""
    account = _alpaca_client().get_account()
    return _to_dict(account)


@weave.op()
def execute_trade(
    ticker: str,
    side: str,  # "buy" or "sell"
    notional_usd: float,
    rationale: str,
) -> dict:
    """
    Execute a paper trade on Alpaca.
    Uses notional (dollar amount) ordering so we don't need to calculate shares.
    """
    order_request = MarketOrderRequest(
        symbol=ticker,
        notional=str(round(notional_usd, 2)),
        side=OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL,
        type=OrderType.MARKET,
        time_in_force=TimeInForce.DAY,
    )

    try:
        order = _alpaca_client().submit_order(order_data=order_request)
        return {
            "success": True,
            "order_id": getattr(order, "id", None),
            "ticker": ticker,
            "side": side,
            "notional_usd": notional_usd,
            "status": getattr(order, "status", None),
            "rationale": rationale,
        }
    except Exception as exc:
        return {
            "success": False,
            "error": str(exc),
            "ticker": ticker,
            "side": side,
            "notional_usd": notional_usd,
        }


@weave.op()
def get_positions() -> list:
    """Get current open positions."""
    positions = _alpaca_client().get_positions()
    return [_to_dict(position) for position in positions]
