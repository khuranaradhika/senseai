import concurrent.futures
import weave
from src.core.schemas import DebateState, DebateRound, CommitteeConfig, Vote
from src.tools.market_data import fetch_market_data
from src.tools.alpaca import execute_trade, get_account
from src.agents.bull_agent import bull_agent
from src.agents.bear_agent import bear_agent
from src.agents.risk_agent import risk_agent
from src.agents.macro_agent import macro_agent
from src.agents.chair_agent import chair_tiebreak, chair_consensus
from src.agents.compliance_agent import compliance_agent


@weave.op()
def run_committee(query: str, ticker: str, config: CommitteeConfig = None, emit=None) -> DebateState:
    """
    Main orchestrator. Runs the full investment committee pipeline:
    1. Fetch market data
    2. Round 1: Parallel specialist debate
    3. Round 2: Rebuttals (Bull sees Bear, Bear sees Bull)
    4. Vote tally → consensus or Chair tiebreak
    5. Compliance gate
    6. Alpaca execution (if approved)

    `emit`, if provided, is called with dict events as each stage completes,
    so a frontend (e.g. the SSE server) can stream the debate in real time.
    """
    def _emit(event: dict):
        if emit is not None:
            emit(event)

    if config is None:
        config = CommitteeConfig(ticker=ticker)

    state = DebateState(ticker=ticker, query=query, market_data=None, round=DebateRound.INITIAL)

    # ── Step 1: Fetch market data ────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  INVESTMENT COMMITTEE: {ticker}")
    print(f"  Query: {query}")
    print(f"{'='*60}")
    print("\n[1/6] Fetching market data...")
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

    # ── Step 2: Round 1 — parallel specialist debate ─────────────────────────
    print("\n[2/6] Round 1 — Initial positions (parallel)...")
    _emit({"type": "status", "message": "Round 1 — Initial positions..."})
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        bull_future = executor.submit(bull_agent, ticker, query, state.market_data)
        bear_future = executor.submit(bear_agent, ticker, query, state.market_data)
        risk_future = executor.submit(risk_agent, ticker, query, state.market_data)
        macro_future = executor.submit(macro_agent, ticker, query, state.market_data)

        bull_r1 = bull_future.result()
        bear_r1 = bear_future.result()
        risk_r1 = risk_future.result()
        macro_r1 = macro_future.result()

    state.findings = [bull_r1, bear_r1, risk_r1, macro_r1]

    for f in state.findings:
        print(f"  {f.agent_name}: {f.vote.value} ({f.confidence:.0%}) — {f.thesis[:80]}...")
        _emit({
            "type": "finding",
            "round": 1,
            "agent": f.agent_name,
            "vote": f.vote.value,
            "confidence": f.confidence,
            "thesis": f.thesis,
            "key_points": f.key_points,
        })

    # ── Step 3: Round 2 — rebuttals (Bull vs Bear) ───────────────────────────
    print("\n[3/6] Round 2 — Rebuttals...")
    _emit({"type": "status", "message": "Round 2 — Rebuttals..."})
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        bull_r2_future = executor.submit(
            bull_agent, ticker, query, state.market_data, bear_r1.thesis
        )
        bear_r2_future = executor.submit(
            bear_agent, ticker, query, state.market_data, bull_r1.thesis
        )
        bull_r2 = bull_r2_future.result()
        bear_r2 = bear_r2_future.result()

    state.rebuttals = [bull_r2, bear_r2]
    state.round = DebateRound.REBUTTAL

    for r in state.rebuttals:
        print(f"  {r.agent_name} rebuttal: {r.vote.value} — {r.rebuttal[:80] if r.rebuttal else ''}...")
        _emit({
            "type": "finding",
            "round": 2,
            "agent": r.agent_name,
            "vote": r.vote.value,
            "confidence": r.confidence,
            "thesis": r.rebuttal or r.thesis,
            "key_points": r.key_points,
        })

    # ── Step 4: Vote tally ────────────────────────────────────────────────────
    print("\n[4/6] Tallying votes...")

    # Final votes: rebuttals override round 1 for bull/bear; risk/macro keep round 1
    final_findings = [bull_r2, bear_r2, risk_r1, macro_r1]
    state.votes = {f.agent_name: f.vote for f in final_findings}

    vote_counts = {}
    for v in state.votes.values():
        vote_counts[v.value] = vote_counts.get(v.value, 0) + 1

    print(f"  Vote breakdown: {vote_counts}")

    # Determine consensus
    winning_vote = max(vote_counts, key=vote_counts.get)
    winning_count = vote_counts[winning_vote]

    if winning_count >= config.consensus_threshold:
        # Consensus reached (3:1 or 4:0)
        print(f"  ✓ Consensus: {winning_vote} ({winning_count}/4 votes)")
        rationale, position_size = chair_consensus(
            state, config, Vote(winning_vote), vote_counts
        )
        state.final_vote = Vote(winning_vote)
        state.chair_decision = rationale
        state.position_size = position_size
    else:
        # Split vote (2:2) — Chair breaks tie
        print(f"  ⚖ Split vote — Chair breaking tie...")
        final_vote, rationale, position_size = chair_tiebreak(state, config)
        state.final_vote = final_vote
        state.chair_decision = rationale
        state.position_size = position_size
        print(f"  Chair decision: {final_vote.value}")

    print(f"  Rationale: {state.chair_decision}")
    print(f"  Proposed position: ${state.position_size:.2f}")
    _emit({
        "type": "votes",
        "final_vote": state.final_vote.value,
        "position_size": state.position_size,
        "chair_decision": state.chair_decision,
    })

    # ── Step 5: Compliance gate ───────────────────────────────────────────────
    print("\n[5/6] Compliance check...")
    approved, compliance_reason, adjusted_size = compliance_agent(state, config)
    state.compliance_approved = approved
    state.compliance_reason = compliance_reason
    state.position_size = adjusted_size

    print(f"  {'✓ APPROVED' if approved else '✗ BLOCKED'}: {compliance_reason}")
    _emit({
        "type": "compliance",
        "approved": approved,
        "reason": compliance_reason,
        "position_size": state.position_size,
    })

    # ── Step 6: Execute trade ─────────────────────────────────────────────────
    print("\n[6/6] Execution...")

    def _emit_execution():
        _emit({
            "type": "execution",
            "executed": state.trade_executed,
            "final_vote": state.final_vote.value if state.final_vote else None,
            "position_size": state.position_size,
            "result": state.trade_result,
        })

    if not approved:
        print(f"  Trade blocked by compliance. No order placed.")
        state.trade_executed = False
        _emit_execution()
        return state

    if state.final_vote == Vote.HOLD:
        print(f"  Final vote is HOLD. No order placed.")
        state.trade_executed = False
        _emit_execution()
        return state

    side = "buy" if state.final_vote == Vote.BUY else "sell"

    # Verify account has buying power
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
        ticker=state.ticker,
        side=side,
        notional_usd=state.position_size,
        rationale=state.chair_decision,
    )

    state.trade_result = result
    state.trade_executed = result.get("success", False)

    if state.trade_executed:
        print(f"  ✓ TRADE EXECUTED: {side.upper()} ${state.position_size:.2f} of {ticker}")
        print(f"  Order ID: {result.get('order_id')}")
    else:
        print(f"  ✗ Trade failed: {result.get('error')}")

    _emit_execution()

    print(f"\n{'='*60}")
    print(f"  COMMITTEE COMPLETE")
    print(f"  Decision: {state.final_vote.value} | Size: ${state.position_size:.2f}")
    print(f"  Executed: {state.trade_executed}")
    print(f"{'='*60}\n")

    return state
