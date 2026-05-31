# SenseAI — Architecture

This document describes how SenseAI is built end to end: the pipeline, every module's
role, the data model, the live event contract, the safety layer, and observability.

---

## 1. The pipeline

A single run is orchestrated by `run_committee()` in
[src/core/orchestrator.py](src/core/orchestrator.py):

```
run_committee(query, ticker, config, emit, intent)
│
├─ 0. Understand the query
│     intent = parse_intent(query, ticker)          # src/agents/intent.py
│     directive = intent_directive(intent)          # horizon → how to weigh data
│     time_ctx  = time_context()                    # today's date + market open/closed
│
├─ 1. Research (fetched once, reused all rounds)
│     market_data = fetch_market_data(ticker)        # price, RSI(Wilder), MACD, range, volume
│     fundamentals = fetch_fundamentals(ticker)      # P/E, fwd P/E, PEG, growth, margins, ROE…
│     sector       = fetch_sector(ticker)            # sector + relative strength vs sector ETF
│     macro        = fetch_macro()                    # S&P, Nasdaq, VIX, 10Y, DXY
│     news         = fetch_news(ticker)              # recent headlines
│     research = fundamentals + sector + macro + news (one brief)
│
├─ 2-3. Iterative debate  (for round in 1..MAX_DEBATE_ROUNDS)
│     parallel: analyst_round(name, …) for name in [Bull, Bear, Risk, Macro]
│        each sees: market data, research brief, directive (horizon), time_ctx,
│                   the other analysts' latest positions, the Chair's last note,
│                   and its own previous position → returns vote + thesis + confidence
│     chair_note = chair_moderate(...)               # active moderation after EVERY round
│     unanimous = (all four votes identical)
│     stop if  round >= MIN_DEBATE_ROUNDS and unanimous   → consensus
│     stop if  round == MAX_DEBATE_ROUNDS                 → no consensus
│
├─ 4. Chair decision
│     final_vote, rationale, size, conviction = chair_decide(state, config, consensus_vote, …)
│        consensus → ratify it + size by conviction;  no consensus → break the tie
│
├─ 5. Compliance (LLM, advisory)
│     approved, reason, adjusted_size = compliance_agent(state, config)
│
└─ 6. Execution (deterministic guardrails are the final gate)
      guardrails.evaluate(...)  → approve/clamp/block
      if approved and side in {buy, sell}:  alpaca.execute_trade(...)
      record_decision(state)     # journal
      log_run_to_wandb(state)    # metrics (server path)
```

### Debate dynamics
- **Data-driven, not advocacy.** Bull/Bear/Risk/Macro are analytical *lenses*, each prompted
  to vote honestly from evidence — not to defend a predetermined side.
- **Minds change on evidence, not headcount.** The prompts explicitly forbid conforming to
  the majority ("the number of analysts on a side is NOT evidence"); the Chair never cites the
  tally and pushes the *majority* to rebut the minority's best point.
- **Consensus = unanimous**, but only allowed to end the debate after `MIN_DEBATE_ROUNDS`.
  Genuine splits ride to `MAX_DEBATE_ROUNDS` and the Chair breaks the tie.
- **Horizon shapes weighting.** Intraday → technicals/momentum; long → fundamentals/secular.

---

## 2. Module map

```
main.py            CLI entry (runs demo tickers, logs to W&B, journals)
server.py          FastAPI server: serves the UI + /run SSE stream + /logo.png
test.py            smoke/integration runner (tools, intent, guardrails, journal, committee)
ui/index.html      single-page dashboard (SSE client, no build step)

src/core/
  orchestrator.py  run_committee() — the whole pipeline above
  config.py        CONFIG singleton: all thresholds + model tiers (env-overridable)
  schemas.py       dataclasses: Intent, MarketData, AgentFinding, DebateState, …
  llm.py           W&B Inference client: _call (retry/backoff), call_llm, call_typed
  parsing.py       parse_structured(): JSON extract → Pydantic validate → reprompt-once
  guardrails.py    evaluate(): deterministic pre-trade checks; gather_inputs()
  clock.py         time_context(): today + market-open grounding
  journal.py       SQLite decision log + review() forward-return scoring
  evaluation.py    score_debate(), log_debate_summary(), log_run_to_wandb()

src/agents/
  intent.py        parse_intent() + horizon buckets/guidance + intent_directive()
  analyst.py       PERSONAS (Bull/Bear/Risk/Macro) + analyst_round()
  chair_agent.py   chair_moderate() (per-round) + chair_decide() (final)
  compliance_agent.py  LLM compliance review (advisory)

src/tools/
  market_data.py   yfinance price + Wilder RSI + MACD + range/volume + as-of date
  fundamentals.py  yfinance valuation/growth/profitability/balance-sheet
  sector.py        sector classification + 1-mo relative strength vs sector ETF
  macro.py         indices, VIX, 10Y yield, DXY (level + 1-mo change)
  news.py          recent headlines
  alpaca.py        account / positions / clock / orders-today / execute_trade
```

---

## 3. Data model ([src/core/schemas.py](src/core/schemas.py))

- **`Intent`** — `horizon_bucket` (INTRADAY/SHORT/MEDIUM/LONG/VERY_LONG), `horizon_detail`,
  `direction`, `risk_tolerance`, `catalysts`, `constraints`, `interpretation`.
- **`MarketData`** — price, change %, volume/avg, 52-wk range, P/E, market cap, RSI, MACD,
  `summary`, `as_of` (latest bar date).
