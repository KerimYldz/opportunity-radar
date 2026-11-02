"""Telegram inbox and Bluesky parsing. All messages and posts are MOCK data."""

import json

from opportunity_radar import filters
from opportunity_radar.inbox import NEED_TEXT, parse_message, platform_for, process_inbox
from opportunity_radar.pipeline import Pipeline, RunReport
from opportunity_radar.sources.bluesky import parse_search

OWNER = "111"


class FakeBot:
    def __init__(self, updates):
        self.updates = updates
        self.sent: list[tuple[str, int | None]] = []
        self.offsets = []

    def get_updates(self, offset=None):
        self.offsets.append(offset)
        return [u for u in self.updates if offset is None or u["update_id"] >= offset]

    def send(self, text, reply_to=None):
        self.sent.append((text, reply_to))


def msg(uid, text, chat=OWNER):
    return {"update_id": uid, "message": {"message_id": uid * 10, "chat": {"id": int(chat), "type": "private"}, "text": text}}


FB_POST = ("https://www.facebook.com/groups/mock/posts/123 MOCK: Does anyone know someone who can help me "
           "organize my small business customer list in Excel? Lots of duplicates. Happy to pay. Cherry Hill.")


def test_platform_detection():
    assert platform_for("https://m.facebook.com/groups/x/posts/1") == "facebook"
    assert platform_for("https://nextdoor.com/p/abc") == "nextdoor"
    assert platform_for("https://example.org/x") == "example.org"


def test_parse_message_splits_link_and_text():
    url, body = parse_message(FB_POST)
    assert url == "https://www.facebook.com/groups/mock/posts/123"
    assert body.startswith("MOCK: Does anyone")


def test_inbox_analyzes_owner_post_and_replies(settings, store):
    bot = FakeBot([msg(1, FB_POST)])
    report = process_inbox(bot, Pipeline(settings, store, bot), OWNER)
    assert report.analyzed == 1
    text, reply_to = bot.sent[0]
    assert "MANUAL LEAD — ASSESSMENT" in text and reply_to == 10
    row = store.conn.execute("SELECT * FROM leads").fetchone()
    assert row["source"] == "facebook (manual)"
    assert json.loads(row["analysis_json"])["suitability"] >= 75


def test_inbox_ignores_strangers(settings, store):
    bot = FakeBot([msg(1, FB_POST, chat="999")])
    report = process_inbox(bot, Pipeline(settings, store, bot), OWNER)
    assert report.ignored == 1 and not bot.sent


def test_inbox_link_without_text_asks_for_text(settings, store):
    bot = FakeBot([msg(1, "https://www.facebook.com/share/p/mock1/")])
    process_inbox(bot, Pipeline(settings, store, bot), OWNER)
    assert bot.sent[0][0] == NEED_TEXT


def test_inbox_does_not_reprocess(settings, store):
    bot = FakeBot([msg(5, FB_POST)])
    p = Pipeline(settings, store, bot)
    process_inbox(bot, p, OWNER)
    process_inbox(bot, p, OWNER)
    assert len(bot.sent) == 1
    assert bot.offsets[-1] == 6


def test_shared_posts_are_not_resent_as_alerts(settings, store):
    bot = FakeBot([msg(1, FB_POST)])
    p = Pipeline(settings, store, bot)
    process_inbox(bot, p, OWNER)
    bot.sent.clear()
    p.notify(RunReport())
    assert bot.sent == []


MOCK_BSKY = {"posts": [
    {"uri": "at://did:plc:mock/app.bsky.feed.post/3mockaaa", "author": {"handle": "mock.bsky.social"},
     "indexedAt": "2026-11-02T10:00:00.000Z",
     "record": {"text": "MOCK: willing to pay someone to fix my Excel budget spreadsheet, formulas are broken", "langs": ["en"]}},
    {"uri": "at://did:plc:mock/app.bsky.feed.post/3mockbbb", "author": {"handle": "mock.bsky.social"},
     "indexedAt": "2026-11-02T10:00:00.000Z",
     "record": {"text": "MOCK reply", "reply": {"parent": {}}}},
    {"uri": "at://did:plc:mock/app.bsky.feed.post/3mockccc", "author": {"handle": "mock.bsky.social"},
     "indexedAt": "2026-11-02T10:00:00.000Z",
     "record": {"text": "MOCK: just made a spreadsheet of my books lol", "langs": ["en"]}},
]}


def test_bluesky_parse_skips_replies():
    posts = parse_search(MOCK_BSKY, "test")
    assert [p.url for p in posts] == ["https://bsky.app/profile/mock.bsky.social/post/3mockaaa",
                                      "https://bsky.app/profile/mock.bsky.social/post/3mockccc"]
    assert posts[0].date_verified


def test_bluesky_chatter_capped_but_hire_intent_passes(settings):
    hire, chatter = parse_search(MOCK_BSKY, "test")
    assert filters.analyze(hire, settings, age_hours=1).suitability >= 75
    assert filters.analyze(chatter, settings, age_hours=1).suitability <= 60
