"""
Chair — the super agent.

Two roles:
  1. ACTIVE MODERATOR: after every debate round it summarizes where the committee
     stands, flags the weakest arguments, and sets what the analysts should
     resolve next round. Its note is fed back into the next round of analysts.
  2. DECIDER: once the debate ends (unanimous after the minimum rounds, or the
     round cap is hit), it synthesizes the final call + position size — breaking
     the tie itself when the committee never converged.
"""
from typing import Literal, Optional

import weave
from pydantic import BaseModel, Field

from src.core.llm import call_typed
from src.core.schemas import AgentFinding, CommitteeConfig, DebateState, Vote


class ChairModeration(BaseModel):
    summary: str
    weak_arguments: list[str]
    focus_next: str


class ChairDecision(BaseModel):
    decision: Literal["BUY", "SELL", "HOLD"]
    rationale: str
    position_size_usd: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0, le=1.0)


def _positions(findings: list[AgentFinding]) -> str:
    return "\n".join(
        f"- {f.agent_name} [{f.vote.value}, conf {f.confidence:.0%}]"
        f"{' (changed)' if f.changed_vote else ''}: {f.thesis}"
        for f in findings
    )


@weave.op()
def chair_moderate(
    state: DebateState,
    round_findings: list[AgentFinding],
    round_num: int,
    directive: str = "",
    time_ctx: str = "",
    research: str = "",
) -> str:
    """Active moderation after a round. Returns a guidance note for the next round."""
    system = """You are the Chair of an AI investment committee moderating a debate.
You do NOT vote. Each round: (1) state the core DISAGREEMENT and the single
strongest argument on EACH side, (2) name the weakest/unsupported claims on ANY
side, and (3) pose the specific question(s) that would actually resolve the
disagreement next round — keeping the user's time horizon central.

Protect independent thinking. The NUMBER of analysts on a side is NOT evidence and
must never be used as pressure. Do not tell anyone to 'join' the majority. When a
minority view is well-supported, push the MAJORITY to rebut its best point rather
than asking the minority to fold. Your goal is the strongest reasoning, not a quick
consensus. Be specific and concise. Respond ONLY with valid JSON."""
    mandate = f"\nUser mandate:\n{directive}\n" if directive else ""
    clock = f"{time_ctx}\n" if time_ctx else ""
    research_block = f"\nResearch:\n{research}\n" if research else ""

    user = f"""{clock}Ticker: {state.ticker}
Query: {state.query}
Market Data: {state.market_data.summary}
{research_block}{mandate}
Round {round_num} positions:
{_positions(round_findings)}

Respond with a JSON object:
{{
  "summary": "the core disagreement + the strongest argument on EACH side (do NOT cite how many analysts are on each side)",
  "weak_arguments": ["thin / unsupported claims on ANY side"],
  "focus_next": "the specific question(s) that would resolve the disagreement — directed at whichever side must answer it (majority or minority)"
}}"""

    mod = call_typed(system, user, ChairModeration, agent_name="chair_moderator", smart=True)
    weak = "; ".join(mod.weak_arguments) if mod.weak_arguments else "none flagged"
    return f"{mod.summary} Weak points: {weak}. Focus next: {mod.focus_next}"


@weave.op()
def chair_decide(
    state: DebateState,
    config: CommitteeConfig,
    consensus_vote: Optional[Vote],
    directive: str = "",
    time_ctx: str = "",
    research: str = "",
) -> tuple[Vote, str, float, float]:
    """
    Final decision. If `consensus_vote` is set the committee was unanimous and the
    Chair ratifies it with a rationale + sizing. Otherwise the debate hit the round
    cap without converging and the Chair must break the tie.
    """
    final = state.transcript[-1] if state.transcript else []
    mandate = f"\nUser mandate:\n{directive}\n" if directive else ""
    clock = f"{time_ctx}\n" if time_ctx else ""
    research_block = f"\nResearch:\n{research}\n" if research else ""

    if consensus_vote is not None:
        situation = (
            f"The committee reached UNANIMOUS consensus on {consensus_vote.value} "
            f"after {state.rounds_run} rounds. Ratify it: synthesize the rationale "
            f"and set a position size proportional to conviction."
        )
    else:
        situation = (
            f"After {state.rounds_run} rounds the committee did NOT converge. "
            f"You must break the tie and cast the deciding vote."
        )

    system = """You are the Chair of an AI investment committee. The debate is over.
Make the final call and set a position size proportional to the strength of
conviction (smaller when the committee is divided or evidence is mixed).
Respond ONLY with valid JSON."""

    user = f"""{clock}Ticker: {state.ticker}
Query: {state.query}
Market Data: {state.market_data.summary}
{research_block}{mandate}
{situation}

Final analyst positions:
{_positions(final)}

Max position size allowed: ${config.max_position_usd:.2f}

Respond with a JSON object:
{{
  "decision": "BUY" or "SELL" or "HOLD",
  "rationale": "2-3 sentence synthesis of the decisive arguments",
  "position_size_usd": dollar amount between 0 and {config.max_position_usd:.0f},
  "confidence": 0.0-1.0
}}"""

    out = call_typed(system, user, ChairDecision, agent_name="chair_decider", smart=True)
    size = min(float(out.position_size_usd), config.max_position_usd)
    decision = consensus_vote if consensus_vote is not None else Vote(out.decision)
    return decision, out.rationale, size, out.confidence
