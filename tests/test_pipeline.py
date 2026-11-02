import json

from opportunity_radar.notifier import TelegramError, format_lead
from opportunity_radar.pipeline import Pipeline

from .conftest import mock_post


class FakeNotifier:
    def __init__(self, fail=False):
        self.sent: list[str] = []
        self.fail = fail

    def send(self, text):
        if self.fail:
            raise TelegramError("MOCK failure")
        self.sent.append(text)


def good_posts():
    return [
        mock_post(),
        mock_post(title="[Task] MOCK convert 30 PDF invoices to Excel",
                  body="MOCK: I need someone to extract data from 30 PDF invoices into one Excel spreadsheet. Paying $60, remote.",
                  url="https://www.reddit.com/r/slavelabour/comments/mock002/x/"),
    ]


def test_second_run_does_not_resend(settings, store):
    notifier = FakeNotifier()
    p = Pipeline(settings, store, notifier)
    r1 = p.run(good_posts())
    assert r1.notified == 2
    r2 = p.run(good_posts())
    assert r2.new == 0 and r2.known == 2
    assert r2.notified == 0
    assert len(notifier.sent) == 2


def test_same_post_via_different_url_form_is_known(settings, store):
    p = Pipeline(settings, store, FakeNotifier())
    p.run([mock_post()])
    alt = mock_post(url="https://old.reddit.com/r/slavelabour/comments/MOCK001/?utm=1")
    assert p.run([alt]).known == 1


def test_repost_with_new_url_is_not_notified(settings, store):
    notifier = FakeNotifier()
    p = Pipeline(settings, store, notifier)
    p.run([mock_post()])
    repost = mock_post(url="https://www.reddit.com/r/DoneDirtCheap/comments/mock999/repost/")
    r = p.run([repost])
    assert r.duplicates == 1 and r.notified == 0
    assert len(notifier.sent) == 1


def test_failed_send_is_retried_next_run(settings, store):
    failing = FakeNotifier(fail=True)
    p = Pipeline(settings, store, failing)
    r1 = p.run([mock_post()])
    assert r1.notified == 0 and r1.errors
    ok = FakeNotifier()
    p.notifier = ok
    r2 = p.run([])
    assert r2.notified == 1


def test_cold_start_limits_alerts(settings, store):
    settings["notifications"]["cold_start_max"] = 1
    notifier = FakeNotifier()
    p = Pipeline(settings, store, notifier)
    r = p.run(good_posts())
    assert r.cold_start and r.notified == 1
    states = {row["notify_state"] for row in store.conn.execute("SELECT notify_state FROM leads")}
    assert states == {"sent", "suppressed"}


def test_high_scam_and_offers_not_notified(settings, store):
    notifier = FakeNotifier()
    p = Pipeline(settings, store, notifier)
    scammy = mock_post(title="[Task] MOCK easy Excel data entry",
                       body="MOCK: I will send you a check, deposit the check, then buy gift cards. Pay $50.",
                       url="https://www.reddit.com/r/slavelabour/comments/mock003/x/")
    offer = mock_post(title="[For Hire] MOCK Excel wizard", body="MOCK: hire me, my rates are low.",
                      url="https://www.reddit.com/r/forhire/comments/mock004/x/")
    r = p.run([scammy, offer])
    assert r.notified == 0 and r.new == 2


def test_unknown_date_not_notified_by_default(settings, store):
    p = Pipeline(settings, store, FakeNotifier())
    assert p.run([mock_post(hours_ago=None)]).notified == 0


def test_old_post_never_notified(settings, store):
    p = Pipeline(settings, store, FakeNotifier())
    assert p.run([mock_post(hours_ago=72)]).notified == 0


def test_notification_contains_required_fields(settings, store):
    notifier = FakeNotifier()
    Pipeline(settings, store, notifier).run([mock_post()])
    msg = notifier.sent[0]
    for needle in ["YENİ İŞ", "MOCK need help cleaning up my Excel", "MOCK: I have an Excel spreadsheet",
                   "Reddit · r/slavelabour", "saat önce", "Bütçe: $50", "Önerilen fiyat:", "Tahmini süre:",
                   "Uygunluk:", "Dolandırıcılık riski:", "uzaktan yapılabilir", "comments/mock001"]:
        assert needle in msg


def test_html_in_post_is_escaped(settings, store):
    notifier = FakeNotifier()
    post = mock_post(title="[Task] MOCK <b>Excel</b> help <script>", url="https://www.reddit.com/r/slavelabour/comments/mock005/x/")
    Pipeline(settings, store, notifier).run([post])
    assert "<script>" not in notifier.sent[0]


def test_times_shown_in_new_york():
    from datetime import datetime, timezone
    from opportunity_radar.notifier import local_time
    # 2026-11-02 is after DST ended, so New York is UTC-5 (EST).
    assert local_time(datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)) == "Nov 02, 12:00 PM EST"
    assert local_time(datetime(2026, 7, 1, 16, 0, tzinfo=timezone.utc)) == "Jul 01, 12:00 PM EDT"
