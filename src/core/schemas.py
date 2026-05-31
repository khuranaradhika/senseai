from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class Vote(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class DebateRound(Enum):
    INITIAL = "initial"
    REBUTTAL = "rebuttal"


@dataclass
class MarketData:
    ticker: str
    current_price: float
    price_change_pct: float
    volume: float
    avg_volume: float
    week_52_high: float
    week_52_low: float
    pe_ratio: Optional[float]
    market_cap: Optional[float]
    rsi: Optional[float]
    macd_signal: Optional[str]  # "bullish" | "bearish" | "neutral"
    summary: str
    as_of: Optional[str] = None  # date of the latest price bar (data freshness)


@dataclass
class AgentFinding:
    agent_name: str
    thesis: str
    key_points: list[str]
    confidence: float  # 0.0 - 1.0
    vote: Vote
    rebuttal: Optional[str] = None  # populated in round 2
    round: int = 1
    changed_vote: bool = False  # did this agent change its vote vs its last round?


@dataclass
class Intent:
    """Structured understanding of the user's query."""
    raw_query: str
    horizon_bucket: Optional[str] = None   # SHORT | MEDIUM | LONG | VERY_LONG
    horizon_detail: Optional[str] = None   # e.g. "~2 weeks", "about 5 years"
    horizon_detected: bool = False
    direction: Optional[str] = None        # long | short | trim | open
    risk_tolerance: Optional[str] = None   # conservative | moderate | aggressive
    catalysts: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    interpretation: str = ""               # human-readable one-liner


@dataclass
class DebateState:
    ticker: str
    query: str
    market_data: Optional[MarketData]
    round: DebateRound
    intent: Optional[Intent] = None
    # Full iterative debate: transcript[i] is the list of findings from round i+1.
    transcript: list[list[AgentFinding]] = field(default_factory=list)
    chair_notes: list[str] = field(default_factory=list)  # one moderation note per round
    rounds_run: int = 0
    consensus_reached: bool = False
    # findings = round 1 positions; rebuttals = final round positions (kept for
    # backward-compat with evaluation.py / W&B logging). votes = final votes.
    findings: list[AgentFinding] = field(default_factory=list)
    rebuttals: list[AgentFinding] = field(default_factory=list)
    votes: dict[str, Vote] = field(default_factory=dict)
    chair_decision: Optional[str] = None
    final_vote: Optional[Vote] = None
    conviction: Optional[float] = None  # chair's confidence in the final call
    position_size: Optional[float] = None
    trade_executed: bool = False
    trade_result: Optional[dict] = None
    compliance_approved: bool = False
    compliance_reason: Optional[str] = None


@dataclass
class CommitteeConfig:
    max_debate_rounds: int = 2
    consensus_threshold: int = 3  # out of 4 votes needed
    max_position_usd: float = 1000.0
    min_confidence_to_trade: float = 0.6
    ticker: str = "NVDA"
