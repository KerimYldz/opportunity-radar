"""Bluesky public search API (app.bsky.feed.searchPosts on api.bsky.app). No login needed.

Bluesky's AppView API is public and documented. Posts there are mostly conversation, so
everything from this source must show explicit hiring intent to pass the alert gate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from ..http import PoliteClient, RequestBudgetExceeded
from ..models import RawPost
from .base import Collector

log = logging.getLogger(__name__)

API = "https://api.bsky.app/xrpc/app.bsky.feed.searchPosts"


def post_url(uri: str, handle: str) -> str | None:
    # at://did:plc:xxx/app.bsky.feed.post/<rkey>
    parts = uri.split("/")
    if len(parts) < 5 or parts[3] != "app.bsky.feed.post":
        return None
    return f"https://bsky.app/profile/{handle}/post/{parts[4]}"


def parse_search(data: dict, label: str) -> list[RawPost]:
    posts: list[RawPost] = []
    for p in data.get("posts", []):
        record = p.get("record") or {}
        if record.get("reply"):
            continue  # replies are almost always conversation, not requests
        langs = record.get("langs")
        if langs and "en" not in langs:
            continue
        handle = (p.get("author") or {}).get("handle", "")
        url = post_url(p.get("uri", ""), handle)
        text = (record.get("text") or "").strip()
        if not url or not text:
            continue
        # indexedAt is set by Bluesky's servers; createdAt is whatever the client claims.
        published = None
        try:
            published = datetime.fromisoformat(p["indexedAt"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            pass
        first_line = text.splitlines()[0]
        posts.append(RawPost(
            source="bluesky",
            source_detail=label,
            url=url,
            title=first_line[:120],
            body=text,
            author=handle,
            published_at=published,
            date_verified=published is not None,
            external_id=p.get("uri"),
        ))
    return posts


class BlueskyCollector(Collector):
    name = "bluesky"

    def __init__(self, cfg: dict, client: PoliteClient | None = None):
        super().__init__()
        self.cfg = cfg
        self.client = client or PoliteClient(
            user_agent=cfg.get("user_agent", "opportunity-radar/0.1"),
            min_interval=cfg.get("min_interval_seconds", 1),
            max_requests=cfg.get("max_requests_per_run", 20),
        )

    def collect(self) -> list[RawPost]:
        since = (datetime.now(timezone.utc) - timedelta(days=self.cfg.get("since_days", 3))).strftime("%Y-%m-%dT%H:%M:%SZ")
        posts: list[RawPost] = []
        for query in self.cfg.get("queries", []):
            url = f"{API}?{urlencode({'q': query, 'sort': 'latest', 'limit': 50, 'since': since})}"
            try:
                resp = self.client.get(url)
            except RequestBudgetExceeded:
                self.errors.append("bluesky: request budget exhausted")
                break
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"bluesky: {type(exc).__name__}")
                continue
            if resp.status_code != 200:
                self.errors.append(f"bluesky '{query}': HTTP {resp.status_code}")
                if resp.status_code in (401, 403):
                    break
                continue
            try:
                got = parse_search(resp.json(), f"search: {query}")
            except ValueError:
                self.errors.append(f"bluesky '{query}': bad JSON")
                continue
            log.info("bluesky '%s': %d posts", query, len(got))
            posts.extend(got)
        return posts
