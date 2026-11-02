"""Telegram notifications to the owner only. Never messages prospective customers."""

from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000


class TelegramError(RuntimeError):
    pass


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, timeout: float = 15.0):
        self._token = token
        self.chat_id = chat_id
        self.timeout = timeout

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "<redacted>") if self._token else text

    def _call(self, method: str, payload: dict) -> dict:
        url = API.format(token=self._token, method=method)
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            # Exception messages can embed the URL, which contains the token.
            raise TelegramError(self._redact(f"{type(exc).__name__}: {exc}")) from None
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        if resp.status_code != 200 or not data.get("ok"):
            raise TelegramError(f"Telegram {method} failed: HTTP {resp.status_code} {data.get('description', '')}")
        return data

    def send(self, text: str, reply_to: int | None = None) -> None:
        if len(text) > MAX_LEN:
            text = text[: MAX_LEN - 20] + "\n…(truncated)"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_to:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        self._call("sendMessage", payload)

    def get_updates(self, offset: int | None = None) -> list[dict]:
        payload = {"timeout": 0, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        return self._call("getUpdates", payload).get("result", [])

    def get_me(self) -> dict:
        return self._call("getMe", {}).get("result", {})


DISPLAY_TZ = ZoneInfo(os.getenv("RADAR_TIMEZONE") or "America/New_York")


def local_time(dt: datetime) -> str:
    """Human-facing timestamps use the owner's time zone (New York by default)."""
    return dt.astimezone(DISPLAY_TZ).strftime("%b %d, %I:%M %p %Z")


def _e(value) -> str:
    return html.escape(str(value), quote=False)


def format_age(published_iso: str | None, verified: bool) -> str:
    if not published_iso:
        return "UNKNOWN (publication date not verifiable)"
    published = datetime.fromisoformat(published_iso)
    hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    age = f"{int(hours * 60)} min" if hours < 1 else f"{hours:.1f} h" if hours < 48 else f"{hours / 24:.1f} days"
    return f"{age} ago ({local_time(published)}{', from source' if verified else ', unverified'})"


def format_lead(row, analysis: dict, header: str = "OPPORTUNITY RADAR — NEW LEAD") -> str:
    scam = analysis["scam"]
    price = (
        f"${analysis['est_price_low']}–${analysis['est_price_high']} (rule-based estimate)"
        if analysis.get("est_price_low") is not None else "n/a"
    )
    hours = f"~{analysis['est_hours']} h incl. communication, QA, revisions" if analysis.get("est_hours") else "n/a"
    body = (row["body"] or "").strip()
    excerpt = body[:500] + ("…" if len(body) > 500 else "")
    lines = [
        f"<b>{_e(header)}</b>",
        "",
        f"<b>{_e(row['title'])}</b>",
        f"<b>Source:</b> {_e(row['source'])} · {_e(row['source_detail'] or '')}",
        f"<b>Post age:</b> {_e(format_age(row['published_at'], bool(row['date_verified'])))}",
        f"<b>Request (excerpt from post):</b> {_e(excerpt) or '(no body text)'}",
        f"<b>Advertised budget:</b> {_e(analysis.get('advertised_budget') or 'not stated')}",
        f"<b>Suggested price:</b> {_e(price)}",
        f"<b>Est. time:</b> {_e(hours)}",
        f"<b>Categories:</b> {_e(', '.join(analysis['categories']))} · complexity {_e(analysis['complexity'])}",
        f"<b>Suitability:</b> {analysis['suitability']}/100 · <b>Priority:</b> {analysis['priority']}/100",
        f"<b>Scam risk:</b> {scam['score']}/100 — {_e(scam['explanation'])}",
        f"<b>Remote/local:</b> {_e(analysis['remote'])}",
        f"<b>Analysis:</b> {_e(analysis.get('analysis_mode', 'rules'))} (AI summary unavailable in rule-based mode)",
        "",
        f"<a href=\"{html.escape(row['url'])}\">Open original post</a>",
        _e(row["url"]),
    ]
    return "\n".join(lines)
