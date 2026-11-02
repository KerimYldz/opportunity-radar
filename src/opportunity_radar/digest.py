"""Daily Telegram summary of leads that came close to the alert threshold.

Instant alerts stay strict; this lets the owner see near misses and know the radar is
alive on days when nothing qualifies. Sent once per local day, on the first run after
the configured hour (New York time by default).
"""

from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone

from .notifier import CATEGORY_TR, DISPLAY_TZ, TelegramNotifier, format_age, source_label
from .storage import Store

META_KEY = "digest_last_date"


def _e(value) -> str:
    return html.escape(str(value), quote=False)


def format_digest(rows, scanned: int, alerted: int, local_now: datetime) -> str:
    lines = [f"<b>📋 GÜNLÜK ÖZET · {local_now:%d %b}</b>",
             f"Son 24 saatte {scanned} ilan tarandı, {alerted} tanesi için bildirim gönderildi."]
    if not rows:
        lines.append("Eşiğe yakın ilan da çıkmadı. Sistem çalışıyor, uygun iş bekleniyor.")
        return "\n".join(lines)
    lines += ["Bildirim eşiğine yaklaşan en iyi ilanlar:", ""]
    for i, row in enumerate(rows, 1):
        cats = ", ".join(CATEGORY_TR.get(c, c) for c in (row["categories"] or "").split(",") if c) or "belirsiz"
        lines += [
            f"{i}. <b>{_e(row['title'][:90])}</b>",
            f"   {_e(source_label(row))} · {_e(format_age(row['published_at'], bool(row['date_verified'])))}",
            f"   {_e(cats)} · Uygunluk {row['suitability']} · Risk {row['scam_score']}",
            f"   <a href=\"{html.escape(row['url'])}\">👉 İlanı aç</a>",
        ]
    return "\n".join(lines)


def maybe_send_digest(settings: dict, store: Store, notifier: TelegramNotifier, now: datetime | None = None) -> bool:
    cfg = settings.get("digest", {})
    if not cfg.get("enabled", True):
        return False
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(DISPLAY_TZ)
    today = local_now.date().isoformat()
    if local_now.hour < cfg.get("hour", 18) or store.get_meta(META_KEY) == today:
        return False
    since = (now - timedelta(hours=24)).isoformat()
    alert_min = settings.get("notifications", {}).get("min_suitability", 75)
    rows = store.conn.execute(
        """SELECT *, json_extract(analysis_json, '$.categories') AS cats_json FROM leads
           WHERE discovered_at >= ? AND passed = 1 AND duplicate_of IS NULL
             AND notify_state != 'sent' AND source NOT LIKE '%(manual)'
             AND suitability >= ? AND suitability < ? AND scam_score <= ?
           ORDER BY priority DESC LIMIT ?""",
        (since, cfg.get("min_suitability", 55), alert_min, cfg.get("max_scam_risk", 40), cfg.get("max_items", 5)),
    ).fetchall()
    rows = [dict(r, categories=",".join(json.loads(r["cats_json"] or "[]"))) for r in rows]
    scanned = store.conn.execute("SELECT COUNT(*) FROM leads WHERE discovered_at >= ?", (since,)).fetchone()[0]
    alerted = store.conn.execute(
        "SELECT COUNT(*) FROM leads WHERE notified_at >= ? AND source NOT LIKE '%(manual)'", (since,)
    ).fetchone()[0]
    notifier.send(format_digest(rows, scanned, alerted, local_now))
    store.set_meta(META_KEY, today)
    return True
