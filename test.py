#!/usr/bin/env python
"""
Smoke / integration test runner for the Investment Committee.

Usage:
  python test.py                          # fast checks (no LLM): tools, guardrails, journal
  python test.py tools [TICKER]           # data tools only (yfinance)
  python test.py intent                   # query-understanding parser (LLM)
  python test.py guardrails               # deterministic guardrail scenarios
  python test.py journal                  # decision journal record/review (temp db)
  python test.py committee [TICKER] [HORIZON]   # full end-to-end debate (slow ~2 min)
  python test.py all [TICKER] [HORIZON]         # everything incl. a full debate

Flags:
  --quick    cap the debate at 2 rounds (committee / all)

Exit code is 0 only if every selected check passes.
"""
import os
import sys

PASS, FAIL = "✓", "✗"


def _ok(label: str, cond: bool, detail: str = "") -> bool:
    print(f"  {PASS if cond else FAIL} {label}" + (f" — {detail}" if detail else ""))
    return bool(cond)


def test_tools(ticker: str = "NVDA") -> bool:
    print(f"[tools] {ticker}")
    from src.tools.market_data import fetch_market_data
    from src.tools.fundamentals import fetch_fundamentals
    from src.tools.sector import fetch_sector
    from src.tools.macro import fetch_macro
    from src.tools.news import fetch_news

    ok = True
    md = fetch_market_data(ticker)
    rsi_str = f"{md.rsi:.1f}" if md.rsi is not None else "n/a"
    ok &= _ok("market_data", md.current_price > 0, f"${md.current_price:.2f} RSI {rsi_str} ({md.as_of})")
    ok &= _ok("fundamentals", "summary" in fetch_fundamentals(ticker))
    ok &= _ok("sector", bool(fetch_sector(ticker)["summary"]))
    ok &= _ok("macro", "summary" in fetch_macro())
    ok &= _ok("news", isinstance(fetch_news(ticker)["headlines"], list))
    return ok


def test_intent() -> bool:
    print("[intent]  (uses the LLM)")
    from src.agents.intent import parse_intent

    ok = True
    a = parse_intent("swing trade NVDA over the next two weeks", "NVDA")
    ok &= _ok("short horizon", a.horizon_bucket == "SHORT", str(a.horizon_bucket))
    b = parse_intent("hold AAPL for 20 years in my retirement account", "AAPL")
    ok &= _ok("very-long horizon", b.horizon_bucket == "VERY_LONG", str(b.horizon_bucket))
    return ok


def test_guardrails() -> bool:
    print("[guardrails]")
    from src.core.guardrails import evaluate
    from src.core.config import CONFIG

    acct = {"equity": "100000", "buying_power": "100000"}
    base = dict(ticker="NVDA", direction="BUY", conviction=0.8, avg_confidence=0.7,
                proposed_notional=500.0, account=acct, positions=[],
                clock={"is_open": True}, daily_trade_count=0)
    ok = True
    ok &= _ok("approves clean BUY", evaluate(**base).approved)
    ok &= _ok("blocks low conviction", not evaluate(**{**base, "conviction": 0.5}).approved)
    ok &= _ok("blocks closed market", not evaluate(**{**base, "clock": {"is_open": False}}).approved)
    ok &= _ok("blocks HOLD", not evaluate(**{**base, "direction": "HOLD"}).approved)
    ok &= _ok("clamps to max position",
              evaluate(**{**base, "proposed_notional": 1e9}).notional_usd == CONFIG.max_position_usd)
    return ok


def test_journal() -> bool:
    print("[journal]  (temp db)")
    import tempfile
    import pathlib
    from src.core import journal

    journal.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "decisions.db"
    from src.core.schemas import DebateState, DebateRound, Vote, Intent, MarketData

    md = MarketData(ticker="NVDA", current_price=200.0, price_change_pct=0.0, volume=0,
                    avg_volume=0, week_52_high=0, week_52_low=0, pe_ratio=None,
                    market_cap=None, rsi=50.0, macd_signal="neutral", summary="x")
    state = DebateState(
        ticker="NVDA", query="q", market_data=md, round=DebateRound.REBUTTAL,
        intent=Intent(raw_query="q", horizon_bucket="SHORT", horizon_detected=True),
        final_vote=Vote.BUY, conviction=0.8, position_size=300.0,
        consensus_reached=True, rounds_run=4,
    )
    ok = _ok("record_decision", journal.record_decision(state) is not None)
    metrics = journal.review(log_wandb=False)
    ok &= _ok("review scores it", metrics.get("scored_total", 0) >= 1)
    return ok


def test_committee(ticker: str = "NVDA", horizon: str = "MEDIUM") -> bool:
    print(f"[committee] {ticker} / {horizon}  (full debate — slow)")
    from src.core.orchestrator import run_committee
    from src.core.schemas import CommitteeConfig, Intent

    intent = Intent(raw_query="test", horizon_bucket=horizon, horizon_detected=True)
    state = run_committee(
        query=f"Is {ticker} a buy?", ticker=ticker,
        config=CommitteeConfig(ticker=ticker, max_position_usd=500.0), intent=intent,
    )
    ok = _ok("final vote produced", state.final_vote is not None,
             state.final_vote.value if state.final_vote else None)
    ok &= _ok("ran the debate", state.rounds_run >= 1, f"{state.rounds_run} rounds")
    ok &= _ok("chair conviction set", state.conviction is not None)
    return ok


def main() -> None:
    argv = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--quick" in sys.argv:
        os.environ["MIN_DEBATE_ROUNDS"] = "2"   # must be set before config import
    mode = argv[0] if argv else "fast"
    ticker = argv[1] if len(argv) > 1 else "NVDA"
    horizon = argv[2] if len(argv) > 2 else "MEDIUM"

    selected = {
        "tools":      mode in ("fast", "all", "tools"),
        "intent":     mode in ("all", "intent"),
        "guardrails": mode in ("fast", "all", "guardrails"),
        "journal":    mode in ("fast", "all", "journal"),
        "committee":  mode in ("all", "committee"),
    }

    results: dict[str, bool] = {}
    if selected["tools"]:      results["tools"] = test_tools(ticker)
    if selected["intent"]:     results["intent"] = test_intent()
    if selected["guardrails"]: results["guardrails"] = test_guardrails()
    if selected["journal"]:    results["journal"] = test_journal()
    if selected["committee"]:  results["committee"] = test_committee(ticker, horizon)

    if not results:
        print(__doc__)
        sys.exit(2)

    print("\n=== SUMMARY ===")
    for name, passed in results.items():
        print(f"  {PASS if passed else FAIL} {name}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
