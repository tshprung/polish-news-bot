"""Bounded translation retries, distinct from intentional editorial rejection."""
import json
import time
from datetime import datetime, timezone

MAX_ATTEMPTS = 3


def init_retry_queue(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS article_retries (article_id TEXT PRIMARY KEY, article_json TEXT NOT NULL, "
        "attempts INTEGER NOT NULL, next_retry_epoch INTEGER NOT NULL, expires_epoch INTEGER NOT NULL, "
        "last_error TEXT NOT NULL, status TEXT NOT NULL)"
    )


def is_translation_failure(reason: str | None) -> bool:
    value = (reason or "").lower()
    return value.startswith(("non-hebrew", "no hebrew", "mixed-script", "geo mismatch", "response too short",
        "response truncated", "summary too long", "hebrew too short", "too few hebrew", "sanitization",
        "empty after", "body not accessible", "insufficient content"))


def schedule_article_retry(conn, article: dict, reason: str) -> bool:
    init_retry_queue(conn)
    now = int(time.time())
    row = conn.execute("SELECT attempts, expires_epoch FROM article_retries WHERE article_id = ?", (article["id"],)).fetchone()
    attempts = (row[0] if row else 0) + 1
    published = article.get("sort_key")
    expires = row[1] if row else min(now + 48 * 3600,
        int(published.timestamp()) + 48 * 3600 if isinstance(published, datetime) else now + 48 * 3600)
    pending = attempts < MAX_ATTEMPTS and now < expires
    payload = dict(article)
    if isinstance(payload.get("sort_key"), datetime):
        payload["sort_key"] = payload["sort_key"].isoformat()
    conn.execute(
        "INSERT INTO article_retries VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(article_id) DO UPDATE SET article_json=excluded.article_json, attempts=excluded.attempts, "
        "next_retry_epoch=excluded.next_retry_epoch, last_error=excluded.last_error, status=excluded.status",
        (article["id"], json.dumps(payload, ensure_ascii=False), attempts,
         now + 1800 * attempts, expires, reason[:500], "pending" if pending else "exhausted")
    )
    conn.commit()
    return pending


def retry_articles_and_states(conn) -> tuple[list[dict], dict[str, str]]:
    init_retry_queue(conn)
    now = int(time.time())
    conn.execute("UPDATE article_retries SET status='expired' WHERE status='pending' AND expires_epoch <= ?", (now,))
    rows = conn.execute("SELECT article_id, article_json, next_retry_epoch, status FROM article_retries").fetchall()
    due, states = [], {}
    for key, payload, next_epoch, status in rows:
        states[key] = status
        if status != "pending" or next_epoch > now:
            continue
        item = json.loads(payload)
        item["sort_key"] = datetime.fromisoformat(item["sort_key"]) if item.get("sort_key") else datetime.now(timezone.utc)
        due.append(item)
    return due, states


def resolve_article_retry(conn, article_id: str):
    init_retry_queue(conn)
    conn.execute("UPDATE article_retries SET status='resolved' WHERE article_id=? AND status='pending'", (article_id,))
