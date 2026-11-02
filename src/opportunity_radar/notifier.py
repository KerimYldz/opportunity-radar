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


# Messages are in Turkish for the owner; the poster's own words stay in the original language.
CATEGORY_TR = {
    "spreadsheet": "Excel / tablo", "google_sheets": "Google Sheets", "pdf_documents": "PDF / belge",
    "data_cleaning": "veri girişi / temizleme", "files_csv": "dosya / CSV düzenleme",
    "computer_help": "bilgisayar yardımı", "website": "web sitesi", "dashboard_report": "rapor / dashboard",
    "automation_script": "otomasyon / script", "extraction": "veri çıkarma",
}
REMOTE_TR = {
    "remote": "uzaktan yapılabilir", "remote-likely": "muhtemelen uzaktan yapılabilir",
    "local-ok": "yüz yüze (senin bölgende)", "local-outside": "yüz yüze (bölge dışı)", "unknown": "uzaktan mı belli değil",
}
COMPLEXITY_TR = {"low": "basit", "medium": "orta", "high": "büyük / uzun soluklu"}
BAND_TR = {"Low apparent risk": "düşük görünüyor", "Some concerns": "bazı şüpheler var",
           "High concern": "yüksek şüphe", "Very high concern": "çok yüksek şüphe"}
SIGNAL_TR = {
    "upfront_payment": "başlamak için ücret istiyor", "fake_check": "çek gönderme / bozdurma",
    "gift_cards": "hediye kartı", "crypto_payment": "kripto ile ödeme", "bank_details": "banka bilgisi istiyor",
    "identity_docs": "kimlik / SSN istiyor", "buy_equipment": "ekipman al, geri öderiz diyor",
    "money_movement": "para aktarımı", "off_platform_chat": "WhatsApp/Telegram'a çağırıyor",
    "earn_hype": "abartılı kazanç vaadi", "recruitment_style": "toplu eleman alımı dili",
    "link_shortener": "kısaltılmış link", "urgency_pressure": "acele baskısı", "unpaid_trial": "ücretsiz deneme işi",
    "pay_too_high_for_trivial": "basit iş için çok yüksek ücret", "many_external_links": "çok sayıda dış link",
    "repetitive_ad": "aynı ilan tekrar tekrar paylaşılmış",
}


def format_age(published_iso: str | None, verified: bool) -> str:
    if not published_iso:
        return "tarihi bilinmiyor"
    published = datetime.fromisoformat(published_iso)
    hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600
    age = f"{int(hours * 60)} dk" if hours < 1 else f"{hours:.0f} saat" if hours < 48 else f"{hours / 24:.0f} gün"
    return f"{age} önce ({local_time(published)})"


def source_label(row) -> str:
    source = row["source"] or ""
    if source.endswith("(manual)"):
        return f"{source.removesuffix(' (manual)').capitalize()} (senin gönderdiğin)"
    if source == "reddit":
        return f"Reddit · {row['source_detail']}"
    return source.capitalize()


def scam_line(scam: dict) -> str:
    band = BAND_TR.get(scam["band"], scam["band"])
    signals = [SIGNAL_TR.get(s["code"], s["code"]) for s in scam.get("signals", [])]
    if signals:
        text = f"{scam['score']}/100, {band}: {', '.join(signals)}"
    else:
        text = f"{scam['score']}/100, uyarı işareti yok (kişinin güvenilir olduğu anlamına gelmez)"
    if scam.get("uncertain"):
        text += ". Metin çok kısa, emin olmak zor"
    return text


def format_lead(row, analysis: dict, header: str = "🔔 YENİ İŞ") -> str:
    scam = analysis["scam"]
    body = (row["body"] or "").strip()
    excerpt = body[:350] + ("…" if len(body) > 350 else "")
    cats = ", ".join(CATEGORY_TR.get(c, c) for c in analysis["categories"]) or "belirsiz"
    budget = analysis.get("advertised_budget")
    price = (f"${analysis['est_price_low']}–{analysis['est_price_high']}"
             if analysis.get("est_price_low") is not None else "tahmin yok")
    summary = (f"{source_label(row)}, {format_age(row['published_at'], bool(row['date_verified']))}. "
               f"{cats.capitalize()} işi, {COMPLEXITY_TR.get(analysis['complexity'], '')}, "
               f"{REMOTE_TR.get(analysis['remote'], analysis['remote'])}.")
    lines = [
        f"<b>{_e(header)}</b>",
        "",
        f"<b>{_e(row['title'])}</b>",
        f"<i>{_e(excerpt)}</i>" if excerpt and excerpt != row["title"] else "",
        "",
        f"🇹🇷 {_e(summary)}",
        f"💵 Bütçe: {_e(budget) + ' (ilanda yazıyor)' if budget else 'yazmamış'} · Önerilen fiyat: {_e(price)}",
        f"⏱ Tahmini süre: ~{analysis['est_hours']} saat (iletişim ve kontrol dahil)" if analysis.get("est_hours") else "",
        f"✅ Uygunluk: {analysis['suitability']}/100",
        f"🛡 Dolandırıcılık riski: {_e(scam_line(scam))}",
        "",
        f"<a href=\"{html.escape(row['url'])}\">👉 İlanı aç</a>",
    ]
    return "\n".join(line for i, line in enumerate(lines) if line or (i and lines[i - 1]))
