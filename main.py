import os
import wandb
import weave
from dotenv import load_dotenv
from src.core.orchestrator import run_committee
from src.core.evaluation import log_debate_summary
from src.core.schemas import CommitteeConfig

load_dotenv(override=True)


def main():
    # ── Init Weave + W&B ─────────────────────────────────────────────────────
    from src.core.config import CONFIG, FAST_MODEL, SMART_MODEL

    weave.init("investment-committee")
    wandb.init(
        project="investment-committee",
        config={
            "fast_model": FAST_MODEL,
            "smart_model": SMART_MODEL,
            "max_debate_rounds": 2,
            "consensus_threshold": 3,
            "max_position_usd": CONFIG.max_position_usd,
        }
    )

    # ── Config ────────────────────────────────────────────────────────────────
    config = CommitteeConfig(
        max_debate_rounds=2,
        consensus_threshold=3,
        max_position_usd=1000.0,
        min_confidence_to_trade=0.6,
    )

    # ── Demo queries ──────────────────────────────────────────────────────────
    demo_cases = [
        ("NVDA", "Should we take a long position given AI capex supercycle thesis?"),
        ("TSLA", "Is Tesla a buy after recent price action and macro headwinds?"),
        ("AAPL", "Should we hold or add to our Apple position?"),
    ]

    for ticker, query in demo_cases:
        print(f"\nRunning committee for {ticker}...")
        config.ticker = ticker

        # Run the committee
        state = run_committee(query=query, ticker=ticker, config=config)

        # Log structured summary to W&B + Weave
        summary = log_debate_summary(state)
        wandb.log({
            f"{ticker}/final_vote": summary["final_vote"],
            f"{ticker}/position_size": summary["position_size"],
            f"{ticker}/trade_executed": int(summary["trade_executed"]),
            f"{ticker}/compliance_approved": int(summary["compliance_approved"]),
            f"{ticker}/required_tiebreak": int(summary["required_tiebreak"]),
            **{
                f"{ticker}/confidence_{agent}": conf
                for agent, conf in summary["agent_confidences"].items()
            }
        })

        print(f"\n{'─'*40}")
        print(f"W&B logged for {ticker}")
        print(f"{'─'*40}")

    wandb.finish()
    print("\nAll committee runs complete. Check W&B + Weave for full traces.")


if __name__ == "__main__":
    main()
