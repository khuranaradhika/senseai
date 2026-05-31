"""
Evaluation + W&B logging for the iterative committee.

- `score_debate` turns a finished debate into process-quality scores (how much the
  debate actually moved, whether it converged, final conviction).
- `log_debate_summary` produces a JSON-safe summary of the run.
- `log_run_to_wandb` records both to a W&B run — used by the live server so UI
  runs populate the W&B dashboard, not just Weave traces. It never raises: a W&B
  hiccup must not break a debate.
"""
import weave

from src.core.schemas import DebateState


def _vote_diversity(findings) -> float:
    votes = [f.vote.value for f in findings]
    return len(set(votes)) / max(len(votes), 1) if votes else 0.0


@weave.op()
def score_debate(state: DebateState) -> dict:
    """Process-quality signals for the debate (no ground truth needed)."""
    transcript = state.transcript or []
    first = transcript[0] if transcript else []
    last = transcript[-1] if transcript else []
    vote_changes = sum(1 for rnd in transcript for f in rnd if f.changed_vote)
    avg_final_conf = sum(f.confidence for f in last) / max(len(last), 1) if last else 0.0
    return {
        "rounds_run": state.rounds_run,
        "consensus_reached": bool(state.consensus_reached),
        "tiebreak_needed": not bool(state.consensus_reached),
        "initial_vote_diversity": _vote_diversity(first),   # 1.0 = total disagreement at start
        "final_vote_diversity": _vote_diversity(last),      # ~0.25 = unanimous at end
        "vote_changes": vote_changes,                       # how much minds actually moved
        "avg_final_confidence": avg_final_conf,
    }


@weave.op()
def log_debate_summary(state: DebateState) -> dict:
    """JSON-safe summary of a finished debate."""
    last = state.transcript[-1] if state.transcript else state.findings
    return {
        "ticker": state.ticker,
        "query": state.query,
        "horizon": state.intent.horizon_bucket if state.intent else None,
        "final_vote": state.final_vote.value if state.final_vote else None,
        "position_size": state.position_size,
        "trade_executed": state.trade_executed,
        "compliance_approved": state.compliance_approved,
        "rounds_run": state.rounds_run,
        "consensus_reached": state.consensus_reached,
        "vote_breakdown": {k: v.value for k, v in state.votes.items()},
        "agent_confidences": {f.agent_name: f.confidence for f in last},
        "chair_rationale": state.chair_decision,
        # back-compat key still consumed by main.py
        "required_tiebreak": not state.consensus_reached,
    }


def log_run_to_wandb(state: DebateState, project: str = "investment-committee") -> dict | None:
    """
    Log one committee run to W&B (its own run). Returns {summary, scores, wandb_url}
    or None if logging failed. Robust by design — never raises into the caller.
    """
    try:
        import wandb

        summary = log_debate_summary(state)
        scores = score_debate(state)

        run = wandb.init(
            project=project,
            reinit=True,
            config={
                "ticker": summary["ticker"],
                "horizon": summary["horizon"],
                "final_vote": summary["final_vote"],
                "consensus_reached": summary["consensus_reached"],
            },
        )
        wandb.log({
            "position_size": summary["position_size"] or 0.0,
            "trade_executed": int(summary["trade_executed"]),
            "compliance_approved": int(summary["compliance_approved"]),
            "rounds_run": scores["rounds_run"],
            "consensus_reached": int(scores["consensus_reached"]),
            "vote_changes": scores["vote_changes"],
            "initial_vote_diversity": scores["initial_vote_diversity"],
            "final_vote_diversity": scores["final_vote_diversity"],
            "avg_final_confidence": scores["avg_final_confidence"],
            **{f"confidence/{a}": c for a, c in summary["agent_confidences"].items()},
        })
        url = getattr(run, "url", None)
        run.finish()
        return {"summary": summary, "scores": scores, "wandb_url": url}
    except Exception as e:  # noqa: BLE001
        print(f"[wandb] run logging skipped: {e}")
        return None
