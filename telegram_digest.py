import html
import logging
import os
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from database import get_unsent_telegram_digest_items, mark_telegram_digest_items_sent
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
    selected, deferred = [], []
    counts: Counter[str] = Counter()
    for item in items:
        category = item.get("category") or "other"
        if counts[category] >= 2:
            deferred.append(item)
            continue
        selected.append(item)
        counts[category] += 1
        if len(selected) >= limit:
            return selected
    return (selected + deferred)[:limit]


def send_daily_telegram_digest(conn, client: OpenAI, session, timeout) -> bool:
    if os.environ.get("NEWS_DIGEST_ENABLED", "1").strip() != "1":
        log.info("Telegram daily digest disabled")
        return False
    items = get_unsent_telegram_digest_items(conn)
    selected = _diversify_items(items, _max_items())
    if not selected:
        return False
    now = datetime.now(ZoneInfo("Europe/Warsaw"))
    header = f"🇵🇱 <b>חדשות פולין — {now.strftime('%d.%m.%Y')}</b>"
    # Reuse the verified Hebrew summaries: every selected story appears, with its
    # own source. Split only between complete entries, never inside an HTML tag.
    chunks = []
    message, chunk_items = header, []
    for item in selected:
        label = f"{item.get('source') or ''}: {(item.get('title') or '')[:200]}"
        entry = "\n\n• " + html.escape(item["summary_he"], quote=False)
        entry += "\n" + telegram_html_anchor(item["url"], label)
        if len(header) + len(entry) > 3500:
            log.warning("Oversize digest item %s left pending", item["id"])
            continue
        if len(message) + len(entry) > 3500 and chunk_items:
            chunks.append((message, chunk_items))
            message, chunk_items = header, []
        message += entry
        chunk_items.append(item)
    if chunk_items:
        chunks.append((message, chunk_items))
    for message, delivered in chunks:
        send_to_telegram(session, message, timeout=timeout)
        mark_telegram_digest_items_sent(conn, [int(x["id"]) for x in delivered], "evening", now.isoformat())
        for item in delivered:
            save_dedup_snapshot(conn, item["article_id"], item.get("title", ""), "", int(now.timestamp()))
        conn.commit()
    log.info("Telegram daily digest: selected=%d delivered=%d pending=%d", len(selected),
             sum(len(batch) for _, batch in chunks), len(items) - sum(len(batch) for _, batch in chunks))
    return bool(chunks)
