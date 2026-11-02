"""Deduplication by canonical URL and content similarity."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlparse

_REDDIT_ID = re.compile(r"/comments/([a-z0-9]+)", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9$]+")


def canonical_url(url: str) -> str:
    """Lower-case host, drop query/fragment/trailing slash; collapse reddit URLs to the post id."""
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower()
    if host.startswith(("old.", "new.", "np.", "m.")) and "reddit.com" in host:
        host = "www.reddit.com"
    if host == "reddit.com":
        host = "www.reddit.com"
    if host.endswith("redd.it") or "reddit.com" in host:
        m = _REDDIT_ID.search(parsed.path)
        if m:
            return f"https://www.reddit.com/comments/{m.group(1).lower()}"
        if host.endswith("redd.it"):
            return f"https://www.reddit.com/comments/{parsed.path.strip('/').lower()}"
    path = parsed.path.rstrip("/") or "/"
    return f"https://{host}{path}"


def lead_id(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def normalize(text: str) -> str:
    return " ".join(_WORD.findall(text.lower()))


def fingerprint(title: str, body: str) -> str:
    return hashlib.sha1(normalize(f"{title} {body}").encode()).hexdigest()


def shingles(text: str, k: int = 3) -> set[str]:
    words = normalize(text).split()
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + k]) for i in range(len(words) - k + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
