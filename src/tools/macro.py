"""
Macro tool.

Top-down regime signals the Macro Strategist needs: broad market trend, the
volatility/fear gauge (VIX), rates (US 10Y), and the dollar. Each shows its level
plus 1-month change. Degrades gracefully per-instrument so one missing series
never breaks the brief.
"""
import weave
import yfinance as yf

# yfinance symbols → display name
_MACRO = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq",
    "^VIX": "VIX",
    "^TNX": "US 10Y yield",
    "DX-Y.NYB": "US Dollar (DXY)",
}


def _level_and_change(symbol: str, period: str = "1mo"):
    try:
        hist = yf.Ticker(symbol).history(period=period)
        if hist.empty:
            return None, None
        close = hist["Close"]
        last, first = float(close.iloc[-1]), float(close.iloc[0])
        chg = (last - first) / first * 100 if first else 0.0
        return last, chg
    except Exception:
        return None, None


@weave.op()
def fetch_macro() -> dict:
    """Macro regime snapshot + a compact summary string."""
    data: dict = {}
    parts: list[str] = []
    for symbol, name in _MACRO.items():
        level, chg = _level_and_change(symbol)
        data[name] = {"level": level, "change_1mo_pct": chg}
        if level is not None:
            parts.append(f"{name} {level:.2f} ({chg:+.1f}% 1mo)")

    data["summary"] = (
        "Macro regime (1-month): " + "; ".join(parts) + "."
        if parts else "Macro data unavailable."
    )
    return data
