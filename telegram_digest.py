import html
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from openai import OpenAI

from database import get_unsent_telegram_digest_items, mark_telegram_digest_items_sent
from telegram_bot import send_to_telegram, telegram_html_anchor

log = logging.getLogger(__name__)


def _max_items() -> int:
    try:
        return max(4, min(10, int(os.environ.get("NEWS_DIGEST_MAX_ITEMS", "8"))))
    except ValueError:
        return 8


def _build_prompt(items: list[dict]) -> tuple[str, str]:
    system = (
        "You write a concise Hebrew Telegram daily news brief about Poland. "
        "Use ONLY the supplied facts. Do not invent facts, dates, numbers, causes, or implications. "
        "Select the most consequential developments for an ordinary resident of Poland. "
        "Prefer laws, government decisions, taxes, prices, economy, security, major infrastructure, "
        "health, education, and major Poland-related foreign/EU developments. "
        "Ignore sports, celebrity, lifestyle, routine crime, and trivial local stories unless their impact is substantial. "
        "Return plain text, not Markdown or HTML. "
        "Start with one short 'תמונת מצב' sentence, then 4-8 bullets. "
        "Each bullet must have a short Hebrew headline followed by 1-2 concise sentences explaining what happened and why it matters."
    )
    blocks = []
    for i, item in enumerate(items, 1):
        blocks.append(
            "\n".join([
                f"ITEM {i}",
                f"importance_score: {item.get('importance_score')}",
                f"category: {item.get('category') or 'other'}",
                f"source: {item.get('source') or ''}",
                f"title: {item.get('title') or ''}",
                f"summary_he: {item.get('summary_he') or ''}",
            ])
        )
    user = "\n\n---\n\n".join(blocks)
    return system, user


def send_daily_telegram_digest(conn, client: OpenAI, session, timeout) -> bool:
    if os.environ.get("NEWS_DIGEST_ENABLED", "1").strip() != "1":
        log.info("Telegram daily digest disabled")
        return False

    items = get_unsent_telegram_digest_items(conn)
    if not items:
        log.info("Telegram daily digest: no unsent items")
        return False

    limit = _max_items()
    selected = items[:limit]
    system, user = _build_prompt(selected)
    resp = client.chat.completions.create(
        model=os.environ.get("NEWS_DIGEST_MODEL", "gpt-5.4-mini"),
        max_completion_tokens=1400,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    body = (resp.choices[0].message.content or "").strip()
    if not body:
        log.warning("Telegram daily digest: empty model response")
        return False

    now = datetime.now(ZoneInfo("Europe/Warsaw"))
    header = f"🇵🇱 <b>Poland Daily Brief — {now.strftime('%d.%m.%Y')}</b>"
    links = []
    for item in selected:
        title = html.escape(item.get("title") or "", quote=False)
        source = html.escape(item.get("source") or "", quote=False)
        url = item.get("url") or ""
        links.append(telegram_html_anchor(url, f"{source}: {title}"))

    message = header + "\n\n" + html.escape(body, quote=False) + "\n\n<b>Sources</b>\n" + "\n".join(f"• {x}" for x in links)
    if len(message) > 3900:
        message = message[:3850] + "…"

    send_to_telegram(session, message, timeout=timeout)
    sent_ids = [int(x["id"]) for x in items]
    mark_telegram_digest_items_sent(conn, sent_ids, "evening", now.isoformat())
    conn.commit()
    log.info("Telegram daily digest sent: selected=%d consumed=%d", len(selected), len(sent_ids))
    return True
