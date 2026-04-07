import sqlite3
import time
from datetime import datetime, timedelta, timezone

import database


class _Feed:
    def __init__(self, entries, title="Feed"):
        self.entries = entries
        self.feed = {"title": title}


def _conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE seen_articles (id TEXT PRIMARY KEY, sent_at TEXT)")
    return c


def test_skips_and_marks_stale_rss_items(monkeypatch):
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=60)
    old_parsed = time.gmtime(old.timestamp())
    new_parsed = time.gmtime(now.timestamp())

    entries = [
        {
            "id": "old1",
            "link": "https://example.com/old",
            "title": "Old post",
            "summary": "x",
            "published_parsed": old_parsed,
        },
        {
            "id": "new1",
            "link": "https://example.com/new",
            "title": "New post",
            "summary": "y",
            "published_parsed": new_parsed,
        },
    ]

    monkeypatch.setattr(database, "FEEDS", ["https://feed.local/x"])
    monkeypatch.setattr(database.feedparser, "parse", lambda _url: _Feed(entries))

    c = _conn()
    out = database.get_new_articles(c)
    ids = {a["id"] for a in out}
    assert "new1" in ids
    assert "old1" not in ids

    row = c.execute("SELECT 1 FROM seen_articles WHERE id='old1'").fetchone()
    assert row is not None
