import json
import weave
from src.core.llm import call_llm_structured
from src.core.schemas import AgentFinding, Vote, DebateState, CommitteeConfig


@weave.op()
def chair_tiebreak(
    state: DebateState,
    config: CommitteeConfig,
) -> tuple[Vote, str, float]:
    """
    Chair agent: called when vote is split 2-2.
    Reviews all findings and rebuttals, casts deciding vote,
    and determines position size.
    """
    system = """You are the Chair of an AI investment committee.
The committee is split. You must cast the deciding vote and justify it
by synthesizing all arguments. Be decisive. Set a position size proportional
to conviction level.
Respond ONLY in valid JSON. No markdown, no preamble."""

    findings_summary = "\n".join([
        f"{f.agent_name}: {f.thesis} [Vote: {f.vote.value}, Confidence: {f.confidence:.0%}]"
        for f in state.findings
    ])

    rebuttals_summary = "\n".join([
        f"{f.agent_name} rebuttal: {f.rebuttal}"
        for f in state.rebuttals
        if f.rebuttal
    ]) if state.rebuttals else "No rebuttals yet."

    vote_breakdown = {k: v.value for k, v in state.votes.items()}

    user = f"""
Ticker: {state.ticker}
Query: {state.query}

Committee findings:
{findings_summary}

Rebuttals:
{rebuttals_summary}

Current vote breakdown: {vote_breakdown}
The vote is SPLIT. You must break the tie.

Max position size allowed: ${config.max_position_usd:.2f}

Respond with a JSON object:
{{
  "decision": "BUY" or "SELL" or "HOLD",
  "rationale": "2-3 sentence explanation synthesizing the key arguments",
  "position_size_usd": dollar amount between 0 and {config.max_position_usd},
  "confidence": 0.0-1.0
}}
"""

    raw = call_llm_structured(system=system, user=user, agent_name="chair_agent", smart=True)
    data = json.loads(raw)

    return (
        Vote(data["decision"]),
        data["rationale"],
        float(data.get("position_size_usd", config.max_position_usd * 0.5)),
    )


@weave.op()
def chair_consensus(
    state: DebateState,
    config: CommitteeConfig,
    winning_vote: Vote,
    vote_counts: dict,
) -> tuple[str, float]:
    """
    Chair agent: called when there IS consensus (3:1 or 4:0).
    Synthesizes rationale and sets position size based on conviction.
    """
    system = """You are the Chair of an AI investment committee.
The committee has reached consensus. Synthesize the key arguments
into a final decision rationale and set position size proportional
to the strength of conviction.
Respond ONLY in valid JSON. No markdown, no preamble."""

    findings_summary = "\n".join([
        f"{f.agent_name}: {f.thesis} [Vote: {f.vote.value}, Confidence: {f.confidence:.0%}]"
        for f in state.findings
    ])

    user = f"""
Ticker: {state.ticker}
Query: {state.query}
Consensus vote: {winning_vote.value}
Vote breakdown: {vote_counts}

Committee findings:
{findings_summary}

Max position size: ${config.max_position_usd:.2f}

Respond with a JSON object:
{{
  "rationale": "2-3 sentence synthesis of why the committee reached this decision",
  "position_size_usd": dollar amount (higher conviction = larger position, max ${config.max_position_usd:.2f})
}}
"""

    raw = call_llm_structured(system=system, user=user, agent_name="chair_consensus", smart=True)
    data = json.loads(raw)

    return (
        data["rationale"],
        float(data.get("position_size_usd", config.max_position_usd * 0.5)),
    )