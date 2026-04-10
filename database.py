"""SQLite: seen article ids + snapshots for cross-run dedup."""
import logging
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import feedparser

from config import (
    DB_PATH,
    FEEDS,
    MAX_ARTICLE_AGE_HOURS,
    RATE_LIMIT_KEY_FUEL_TOURISM_DE_PL,
    RATE_LIMIT_KEY_TK_JUDGE_OATH,
    RATE_LIMIT_KEY_WEATHER,
)

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
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_post_rate ("
        "singleton INTEGER PRIMARY KEY CHECK (singleton = 1), "
        "last_sent_epoch INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS channel_rate_limits ("
        "rate_key TEXT PRIMARY KEY, "
        "last_sent_epoch INTEGER NOT NULL)"
    )
    _migrate_weather_rate_to_channel_limits(conn)
    conn.execute("DELETE FROM seen_articles WHERE sent_at < datetime('now', '-2 days')")
    cutoff = int(time.time()) - _DEDUP_RECENT_TTL_SEC
    conn.execute("DELETE FROM dedup_recent WHERE sort_epoch < ?", (cutoff,))
    conn.commit()
    return conn


def _migrate_weather_rate_to_channel_limits(conn: sqlite3.Connection) -> None:
    """Copy legacy weather_post_rate row into channel_rate_limits once."""
    try:
        row = conn.execute(
            "SELECT last_sent_epoch FROM weather_post_rate WHERE singleton = 1"
        ).fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO channel_rate_limits (rate_key, last_sent_epoch) "
                "VALUES (?, ?)",
                (RATE_LIMIT_KEY_WEATHER, row[0]),
            )
    except sqlite3.OperationalError:
        pass


def rate_limit_allowed(conn: sqlite3.Connection, rate_key: str, interval_sec: int) -> bool:
    row = conn.execute(
        "SELECT last_sent_epoch FROM channel_rate_limits WHERE rate_key = ?", (rate_key,)
    ).fetchone()
    if row is None:
        return True
    return time.time() - row[0] >= interval_sec


def record_rate_limit_hit(conn: sqlite3.Connection, rate_key: str) -> None:
    conn.execute(
        "INSERT INTO channel_rate_limits (rate_key, last_sent_epoch) VALUES (?, ?) "
        "ON CONFLICT(rate_key) DO UPDATE SET last_sent_epoch = excluded.last_sent_epoch",
        (rate_key, int(time.time())),
    )


def weather_post_allowed(conn: sqlite3.Connection, interval_sec: int) -> bool:
    """False if a Polish weather / IMGW-style post was sent within the last interval_sec."""
    return rate_limit_allowed(conn, RATE_LIMIT_KEY_WEATHER, interval_sec)


def record_weather_post(conn: sqlite3.Connection) -> None:
    record_rate_limit_hit(conn, RATE_LIMIT_KEY_WEATHER)


def fuel_tourism_post_allowed(conn: sqlite3.Connection, interval_sec: int) -> bool:
    return rate_limit_allowed(conn, RATE_LIMIT_KEY_FUEL_TOURISM_DE_PL, interval_sec)


def record_fuel_tourism_post(conn: sqlite3.Connection) -> None:
    record_rate_limit_hit(conn, RATE_LIMIT_KEY_FUEL_TOURISM_DE_PL)


def tk_judge_oath_post_allowed(conn: sqlite3.Connection, interval_sec: int) -> bool:
    return rate_limit_allowed(conn, RATE_LIMIT_KEY_TK_JUDGE_OATH, interval_sec)


def record_tk_judge_oath_post(conn: sqlite3.Connection) -> None:
    record_rate_limit_hit(conn, RATE_LIMIT_KEY_TK_JUDGE_OATH)


def get_new_articles(conn):
    new_articles = []
    now_utc = datetime.now(timezone.utc)
    min_dt = now_utc - timedelta(hours=int(MAX_ARTICLE_AGE_HOURS))
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
                        dt = now_utc
                    if dt < min_dt:
                        conn.execute(
                            "INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article_id,)
                        )
                        continue
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
    conn.commit()
    return new_articles
