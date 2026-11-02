"""Collect -> dedup -> Stage 1 analysis -> score -> store -> notify."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import dedup, filters, scoring
from .models import Assessment, RawPost
from .notifier import TelegramError, TelegramNotifier, format_lead
from .storage import Store

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    fetched: int = 0
    known: int = 0
    new: int = 0
    passed: int = 0
    duplicates: int = 0
    eligible: int = 0
    notified: int = 0
    cold_start: bool = False
    errors: list[str] = field(default_factory=list)


def is_eligible(a: Assessment, hours: float | None, ncfg: dict, duplicate_of: str | None) -> bool:
    if not a.passed or duplicate_of:
        return False
    if a.suitability < ncfg.get("min_suitability", 75):
        return False
    if a.scam.score > ncfg.get("max_scam_risk", 40) and not ncfg.get("include_high_risk", False):
        return False
    if hours is None:
        return bool(ncfg.get("allow_unknown_date", False))
    return hours <= ncfg.get("max_age_hours", 48)


class Pipeline:
    def __init__(self, settings: dict, store: Store, notifier: TelegramNotifier | None):
        self.settings = settings
        self.store = store
        self.notifier = notifier
        self.ncfg = settings.get("notifications", {})
        self.dcfg = settings.get("dedup", {})

    def find_duplicate(self, post: RawPost, fp: str, recent: list) -> tuple[str | None, int]:
        """Return (id of earlier near-identical lead, how many copies exist)."""
        exact = self.store.by_fingerprint(fp)
        if exact:
            return exact[0]["id"], len(exact)
        mine = dedup.shingles(f"{post.title} {post.body}")
        threshold = self.dcfg.get("similarity_threshold", 0.85)
        matches = [r["id"] for r in recent if dedup.jaccard(mine, dedup.shingles(f"{r['title']} {r['body']}")) >= threshold]
        return (matches[0] if matches else None), len(matches)

    def ingest(self, posts: list[RawPost], report: RunReport, now: datetime | None = None) -> list[str]:
        """Analyze and store unseen posts. Returns ids of leads that became 'pending'."""
        now = now or datetime.now(timezone.utc)
        recent = list(self.store.recent_texts(self.dcfg.get("lookback_days", 30)))
        pending: list[str] = []
        seen_this_run: set[str] = set()
        for post in posts:
            lid = dedup.lead_id(post.url)
            if lid in seen_this_run or self.store.has(lid):
                report.known += 1
                continue
            seen_this_run.add(lid)
            fp = dedup.fingerprint(post.title, post.body)
            duplicate_of, copies = self.find_duplicate(post, fp, recent)
            hours = scoring.age_hours(post.published_at, now)
            a = filters.analyze(post, self.settings, repost_count=copies, age_hours=hours)
            a.recency = scoring.recency_score(hours)
            a.priority = scoring.priority(a, hours, self.settings.get("priority_weights"))
            eligible = is_eligible(a, hours, self.ncfg, duplicate_of)
            self.store.insert({
                "id": lid,
                "canonical_url": dedup.canonical_url(post.url),
                "url": post.url,
                "source": post.source,
                "source_detail": post.source_detail,
                "title": post.title,
                "body": post.body,
                "author": post.author,
                "published_at": post.published_at,
                "date_verified": int(post.date_verified),
                "discovered_at": now,
                "fingerprint": fp,
                "duplicate_of": duplicate_of,
                "passed": int(a.passed),
                "reject_reason": a.reject_reason,
                "suitability": a.suitability,
                "scam_score": a.scam.score,
                "priority": a.priority,
                "analysis_json": a.to_dict(),
                "notify_state": "pending" if eligible else "ineligible",
            })
            recent.append({"id": lid, "title": post.title, "body": post.body})
            report.new += 1
            report.passed += a.passed
            report.duplicates += duplicate_of is not None
            if eligible:
                pending.append(lid)
        report.eligible = len(pending)
        return pending

    def notify(self, report: RunReport, dry_run: bool = False) -> None:
        max_age = self.ncfg.get("max_age_hours", 48)
        rows = self.store.pending_notifications(max_age_hours=max_age)
        if report.cold_start:
            keep = self.ncfg.get("cold_start_max", 3)
            for row in rows[keep:]:
                self.store.set_notify_state(row["id"], "suppressed")
            rows = rows[:keep]
            log.info("cold start: alerting on top %d, suppressed the rest", len(rows))
        rows = rows[: self.ncfg.get("max_per_run", 10)]
        for row in rows:
            analysis = json.loads(row["analysis_json"])
            hours = scoring.age_hours(datetime.fromisoformat(row["published_at"])) if row["published_at"] else None
            if hours is not None and hours > max_age:
                self.store.set_notify_state(row["id"], "expired")
                continue
            text = format_lead(row, analysis)
            if dry_run or self.notifier is None:
                log.info("[dry-run] would notify: %s (%s)", row["title"], row["url"])
                continue
            try:
                self.notifier.send(text)
            except TelegramError as exc:
                report.errors.append(str(exc))
                log.error("notification failed, will retry next run: %s", exc)
                break
            self.store.set_notify_state(row["id"], "sent")
            report.notified += 1

    def run(self, posts: list[RawPost], dry_run: bool = False) -> RunReport:
        report = RunReport(fetched=len(posts))
        report.cold_start = self.store.is_empty()
        self.ingest(posts, report)
        self.notify(report, dry_run=dry_run)
        return report
