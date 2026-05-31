import weave
from src.core.schemas import DebateState, Vote


class CommitteeEvaluator(weave.Scorer):
    """
    Weave scorer that evaluates committee decision quality.
    Used for deep instrumentation beyond just tracing.
    """

    @weave.op()
    def score(self, output: dict) -> dict:
        """
        Score a committee run on multiple dimensions.
        output is the serialized DebateState.
        """
        scores = {}

        # 1. Debate quality: did rebuttals actually address the other side?
        scores["has_rebuttals"] = bool(output.get("rebuttals"))

        # 2. Vote diversity: did agents actually disagree, or did they all agree?
        votes = list(output.get("votes", {}).values())
        unique_votes = len(set(votes))
        scores["vote_diversity"] = unique_votes / max(len(votes), 1)

        # 3. Confidence calibration: average confidence across agents
        findings = output.get("findings", [])
        if findings:
            avg_conf = sum(f.get("confidence", 0) for f in findings) / len(findings)
            scores["avg_confidence"] = avg_conf

        # 4. Compliance gate triggered: did compliance actually do something?
        scores["compliance_approved"] = output.get("compliance_approved", False)
        scores["trade_executed"] = output.get("trade_executed", False)

        # 5. Chair had to break tie: measures real orchestration complexity
        vote_counts = {}
        for v in votes:
            vote_counts[v] = vote_counts.get(v, 0) + 1
        max_votes = max(vote_counts.values()) if vote_counts else 0
        scores["required_tiebreak"] = max_votes <= 2

        return scores


@weave.op()
def log_debate_summary(state: DebateState) -> dict:
    """
    Logs a structured summary of the debate for Weave dashboard.
    """
    return {
        "ticker": state.ticker,
        "query": state.query,
        "final_vote": state.final_vote.value if state.final_vote else None,
        "position_size": state.position_size,
        "trade_executed": state.trade_executed,
        "compliance_approved": state.compliance_approved,
        "vote_breakdown": {k: v.value for k, v in state.votes.items()},
        "required_tiebreak": max(
            (list(state.votes.values()).count(v) for v in set(state.votes.values())), default=0
        ) <= 2,
        "agent_confidences": {
            f.agent_name: f.confidence for f in state.findings
        },
        "chair_rationale": state.chair_decision,
    }
