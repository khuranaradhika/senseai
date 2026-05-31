# SenseAI — Investment Committee v2: Executable Plan

> Re-architecture from the static bull/bear/chair/compliance committee to a
> **dynamic, routed, self-critiquing pipeline**. Optimized for a judged hackathon
> demo where the **Weave story is the product**: every routing decision and every
> critic rejection is a visible trace, so judges see the reasoning *behind* the
> harness in real time — not just the final trade.

## Decisions locked
- **Migration:** Full replacement. Retire `orchestrator.py` + `bull/bear/risk/macro/chair/compliance` agents. Reuse infra only: [src/core/llm.py](src/core/llm.py) (W&B DeepSeek), [src/tools/alpaca.py](src/tools/alpaca.py), [server.py](server.py) SSE, Weave.
- **Tools:** yfinance + free sources (no paid keys).
- **Goal:** Hackathon / judged demo — MVP scope, reliability over a handful of live runs, rich traces.
- **Loop limits (conservative):** Critic ≤ 2 revision rounds per finding. Execute only if `conviction ≥ 0.70` **AND** `avg_specialist_confidence ≥ 0.60`.

---

## Target architecture

```
UserQuery
   ↓
PlannerAgent ── reads query, selects which specialists to invoke   [TRACE: routing decision + rationale]
   ↓ (dynamic routing — 1..4 specialists)
[MacroAgent] [SectorAgent] [CompanyAgent] [SentimentAgent]         (parallel, each does tool use)
   ↓
CriticAgent ── scores each finding; weak ones go back for revision [TRACE: every accept/reject + reason]
   ↑──────── feedback loop (max 2 rounds/finding) ────────┐
   ↓                                                       │
ArbiterAgent ── synthesizes approved findings → structured thesis
   ↓
ConvictionScorerAgent ── conviction score (0–1) + position sizing
   ↓ (deterministic gate: conviction ≥ 0.70 AND avg_conf ≥ 0.60)
ExecutionAgent ── deterministic guardrails → Alpaca paper trade
```

### Specialist → tool mapping (yfinance + free)
| Specialist | Question it answers | Tools |
|---|---|---|
| **MacroAgent** | Is the macro regime a tailwind or headwind? | indices (`^GSPC`), VIX (`^VIX`), 10y yield (`^TNX`), DXY |
| **SectorAgent** | How does the name look vs its sector/peers? | sector lookup, peer list, relative performance |
| **CompanyAgent** | Are the fundamentals + technicals sound? | yfinance `.info` (P/E, margins, growth), price/RSI/MACD |
| **SentimentAgent** | What's the news/sentiment posture? | yfinance `.news` / free RSS headlines |

Each tool is a `@weave.op`, so tool calls show up as traces. Specialists select tools via a **bounded function-calling loop (≤3 tool calls each)**; if the model returns no tool call, we fall back to pre-fetched context so a run never stalls.

---

## Data model (`src/core/schemas.py` — full rewrite, Pydantic)

- `Query{ ticker, question, raw }`
- `RoutingDecision{ selected: list[SpecialistName], skipped: list[SpecialistName], rationale }`
- `Evidence{ source, key, value, note }` — what a finding actually cited
- `SpecialistFinding{ agent, signal: Literal["bullish","bearish","neutral"], thesis, key_points, evidence: list[Evidence], confidence: float, revision: int }`
- `Critique{ finding_agent, approved: bool, score: float, issues: list[str], revision_request: str | None }`
- `Thesis{ direction: Literal["BUY","SELL","HOLD"], summary, supporting: list[str], opposing: list[str], risks: list[str] }`
- `ConvictionResult{ conviction: float, position_size_usd: float, sizing_rationale }`
- `GuardrailCheck{ name, passed: bool, detail }`
- `ExecutionResult{ executed: bool, side, notional_usd, order_id?, blocked_by?, checks: list[GuardrailCheck] }`
- `PipelineState{ query, routing, findings, critiques, thesis, conviction, execution, started_at }`

All agent outputs are validated against these models via the safe-parse layer (no raw `json.loads`).

---

## Phased build

### Phase 0 — Foundation & guardrails *(START HERE — see [todo.md](todo.md))*
Reusable substrate that every agent depends on. Detailed checklist in todo.md.
- `src/core/config.py` — central thresholds + model tiers (kills stale `claude-sonnet` in [main.py](main.py:18)).
- `src/core/parsing.py` — `parse_structured(raw, Model)`: fence-strip → `json.loads` → Pydantic validate → **one reprompt on failure** → typed error. Replaces every bare `json.loads`.
- `src/core/llm.py` — add retry/backoff + timeout around the W&B call; keep `call_llm` / `call_llm_structured` signatures.
- `src/core/guardrails.py` — deterministic pre-trade checks (thresholds, position cap, buying power, market hours, duplicate position, daily trade count). **Thresholds enforced in code, never just in a prompt.**
- `tests/` — pytest for parse-repair, threshold enforcement, position clamp, critic-loop termination.

