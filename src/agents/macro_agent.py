import json
import weave
from src.core.llm import call_llm_structured
from src.core.schemas import AgentFinding, Vote, MarketData


@weave.op()
def macro_agent(
    ticker: str,
    query: str,
    market_data: MarketData,
) -> AgentFinding:
    """
    Macro agent: assesses current macro regime and whether it supports
    the trade. Considers rates, inflation, sector rotation, and market sentiment.
    """
    system = """You are the Macro Strategist on an AI investment committee.
Your job is to assess the current macro environment and whether it supports
or undermines the trade. Think about: interest rates, inflation, sector rotation,
risk-on vs risk-off sentiment, and the broader market context.
Respond ONLY in valid JSON. No markdown, no preamble."""

    user = f"""
Ticker: {ticker}
Query: {query}
Market Data: {market_data.summary}

Assess the macro environment as of May 2026. Consider:
- Current rate environment and Fed posture
- Sector-specific macro tailwinds/headwinds for {ticker}'s industry
- Risk-on vs risk-off market regime
- Any relevant geopolitical or policy factors

Respond with a JSON object:
{{
  "thesis": "macro assessment in 2-3 sentences",
  "key_points": ["factor 1", "factor 2", "factor 3"],
  "regime": "risk-on" or "risk-off" or "neutral",
  "confidence": 0.0-1.0,
  "vote": "BUY" or "HOLD" or "SELL"
}}
"""

    raw = call_llm_structured(system=system, user=user, agent_name="macro_agent")
    data = json.loads(raw)

    return AgentFinding(
        agent_name="Macro Strategist",
        thesis=data["thesis"],
        key_points=data["key_points"],
        confidence=float(data["confidence"]),
        vote=Vote(data["vote"]),
        supporting_data={"regime": data.get("regime", "neutral")},
    )
