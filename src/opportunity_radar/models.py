"""Core data types shared by collectors, analyzers and storage."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime


@dataclass
class RawPost:
    """A post exactly as retrieved from a source. Treated as untrusted input."""

    source: str                       # platform, e.g. "reddit", "facebook (manual)"
    source_detail: str                # e.g. "r/forhire"
    url: str
    title: str
    body: str
    author: str | None = None
    published_at: datetime | None = None   # tz-aware UTC; None when not verifiable
    date_verified: bool = False             # True only if the source itself states the date
    external_id: str | None = None


@dataclass
class ScamSignal:
    code: str
    weight: int
    evidence: str                     # short snippet of the text that triggered it


@dataclass
class ScamAssessment:
    score: int
    band: str
    signals: list[ScamSignal] = field(default_factory=list)
    uncertain: bool = False
    explanation: str = ""


@dataclass
class Assessment:
    """Result of the rule-based (Stage 1) analysis. AI fields arrive in Phase 2."""

    intent: str                       # "request" | "offer" | "unclear"
    categories: list[str]
    passed: bool                      # passed Stage 1 filtering
    reject_reason: str | None
    suitability: int
    suitability_reasons: list[str]
    remote: str                       # "remote" | "local-ok" | "local-outside" | "unknown"
    complexity: str                   # "low" | "medium" | "high"
    advertised_budget: str | None     # verbatim from the post, never invented
    est_price_low: int | None         # rule-based estimate, USD
    est_price_high: int | None
    est_hours: float | None           # includes communication / QA / revision overhead
    scam: ScamAssessment
    recency: int = 0
    priority: int = 0
    analysis_mode: str = "rules"      # "rules" until an AI provider is configured

    def to_dict(self) -> dict:
        return asdict(self)
