"""SQLite: seen article ids + snapshots for cross-run dedup."""
import logging
import re
import sqlite3
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import feedparser

from config import DB_PATH, FEEDS

log = logging.getLogger(__name__)

_DEDUP_RECENT_TTL_SEC = 48 * 3600


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS seen_articles "
        "(id TEXT PRIMARY KEY, sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS dedup_recent ("
        "article_id TEXT PRIMARY KEY, "
        "title TEXT NOT NULL, "
        "summary TEXT NOT NULL, "
        "sort_epoch INTEGER NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dedup_recent_epoch ON dedup_recent(sort_epoch)")
    conn.execute("DELETE FROM seen_articles WHERE sent_at < datetime('now', '-7 days')")
    cutoff = int(time.time()) - _DEDUP_RECENT_TTL_SEC
    conn.execute("DELETE FROM dedup_recent WHERE sort_epoch < ?", (cutoff,))
    conn.commit()
    return conn


def get_new_articles(conn):
    new_articles = []
    for feed_url in FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                article_id = entry.get("id") or entry.get("link")
                if not article_id:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM seen_articles WHERE id = ?", (article_id,)
                ).fetchone()
                if not exists:
                    published = entry.get("published_parsed")
                    if published:
                        dt = datetime(*published[:6], tzinfo=timezone.utc)
                    else:
                        dt = datetime.now(timezone.utc)
                    dt_local = dt.astimezone(ZoneInfo("Europe/Warsaw"))
                    new_articles.append({
                        "id": article_id,
                        "link": entry.get("link") or article_id,
                        "title": entry.get("title", ""),
                        "summary": re.sub(r"<[^>]+>", "", entry.get("summary", "")),
                        "source": feed.feed.get("title", feed_url),
                        "date": dt_local.strftime("%d.%m.%Y %H:%M"),
                        "sort_key": dt,
                    })
        except Exception as e:
            log.error(f"Failed to fetch {feed_url}: {e}")
    return new_articles
