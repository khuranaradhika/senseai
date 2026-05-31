import json
import weave
from src.core.llm import call_llm_structured
from src.core.schemas import AgentFinding, Vote, MarketData


@weave.op()
def risk_agent(
    ticker: str,
    query: str,
    market_data: MarketData,
) -> AgentFinding:
    """
    Risk agent: independently assesses tail risks, volatility, and position sizing.
    Votes based on risk-adjusted perspective, not directional thesis.
    """
    system = """You are the Risk Manager on an AI investment committee.
Your job is NOT to have a directional view — it's to assess tail risks,
volatility, liquidity, and whether the risk/reward justifies a position.
You vote BUY only if risk is manageable, HOLD if uncertain, SELL if risk is severe.
Respond ONLY in valid JSON. No markdown, no preamble."""

    user = f"""
Ticker: {ticker}
Query: {query}
Market Data: {market_data.summary}

Assess the risk profile. Respond with a JSON object:
{{
  "thesis": "risk assessment summary in 2-3 sentences",
  "key_points": ["risk 1", "risk 2", "risk 3"],
  "max_recommended_position_pct": 0.0-1.0,
  "confidence": 0.0-1.0,
  "vote": "BUY" or "HOLD" or "SELL"
}}
"""

    raw = call_llm_structured(system=system, user=user, agent_name="risk_agent")
    data = json.loads(raw)

    return AgentFinding(
        agent_name="Risk Manager",
        thesis=data["thesis"],
        key_points=data["key_points"],
        confidence=float(data["confidence"]),
        vote=Vote(data["vote"]),
        supporting_data={
            "max_position_pct": data.get("max_recommended_position_pct", 0.5)
        },
    )
