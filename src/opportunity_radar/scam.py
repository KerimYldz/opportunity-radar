"""Evidence-based scam-risk scoring.

Each signal carries a weight and the text snippet that triggered it. Weak signals are
capped low so a single weak hint never makes a post look fraudulent. A low score means
"no warning signs found", never "verified legitimate".
"""

from __future__ import annotations

import re

from .models import ScamAssessment, ScamSignal

# (code, weight, pattern). Weights >= 25 are strong signals; <= 15 are weak.
SIGNALS: list[tuple[str, int, str]] = [
    ("upfront_payment", 35, r"\b(registration|training|starter|activation|processing)\s+fee\b|\bpay\s+(a\s+)?(small\s+)?fee\b|\bpay\s+to\s+(start|join)\b"),
    ("fake_check", 40, r"\b(cashier'?s?|certified)\s+check\b|\bsend\s+you\s+a\s+check\b|\bdeposit\s+(the|this|a)\s+check\b|\bmobile\s+deposit\b"),
    ("gift_cards", 35, r"\bgift\s?cards?\b|\bitunes\s+cards?\b|\bsteam\s+cards?\b"),
    ("crypto_payment", 25, r"\b(bitcoin|btc|usdt|crypto(currency)?|ethereum|eth wallet|binance)\b"),
    ("bank_details", 35, r"\b(routing\s+number|bank\s+(account\s+)?(details|info|login|credentials)|account\s+number)\b"),
    ("identity_docs", 25, r"\b(ssn|social\s+security|copy\s+of\s+(your\s+)?(id|passport|driver'?s?\s+licen[cs]e)|passport\s+(photo|scan))\b"),
    ("buy_equipment", 30, r"\b(purchase|buy)\s+(the\s+)?(equipment|software|supplies|starter\s+kit)\b.*\b(reimburs|refund)|\breimburs\w*\b.*\b(purchase|buy)\b"),
    ("money_movement", 35, r"\b(receive|transfer|forward)\s+(funds|payments?|money)\s+(for|on behalf)\b|\bpayment\s+processing\s+agent\b|\bmoney\s+mule\b"),
    ("off_platform_chat", 12, r"\b(whats\s?app|telegram|signal\s+app|text\s+me\s+(on|at)\s+\+?\d)\b"),
    ("earn_hype", 15, r"\bearn\s+\$?\d[\d,]*\s*(\+|or more)?\s*(per|a|/)\s*(day|week|hour)\b|\bmake\s+\$\d[\d,]*\s*(daily|a day|per day)\b|\bpassive\s+income\b"),
    ("recruitment_style", 12, r"\b(multiple|several)\s+(positions|openings|roles)\b|\bjoin\s+our\s+(growing\s+)?team\b|\bwe\s+are\s+(hiring|recruiting)\s+(many|several|\d+)\b"),
    ("link_shortener", 15, r"\b(bit\.ly|tinyurl\.com|t\.co|cutt\.ly|rb\.gy|is\.gd|shorturl\.at)/"),
    ("unpaid_trial", 10, r"(?<!no\s)\bunpaid\s+(sample|trial|test)\b"),
    ("urgency_pressure", 8, r"\b(act\s+now|limited\s+spots|first\s+\d+\s+people|today\s+only)\b"),
]

_COMPILED = [(c, w, re.compile(p, re.IGNORECASE | re.DOTALL)) for c, w, p in SIGNALS]
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?\b", re.IGNORECASE)
_TRIVIAL = re.compile(r"\b(easy|simple|quick|5\s*min(ute)?s?|no\s+experience|anyone\s+can)\b", re.IGNORECASE)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)


def band(score: int) -> str:
    if score <= 25:
        return "Low apparent risk"
    if score <= 50:
        return "Some concerns"
    if score <= 75:
        return "High concern"
    return "Very high concern"


def _snippet(text: str, match: re.Match, pad: int = 30) -> str:
    start, end = max(0, match.start() - pad), min(len(text), match.end() + pad)
    return " ".join(text[start:end].split())


def money_amounts(text: str) -> list[float]:
    amounts = []
    for m in _MONEY.finditer(text):
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if m.group(2):
            value *= 1000
        amounts.append(value)
    return amounts


def assess(title: str, body: str, repost_count: int = 0) -> ScamAssessment:
    text = f"{title}\n{body}"
    signals: list[ScamSignal] = []
    for code, weight, rx in _COMPILED:
        m = rx.search(text)
        if m:
            signals.append(ScamSignal(code, weight, _snippet(text, m)))

    amounts = money_amounts(text)
    trivial = _TRIVIAL.search(text)
    if amounts and trivial and max(amounts) >= 1000:
        signals.append(ScamSignal("pay_too_high_for_trivial", 25, f"${max(amounts):,.0f} offered for work described as '{trivial.group(0)}'"))

    links = _URL.findall(text)
    if len(links) >= 4:
        signals.append(ScamSignal("many_external_links", 10, f"{len(links)} external links"))

    if repost_count >= 2:
        signals.append(ScamSignal("repetitive_ad", 20, f"near-identical text seen {repost_count} times"))

    score = min(100, sum(s.weight for s in signals))
    # Several independent signals reinforce each other; a lone weak one does not.
    if len(signals) == 1 and signals[0].weight <= 15:
        score = min(score, 15)

    uncertain = len(body.strip()) < 60
    if signals:
        parts = "; ".join(f"{s.code} (\"{s.evidence[:70]}\")" for s in signals)
        explanation = f"{band(score)}. Signals: {parts}."
    else:
        explanation = "No known warning signs found in the text. This does not verify the poster or the job."
    if uncertain:
        explanation += " Post text is very short, so the risk is uncertain."
    return ScamAssessment(score=score, band=band(score), signals=signals, uncertain=uncertain, explanation=explanation)
