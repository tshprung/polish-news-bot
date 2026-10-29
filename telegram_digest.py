import html
import logging
import os
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from database import (get_unsent_telegram_digest_items, mark_telegram_digest_items_sent,
                      telegram_digest_day_state, complete_telegram_digest_day)
from hebrew_editor import edit_hebrew_items
from editorial import select_editorial_items
from article_fetch import fetch_article_body
from telegram_format import format_digest_chunks
from email_digest import score_and_classify_item
from dedup import save_dedup_snapshot
from telegram_bot import send_to_telegram, telegram_html_anchor

log = logging.getLogger(__name__)


def _max_items() -> int:
    try:
        return max(4, min(10, int(os.environ.get("NEWS_DIGEST_MAX_ITEMS", "8"))))
    except ValueError:
        return 8


def _diversify_items(items: list[dict], limit: int) -> list[dict]:
    """Prefer category breadth, then fill remaining slots by importance.

    Story-level duplicate checks happen at ingestion. Broad security/political
    topics must not suppress unrelated events or material follow-ups.
    """
    selected, remaining = [], list(items)
    counts: Counter[str] = Counter()
    while remaining and len(selected) < limit:
        # A small breadth preference must not promote trivial reactions over
        # consequential decisions merely because several decisions share a topic.
        item = max(remaining, key=lambda row: int(row.get("importance_score") or 0)
                   - 8 * counts[row.get("category") or "other"])
        remaining.remove(item)
        category = item.get("category") or "other"
        selected.append(item)
        counts[category] += 1
    return selected


def prepare_daily_telegram_digest(conn, client, session, timeout, limit=None):
    """Read candidates and run source-backed selection/editing; never consume/send."""
    items = get_unsent_telegram_digest_items(conn)
    for item in items:
        score, category, _ = score_and_classify_item(item["title"], item["source"], item["url"], item["summary_he"])
        item.update(importance_score=score, category=category)
    selected = select_editorial_items(client, items, _max_items() if limit is None else limit)
    sourced = []
    for item in selected:
        if not item.get("source_text"):
            body = fetch_article_body(session, item["url"], timeout)
            if body:
                item["source_text"] = (item["title"] + ". " + body)[:8000]
        if not item.get("source_text"):
            log.warning("Digest item %s lacks source evidence; left pending", item["id"])
            continue
        sourced.append(item)
    edited = edit_hebrew_items(client, sourced)
    now = datetime.now(ZoneInfo("Europe/Warsaw"))
    return format_digest_chunks(edited, now.strftime("%d.%m.%Y"))


def send_daily_telegram_digest(conn, client: OpenAI, session, timeout) -> bool:
    if os.environ.get("NEWS_DIGEST_ENABLED", "1").strip() != "1":
        log.info("Telegram daily digest disabled")
        return False
    now = datetime.now(ZoneInfo("Europe/Warsaw"))
    completed, delivered_today = telegram_digest_day_state(conn, now)
    remaining = _max_items() - delivered_today
    if completed or remaining <= 0:
        log.info("Telegram digest already delivered today (%d stories)", delivered_today)
        return False
    chunks = prepare_daily_telegram_digest(conn, client, session, timeout, remaining)
    for message, delivered in chunks:
        send_to_telegram(session, message, timeout=timeout)
        mark_telegram_digest_items_sent(conn, [int(x["id"]) for x in delivered], "evening", now.isoformat())
        for item in delivered:
            conn.execute("UPDATE email_digest_items SET summary_he = ?, source_text = ? WHERE id = ?",
                         (item["summary_he"], item.get("source_text", ""), item["id"]))
            save_dedup_snapshot(conn, item["article_id"], item.get("title", ""), "", int(now.timestamp()))
        conn.commit()
    if chunks:
        complete_telegram_digest_day(conn, now)
        conn.commit()
    log.info("Telegram daily digest: messages=%d delivered=%d", len(chunks), sum(len(batch) for _, batch in chunks))
    return bool(chunks)
