"""
Current-time grounding for the committee.

The agents otherwise have no idea what "now" is (they'd infer it from training
data), which makes horizon reasoning — especially INTRADAY — unreliable. This
provides a single, factual "now" string: today's date/weekday plus whether the
US equity market is currently open (via the Alpaca clock, with a safe fallback).
"""
from datetime import datetime, timezone


def market_status() -> str:
    """OPEN / CLOSED via Alpaca; UNKNOWN if the clock can't be reached."""
    try:
        from src.tools.alpaca import get_clock
        return "OPEN" if get_clock().get("is_open") else "CLOSED"
    except Exception:  # noqa: BLE001 — never let a clock hiccup break a run
        return "UNKNOWN"


def time_context() -> str:
    """One-line grounding fact injected into prompts."""
    now = datetime.now(timezone.utc).astimezone()
    return (
        f"CURRENT TIME: {now:%A, %Y-%m-%d %H:%M %Z}. "
        f"The US equity market is currently {market_status()}. "
        f"Reason relative to this present moment, not any assumed date."
    )
