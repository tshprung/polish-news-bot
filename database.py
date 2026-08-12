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
        "article_id TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL, sort_epoch INTEGER NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dedup_recent_epoch ON dedup_recent(sort_epoch)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_post_rate (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), last_sent_epoch INTEGER NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS channel_rate_limits (rate_key TEXT PRIMARY KEY, last_sent_epoch INTEGER NOT NULL)"
    )
    _migrate_weather_rate_to_channel_limits(conn)
    _init_email_digest_items(conn)
    conn.execute("DELETE FROM seen_articles WHERE sent_at < datetime('now', '-2 days')")
    cutoff = int(time.time()) - _DEDUP_RECENT_TTL_SEC
    conn.execute("DELETE FROM dedup_recent WHERE sort_epoch < ?", (cutoff,))
    conn.commit()
    return conn


def _init_email_digest_items(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS email_digest_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, article_id TEXT NOT NULL UNIQUE, url TEXT NOT NULL, "
        "title TEXT NOT NULL, source TEXT NOT NULL, published_at TEXT NULL, published_epoch INTEGER NULL, "
        "created_at TEXT NOT NULL, summary_he TEXT NOT NULL, importance_score INTEGER NOT NULL DEFAULT 0, "
        "category TEXT NULL, region TEXT NULL, email_digest_sent_at TEXT NULL, email_digest_slot TEXT NULL, "
        "telegram_digest_sent_at TEXT NULL, telegram_digest_slot TEXT NULL"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_digest_unsent ON email_digest_items(email_digest_sent_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_digest_score ON email_digest_items(importance_score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_digest_category ON email_digest_items(category)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_email_digest_region ON email_digest_items(region)")

    cols = {r[1] for r in conn.execute("PRAGMA table_info(email_digest_items)").fetchall()}
    added_telegram_columns = False
    for col, ddl in (
        ("published_epoch", "ALTER TABLE email_digest_items ADD COLUMN published_epoch INTEGER NULL"),
        ("telegram_digest_sent_at", "ALTER TABLE email_digest_items ADD COLUMN telegram_digest_sent_at TEXT NULL"),
        ("telegram_digest_slot", "ALTER TABLE email_digest_items ADD COLUMN telegram_digest_slot TEXT NULL"),
    ):
        if col not in cols:
            try:
                conn.execute(ddl)
                if col == "telegram_digest_sent_at":
                    added_telegram_columns = True
            except sqlite3.OperationalError:
                pass
    # Existing email-digest history predates the Telegram daily brief. Do not dump
    # the backlog into the first Telegram brief after deployment.
    if added_telegram_columns:
        conn.execute(
            "UPDATE email_digest_items SET telegram_digest_sent_at = COALESCE(created_at, datetime('now')), "
            "telegram_digest_slot = 'pre_telegram_migration' WHERE telegram_digest_sent_at IS NULL"
        )


def _migrate_weather_rate_to_channel_limits(conn: sqlite3.Connection) -> None:
    try:
        row = conn.execute("SELECT last_sent_epoch FROM weather_post_rate WHERE singleton = 1").fetchone()
        if row:
            conn.execute(
                "INSERT OR IGNORE INTO channel_rate_limits (rate_key, last_sent_epoch) VALUES (?, ?)",
                (RATE_LIMIT_KEY_WEATHER, row[0]),
            )
    except sqlite3.OperationalError:
        pass


def rate_limit_allowed(conn: sqlite3.Connection, rate_key: str, interval_sec: int) -> bool:
    row = conn.execute("SELECT last_sent_epoch FROM channel_rate_limits WHERE rate_key = ?", (rate_key,)).fetchone()
    return row is None or time.time() - row[0] >= interval_sec


def record_rate_limit_hit(conn: sqlite3.Connection, rate_key: str) -> None:
    conn.execute(
        "INSERT INTO channel_rate_limits (rate_key, last_sent_epoch) VALUES (?, ?) "
        "ON CONFLICT(rate_key) DO UPDATE SET last_sent_epoch = excluded.last_sent_epoch",
        (rate_key, int(time.time())),
    )


def weather_post_allowed(conn: sqlite3.Connection, interval_sec: int) -> bool:
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


def store_email_digest_item(conn, article: dict, summary_he: str, importance_score: int = 0, category: str | None = None, region: str | None = None) -> bool:
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    published_at = article.get("date")
    published_epoch = None
    try:
        sk = article.get("sort_key")
        if sk is not None:
            published_epoch = int(sk.timestamp())
    except Exception:
        pass
    cur = conn.execute(
        "INSERT OR IGNORE INTO email_digest_items "
        "(article_id, url, title, source, published_at, published_epoch, created_at, summary_he, importance_score, category, region) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (article.get("id"), article.get("link"), article.get("title"), article.get("source"), published_at,
         published_epoch, now_iso, summary_he, int(importance_score or 0), category, region),
    )
    return bool(cur.rowcount)


def _rows_to_digest_items(rows) -> list[dict]:
    return [
        {"id": r[0], "article_id": r[1], "url": r[2], "title": r[3], "source": r[4],
         "published_at": r[5], "published_epoch": r[6], "created_at": r[7], "summary_he": r[8],
         "importance_score": r[9], "category": r[10], "region": r[11]}
        for r in rows
    ]


def get_unsent_email_digest_items(conn) -> list[dict]:
    cur = conn.execute(
        "SELECT id, article_id, url, title, source, published_at, published_epoch, created_at, summary_he, importance_score, category, region "
        "FROM email_digest_items WHERE email_digest_sent_at IS NULL ORDER BY importance_score DESC, id ASC"
    )
    return _rows_to_digest_items(cur.fetchall())


def get_unsent_telegram_digest_items(conn) -> list[dict]:
    cur = conn.execute(
        "SELECT id, article_id, url, title, source, published_at, published_epoch, created_at, summary_he, importance_score, category, region "
        "FROM email_digest_items WHERE telegram_digest_sent_at IS NULL ORDER BY importance_score DESC, published_epoch DESC, id DESC"
    )
    return _rows_to_digest_items(cur.fetchall())


def mark_email_digest_items_sent(conn, item_ids: list[int], slot: str, sent_at_iso: str) -> None:
    if not item_ids:
        return
    placeholders = ",".join("?" for _ in item_ids)
    conn.execute(
        f"UPDATE email_digest_items SET email_digest_sent_at = ?, email_digest_slot = ? WHERE id IN ({placeholders}) AND email_digest_sent_at IS NULL",
        (sent_at_iso, slot, *item_ids),
    )


def mark_telegram_digest_items_sent(conn, item_ids: list[int], slot: str, sent_at_iso: str) -> None:
    if not item_ids:
        return
    placeholders = ",".join("?" for _ in item_ids)
    conn.execute(
        f"UPDATE email_digest_items SET telegram_digest_sent_at = ?, telegram_digest_slot = ? WHERE id IN ({placeholders}) AND telegram_digest_sent_at IS NULL",
        (sent_at_iso, slot, *item_ids),
    )


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
                exists = conn.execute("SELECT 1 FROM seen_articles WHERE id = ?", (article_id,)).fetchone()
                if exists:
                    continue
                published = entry.get("published_parsed")
                dt = datetime(*published[:6], tzinfo=timezone.utc) if published else now_utc
                if dt < min_dt:
                    conn.execute("INSERT OR IGNORE INTO seen_articles (id) VALUES (?)", (article_id,))
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
            log.error("Failed to fetch %s: %s", feed_url, e)
    conn.commit()
    return new_articles
