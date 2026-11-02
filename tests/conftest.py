"""Shared fixtures. ALL posts here are MOCK data written for tests, not real discoveries."""

from datetime import datetime, timedelta, timezone

import pytest

from opportunity_radar.config import DEFAULT_CONFIG, load_settings
from opportunity_radar.models import RawPost
from opportunity_radar.storage import Store

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def settings():
    return load_settings(DEFAULT_CONFIG)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


def mock_post(title="[Task] MOCK need help cleaning up my Excel customer list",
              body="MOCK: I have an Excel spreadsheet with ~800 customers and lots of duplicates. "
                   "Need someone to remove duplicates and fix the formatting. Will pay $50. Remote is fine.",
              url="https://www.reddit.com/r/slavelabour/comments/mock001/mock_task/",
              hours_ago=2, sub="r/slavelabour", author="/u/mock_user"):
    published = datetime.now(timezone.utc) - timedelta(hours=hours_ago) if hours_ago is not None else None
    return RawPost(source="reddit", source_detail=sub, url=url, title=title, body=body,
                   author=author, published_at=published, date_verified=published is not None)