- **`AgentFinding`** — `agent_name`, `thesis`, `key_points`, `confidence`, `vote` (BUY/SELL/HOLD),
  `round`, `changed_vote`, optional `rebuttal`.
- **`DebateState`** — the run's full state: `intent`, `market_data`, `transcript`
  (list of rounds, each a list of findings), `chair_notes`, `rounds_run`,
  `consensus_reached`, `final_vote`, `conviction`, `position_size`, compliance fields,
  `trade_executed`, `trade_result`. (`findings` = round 1, `rebuttals` = last round — kept
  for backward-compatible logging.)

Agent outputs are validated into **Pydantic** models (`AnalystOutput`, `ChairModeration`,
`ChairDecision`, `ComplianceOutput`, `IntentOutput`) via `call_typed`, then mapped to the
dataclasses above.

---

## 4. LLM layer ([src/core/llm.py](src/core/llm.py))

- **`_call`** posts to the W&B Inference `/chat/completions` endpoint with retry +
  exponential backoff (`LLM_MAX_RETRIES`, `LLM_TIMEOUT_S`); 4xx surfaces immediately, 5xx/timeouts retry.
- **`call_typed(system, user, Model, smart=…)`** is the safe path every agent uses:
  call → `parse_structured` (strip fences → `json.loads` → `Model.model_validate`) →
  on failure, **reprompt once** with the error → else raise typed `StructuredParseError`.
  A single malformed response never crashes a run.
- Two model tiers (`smart` flag) selected from `CONFIG`.

---

## 5. Safety: the guardrail layer ([src/core/guardrails.py](src/core/guardrails.py))

`evaluate(...)` is a **pure, network-free** function (the orchestrator passes in account /
positions / clock / daily count via `gather_inputs()`), so it is fully unit-tested. It runs
**after** the LLM compliance review and is the final word:

| Check | Blocks when |
|---|---|
| `actionable_direction` | vote is HOLD (no order by design) |
| `confidence_gate` | conviction < `CONVICTION_MIN` **or** avg confidence < `AVG_CONF_MIN` |
| `market_open` | market is closed |
| `daily_trade_cap` | today's order count ≥ `MAX_DAILY_TRADES` |
| `no_conflicting_position` | an open position already exists in the symbol |
| `sufficient_sizing` | clamped notional ≤ 0 |

Final size = `min(proposed, MAX_POSITION_USD, MAX_PORTFOLIO_PCT × equity, buying_power)`.
Broker unreachable → **block for safety**. Per-run budget (UI "Max Buy") overrides the global
cap via `dataclasses.replace(CONFIG, max_position_usd=…)`.

---

## 6. Live event contract (SSE)

The UI opens an `EventSource` to `GET /run?ticker=&query=&horizon=&max_position=`. The server
runs the committee in a worker thread; `run_committee`'s `emit` callback pushes typed JSON
events onto a queue that the SSE generator streams. Event types:

| Event | Payload (key fields) |
|---|---|
| `intent` | horizon_bucket, direction, risk_tolerance, catalysts, constraints, interpretation |
| `status` | message |
| `market_data` | price, change_pct, rsi, macd |
| `research` | fundamentals, sector, macro, news[] |
| `round_start` | round |
| `finding` | round, agent, vote, confidence, thesis, key_points, changed_vote |
| `chair_note` | round, note, vote_counts, unanimous |
| `votes` | final_vote, position_size, chair_decision, consensus, rounds |
| `compliance` | approved, reason, position_size |
| `execution` | executed, final_vote, position_size, result, blocked_by, guardrails[] |
| `metrics` | scores, wandb_url |
| `complete` | — |

The same `emit` interface means the CLI runs the identical pipeline with no callback.

---

## 7. Frontend ([ui/index.html](ui/index.html))

Single file, no build step. Brand: **SenseAI** (Chakra Petch wordmark, deep-navy + cyan to
match the logo; BUY-green / SELL-red / HOLD-amber for votes). Live views:

- **Sticky status bar** — pipeline stage + live round + running tally + consensus pill.
- **Vote-trajectory matrix** — agents × rounds grid; each cell is the vote (colored) with a
  `↻` when it changed; shows the "minds changing" story at a glance.
- **Collapsible round groups** — each round is a `<details>` block; older rounds auto-collapse
  so a 20-round run stays scannable.
- **Research card** — fundamentals / sector / macro / news.
- **Verdict + trade card** — final call, size, consensus-vs-tiebreak, and every guardrail check.

---

## 8. Observability

- **Weave** (`weave.init("investment-committee")`): `@weave.op` on the orchestrator, every
  agent, `call_llm`/`call_typed`, and every tool → a full nested trace per run.
- **W&B metrics** (`evaluation.log_run_to_wandb`): one run per decision with decision +
  process-quality metrics (`score_debate`: rounds, consensus, vote_changes, initial/final
  vote diversity, avg final confidence).
- **Journal** (`journal.py`): SQLite store of every decision + entry price; `review()` fetches
  the forward price, computes the realized move, labels correctness, and aggregates hit-rate /
  returns-by-vote / conviction calibration → logged to W&B as a `review` run.

---

## 9. Tests

- `tests/test_parsing.py` — fence-strip, valid parse, reprompt-repair, hard-fail, schema violation.
- `tests/test_guardrails.py` — every guardrail branch (gate, market closed, daily cap, conflict,
  clamping to each cap).
- `test.py` — runnable smoke checks across tools / intent / guardrails / journal / a full committee.
