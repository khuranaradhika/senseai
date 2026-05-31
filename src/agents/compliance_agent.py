import json
import weave
from src.core.llm import call_llm_structured
from src.core.schemas import DebateState, CommitteeConfig


@weave.op()
def compliance_agent(
    state: DebateState,
    config: CommitteeConfig,
) -> tuple[bool, str, float]:
    """
    Compliance agent: final gate before execution.
    Can BLOCK a trade if risk limits are breached.
    Returns (approved, reason, adjusted_position_size).
    """
    system = """You are the Compliance Officer on an AI investment committee.
Your job is to be the last line of defense before capital is deployed.
You check: position size limits, volatility thresholds, and whether
the committee's confidence justifies the trade size.
You can approve, reduce position size, or block entirely.
Respond ONLY in valid JSON. No markdown, no preamble."""

    avg_confidence = (
        sum(f.confidence for f in state.findings + state.rebuttals)
        / max(len(state.findings + state.rebuttals), 1)
    )

    vote_counts = {}
    for v in state.votes.values():
        vote_counts[v.value] = vote_counts.get(v.value, 0) + 1

    user = f"""
Ticker: {state.ticker}
Final vote: {state.final_vote.value if state.final_vote else 'UNKNOWN'}
Vote breakdown: {vote_counts}
Chair decision: {state.chair_decision}
Average committee confidence: {avg_confidence:.2f}
Proposed position size: ${state.position_size:.2f}
Max allowed position: ${config.max_position_usd:.2f}
Min confidence to trade: {config.min_confidence_to_trade}

Check compliance and respond with a JSON object:
{{
  "approved": true or false,
  "reason": "explanation of decision",
  "adjusted_position_usd": dollar amount (reduce if needed, 0 if blocked)
}}
"""

    raw = call_llm_structured(system=system, user=user, agent_name="compliance_agent", smart=True)
    data = json.loads(raw)

    approved = bool(data["approved"])
    reason = data["reason"]
    adjusted = float(data.get("adjusted_position_usd", 0))

    # Hard override: never exceed max position regardless of LLM output
    adjusted = min(adjusted, config.max_position_usd)

    return approved, reason, adjusted