import os
import asyncio
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import wandb
import weave

load_dotenv()

from src.core.schemas import CommitteeConfig, DebateState
from src.core.orchestrator import run_committee
from src.core.evaluation import log_debate_summary

app = FastAPI(title="Autonomous Investment Committee")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

weave.init("investment-committee")


def state_to_json(state: DebateState) -> dict:
    """Serialize DebateState to JSON-safe dict."""
    return {
        "ticker": state.ticker,
        "query": state.query,
        "market_data": {
            "summary": state.market_data.summary if state.market_data else "",
            "current_price": state.market_data.current_price if state.market_data else 0,
            "price_change_pct": state.market_data.price_change_pct if state.market_data else 0,
            "rsi": state.market_data.rsi if state.market_data else None,
            "macd_signal": state.market_data.macd_signal if state.market_data else None,
        } if state.market_data else {},
        "findings": [
            {
                "agent_name": f.agent_name,
                "thesis": f.thesis,
                "key_points": f.key_points,
                "confidence": f.confidence,
                "vote": f.vote.value,
            }
            for f in state.findings
        ],
        "rebuttals": [
            {
                "agent_name": f.agent_name,
                "thesis": f.thesis,
                "rebuttal": f.rebuttal,
                "confidence": f.confidence,
                "vote": f.vote.value,
            }
            for f in state.rebuttals
        ],
        "votes": {k: v.value for k, v in state.votes.items()},
        "final_vote": state.final_vote.value if state.final_vote else None,
        "chair_decision": state.chair_decision,
        "position_size": state.position_size,
        "compliance_approved": state.compliance_approved,
        "compliance_reason": state.compliance_reason,
        "trade_executed": state.trade_executed,
        "trade_result": state.trade_result,
    }


async def stream_committee(ticker: str, query: str):
    """
    Run committee and stream SSE events for each stage.
    Each event has a 'stage' and 'data' field.
    """
    config = CommitteeConfig(
        ticker=ticker,
        max_position_usd=1000.0,
        consensus_threshold=3,
        min_confidence_to_trade=0.6,
    )

    def sse(event_type: str, data: dict) -> str:
        return f"data: {json.dumps({'type': event_type, **data})}\n\n"

    yield sse("status", {"message": f"Fetching market data for {ticker}..."})
    await asyncio.sleep(0.1)

    # Run in thread to not block event loop
    loop = asyncio.get_event_loop()
    state = await loop.run_in_executor(
        None, lambda: run_committee(query=query, ticker=ticker, config=config)
    )

    # Stream market data
    if state.market_data:
        yield sse("market_data", {
            "summary": state.market_data.summary,
            "price": state.market_data.current_price,
            "change_pct": state.market_data.price_change_pct,
            "rsi": state.market_data.rsi,
            "macd": state.market_data.macd_signal,
        })
        await asyncio.sleep(0.3)

    # Stream round 1 findings
    yield sse("status", {"message": "Round 1: Initial positions..."})
    for finding in state.findings:
        yield sse("finding", {
            "agent": finding.agent_name,
            "thesis": finding.thesis,
            "key_points": finding.key_points,
            "confidence": finding.confidence,
            "vote": finding.vote.value,
            "round": 1,
        })
        await asyncio.sleep(0.4)

    # Stream rebuttals
    yield sse("status", {"message": "Round 2: Rebuttals..."})
    for rebuttal in state.rebuttals:
        yield sse("finding", {
            "agent": rebuttal.agent_name,
            "thesis": rebuttal.rebuttal or rebuttal.thesis,
            "confidence": rebuttal.confidence,
            "vote": rebuttal.vote.value,
            "round": 2,
        })
        await asyncio.sleep(0.4)

    # Stream votes
    yield sse("votes", {
        "votes": {k: v.value for k, v in state.votes.items()},
        "final_vote": state.final_vote.value if state.final_vote else None,
        "chair_decision": state.chair_decision,
        "position_size": state.position_size,
    })
    await asyncio.sleep(0.4)

    # Stream compliance
    yield sse("compliance", {
        "approved": state.compliance_approved,
        "reason": state.compliance_reason,
        "adjusted_size": state.position_size,
    })
    await asyncio.sleep(0.4)

    # Stream execution result
    yield sse("execution", {
        "executed": state.trade_executed,
        "result": state.trade_result,
        "final_vote": state.final_vote.value if state.final_vote else None,
        "position_size": state.position_size,
    })

    # Log to W&B
    summary = log_debate_summary(state)
    yield sse("complete", {"summary": summary})


@app.get("/run")
async def run_endpoint(ticker: str = "NVDA", query: str = "Should we take a position?"):
    return StreamingResponse(
        stream_committee(ticker.upper(), query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/", response_class=HTMLResponse)
async def root():
    with open("ui/index.html") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=True)
