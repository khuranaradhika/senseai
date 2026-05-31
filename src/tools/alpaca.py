import os
import requests
import weave
from dotenv import load_dotenv

load_dotenv(override=True)

ALPACA_BASE_URL = os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")


def _headers():
    return {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        "Content-Type": "application/json",
    }


@weave.op()
def get_account() -> dict:
    r = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=_headers())
    r.raise_for_status()
    return r.json()


@weave.op()
def execute_trade(ticker: str, side: str, notional_usd: float, rationale: str) -> dict:
    """Execute a paper trade using Alpaca REST API directly (no SDK dependency)."""
    payload = {
        "symbol": ticker,
        "notional": str(round(notional_usd, 2)),
        "side": side,
        "type": "market",
        "time_in_force": "day",
    }
    r = requests.post(
        f"{ALPACA_BASE_URL}/v2/orders",
        headers=_headers(),
        json=payload,
    )
    if r.status_code in (200, 201):
        result = r.json()
        return {
            "success": True,
            "order_id": result.get("id"),
            "ticker": ticker,
            "side": side,
            "notional_usd": notional_usd,
            "status": result.get("status"),
            "rationale": rationale,
        }
    else:
        return {
            "success": False,
            "error": r.text,
            "ticker": ticker,
            "side": side,
            "notional_usd": notional_usd,
        }


@weave.op()
def get_positions() -> list:
    r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=_headers())
    r.raise_for_status()
    return r.json()


@weave.op()
def get_clock() -> dict:
    """Market clock — {'is_open': bool, 'next_open': ..., 'next_close': ...}."""
    r = requests.get(f"{ALPACA_BASE_URL}/v2/clock", headers=_headers())
    r.raise_for_status()
    return r.json()