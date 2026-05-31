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


@dataclass
class AgentFinding:
    agent_name: str
    thesis: str
    key_points: list[str]
    confidence: float  # 0.0 - 1.0
    vote: Vote
    supporting_data: dict = field(default_factory=dict)
    rebuttal: Optional[str] = None  # populated in round 2


@dataclass
class DebateState:
    ticker: str
    query: str
    market_data: Optional[MarketData]
    round: DebateRound
    findings: list[AgentFinding] = field(default_factory=list)
    rebuttals: list[AgentFinding] = field(default_factory=list)
    votes: dict[str, Vote] = field(default_factory=dict)
    chair_decision: Optional[str] = None
    final_vote: Optional[Vote] = None
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
