# Autonomous Investment Committee

Multi-agent system where AI analysts debate, vote, and execute live paper trades.

## Architecture

```
UserQuery
    ↓
[Market Data Fetch — yfinance]
    ↓
Round 1: Parallel Debate
  ┌─────────────────────────────────────────┐
  │  BullAgent  BearAgent  RiskAgent  MacroAgent  │
  └─────────────────────────────────────────┘
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
pip install -r requirements.txt
cp .env.example .env
# Fill in your API keys
python main.py
```

## API Keys needed
- `ANTHROPIC_API_KEY`
- `WANDB_API_KEY`
- `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` (paper trading)

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
- **Anthropic Claude** — all agent reasoning (claude-sonnet-4-20250514)
- **Alpaca** — paper trade execution
