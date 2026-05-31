# TODO — Phase 0: Foundation & Guardrails (do first)

> These are the **guardrail todos** we start on now. They're the substrate the
> whole v2 pipeline ([plan.md](plan.md)) is built on — every agent depends on
> safe parsing, central config, and deterministic guardrails. Build + test these
> before any pipeline agents.

## Order of work

### 1. Central config — `src/core/config.py`
- [ ] Define one config object with all thresholds:
  - `CONVICTION_MIN = 0.70`, `AVG_CONF_MIN = 0.60`
  - `MAX_CRITIC_ROUNDS = 2`
  - `MAX_POSITION_USD = 1000.0`, `MAX_PORTFOLIO_PCT = 0.10`
  - `MAX_DAILY_TRADES = 5`, `MAX_TOOL_CALLS = 3`
  - model tiers: `FAST` / `SMART` (point at the W&B DeepSeek IDs already in [src/core/llm.py](src/core/llm.py))
- [ ] Load overrides from env; sensible defaults baked in.
- [ ] Remove the stale `"model": "claude-sonnet-..."` config in [main.py](main.py:18) — it's a leftover from the W&B migration.
- **Done when:** thresholds live in exactly one place and are imported, not duplicated.

### 2. Safe structured-output layer — `src/core/parsing.py`
- [ ] `parse_structured(raw: str, model: type[BaseModel]) -> BaseModel`:
  fence-strip → `json.loads` → Pydantic `model_validate`.
- [ ] On failure: **one reprompt** including the validation error, then re-parse.
- [ ] On second failure: raise a typed `StructuredParseError` (caller decides fallback).
- [ ] Replace every bare `json.loads(raw)` in the agents once Phase 2 lands.
- **Done when:** a deliberately malformed LLM response is repaired or fails cleanly — never crashes a run.

### 3. LLM resilience — `src/core/llm.py`
- [ ] Wrap the `requests.post` in retry w/ exponential backoff (3 attempts) on timeout / 5xx / connection error.
- [ ] Keep the existing 60s timeout; keep `call_llm` / `call_llm_structured` signatures stable.
- [ ] Optional: smart→fast model fallback on repeated failure.
- **Done when:** a transient W&B inference blip retries instead of killing the pipeline.

### 4. Deterministic guardrails — `src/core/guardrails.py`
- [ ] `check_execution(thesis, conviction, account, config) -> list[GuardrailCheck]`, enforced **in code** (not prompts):
  - [ ] **Confidence gate:** `conviction ≥ CONVICTION_MIN` AND `avg_specialist_confidence ≥ AVG_CONF_MIN` (this is the gate that's currently only advisory text).
  - [ ] **Position cap:** clamp notional to `MAX_POSITION_USD`.
  - [ ] **Portfolio cap:** notional ≤ `MAX_PORTFOLIO_PCT × equity`.
  - [ ] **Buying power:** sufficient cash (Alpaca account).
  - [ ] **Market hours:** Alpaca clock says open.
  - [ ] **Duplicate/conflicting position:** don't stack or reverse an open position blindly.
  - [ ] **Daily trade cap:** ≤ `MAX_DAILY_TRADES`.
  - [ ] **HOLD → skip** (no order).
- [ ] Any failed check ⇒ trade blocked, with the failing check name surfaced to the UI/trace.
- **Done when:** execution is impossible unless every deterministic check passes, regardless of what any LLM says.

### 5. Critic-loop bound (guardrail for cost/looping)
- [ ] Enforce `MAX_CRITIC_ROUNDS = 2` with a deterministic counter in the pipeline (Phase 3).
- [ ] After the cap: accept-with-flag or drop the finding — never loop indefinitely.
- **Done when:** a perpetually-rejected finding terminates deterministically.

### 6. Tests — `tests/` (pytest)
- [ ] `test_parsing.py` — fence-strip, valid parse, repair-on-bad-json, hard-fail path.
- [ ] `test_guardrails.py` — confidence gate blocks below threshold; position clamp; portfolio cap; HOLD skip; market-closed block.
- [ ] `test_critic_loop.py` — loop terminates at 2 rounds.
- **Done when:** `pytest` is green and covers every deterministic guardrail branch.

---

## After Phase 0
Proceed through [plan.md](plan.md): Phase 1 (tools) → Phase 2 (agents) → Phase 3 (pipeline + Weave) → Phase 4 (SSE + UI) → Phase 5 (retire legacy + demo polish).

## Definition of done (Phase 0)
- `config.py`, `parsing.py`, `guardrails.py` exist and are imported by nothing legacy.
- Thresholds enforced in code, not prompts.
- Malformed JSON and transient LLM errors are non-fatal.
- `pytest` green.
