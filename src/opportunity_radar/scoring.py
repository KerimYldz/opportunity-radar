"""Lead priority = weighted mix of suitability, recency, economics, scam safety, remote fit."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import Assessment

DEFAULT_WEIGHTS = {"suitability": 0.30, "recency": 0.25, "economic": 0.20, "scam_safety": 0.15, "remote": 0.10}
UNKNOWN_DATE_RECENCY = 20  # conservative penalty when the post date cannot be verified


def age_hours(published_at: datetime | None, now: datetime | None = None) -> float | None:
    if published_at is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - published_at).total_seconds() / 3600)


def recency_score(hours: float | None) -> int:
    if hours is None:
        return UNKNOWN_DATE_RECENCY
    for limit, score in ((3, 100), (12, 90), (24, 80), (48, 60), (96, 30), (168, 10)):
        if hours <= limit:
            return score
    return 0


def economic_score(a: Assessment) -> int:
    if a.est_price_low is None:
        return 20
    mid = (a.est_price_low + a.est_price_high) / 2
    # Sweet spot $30-200; bigger jobs are usually also riskier and slower to land.
    if mid < 30:
        score = 30
    elif mid <= 200:
        score = 50 + (mid - 30) / 170 * 50
    else:
        score = 70
    if a.est_hours and a.est_hours > 0:
        hourly = mid / a.est_hours
        if hourly < 15:
            score -= 20
    return int(max(0, min(100, score)))


REMOTE_SCORES = {"remote": 100, "remote-likely": 85, "local-ok": 70, "unknown": 50, "local-outside": 0}


def priority(a: Assessment, hours: float | None, weights: dict | None = None) -> int:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    parts = {
        "suitability": a.suitability,
        "recency": recency_score(hours),
        "economic": economic_score(a),
        "scam_safety": 100 - a.scam.score,
        "remote": REMOTE_SCORES.get(a.remote, 50),
    }
    return int(round(sum(parts[k] * w[k] for k in parts)))
