"""Telegram inbox: analyze posts the owner shares with the bot (Facebook, Nextdoor, anything).

This is how Facebook/Nextdoor leads get in without any scraping: you copy a post you can
already see and send it to your own bot. Only messages from TELEGRAM_CHAT_ID are processed;
anyone else who finds the bot is ignored. Links in messages are never opened.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .dedup import lead_id
from .models import RawPost
from .notifier import TelegramError, TelegramNotifier, format_lead
from .pipeline import Pipeline, RunReport

log = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PLATFORMS = {
    "facebook.com": "facebook", "fb.com": "facebook", "fb.me": "facebook", "fb.watch": "facebook",
    "nextdoor.com": "nextdoor", "craigslist.org": "craigslist", "reddit.com": "reddit",
    "bsky.app": "bluesky", "x.com": "x", "twitter.com": "x", "instagram.com": "instagram",
}
OFFSET_KEY = "telegram_update_offset"

HELP = (
    "<b>Opportunity Radar inbox</b>\n"
    "Send me a post you found (Facebook, Nextdoor, anywhere) in ONE message:\n"
    "1. the post link\n2. the post text (copy it from the app)\n\n"
    "I check my inbox on every scheduled run (about every 15 minutes) and reply with the "
    "suitability score, scam risk and a suggested price. I never contact the poster."
)
NEED_TEXT = (
    "Got the link, but I also need the post text — I don't open Facebook/Nextdoor links myself. "
    "Copy the post text and send the link and the text together in one message."
)
NEED_LINK = "Please include the link to the original post together with its text, so the lead keeps its source."


def platform_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for domain, name in PLATFORMS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host.removeprefix("www.") or "unknown"


@dataclass
class InboxReport:
    received: int = 0
    analyzed: int = 0
    ignored: int = 0


def parse_message(text: str) -> tuple[str | None, str]:
    urls = URL_RE.findall(text)
    url = urls[0].rstrip(").,>\"'") if urls else None
    body = URL_RE.sub(" ", text).strip()
    return url, body


def process_inbox(notifier: TelegramNotifier, pipeline: Pipeline, owner_chat_id: str) -> InboxReport:
    store = pipeline.store
    report = InboxReport()
    offset = store.get_meta(OFFSET_KEY)
    updates = notifier.get_updates(offset=int(offset) + 1 if offset else None)
    for update in updates:
        # Advance first: a message that crashes analysis must not be retried forever.
        store.set_meta(OFFSET_KEY, update["update_id"])
        msg = update.get("message") or {}
        if str((msg.get("chat") or {}).get("id")) != str(owner_chat_id):
            report.ignored += 1
            continue
        report.received += 1
        text = (msg.get("text") or msg.get("caption") or "").strip()
        reply_to = msg.get("message_id")
        try:
            if not text or text.startswith("/"):
                notifier.send(HELP, reply_to=reply_to)
                continue
            url, body = parse_message(text)
            if not url:
                notifier.send(NEED_LINK, reply_to=reply_to)
                continue
            if len(body) < 20:
                notifier.send(NEED_TEXT, reply_to=reply_to)
                continue
            lid = lead_id(url)
            known = store.has(lid)
            if not known:
                post = RawPost(
                    source=f"{platform_for(url)} (manual)",
                    source_detail="shared via Telegram",
                    url=url,
                    title=body.splitlines()[0][:120],
                    body=body,
                    published_at=None,
                    date_verified=False,
                )
                pipeline.ingest([post], RunReport(fetched=1))
            row = store.get(lid)
            header = "ALREADY ANALYZED — ASSESSMENT" if known else "MANUAL LEAD — ASSESSMENT"
            notifier.send(format_lead(row, json.loads(row["analysis_json"]), header=header), reply_to=reply_to)
            store.set_notify_state(lid, "sent")
            report.analyzed += 1
        except TelegramError as exc:
            log.error("inbox reply failed: %s", exc)
    return report
