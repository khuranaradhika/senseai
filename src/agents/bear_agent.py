import json
import weave
from src.core.llm import call_llm_structured
from src.core.schemas import AgentFinding, Vote, MarketData


@weave.op()
def bear_agent(
    ticker: str,
    query: str,
    market_data: MarketData,
    bull_thesis: str = "",  # populated in round 2
) -> AgentFinding:
    """
    Bear agent: builds the strongest possible case against going long.
    In round 2, receives bull thesis and rebuts it.
    """
    is_rebuttal = bool(bull_thesis)

    system = """You are the Bear analyst on an AI investment committee.
Your job is to build the strongest possible case for caution — SELL or HOLD.
Identify overvaluation, risks, macro headwinds, and structural problems.
Be specific and cite the data provided.
Respond ONLY in valid JSON. No markdown, no preamble."""

    if is_rebuttal:
        user = f"""
Ticker: {ticker}
Query: {query}
Market Data: {market_data.summary}

The Bull analyst argued:
{bull_thesis}

Respond with a JSON object:
{{
  "thesis": "your overall bear thesis in 2-3 sentences",
  "key_points": ["point 1", "point 2", "point 3"],
  "rebuttal": "direct rebuttal to the bull's specific arguments",
  "confidence": 0.0-1.0,
  "vote": "SELL" or "HOLD" or "BUY"
}}
"""
    else:
        user = f"""
Ticker: {ticker}
Query: {query}
Market Data: {market_data.summary}

Build your initial bear thesis. Respond with a JSON object:
{{
  "thesis": "your overall bear thesis in 2-3 sentences",
  "key_points": ["point 1", "point 2", "point 3"],
  "confidence": 0.0-1.0,
  "vote": "SELL" or "HOLD" or "BUY"
}}
"""

    raw = call_llm_structured(system=system, user=user, agent_name="bear_agent")
    data = json.loads(raw)

    return AgentFinding(
        agent_name="Bear Analyst",
        thesis=data["thesis"],
        key_points=data["key_points"],
        confidence=float(data["confidence"]),
        vote=Vote(data["vote"]),
        rebuttal=data.get("rebuttal"),
    )
