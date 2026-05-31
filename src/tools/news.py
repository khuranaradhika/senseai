"""
News tool.

Recent headlines from yfinance — the sentiment/catalyst signal no other input
carries. Handles the nested `content` shape (yfinance ≥ 1.x) and the older flat
shape, and degrades to an empty list on any error.
"""
import weave
import yfinance as yf


def _extract(item: dict) -> dict | None:
    # yfinance >= 1.x: fields live under item["content"]
    c = item.get("content", item)
    title = c.get("title")
    if not title:
        return None
    provider = c.get("provider") or {}
    publisher = provider.get("displayName") if isinstance(provider, dict) else None
    when = c.get("pubDate") or c.get("displayTime") or ""
    return {"title": title, "publisher": publisher or item.get("publisher") or "—", "when": (when or "")[:10]}


@weave.op()
def fetch_news(ticker: str, limit: int = 5) -> dict:
    """Return up to `limit` recent headlines + a compact summary string."""
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception:
        raw = []

    headlines = [h for h in (_extract(i) for i in raw) if h][:limit]

    if headlines:
        summary = "\n".join(f"- {h['title']} ({h['publisher']}, {h['when']})" for h in headlines)
    else:
        summary = "No recent headlines available."

    return {"headlines": headlines, "summary": summary}