**Exit criteria:** guardrails + parsing unit-tested green; thresholds enforced deterministically; malformed LLM JSON never crashes a run.

### Phase 1 — Tools (`src/tools/`)
- Refactor [src/tools/market_data.py](src/tools/market_data.py) into a reusable price/technical tool.
- New `fundamentals.py`, `sector.py`, `news.py`, `macro.py` — each a `@weave.op` returning a small typed dict.
- A `ToolRegistry` mapping specialist → allowed tools + OpenAI-style tool schemas.

**Exit criteria:** each tool callable standalone, returns within timeout, degrades gracefully when yfinance is missing a field.

### Phase 2 — Agents (`src/agents/`)
- `planner.py` — given the query, emit `RoutingDecision` (1–4 specialists + rationale). This is the headline dynamic-routing trace.
- `specialists/{macro,sector,company,sentiment}.py` — each runs its bounded tool-calling loop, returns a `SpecialistFinding` with cited `evidence`.
- `critic.py` — scores a finding; `approved=False` emits a `revision_request`. **Calibrated:** must lower confidence / flag when evidence is thin.
- `arbiter.py` — synthesize approved findings → `Thesis` (direction + supporting/opposing/risks).
- `conviction.py` — `Thesis` + findings → `ConvictionResult` (conviction + sizing via vol-aware rule bounded by config caps, not free-form).
- `execution.py` — runs `guardrails.py`, then fires Alpaca paper trade via [src/tools/alpaca.py](src/tools/alpaca.py) only if all checks pass.

**Exit criteria:** each agent independently testable with a fixture state; outputs validate against schemas.

### Phase 3 — Pipeline orchestration (`src/core/pipeline.py`)
Replaces `orchestrator.py`. `run_pipeline(query, ticker, config, emit=None)`:
1. Planner → routing.
2. Parallel specialists (ThreadPoolExecutor) over the *selected* set only.
3. Critic loop per finding (≤2 rounds; re-invoke specialist with `revision_request`).
4. Arbiter → thesis.
5. Conviction → score + size.
6. Execution gate → guardrails → Alpaca.
`emit` callback fires a typed event at **every** step (incl. each routing choice, each tool call, each critic verdict + revision) — same pattern already wired into the current orchestrator.

**Weave instrumentation:** `@weave.op` on pipeline, planner, each specialist, each tool, critic, arbiter, conviction, execution. Routing rationale and critic rejections are first-class trace attributes — the demo story.

**Exit criteria:** full run from query → execution completes; Weave shows nested traces with routing + rejection reasoning.

### Phase 4 — SSE events + UI
- `src/core/events.py` — typed event builders.
- [server.py](server.py) `/run` — drive `run_pipeline`; new event types: `routing`, `tool_call`, `finding`, `critique`, `revision`, `thesis`, `conviction`, `execution`, `complete`.
- [ui/index.html](ui/index.html) — pipeline stages become **Planner → Route → Specialists → Critic → Arbiter → Conviction → Execute**; new specialist cards; a **Critic rejections** panel (the visual hook); routing rationale banner.

**Exit criteria:** live demo streams routing + rejections visibly; reconnect/disconnect handled.

### Phase 5 — Retire old system + polish
- Delete `orchestrator.py` + 6 legacy agents; update [main.py](main.py) CLI to `run_pipeline`.
- README + demo script (3 tickers showing: a clean BUY, a critic-forced revision, a HOLD/blocked-by-guardrail).
- Smoke test across the demo tickers.

**Exit criteria:** `python main.py` and `python server.py` both run the new pipeline end-to-end; no references to retired modules.

---

## Risks & mitigations
- **LLM JSON drift** → safe-parse + reprompt (Phase 0) makes it non-fatal.
- **Critic infinite loop / cost** → hard 2-round cap + tool-call cap.
- **yfinance flakiness/rate limits** → per-tool try/except + graceful degradation; cache within a run.
- **W&B inference latency** → retry/backoff + per-call timeout; fast tier for specialists, smart tier for critic/arbiter/conviction.
- **Demo reliability** → deterministic guardrails + fallbacks mean a run always reaches a verdict.

## Out of scope (v2)
Live (non-paper) trading, multi-ticker portfolios, backtesting/P&L attribution, auth, paid data. Captured as future work.
