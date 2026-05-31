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
from fastapi.responses import FileResponse, Response, StreamingResponse

from src.core.orchestrator import run_committee
from src.core.schemas import CommitteeConfig
from src.core.evaluation import log_run_to_wandb
from src.core.journal import record_decision
from src.agents.intent import parse_intent

load_dotenv(override=True)

BASE_DIR = Path(__file__).resolve().parent
INDEX_HTML = BASE_DIR / "ui" / "index.html"

# Weave tracing is best-effort — the UI still works if W&B isn't reachable.
try:
    weave.init("investment-committee")
except Exception as e:  # noqa: BLE001
    print(f"[server] weave.init skipped: {e}")

app = FastAPI(title="SenseAI")


@app.get("/")
def index():
    return FileResponse(INDEX_HTML)


@app.get("/logo.png")
def logo():
    path = BASE_DIR / "ui" / "logo.png"
    if not path.exists():
        return Response(status_code=404)
    return FileResponse(path)


def _committee_stream(ticker: str, query: str, horizon: str, max_position: float):
    """Run the committee in a worker thread and yield SSE frames as events arrive."""
    events: "queue.Queue" = queue.Queue()
    SENTINEL = object()

    def emit(event: dict):
        events.put(event)

    def worker():
        try:
            # The UI always supplies an explicit horizon, which overrides inference;
            # the parser still extracts direction/risk/catalysts and the interpretation.
            intent = parse_intent(query, ticker, horizon_override=horizon)
            config = CommitteeConfig(ticker=ticker, max_position_usd=max_position)
            state = run_committee(query=query, ticker=ticker, config=config, emit=emit, intent=intent)

            # Persist the decision for later outcome scoring (the ground-truth loop).
            record_decision(state)

            # Log this run's metrics to W&B (separate from the Weave trace) so live
            # UI runs populate the dashboard too — not just CLI runs.
            logged = log_run_to_wandb(state)
            if logged:
                events.put({
                    "type": "metrics",
                    "scores": logged["scores"],
                    "wandb_url": logged["wandb_url"],
                })
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
def run(
    ticker: str = "NVDA",
    query: str = "Should we take a position?",
    horizon: str = "MEDIUM",
    max_position: float = 1000.0,
):
    ticker = (ticker or "NVDA").strip().upper()
    # Clamp the user-supplied budget to a sane paper-trading range.
    max_position = min(max(max_position, 1.0), 1_000_000.0)
    return StreamingResponse(
        _committee_stream(ticker, query, horizon, max_position),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering so events flush live
        },
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
