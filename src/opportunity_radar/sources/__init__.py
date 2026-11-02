"""Source collectors. Each collector only uses permitted, public access methods."""

from __future__ import annotations

import logging

from ..models import RawPost
from .base import Collector
from .bluesky import BlueskyCollector
from .reddit_rss import RedditRSSCollector

log = logging.getLogger(__name__)


def build_collectors(settings: dict) -> list[Collector]:
    sources = settings.get("sources", {})
    collectors: list[Collector] = []
    for name, cfg in sources.items():
        if not cfg.get("enabled"):
            log.info("source %s is disabled", name)
        elif name == "reddit_rss":
            collectors.append(RedditRSSCollector(cfg))
        elif name == "bluesky":
            collectors.append(BlueskyCollector(cfg))
    return collectors


def collect_all(collectors: list[Collector]) -> tuple[list[RawPost], list[str]]:
    """Run every collector; one failing source never stops the others."""
    posts: list[RawPost] = []
    errors: list[str] = []
    for collector in collectors:
        try:
            got = collector.collect()
            log.info("%s returned %d posts", collector.name, len(got))
            posts.extend(got)
            errors.extend(collector.errors)
        except Exception as exc:  # noqa: BLE001 - isolate source failures
            log.exception("collector %s failed", collector.name)
            errors.append(f"{collector.name}: {type(exc).__name__}: {exc}")
    return posts, errors
