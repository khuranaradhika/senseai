# SenseAI

A multi-agent **investment committee**: four data-driven AI analysts debate a ticker
across multiple rounds, change their minds on evidence (not on the headcount), and a
Chair synthesizes the call. The decision passes an LLM compliance review and a layer
of **deterministic guardrails** before a live Alpaca **paper** trade fires. Every step
is traced in W&B Weave, logged as W&B metrics, and journaled for later outcome scoring.

> ⚠️ Research/demo project on **paper trading** only. It is not investment advice and
> has no proven track record — see [Limitations](#limitations).

---

## How it works (high level)

```
User query + ticker + horizon + budget
        │
        ▼
 Intent parser ─ understands the query (time horizon, direction, risk, catalysts)
        │
        ▼
 Research ─ market data + fundamentals + sector + macro + news (yfinance)
        │
        ▼
 Iterative debate ─ Bull · Bear · Risk · Macro analysts argue in parallel
   ▲   │            (min 4 rounds, max 20; they may change their vote each round)
   └───┤  Chair moderates after every round (protects dissent, no headcount pressure)
        │  → ends when UNANIMOUS (after the 4-round floor), else Chair breaks the tie
        ▼
 Chair decision ─ final vote + position size + conviction
        │
        ▼
 Compliance (LLM)  →  Deterministic guardrails (enforced in code)
        │
        ▼
 Alpaca paper trade  →  W&B metrics + decision journal
```

Full detail in **[ARCHITECTURE.md](ARCHITECTURE.md)**. Design decisions and lessons in
**[LEARNINGS.md](LEARNINGS.md)**.

---

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env      # then fill in your keys
```

### `.env`

```env
# Weights & Biases (Inference + Weave) — https://wandb.ai/authorize
WANDB_API_KEY=your_wandb_key

# Alpaca paper trading — https://app.alpaca.markets  (Alpaca's standard APCA_* names)
APCA_API_KEY_ID=your_alpaca_key_id
APCA_API_SECRET_KEY=your_alpaca_secret
APCA_BASE_URL=https://paper-api.alpaca.markets
```

> The Alpaca client also accepts the legacy `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` /
> `ALPACA_BASE_URL` names as a fallback. `.env` is gitignored — never commit real keys.

---

## Run it

**Web UI (recommended):**
```bash
python server.py        # → http://127.0.0.1:8000
```
Enter a ticker, an investment query, a horizon (1 day → 20 years), and a max budget,
then **CONVENE**. Watch the debate stream live: a vote-trajectory matrix, collapsible
rounds, Chair moderation, the verdict, guardrail checks, and a W&B run link.

**CLI (demo tickers):**
```bash
python main.py
```

**Tests / smoke runner:**
```bash
python test.py                       # fast checks (no LLM): tools, guardrails, journal
python test.py committee NVDA SHORT --quick   # one full debate (2 rounds)
python -m pytest tests/ -q           # unit tests (parsing + guardrails)
```

**Score past decisions against forward prices** (run later, once time has passed):
```bash
python -m src.core.journal review
```

See **[SAMPLES.txt](SAMPLES.txt)** for showcase queries and configurations.

---

## LLM configuration

All reasoning runs through the **W&B Inference API** (OpenAI-compatible),
`https://api.inference.wandb.ai/v1`. Two tiers (in [src/core/config.py](src/core/config.py)):

| Tier | Model | Used by |
|------|-------|---------|
| Fast | `deepseek-ai/DeepSeek-V4-Flash` | the four analysts |
| Smart | `deepseek-ai/DeepSeek-V4-Pro` | intent parser, Chair, compliance |

Override with the `FAST_MODEL` / `SMART_MODEL` env vars. List available models:
```bash
curl https://api.inference.wandb.ai/v1/models -H "Authorization: Bearer $WANDB_API_KEY"
```

---

## Configuration knobs

All thresholds live in [src/core/config.py](src/core/config.py) and are env-overridable:

| Env var | Default | Meaning |
|---|---|---|
| `MIN_DEBATE_ROUNDS` | 4 | floor on debate rounds before consensus can end it |
| `MAX_DEBATE_ROUNDS` | 20 | hard ceiling on rounds |
| `CONVICTION_MIN` | 0.70 | execution gate — Chair conviction |
| `AVG_CONF_MIN` | 0.60 | execution gate — average analyst confidence |
| `MAX_POSITION_USD` | 1000 | global hard position cap (UI "Max Buy" overrides per-run) |
| `MAX_PORTFOLIO_PCT` | 0.10 | max fraction of equity per position |
| `MAX_DAILY_TRADES` | 5 | daily trade cap |
| `LLM_TIMEOUT_S` / `LLM_MAX_RETRIES` | 60 / 3 | LLM resilience |

---

## Observability

- **Weave** — every agent/tool call is a `@weave.op`, so a run is a full nested trace
  (intent → research → each round's analysts + Chair → decision → compliance → guardrails → trade).
- **W&B metrics** — each run logs decision + process-quality metrics (rounds, consensus,
  vote-changes, vote diversity, confidence). Fires from **both** the UI and CLI.
- **Decision journal** — every decision is persisted (SQLite, `data/decisions.db`) with its
  entry price; `journal review` scores it against the forward price (hit-rate, returns by
  vote, conviction calibration).

> The W&B/Weave **project** is named `investment-committee` (internal identifier).

---

## Guardrails (enforced in code, not prompts)

No order reaches Alpaca unless every deterministic check in
[src/core/guardrails.py](src/core/guardrails.py) passes: actionable direction (not HOLD),
**confidence gate**, **market open**, **daily-trade cap**, **no conflicting position**, and
sizing **clamped** to the tightest of position cap / portfolio % / buying power. If the
broker is unreachable, the trade is **blocked for safety**. The LLMs cannot override these.

---

## Limitations

- **No proven track record** — the journal can score outcomes, but there's no statistically
  meaningful sample yet. A robust *process* is not the same as good predictions.
- **LLM-dependent reasoning** — votes/conviction are self-reported and uncalibrated; agents
  can still hallucinate figures not present in the research brief.
- **Thin, third-party data** — single source (yfinance), delayed/last-close, home-rolled
  indicators (RSI uses Wilder's smoothing).
- **No real risk model** — sizing is bounded by caps, not vol-targeting / portfolio risk.
- **Demo-grade ops** — single-user server; no auth; per-run `wandb.init`.
- **Equities only** — no options/derivatives support.

---

## Sponsor tools

- **W&B Weave** — agent tracing & debate observability
- **W&B Inference** — all LLM reasoning (DeepSeek V4)
- **Alpaca** — paper-trade execution
