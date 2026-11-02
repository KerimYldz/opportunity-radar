"""Reddit public Atom feeds (listing + search). No login, no JSON API, no scraping of HTML.

Reddit serves these feeds publicly for feed readers. We identify ourselves with a
descriptive User-Agent, batch subreddits into one request, and stay under the
anonymous rate limit. For heavier or commercial use, switch to the official OAuth API.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime
from urllib.parse import quote_plus

from defusedxml import ElementTree as ET

from ..http import PoliteClient, RequestBudgetExceeded
from ..models import RawPost
from .base import Collector

log = logging.getLogger(__name__)

ATOM = "{http://www.w3.org/2005/Atom}"
SEARCH_BASE = "https://www.reddit.com"


def search_url(query: str, subreddits: list[str] | None = None) -> str:
    q = quote_plus(query)
    if subreddits:
        return f"{SEARCH_BASE}/r/{'+'.join(subreddits)}/search.rss?q={q}&restrict_sr=on&sort=new&t=week&limit=50"
    return f"{SEARCH_BASE}/search.rss?q={q}&sort=new&t=week&limit=50"


_TAG_RE = re.compile(r"<[^>]+>")
_SUBMITTED_RE = re.compile(r"submitted by\s+/u/\S+.*$", re.IGNORECASE | re.DOTALL)


def html_to_text(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"<br\s*/?>|</p>|</li>", "\n", text, flags=re.IGNORECASE)
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _SUBMITTED_RE.sub("", text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse_atom(xml_text: str, feed_label: str) -> list[RawPost]:
    root = ET.fromstring(xml_text)
    posts: list[RawPost] = []
    for entry in root.findall(f"{ATOM}entry"):
        link_el = entry.find(f"{ATOM}link")
        url = link_el.get("href") if link_el is not None else None
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        entry_id = entry.findtext(f"{ATOM}id") or ""
        # Search feeds also return subreddits (t5_) and users; keep only posts.
        if not url or not title or "/comments/" not in url or (entry_id and not entry_id.startswith("t3_")):
            continue
        published_raw = entry.findtext(f"{ATOM}published") or ""
        published = None
        try:
            published = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
        except ValueError:
            pass
        category = entry.find(f"{ATOM}category")
        sub = category.get("label") if category is not None else None
        author = entry.findtext(f"{ATOM}author/{ATOM}name")
        posts.append(
            RawPost(
                source="reddit",
                source_detail=sub or feed_label,
                url=url,
                title=html.unescape(title),
                body=html_to_text(entry.findtext(f"{ATOM}content") or ""),
                author=author,
                published_at=published,
                date_verified=published is not None,
                external_id=entry_id or None,
            )
        )
    return posts


class RedditRSSCollector(Collector):
    name = "reddit_rss"

    def __init__(self, cfg: dict, client: PoliteClient | None = None):
        super().__init__()
        self.cfg = cfg
        self.client = client or PoliteClient(
            user_agent=cfg["user_agent"],
            min_interval=cfg.get("min_interval_seconds", 8),
            max_requests=cfg.get("max_requests_per_run", 8),
        )

    def feed_urls(self) -> list[tuple[str, str]]:
        urls = [(f["name"], f["url"]) for f in self.cfg.get("feeds", [])]
        for s in self.cfg.get("searches", []):
            label = "search:" + ("+".join(s["subreddits"]) if s.get("subreddits") else "all")
            urls.append((label, search_url(s["query"], s.get("subreddits"))))
        return urls

    def collect(self) -> list[RawPost]:
        posts: list[RawPost] = []
        for label, url in self.feed_urls():
            try:
                resp = self.client.get(url)
            except RequestBudgetExceeded:
                self.errors.append(f"reddit: request budget exhausted before {label}")
                break
            except Exception as exc:  # noqa: BLE001
                self.errors.append(f"reddit {label}: {type(exc).__name__}")
                continue
            if resp.status_code != 200:
                msg = f"reddit {label}: HTTP {resp.status_code}"
                log.warning(msg)
                self.errors.append(msg)
                if resp.status_code == 403:
                    break  # blocked; stop instead of hammering
                continue
            try:
                got = parse_atom(resp.text, label)
            except ET.ParseError as exc:
                self.errors.append(f"reddit {label}: bad feed ({exc})")
                continue
            log.info("reddit %s: %d entries", label, len(got))
            posts.extend(got)
        return posts
