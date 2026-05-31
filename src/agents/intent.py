"""
Query understanding (intent parser).

Turns a free-text query into a structured Intent. The most important dimension
is the TIME HORIZON, because it changes what the committee should weigh: a
2-week position is a trade (technicals, momentum, near-term catalysts) while a
20-year position is an investment (fundamentals, secular trends, durability).

Per design: horizon is NOT guessed when absent — `horizon_detected=False` so the
UI can flag it and ask. A horizon supplied via the UI dropdown is passed as
`horizon_override` and takes precedence over inference.
"""
from typing import Literal, Optional

import weave
from pydantic import BaseModel, Field

from src.core.clock import time_context
from src.core.llm import call_typed
from src.core.schemas import Intent

Bucket = Literal["INTRADAY", "SHORT", "MEDIUM", "LONG", "VERY_LONG"]

HORIZON_LABELS: dict[str, str] = {
    "INTRADAY": "intraday (about 1 day)",
    "SHORT": "short-term (days to a few weeks)",
    "MEDIUM": "medium-term (roughly 1–12 months)",
    "LONG": "long-term (about 1–5 years)",
    "VERY_LONG": "very long-term (5+ years / decades)",
}

# How each horizon changes what analysts should weigh.
HORIZON_GUIDANCE: dict[str, str] = {
    "INTRADAY": (
        "Treat this as a same-day INTRADAY trade. Weight only very short-term price "
        "action, momentum, intraday volatility, liquidity, and today's news/catalysts. "
        "Fundamentals, valuation, and multi-week trends are irrelevant over one day."
    ),
    "SHORT": (
        "Treat this as a TRADE. Weight near-term technicals (RSI, MACD, momentum, "
        "52-week position), volatility, and imminent catalysts heavily. Long-run "
        "fundamentals and valuation matter little over this window."
    ),
    "MEDIUM": (
        "Balance technicals with the earnings trajectory, sector dynamics, and "
        "catalysts likely to play out over the coming quarters. Valuation matters "
        "but secular themes are secondary."
    ),
    "LONG": (
        "Treat this as an INVESTMENT. Weight fundamentals, growth durability, "
        "competitive moat, margins, and valuation. Near-term technicals are mostly "
        "noise and should barely move your vote."
    ),
    "VERY_LONG": (
        "Treat this as a multi-year/decade INVESTMENT. Weight secular megatrends, "
        "business durability, balance-sheet strength, reinvestment runway, and "
        "management quality. Ignore short-term price action and momentum entirely."
    ),
}


class IntentOutput(BaseModel):
    horizon_bucket: Optional[Bucket] = Field(
        None, description="Only set if the query clearly implies a holding period; else null."
    )
    horizon_detail: Optional[str] = None
    direction: Optional[Literal["long", "short", "trim", "open"]] = None
    risk_tolerance: Optional[Literal["conservative", "moderate", "aggressive"]] = None
    catalysts: list[str] = []
    constraints: list[str] = []
    interpretation: str


@weave.op()
def parse_intent(query: str, ticker: str, horizon_override: Optional[str] = None) -> Intent:
    system = """You extract structured trading intent from an analyst's question.
Be conservative about the time horizon: set horizon_bucket ONLY if the query
clearly implies a holding period (e.g. 'swing trade', 'next few weeks', 'hold for
years', 'retirement'). If no horizon is stated or implied, leave horizon_bucket
null — do NOT guess. Respond ONLY with valid JSON."""

    user = f"""{time_context()}

Ticker: {ticker}
Query: "{query}"

Interpret any relative timeframes ('this week', 'before earnings') against the
current date above. Map to a JSON object:
{{
  "horizon_bucket": "INTRADAY" | "SHORT" | "MEDIUM" | "LONG" | "VERY_LONG" | null,
     // INTRADAY=~1 day, SHORT=days-weeks, MEDIUM=1-12 months, LONG=1-5 years, VERY_LONG=5+ years
  "horizon_detail": "short phrase like '~2 weeks', or null",
  "direction": "long" | "short" | "trim" | "open" | null,
  "risk_tolerance": "conservative" | "moderate" | "aggressive" | null,
  "catalysts": ["named events to weigh, e.g. 'Q3 earnings'"],
  "constraints": ["limits, e.g. 'keep exposure small'"],
  "interpretation": "one sentence restating what the user is asking"
}}"""

    out = call_typed(system, user, IntentOutput, agent_name="intent_parser", smart=True)

    bucket = horizon_override if horizon_override in HORIZON_LABELS else out.horizon_bucket
    return Intent(
        raw_query=query,
        horizon_bucket=bucket,
        horizon_detail=out.horizon_detail,
        horizon_detected=bucket is not None,
        direction=out.direction,
        risk_tolerance=out.risk_tolerance,
        catalysts=out.catalysts,
        constraints=out.constraints,
        interpretation=out.interpretation,
    )


def intent_directive(intent: Optional[Intent]) -> str:
    """Build the guidance block injected into analyst/chair prompts."""
    if intent is None:
        return ""
    lines: list[str] = []
    if intent.horizon_bucket:
        detail = f" (user said: {intent.horizon_detail})" if intent.horizon_detail else ""
        lines.append(
            f"TIME HORIZON: {HORIZON_LABELS[intent.horizon_bucket]}{detail}. "
            f"{HORIZON_GUIDANCE[intent.horizon_bucket]}"
        )
    if intent.direction:
        lines.append(f"The user is considering a {intent.direction.upper()} stance.")
    if intent.risk_tolerance:
        lines.append(f"Risk tolerance: {intent.risk_tolerance}.")
    if intent.catalysts:
        lines.append("Catalysts to weigh: " + "; ".join(intent.catalysts) + ".")
    if intent.constraints:
        lines.append("Constraints to respect: " + "; ".join(intent.constraints) + ".")
    return "\n".join(lines)
