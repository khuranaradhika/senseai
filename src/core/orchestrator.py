import concurrent.futures

import weave

from src.core.config import CONFIG
from src.core.clock import time_context
from src.core.schemas import DebateState, DebateRound, CommitteeConfig, Vote
from src.tools.market_data import fetch_market_data
from src.tools.fundamentals import fetch_fundamentals
from src.tools.news import fetch_news
from src.tools.alpaca import execute_trade, get_account
from src.agents.analyst import PERSONAS, analyst_round
from src.agents.chair_agent import chair_moderate, chair_decide
from src.agents.compliance_agent import compliance_agent
from src.agents.intent import parse_intent, intent_directive

ANALYSTS = list(PERSONAS.keys())  # Bull, Bear, Risk, Macro


@weave.op()
def run_committee(
    query: str,
    ticker: str,
    config: CommitteeConfig = None,
    emit=None,
    intent=None,
) -> DebateState:
    """
    Iterative, data-driven investment committee:
    1. Fetch market data.
    2. Debate in rounds — all 4 analysts argue in parallel, see each other's
       positions + the Chair's guidance, and may CHANGE their vote each round.
    3. After every round the Chair (super agent) moderates and tallies. The debate
       ends when the analysts are UNANIMOUS, but only after a floor of
       MIN_DEBATE_ROUNDS, and never past MAX_DEBATE_ROUNDS.
    4. The Chair makes the final call (breaking the tie if no consensus).
    5. Compliance gate.
    6. Alpaca execution (if approved).

    `emit`, if provided, streams dict events per step for the live UI.
    """
    def _emit(event: dict):
        if emit is not None:
            emit(event)

    if config is None:
        config = CommitteeConfig(ticker=ticker)

    # ── Step 0: Understand the query ───────────────────────────────────────────
    # Callers (e.g. the server) may pass a pre-parsed intent; otherwise parse here
    # so the CLI benefits too.
    if intent is None:
        intent = parse_intent(query, ticker)
    directive = intent_directive(intent)
    time_ctx = time_context()  # grounds every agent in the present moment

    state = DebateState(
        ticker=ticker, query=query, market_data=None,
        round=DebateRound.INITIAL, intent=intent,
    )
    print(f"  Intent: {intent.interpretation} "
          f"[horizon={intent.horizon_bucket or 'UNSPECIFIED'}]")
    _emit({
        "type": "intent",
        "horizon_bucket": intent.horizon_bucket,
        "horizon_detail": intent.horizon_detail,
        "horizon_detected": intent.horizon_detected,
        "direction": intent.direction,
        "risk_tolerance": intent.risk_tolerance,
        "catalysts": intent.catalysts,
        "constraints": intent.constraints,
        "interpretation": intent.interpretation,
    })

    # ── Step 1: Market data ────────────────────────────────────────────────────
    print(f"\n{'='*60}\n  INVESTMENT COMMITTEE: {ticker}\n  Query: {query}\n{'='*60}")
    print("\n[1] Fetching market data...")
    _emit({"type": "status", "message": "Fetching market data..."})
    state.market_data = fetch_market_data(ticker)
    print(f"  {state.market_data.summary}")
    _emit({
        "type": "market_data",
        "price": state.market_data.current_price,
        "change_pct": state.market_data.price_change_pct,
        "rsi": state.market_data.rsi,
        "macd": state.market_data.macd_signal,
    })

    # ── Step 1b: Deeper research (distinct data the analysts reason over) ───────
    print("  Pulling fundamentals + news...")
    fundamentals = fetch_fundamentals(ticker)
    news = fetch_news(ticker)
    research = (
        f"FUNDAMENTALS: {fundamentals['summary']}\n\n"
        f"RECENT NEWS:\n{news['summary']}"
    )
    _emit({
        "type": "research",
        "fundamentals": fundamentals["summary"],
        "news": news["headlines"],
    })

    # ── Step 2-3: Iterative debate ─────────────────────────────────────────────
    latest: dict = {}            # agent_name -> most recent AgentFinding
    chair_note = None
    consensus_vote: Vote | None = None

    for round_num in range(1, CONFIG.max_debate_rounds + 1):
        print(f"\n[Round {round_num}] Analysts arguing...")
        _emit({"type": "round_start", "round": round_num})

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ANALYSTS)) as ex:
            futures = {
                name: ex.submit(
                    analyst_round, name, ticker, query, state.market_data,
                    round_num, list(latest.values()), chair_note, latest.get(name),
                    directive, time_ctx, research,
                )
                for name in ANALYSTS
            }
            round_findings = [futures[name].result() for name in ANALYSTS]

        state.transcript.append(round_findings)
        state.rounds_run = round_num

        for f in round_findings:
            latest[f.agent_name] = f
            flag = " (changed)" if f.changed_vote else ""
            print(f"  {f.agent_name}: {f.vote.value} ({f.confidence:.0%}){flag} — {f.thesis[:70]}...")
            _emit({
                "type": "finding", "round": round_num, "agent": f.agent_name,
                "vote": f.vote.value, "confidence": f.confidence, "thesis": f.thesis,
                "key_points": f.key_points, "changed_vote": f.changed_vote,
            })

        votes = [f.vote for f in round_findings]
        vote_counts: dict[str, int] = {}
        for v in votes:
            vote_counts[v.value] = vote_counts.get(v.value, 0) + 1
        unanimous = len(set(votes)) == 1
        print(f"  Votes: {vote_counts} | unanimous={unanimous}")

        # Active moderation after every round.
        chair_note = chair_moderate(state, round_findings, round_num, directive, time_ctx, research)
        state.chair_notes.append(chair_note)
        print(f"  Chair: {chair_note[:90]}...")
        _emit({
            "type": "chair_note", "round": round_num, "note": chair_note,
            "vote_counts": vote_counts, "unanimous": unanimous,
        })

        if round_num >= CONFIG.min_debate_rounds and unanimous:
            consensus_vote = votes[0]
            state.consensus_reached = True
            print(f"  ✓ Unanimous consensus: {consensus_vote.value} after {round_num} rounds")
            break
        if round_num >= CONFIG.max_debate_rounds:
            print(f"  ⚠ Round cap ({CONFIG.max_debate_rounds}) reached without consensus")
            break

    # Backward-compat views for evaluation.py / W&B logging.
    state.findings = state.transcript[0]
    state.rebuttals = state.transcript[-1]
    state.votes = {f.agent_name: f.vote for f in state.transcript[-1]}

    # ── Step 4: Chair final decision ───────────────────────────────────────────
    print("\n[Decision] Chair finalizing...")
    final_vote, rationale, position_size = chair_decide(state, config, consensus_vote, directive, time_ctx, research)
    state.final_vote = final_vote
    state.chair_decision = rationale
    state.position_size = position_size
    state.round = DebateRound.REBUTTAL
    print(f"  Decision: {final_vote.value} | ${position_size:.2f}")
    print(f"  Rationale: {rationale}")
    _emit({
        "type": "votes", "final_vote": final_vote.value,
        "position_size": position_size, "chair_decision": rationale,
        "consensus": state.consensus_reached, "rounds": state.rounds_run,
    })

    # ── Step 5: Compliance gate ────────────────────────────────────────────────
    print("\n[Compliance] Checking...")
    approved, compliance_reason, adjusted_size = compliance_agent(state, config)
    state.compliance_approved = approved
    state.compliance_reason = compliance_reason
    state.position_size = adjusted_size
    print(f"  {'✓ APPROVED' if approved else '✗ BLOCKED'}: {compliance_reason}")
    _emit({
        "type": "compliance", "approved": approved,
        "reason": compliance_reason, "position_size": state.position_size,
    })

    # ── Step 6: Execution ──────────────────────────────────────────────────────
    print("\n[Execution]")

    def _emit_execution():
        _emit({
            "type": "execution",
            "executed": state.trade_executed,
            "final_vote": state.final_vote.value if state.final_vote else None,
            "position_size": state.position_size,
            "result": state.trade_result,
        })

    if not approved:
        print("  Trade blocked by compliance. No order placed.")
        state.trade_executed = False
        _emit_execution()
        return state

    if state.final_vote == Vote.HOLD:
        print("  Final vote is HOLD. No order placed.")
        state.trade_executed = False
        _emit_execution()
        return state

    side = "buy" if state.final_vote == Vote.BUY else "sell"

    try:
        account = get_account()
        buying_power = float(account.get("buying_power", 0))
        if buying_power < state.position_size:
            print(f"  Insufficient buying power (${buying_power:.2f}). Skipping trade.")
            state.trade_executed = False
            _emit_execution()
            return state
    except Exception as e:
        print(f"  Could not verify account: {e}")

    result = execute_trade(
        ticker=state.ticker, side=side,
        notional_usd=state.position_size, rationale=state.chair_decision,
    )
    state.trade_result = result
    state.trade_executed = result.get("success", False)

    if state.trade_executed:
        print(f"  ✓ TRADE EXECUTED: {side.upper()} ${state.position_size:.2f} of {ticker}")
        print(f"  Order ID: {result.get('order_id')}")
    else:
        print(f"  ✗ Trade failed: {result.get('error')}")

    _emit_execution()

    print(f"\n{'='*60}\n  COMMITTEE COMPLETE")
    print(f"  Decision: {state.final_vote.value} | Size: ${state.position_size:.2f} | "
          f"Rounds: {state.rounds_run} | Consensus: {state.consensus_reached}")
    print(f"  Executed: {state.trade_executed}\n{'='*60}\n")

    return state
