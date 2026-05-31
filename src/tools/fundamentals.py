"""
Fundamentals tool.

Pulls valuation, growth, profitability, and balance-sheet signals from yfinance —
the inputs that matter for MEDIUM/LONG/VERY_LONG horizons (and that the one-line
price summary never carried). Degrades gracefully: any field yfinance omits shows
as 'n/a' rather than erroring, so a run never breaks on a missing metric.
"""
from typing import Optional

import weave
import yfinance as yf


def _num(x, suffix: str = "", scale: float = 1.0, dp: int = 2) -> str:
    try:
        if x is None:
            return "n/a"
        return f"{float(x) * scale:.{dp}f}{suffix}"
    except (TypeError, ValueError):
        return "n/a"


@weave.op()
def fetch_fundamentals(ticker: str) -> dict:
    """Structured fundamentals + a compact human-readable summary."""
    try:
        info = yf.Ticker(ticker).info
    except Exception:
        info = {}

    data = {
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "peg_ratio": info.get("trailingPegRatio") or info.get("pegRatio"),
        "price_to_book": info.get("priceToBook"),
        "profit_margin": info.get("profitMargins"),
        "operating_margin": info.get("operatingMargins"),
        "revenue_growth": info.get("revenueGrowth"),
        "earnings_growth": info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth"),
        "debt_to_equity": info.get("debtToEquity"),
        "return_on_equity": info.get("returnOnEquity"),
        "dividend_yield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "recommendation": info.get("recommendationKey"),
        "analyst_count": info.get("numberOfAnalystOpinions"),
        "target_mean_price": info.get("targetMeanPrice"),
    }

    summary = (
        f"Valuation — trailing P/E {_num(data['trailing_pe'])}, "
        f"forward P/E {_num(data['forward_pe'])}, PEG {_num(data['peg_ratio'])}, "
        f"P/B {_num(data['price_to_book'])}. "
        f"Growth — revenue {_num(data['revenue_growth'], '%', 100)}, "
        f"earnings {_num(data['earnings_growth'], '%', 100)}. "
        f"Profitability — net margin {_num(data['profit_margin'], '%', 100)}, "
        f"ROE {_num(data['return_on_equity'], '%', 100)}. "
        f"Balance sheet — debt/equity {_num(data['debt_to_equity'])}. "
        f"Beta {_num(data['beta'])}. "
        f"Analysts — {data['recommendation'] or 'n/a'} "
        f"(n={data['analyst_count'] or 'n/a'}), target ${_num(data['target_mean_price'])}."
    )
    data["summary"] = summary
    return data
