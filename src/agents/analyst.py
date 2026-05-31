"""
Data-driven committee analysts.

Unlike the old bull/bear advocates (which were prompted to *always* argue their
side), these four analysts each reason through a domain lens but reach an HONEST
vote grounded in the data — and they are explicitly allowed, even encouraged, to
change their vote across rounds when another analyst's evidence is stronger.

Each round an analyst sees: the market data, the latest positions of every other
analyst, the Chair's moderation note, and its own previous position. It returns
an updated thesis + vote + confidence.
"""
from typing import Literal, Optional

import weave
from pydantic import BaseModel, Field

from src.core.llm import call_typed
from src.core.schemas import AgentFinding, MarketData, Vote


class AnalystOutput(BaseModel):
    thesis: str
    key_points: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    vote: Literal["BUY", "SELL", "HOLD"]


# name → analytical lens. The lens shapes *what they weigh*, not *what they must conclude*.
PERSONAS: dict[str, str] = {
    "Bull Analyst": (
        "You specialize in the UPSIDE case: growth catalysts, TAM expansion, "
        "competitive moat, earnings momentum, and positive technicals. You look "
        "hardest for reasons to be long — but you are an analyst, not a cheerleader."
    ),
    "Bear Analyst": (
        "You specialize in the DOWNSIDE case: overvaluation, decelerating growth, "
        "competition, margin pressure, and negative technicals. You look hardest "
        "for reasons to be cautious — but you are an analyst, not a permabear."
    ),
    "Risk Manager": (
        "You specialize in RISK: volatility, drawdown potential, position sizing, "
        "liquidity, and technical signals (RSI, MACD, 52-week position). You judge "
        "whether the risk/reward justifies a position at all."
    ),
    "Macro Strategist": (
        "You specialize in the MACRO regime: interest rates, liquidity, sector "
        "rotation, the broad market trend, and how top-down conditions help or hurt "
        "this name right now."
    ),
}

_SYSTEM_TEMPLATE = """You are the {name} on an AI investment committee.
{lens}

You are a DATA-DRIVEN analyst, not an advocate. Form your vote from the evidence:
- If the data supports your usual lens, argue it with specifics.
- If the data contradicts your lens, say so honestly and vote accordingly.
- Weigh the FULL picture — price action & technicals, valuation, growth,
  profitability, balance sheet, sector relative strength, macro regime, and news.
  Do NOT over-index on any single metric. In particular, a high trailing P/E is
  NOT by itself bearish for a fast-growing company: judge valuation against growth
  (forward P/E, PEG), margins, and durability — and weight valuation far less for
  short horizons than for long ones.
- Each round you see the other analysts' arguments and the Chair's guidance.
  UPDATE your view ONLY when a specific argument or data point genuinely defeats
  your reasoning — NEVER just because others agree with each other. The number of
  analysts on a side is NOT evidence. A well-reasoned MINORITY view is more valuable
  to the committee than capitulating for false consensus: hold your ground when the
  data is on your side, and rebut the strongest opposing argument head-on. (Equally,
  don't be stubborn against a genuinely better argument.)
- Calibrate confidence to the strength of the evidence, not to your conviction.

Respond ONLY with a valid JSON object. No markdown, no preamble."""


def _format_peers(latest: list[AgentFinding], me: str) -> str:
    others = [f for f in latest if f.agent_name != me]
    if not others:
        return "(This is round 1 — no other arguments yet.)"
    return "\n".join(
        f"- {f.agent_name} [{f.vote.value}, conf {f.confidence:.0%}]: {f.thesis}"
        for f in others
    )


@weave.op()
def analyst_round(
    name: str,
    ticker: str,
    query: str,
    market_data: MarketData,
    round_num: int,
    latest_positions: list[AgentFinding],
    chair_note: Optional[str],
    my_previous: Optional[AgentFinding],
    directive: str = "",
    time_ctx: str = "",
    research: str = "",
) -> AgentFinding:
    """Run one debate round for a single analyst."""
    system = _SYSTEM_TEMPLATE.format(name=name, lens=PERSONAS[name])
    mandate = f"\nMANDATE (shapes how you weigh the data):\n{directive}\n" if directive else ""
    clock = f"{time_ctx}\n" if time_ctx else ""
    research_block = f"\nResearch:\n{research}\n" if research else ""

    if round_num == 1:
        context = "Form your initial, data-grounded position."
    else:
        prev = (
            f"Your previous position: [{my_previous.vote.value}, "
            f"conf {my_previous.confidence:.0%}] {my_previous.thesis}"
            if my_previous else "(no prior position)"
        )
        context = f"""This is round {round_num}. Reconsider in light of the debate.

{prev}

Other analysts' latest positions:
{_format_peers(latest_positions, name)}

Chair's guidance for this round:
{chair_note or "(none)"}

Engage their strongest point directly. Change your vote only if a specific
argument actually defeats yours — not because you'd otherwise be the lone dissenter.
A correct minority of one beats a comfortable consensus."""

    user = f"""{clock}Ticker: {ticker}
Query: {query}
Market Data: {market_data.summary}
{research_block}{mandate}
{context}

Respond with a JSON object:
{{
  "thesis": "your current thesis in 2-3 sentences, citing the data",
  "key_points": ["specific point 1", "point 2", "point 3"],
  "confidence": 0.0-1.0,
  "vote": "BUY" or "SELL" or "HOLD"
}}"""

    out = call_typed(system, user, AnalystOutput, agent_name=name, smart=False)

    changed = bool(my_previous and my_previous.vote.value != out.vote)
    return AgentFinding(
        agent_name=name,
        thesis=out.thesis,
        key_points=out.key_points,
        confidence=out.confidence,
        vote=Vote(out.vote),
        round=round_num,
        changed_vote=changed,
    )
