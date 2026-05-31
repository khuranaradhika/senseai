"""
Sector tool.

The stock's sector/industry and its relative strength vs its sector — using the
matching SPDR sector ETF as the sector proxy (yfinance gives no clean peer list).
Compares 1-month return of the stock vs the sector ETF to show out/under
-performance. Degrades gracefully when sector or history is unavailable.
"""
import weave
import yfinance as yf

# yfinance sector label → SPDR sector ETF
_SECTOR_ETF = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Energy": "XLE",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}


def _return_1mo(symbol: str):
    try:
        hist = yf.Ticker(symbol).history(period="1mo")
        if hist.empty:
            return None
        c = hist["Close"]
        first = float(c.iloc[0])
        return (float(c.iloc[-1]) - first) / first * 100 if first else None
    except Exception:
        return None


@weave.op()
def fetch_sector(ticker: str) -> dict:
    """Sector classification + 1-month relative strength vs the sector ETF."""
    try:
        info = yf.Ticker(ticker).info
        sector, industry = info.get("sector"), info.get("industry")
    except Exception:
        sector, industry = None, None

    etf = _SECTOR_ETF.get(sector)
    stock_ret = _return_1mo(ticker)
    sector_ret = _return_1mo(etf) if etf else None
    rel = (stock_ret - sector_ret) if (stock_ret is not None and sector_ret is not None) else None

    if not sector:
        summary = "Sector data unavailable."
    else:
        summary = f"Sector: {sector}" + (f" / {industry}" if industry else "")
        if rel is not None:
            verb = "outperforming" if rel > 0 else "underperforming"
            summary += (
                f". 1mo: {ticker} {stock_ret:+.1f}% vs {sector} ({etf}) "
                f"{sector_ret:+.1f}% → {verb} by {abs(rel):.1f}pp."
            )
        else:
            summary += "."

    return {
        "sector": sector, "industry": industry, "etf": etf,
        "stock_return_1mo": stock_ret, "sector_return_1mo": sector_ret,
        "relative_pp": rel, "summary": summary,
    }
