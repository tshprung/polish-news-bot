import html
import logging
import os
import re
from collections import Counter
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


def _event_tokens(item: dict) -> set[str]:
    text = f"{item.get('title') or ''} {item.get('summary_he') or ''}".lower()
    tokens = re.findall(r"[^\W\d_][\w'-]{2,30}", text, flags=re.UNICODE)
    stop = {
        "polska", "polski", "polsce", "polską", "polskim", "polskich", "prezydent", "prezydenta",
        "minister", "ministra", "ministerstwo", "rząd", "rzad", "sejm", "senat", "wiadomo",
        "poinformował", "poinformowal", "nowy", "nowe", "sprawie", "sprawa", "chodzi", "według", "wedlug",
        "פולין", "פולניה", "נשיא", "הנשיא", "הממשלה", "ממשלה", "שר", "שרים", "הודיע", "הודיעה", "אמר", "אמרה",
        "לדברי", "בנושא", "בעקבות", "המדינה", "פולני", "פולנית", "חדשות", "בפולין", "לפי", "היום", "חדש", "חדשה",
        "poland", "president", "minister", "government", "official", "said", "news", "today", "new",
    }
    return {t for t in tokens if t not in stop and len(t) >= 4}


def _event_similarity(a: dict, b: dict) -> float:
    ta, tb = _event_tokens(a), _event_tokens(b)
    if len(ta) < 3 or len(tb) < 3:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def _security_beat(item: dict) -> str | None:
    """Return a coarse security-event key for same-day incident reporting."""
    text = f"{item.get('title') or ''} {item.get('summary_he') or ''}".lower()
    if not re.search(r"רוס|רוסי|אוקרא|רחפנ|כטב|גבול|פיצוצ|התקפ|ירי|צבא|ביטח|drone|russia|ukrain|border", text):
        return None
    if re.search(r"רוס|רוסי|רחפנ|כטב|drone|russia", text) and re.search(r"גבול|אוקרא|פולין|ukrain|border", text):
        return "russia-ukraine-border-incident"
    return "other-security-incident"


def _political_beat(item: dict) -> str | None:
    text = f"{item.get('title') or ''} {item.get('summary_he') or ''}".lower()
    if re.search(r"נשיא|טוסק|ממשלה|ראש הממשלה|prezydent|tusk|rząd", text) and re.search(r"עימות|סכסוך|מחלוקת|spór|konflikt|dispute|ממשל", text):
        return "president-government-dispute"
    return None


def _diversify_items(items: list[dict], limit: int) -> list[dict]:
    if not items:
        return []
    selected: list[dict] = []
    category_counts: Counter[str] = Counter()
    beat_counts: Counter[str] = Counter()
    deferred: list[dict] = []

    for item in items:
        category = (item.get("category") or "other").strip().lower()
        beat = _security_beat(item) or _political_beat(item)
        if beat and beat_counts[beat] >= 1:
            deferred.append(item)
            continue
        if category_counts[category] >= 2:
            deferred.append(item)
            continue
        if any(_event_similarity(item, chosen) >= 0.32 for chosen in selected):
            deferred.append(item)
            continue
        selected.append(item)
        category_counts[category] += 1
        if beat:
            beat_counts[beat] += 1
        if len(selected) >= limit:
            return selected

    # Fill only with genuinely distinct events. Never relax the special
    # same-security-incident or president-government-dispute caps.
    for item in deferred:
        if len(selected) >= limit:
            break
        beat = _security_beat(item) or _political_beat(item)
        if beat and beat_counts[beat] >= 1:
            continue
        category = (item.get("category") or "other").strip().lower()
        if category_counts[category] >= 2:
            continue
        if any(_event_similarity(item, chosen) >= 0.32 for chosen in selected):
            continue
        selected.append(item)
        category_counts[category] += 1
        if beat:
            beat_counts[beat] += 1
    return selected


def _build_prompt(items: list[dict]) -> tuple[str, str]:
    system = (
        "You write a concise Hebrew Telegram daily news brief about Poland. "
        "Use ONLY the supplied facts. Do not invent facts, dates, numbers, causes, or implications. "
        "Select the most consequential developments for an ordinary resident of Poland. "
        "Prefer laws, government decisions, taxes, prices, economy, security, major infrastructure, health, education, and major Poland-related foreign/EU developments. "
        "Ignore sports, celebrity, lifestyle, routine crime, and trivial local stories unless their impact is substantial. "
        "CRITICAL: multiple supplied items can describe the same real-world event. Never create multiple bullets for the same event. "
        "One incident involving Russian drones or attacks near the Polish-Ukrainian border is ONE story, even if the inputs separately mention explosions, evacuations, Tusk, the president, military alerts, or residents' reports. Choose the most important facts and combine them into one bullet. "
        "Likewise, one president-government dispute is ONE story, not one bullet per politician. "
        "Prefer breadth across genuinely different developments. "
        "Return plain text, not Markdown or HTML. Start with one short 'תמונת מצב' sentence, then 4-8 bullets. "
        "Each bullet must have a short Hebrew headline followed by 1-2 concise sentences explaining what happened and why it matters."
    )
    blocks = []
    for i, item in enumerate(items, 1):
        blocks.append("\n".join([
            f"ITEM {i}", f"importance_score: {item.get('importance_score')}", f"category: {item.get('category') or 'other'}",
            f"source: {item.get('source') or ''}", f"title: {item.get('title') or ''}", f"summary_he: {item.get('summary_he') or ''}",
        ]))
    return system, "\n\n---\n\n".join(blocks)


def send_daily_telegram_digest(conn, client: OpenAI, session, timeout) -> bool:
    if os.environ.get("NEWS_DIGEST_ENABLED", "1").strip() != "1":
        log.info("Telegram daily digest disabled")
        return False
    items = get_unsent_telegram_digest_items(conn)
    if not items:
        log.info("Telegram daily digest: no unsent items")
        return False
    limit = _max_items()
    selected = _diversify_items(items, limit)
    if not selected:
        log.info("Telegram daily digest: no items after diversity selection")
        return False
    system, user = _build_prompt(selected)
    resp = client.chat.completions.create(
        model=os.environ.get("NEWS_DIGEST_MODEL", "gpt-5.4-mini"), max_completion_tokens=1400,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
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
