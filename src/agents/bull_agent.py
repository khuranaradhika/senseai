import json
import weave
from src.core.llm import call_llm_structured
from src.core.schemas import AgentFinding, Vote, MarketData


@weave.op()
def bull_agent(
    ticker: str,
    query: str,
    market_data: MarketData,
    bear_thesis: str = "",  # populated in round 2
) -> AgentFinding:
    """
    Bull agent: builds the strongest possible long thesis.
    In round 2, receives bear thesis and rebuts it.
    """
    is_rebuttal = bool(bear_thesis)

    system = """You are the Bull analyst on an AI investment committee.
Your job is to build the strongest possible case for going LONG on a stock.
Be specific, cite the data provided, and be intellectually honest about risks — 
but always argue for the bull case.
Respond ONLY in valid JSON. No markdown, no preamble."""

    if is_rebuttal:
        user = f"""
Ticker: {ticker}
Query: {query}
Market Data: {market_data.summary}

The Bear analyst argued:
{bear_thesis}

Respond with a JSON object:
{{
  "thesis": "your overall bull thesis in 2-3 sentences",
  "key_points": ["point 1", "point 2", "point 3"],
  "rebuttal": "direct rebuttal to the bear's specific arguments",
  "confidence": 0.0-1.0,
  "vote": "BUY" or "HOLD" or "SELL"
}}
"""
    else:
        user = f"""
Ticker: {ticker}
Query: {query}
Market Data: {market_data.summary}

Build your initial bull thesis. Respond with a JSON object:
{{
  "thesis": "your overall bull thesis in 2-3 sentences",
  "key_points": ["point 1", "point 2", "point 3"],
  "confidence": 0.0-1.0,
  "vote": "BUY" or "HOLD" or "SELL"
}}
"""

    raw = call_llm_structured(system=system, user=user, agent_name="bull_agent")
    data = json.loads(raw)

    return AgentFinding(
        agent_name="Bull Analyst",
        thesis=data["thesis"],
        key_points=data["key_points"],
        confidence=float(data["confidence"]),
        vote=Vote(data["vote"]),
        rebuttal=data.get("rebuttal"),
    )
