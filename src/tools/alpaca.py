import os
import requests
from dotenv import load_dotenv
import weave

load_dotenv()

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
    """Get Alpaca paper account info."""
    r = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=_headers())
    r.raise_for_status()
    return r.json()


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
    """Get current open positions."""
    r = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=_headers())
    r.raise_for_status()
    return r.json()
