"""
FastAPI server for the Investment Committee UI.

Serves ui/index.html and exposes /run as a Server-Sent Events (SSE) stream.
The frontend opens an EventSource to /run?ticker=&query=, and this server
runs the committee pipeline in a background thread, forwarding each stage
(market data, findings, votes, compliance, execution) to the browser live.
"""
import json
import queue
import threading
from pathlib import Path

import uvicorn
import weave
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse

from src.core.orchestrator import run_committee
from src.core.schemas import CommitteeConfig

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML = BASE_DIR / "ui" / "index.html"

# Weave tracing is best-effort — the UI still works if W&B isn't reachable.
try:
    weave.init("investment-committee")
except Exception as e:  # noqa: BLE001
    print(f"[server] weave.init skipped: {e}")

app = FastAPI(title="Investment Committee")


@app.get("/")
def index():
    return FileResponse(INDEX_HTML)


def _committee_stream(ticker: str, query: str):
    """Run the committee in a worker thread and yield SSE frames as events arrive."""
    events: "queue.Queue" = queue.Queue()
    SENTINEL = object()

    def emit(event: dict):
        events.put(event)

    def worker():
        try:
            config = CommitteeConfig(
                ticker=ticker,
                max_debate_rounds=2,
                consensus_threshold=3,
                max_position_usd=1000.0,
                min_confidence_to_trade=0.6,
            )
            run_committee(query=query, ticker=ticker, config=config, emit=emit)
        except Exception as e:  # noqa: BLE001
            events.put({"type": "status", "message": f"Error: {e}"})
        finally:
            events.put({"type": "complete"})
            events.put(SENTINEL)

    threading.Thread(target=worker, daemon=True).start()

    while True:
        event = events.get()
        if event is SENTINEL:
            break
        yield f"data: {json.dumps(event)}\n\n"


@app.get("/run")
def run(ticker: str = "NVDA", query: str = "Should we take a position?"):
    ticker = (ticker or "NVDA").strip().upper()
    return StreamingResponse(
        _committee_stream(ticker, query),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering so events flush live
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
