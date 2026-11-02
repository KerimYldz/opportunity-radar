"""Daily digest. All posts are MOCK data."""

from datetime import datetime, timezone

from opportunity_radar.digest import maybe_send_digest
from opportunity_radar.pipeline import Pipeline

from .conftest import mock_post

EVENING = datetime(2026, 11, 2, 23, 30, tzinfo=timezone.utc)   # 6:30 PM New York
MORNING = datetime(2026, 11, 2, 14, 0, tzinfo=timezone.utc)    # 9:00 AM New York


class Bot:
    def __init__(self):
        self.sent = []

    def send(self, text, reply_to=None):
        self.sent.append(text)


def near_miss():
    # Long-term wording lowers suitability below the instant-alert threshold.
    return mock_post(title="MOCK looking for ongoing Excel help, long-term",
                     body="MOCK: Need someone for long-term Excel and data entry help, a few hours a week. Paying $20/hr, remote.",
                     url="https://www.reddit.com/r/slavelabour/comments/mockd01/x/")


def test_digest_sent_once_after_6pm_new_york(settings, store):
    bot = Bot()
    Pipeline(settings, store, bot).run([near_miss()])
    assert not maybe_send_digest(settings, store, bot, now=MORNING)
    assert maybe_send_digest(settings, store, bot, now=EVENING)
    assert not maybe_send_digest(settings, store, bot, now=EVENING)
    msg = bot.sent[-1]
    assert "GÜNLÜK ÖZET" in msg and "ongoing Excel help" in msg and "comments/mockd01" in msg


def test_digest_says_so_when_nothing_close(settings, store):
    bot = Bot()
    assert maybe_send_digest(settings, store, bot, now=EVENING)
    assert "Eşiğe yakın ilan da çıkmadı" in bot.sent[0]


def test_alerted_leads_not_repeated_in_digest(settings, store):
    bot = Bot()
    Pipeline(settings, store, bot).run([mock_post()])
    maybe_send_digest(settings, store, bot, now=datetime.now(timezone.utc).replace(hour=23, minute=30))
    assert "comments/mock001" not in bot.sent[-1]
