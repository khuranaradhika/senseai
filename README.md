# Autonomous Investment Committee

Multi-agent system where AI analysts debate, vote, and execute live paper trades.

## Architecture

```
UserQuery
    ↓
[Market Data Fetch — yfinance]
    ↓
Round 1: Parallel Debate
  ┌───────────────────────────────────────────────┐
  │  BullAgent  BearAgent  RiskAgent  MacroAgent  │
  └───────────────────────────────────────────────┘
    ↓
Round 2: Rebuttals (Bull sees Bear, Bear sees Bull)
    ↓
Vote Tally (3:1 consensus OR Chair tiebreak)
    ↓
ComplianceAgent (can block or reduce position)
    ↓
ExecutionAgent → Alpaca Paper Trade
    ↓
W&B + Weave full trace
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys
python main.py
```

> Note: this project now uses `alpaca-py` instead of the legacy `alpaca-trade-api` package.
> Note: LLM reasoning is served through W&B model access, not Anthropic.

## Example `.env`

```env
WANDB_API_KEY=your_wandb_api_key
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets
```

## API Keys needed
- `WANDB_API_KEY`
- `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` (paper trading)

## LLM configuration
This project uses the W&B inference API for all LLM calls.

- Set `WANDB_API_KEY` in `.env` to your Weights & Biases API key.
- The code uses:
  - `deepseek/deepseek-v4-flash` for specialist agents
  - `deepseek/deepseek-v4-0324` for Chair and Compliance
- If you need to use a different W&B model, update `FAST_MODEL` or `SMART_MODEL` in `src/core/llm.py`.
- Make sure your W&B account has access to the inference models configured in the code.

## Troubleshooting
- If the app fails on LLM calls, confirm `WANDB_API_KEY` is set in `.env` and matches the key in your W&B account.
- Verify your W&B account has inference access to the selected models (`deepseek/deepseek-v4-flash`, `deepseek/deepseek-v4-0324`).
- If you receive `401 Unauthorized`, regenerate your W&B API key and restart with the updated `.env` file.
- If Alpaca calls fail, confirm `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, and `ALPACA_BASE_URL` are correct for paper trading.
- Use `python main.py` from an activated virtual environment after installing requirements.

## What makes this a sophisticated harness

1. **Dynamic routing** — ChairAgent routes to tiebreak or consensus path based on vote outcome
2. **Agent-to-agent communication** — BullAgent sees BearAgent's thesis in round 2 and responds directly
3. **Feedback/interrupt loop** — ComplianceAgent can block ExecutionAgent regardless of committee decision
4. **Parallel execution** — Round 1 fires all 4 agents simultaneously via ThreadPoolExecutor
5. **Live execution consequence** — Alpaca paper trade fires as the terminal action
6. **Deep W&B instrumentation** — Every agent call, vote, rebuttal, and compliance decision is traced

## Demo script

```python
from src.core.orchestrator import run_committee
from src.core.schemas import CommitteeConfig

state = run_committee(
    query="Should we go long on NVDA given AI capex supercycle?",
    ticker="NVDA",
    config=CommitteeConfig(max_position_usd=1000.0)
)
print(state.final_vote, state.trade_executed)
```

## Sponsor tools used
- **W&B Weave** — full agent tracing, evaluation scoring, debate round observability
- **W&B inference** — all agent reasoning and model calls via the W&B API
- **Alpaca** — paper trade execution
