from opportunity_radar.sources.reddit_rss import RedditRSSCollector, html_to_text, parse_atom, search_url

# MOCK feed shaped like Reddit's Atom output.
MOCK_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <author><name>/u/mock_author</name></author>
    <category term="slavelabour" label="r/slavelabour"/>
    <content type="html">&lt;!-- SC_OFF --&gt;&lt;div class="md"&gt;&lt;p&gt;MOCK need my excel sheet fixed. $30&lt;/p&gt;&lt;/div&gt; submitted by &lt;a href="https://www.reddit.com/user/mock_author"&gt; /u/mock_author &lt;/a&gt; [link] [comments]</content>
    <id>t3_mock01</id>
    <link href="https://www.reddit.com/r/slavelabour/comments/mock01/task_mock/"/>
    <updated>2026-11-02T10:00:00+00:00</updated>
    <published>2026-11-02T09:30:00+00:00</published>
    <title>[TASK] MOCK fix excel sheet</title>
  </entry>
  <entry><title>no link entry</title></entry>
</feed>"""


def test_parse_atom():
    posts = parse_atom(MOCK_FEED, "test")
    assert len(posts) == 1
    p = posts[0]
    assert p.title == "[TASK] MOCK fix excel sheet"
    assert p.source_detail == "r/slavelabour"
    assert p.body == "MOCK need my excel sheet fixed. $30"
    assert p.published_at.isoformat() == "2026-11-02T09:30:00+00:00"
    assert p.date_verified


def test_html_to_text_strips_submitted_by():
    assert html_to_text("&lt;p&gt;Hello&lt;/p&gt; submitted by /u/x [link]") == "Hello"


def test_search_url_encoding():
    u = search_url('"need help" excel', ["philadelphia", "southjersey"])
    assert u.startswith("https://www.reddit.com/r/philadelphia+southjersey/search.rss?q=%22need+help%22+excel")
    assert "restrict_sr=on" in u and "sort=new" in u


class FakeResp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return self.responses.pop(0)


def test_collector_stops_on_403():
    cfg = {"user_agent": "test", "feeds": [{"name": "a", "url": "https://x/a"}, {"name": "b", "url": "https://x/b"}]}
    client = FakeClient([FakeResp(403)])
    c = RedditRSSCollector(cfg, client=client)
    assert c.collect() == []
    assert client.calls == 1 and "HTTP 403" in c.errors[0]


def test_collector_continues_after_429():
    cfg = {"user_agent": "test", "feeds": [{"name": "a", "url": "https://x/a"}, {"name": "b", "url": "https://x/b"}]}
    c = RedditRSSCollector(cfg, client=FakeClient([FakeResp(429), FakeResp(200, MOCK_FEED)]))
    assert len(c.collect()) == 1
