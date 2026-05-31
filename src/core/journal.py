"""
Decision journal + outcome evaluation (the real "ground truth" loop).

Every committee decision is persisted with its entry price. Later, `review()`
fetches the *forward* price for each open decision, computes the realized move,
labels whether the call was right, and rolls up decision-quality metrics
(hit rate, average forward return by vote, conviction calibration) — logging the
summary to W&B. This is the only place actual outcomes — not inputs — are scored.

Run scoring with:  python -m src.core.journal review
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.core.schemas import DebateState

DB_PATH = Path(__file__).resolve().parents[2] / "data" / "decisions.db"

# A decision "resolves" correct if the stock moved at least this much the right way.
_MOVE_BAND = 0.005  # 0.5%


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT, ticker TEXT, query TEXT, horizon TEXT,
            final_vote TEXT, conviction REAL, position_size REAL,
            consensus INTEGER, rounds INTEGER,
            executed INTEGER, order_id TEXT,
            entry_price REAL,
            -- filled in at review time:
            scored_ts TEXT, exit_price REAL, return_pct REAL, correct INTEGER
        )
        """
    )
    return conn


def record_decision(state: DebateState) -> Optional[int]:
    """Persist a finished decision. Best-effort — never raises into a run."""
    try:
        md = state.market_data
        conn = _conn()
        cur = conn.execute(
            """INSERT INTO decisions
               (ts, ticker, query, horizon, final_vote, conviction, position_size,
                consensus, rounds, executed, order_id, entry_price)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                state.ticker, state.query,
                state.intent.horizon_bucket if state.intent else None,
                state.final_vote.value if state.final_vote else None,
                state.conviction, state.position_size,
                int(bool(state.consensus_reached)), state.rounds_run,
                int(bool(state.trade_executed)),
                (state.trade_result or {}).get("order_id"),
                md.current_price if md else None,
            ),
        )
        conn.commit()
        rid = cur.lastrowid
        conn.close()
        return rid
    except Exception as e:  # noqa: BLE001
        print(f"[journal] record skipped: {e}")
        return None


def _is_correct(vote: str, return_pct: float) -> Optional[bool]:
    if vote == "BUY":
        return return_pct > _MOVE_BAND
    if vote == "SELL":
        return return_pct < -_MOVE_BAND
    if vote == "HOLD":
        return abs(return_pct) <= _MOVE_BAND  # holding was fine if it stayed flat
    return None


def review(min_age_hours: float = 0.0, log_wandb: bool = True) -> dict:
    """Score every un-scored decision against its forward price; return metrics."""
    from src.tools.market_data import fetch_market_data

    conn = _conn()
    rows = conn.execute("SELECT * FROM decisions WHERE scored_ts IS NULL").fetchall()
    now = datetime.now(timezone.utc)

    price_cache: dict[str, float] = {}
    scored = 0
    for r in rows:
        ts = datetime.fromisoformat(r["ts"])
        if (now - ts).total_seconds() / 3600.0 < min_age_hours:
            continue
        if not r["entry_price"]:
            continue
        ticker = r["ticker"]
        if ticker not in price_cache:
            try:
                price_cache[ticker] = fetch_market_data(ticker).current_price
            except Exception:
                continue
        exit_price = price_cache[ticker]
        ret = (exit_price - r["entry_price"]) / r["entry_price"]
        correct = _is_correct(r["final_vote"], ret)
        conn.execute(
            "UPDATE decisions SET scored_ts=?, exit_price=?, return_pct=?, correct=? WHERE id=?",
            (now.isoformat(), exit_price, ret, None if correct is None else int(correct), r["id"]),
        )
        scored += 1
    conn.commit()

    metrics = _aggregate(conn)
    conn.close()

    print(f"[journal] scored {scored} decision(s)")
    for k, v in metrics.items():
        print(f"  {k}: {v}")

    if log_wandb and scored:
        try:
            import wandb
            run = wandb.init(project="investment-committee", job_type="review", reinit=True)
            wandb.log(metrics)
            run.finish()
        except Exception as e:  # noqa: BLE001
            print(f"[journal] wandb review log skipped: {e}")

    return metrics


def _aggregate(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT * FROM decisions WHERE scored_ts IS NOT NULL").fetchall()
    if not rows:
        return {"scored_total": 0}

    directional = [r for r in rows if r["final_vote"] in ("BUY", "SELL") and r["correct"] is not None]
    correct = [r for r in directional if r["correct"] == 1]
    buys = [r for r in rows if r["final_vote"] == "BUY"]
    sells = [r for r in rows if r["final_vote"] == "SELL"]

    def avg(vals):
        vals = [v for v in vals if v is not None]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    return {
        "scored_total": len(rows),
        "directional_calls": len(directional),
        "hit_rate": round(len(correct) / len(directional), 3) if directional else 0.0,
        "avg_return_buy": avg([r["return_pct"] for r in buys]),
        "avg_return_sell": avg([r["return_pct"] for r in sells]),
        "avg_conviction_correct": avg([r["conviction"] for r in directional if r["correct"] == 1]),
        "avg_conviction_wrong": avg([r["conviction"] for r in directional if r["correct"] == 0]),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "review":
        min_age = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
        review(min_age_hours=min_age)
    else:
        print("usage: python -m src.core.journal review [min_age_hours]")
