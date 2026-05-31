from typing import Optional
import yfinance as yf
import pandas as pd
from src.core.schemas import MarketData
import weave


@weave.op()
def fetch_market_data(ticker: str) -> MarketData:
    """Fetch real market data for a ticker using yfinance."""
    stock = yf.Ticker(ticker)
    info = stock.info
    hist = stock.history(period="3mo")

    # Basic price data
    current_price = info.get("currentPrice") or info.get("regularMarketPrice", 0)
    prev_close = info.get("previousClose", current_price)
    price_change_pct = ((current_price - prev_close) / prev_close * 100) if prev_close else 0

    # RSI calculation
    rsi = _calculate_rsi(hist["Close"])

    # MACD signal
    macd_signal = _calculate_macd_signal(hist["Close"])
    # Format RSI safely (handle None)
    rsi_str = f"{rsi:.1f}" if rsi is not None else "N/A"

    # Date of the most recent price bar — tells agents how fresh the data is.
    try:
        as_of = hist.index[-1].strftime("%Y-%m-%d") if not hist.empty else None
    except Exception:
        as_of = None

    # Position within the 52-week range and volume vs average — fuller price/market
    # picture. (P/E lives in the fundamentals brief, with forward P/E + PEG context,
    # so it isn't duplicated and over-anchored here.)
    low = info.get("fiftyTwoWeekLow", 0) or 0
    high = info.get("fiftyTwoWeekHigh", 0) or 0
    range_str = f", {((current_price - low) / (high - low) * 100):.0f}% of 52w range" if high > low else ""
    vol = info.get("volume", 0) or 0
    avg_vol = info.get("averageVolume", 0) or 0
    vol_str = f"{vol/1e6:.1f}M (avg {avg_vol/1e6:.1f}M)" if avg_vol else "n/a"

    summary = (
        f"{ticker} trading at ${current_price:.2f} "
        f"({'up' if price_change_pct > 0 else 'down'} {abs(price_change_pct):.1f}% on the day). "
        f"52-week range: ${low:.2f}-${high:.2f}{range_str}. "
        f"Volume: {vol_str}. "
        f"RSI: {rsi_str}. MACD: {macd_signal}. "
        f"Market cap: ${info.get('marketCap', 0)/1e9:.1f}B. "
        f"(Price data as of {as_of or 'unknown'}.)"
    )

    return MarketData(
        as_of=as_of,
        ticker=ticker,
        current_price=current_price,
        price_change_pct=price_change_pct,
        volume=info.get("volume", 0),
        avg_volume=info.get("averageVolume", 0),
        week_52_high=info.get("fiftyTwoWeekHigh", 0),
        week_52_low=info.get("fiftyTwoWeekLow", 0),
        pe_ratio=info.get("trailingPE"),
        market_cap=info.get("marketCap"),
        rsi=rsi,
        macd_signal=macd_signal,
        summary=summary,
    )


def _calculate_rsi(prices: pd.Series, period: int = 14) -> Optional[float]:
    """Canonical RSI using Wilder's smoothing (EMA with alpha=1/period),
    matching what TradingView and most charting platforms display."""
    try:
        delta = prices.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])
    except Exception:
        return None


def _calculate_macd_signal(prices: pd.Series) -> str:
    try:
        ema12 = prices.ewm(span=12).mean()
        ema26 = prices.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        if macd.iloc[-1] > signal.iloc[-1]:
            return "bullish"
        elif macd.iloc[-1] < signal.iloc[-1]:
            return "bearish"
        return "neutral"
    except Exception:
        return "neutral"