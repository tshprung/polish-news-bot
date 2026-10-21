import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from openai import OpenAI

from config import (
    fold_pl,
    EMAIL_DIGEST_ENABLED,
    EMAIL_TO,
    MIDDAY_HIGH_IMPORTANCE_SCORE,
    MIDDAY_MIN_HIGH_IMPORTANCE_ITEMS,
    MIDDAY_MIN_ITEMS,
    OPENAI_MODEL_EMAIL_DIGEST,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
)
from email_sender import send_email_html

log = logging.getLogger(__name__)


_SLOT_LIMITS = {
    "morning": {"max_items": 5, "min_words": 150, "max_words": 250, "always_send": True},
    "midday": {"max_items": 4, "min_words": 100, "max_words": 200, "always_send": False},
    "evening": {"max_items": 12, "min_words": 500, "max_words": 900, "always_send": True},
}

_SECTION_TITLES_HE = {
    "politics": "פוליטיקה וממשלה",
    "economy": "כלכלה / מחירים / נדל״ן",
    "crime": "פלילים וביטחון אישי",
    "local": "Wrocław / Dolny Śląsk",
    "foreign": "חוץ / אוקראינה / EU",
    "other": "נושאים נוספים",
}


def _ensure_large_font_html(html_body: str) -> str:
    style = (
        "<style>"
        "html,body{font-size:200%;line-height:1.35;font-family:Arial,Helvetica,sans-serif}"
        "h1{margin:0 0 0.6em 0}h2{margin:1.1em 0 0.4em 0}"
        "p,li{margin:0 0 0.6em 0}"
        "</style>"
    )
    s = (html_body or "").strip()
    if not s:
        return s
    if re.search(r"(?is)<html\b", s):
        if re.search(r"(?is)<head\b", s):
            return re.sub(r"(?is)(<head\b[^>]*>)", r"\1" + style, s, count=1)
        return re.sub(r"(?is)(<html\b[^>]*>)", r"\1<head>" + style + "</head>", s, count=1)
    return "<html><head>" + style + "</head><body>" + s + "</body></html>"


def score_and_classify_item(title: str, source: str, url: str, summary_he: str) -> tuple[int, str, str | None]:
    blob = f"{title}\n{summary_he}".lower()
    # Score public impact, without privileging a particular city or crime beat.
    blob = fold_pl(blob)
    rules = (
        ("health", r"zdrow|szpital|nfz|lekow|epidem|בריאות|חולים"),
        ("education", r"edukac|szkol|uczel|nauczyciel|חינוך|ספר"),
        ("transport", r"kolej|pociag|lotnisk|autostrad|transport|רכבת|תחבורה"),
        ("security", r"bezpieczen|wojsk|obron|nato|granicy|ביטחון|צבא"),
        ("economy", r"inflac|stop.{0,12}procent|cen[ay]|gospodar|podat|zus|כלכלה|מסים"),
        ("politics", r"rzad|sejm|senat|prezydent|ustaw|trybunal|ממשלה|נשיא"),
    )
    category = next((name for name, pattern in rules if re.search(pattern, blob)), "other")
    score = 25 if category != "other" else 15
    national = bool(re.search(r"sejm|senat|rzad|minister|prezydent|nbp|nfz|zus|ogolnopol|ממשלה|ארצי", blob))
    development = bool(re.search(r"uchwal|podpis|zatwierdz|wprowadz|obniz|podwyz|zmian|reform|decyz|weto|אישר|החליט|שינוי", blob))
    if national:
        score += 10
    if development:
        score += 10
    if re.search(r"ewaku|powodz|katastrof|epidem|ofiar|הרוג|פינוי|הצפה", blob):
        score += 20
    # Prefer observable developments over statements about an existing dispute.
    headline = fold_pl(title)
    concrete_event = bool(re.search(
        r"uchwal|przyjet|przyjal|zatwierdz|podpisal|zawetow|wchodzi w zycie|"
        r"wyrok|uniewinn|zatrzym|areszt|ewaku|alert rcb|ostrzezeni|"
        r"spadl samolot|katastrof|wypadek|awaria|raport.{0,70}przyjet|"
        r"התרעת|אישר|זיכה|נעצר|פונה", headline))
    proposal = bool(re.search(r"projekt ustaw|proponuj|przygotow.{0,30}ustaw|הצעת חוק", headline))
    commentary = bool(re.search(
        r"twierdzi|powiedzial|uwaza|skrytykow|oskarz|atakuj|grozi|"
        r"nie ma z kim rozmawiac|niepokoi|reakcja|komentarz|"
        r"mowi o|ekonomistka o|tylko plaster|טען|תקף|ביקר את", headline))
    if concrete_event:
        score += 15
    elif proposal:
        score += 8
    elif commentary:
        score -= 15
    region = "Wrocław / Dolny Śląsk" if re.search(r"wroclaw|dolnoslask|dolny slask", blob) else None
    if re.search(r"sondaz|prognoza pogody|horoskop", blob):
        score -= 20
    return min(100, max(0, score)), category, region


def select_items_for_slot(items: list[dict], slot: str) -> tuple[list[dict], str | None]:
    cfg = _SLOT_LIMITS.get(slot)
    if cfg is None:
        raise ValueError(f"unknown slot: {slot}")

    max_items = int(cfg["max_items"])
    selected = items[:max_items]
    if slot == "midday":
        if len(selected) >= MIDDAY_MIN_ITEMS:
            return selected, None
        hi = [x for x in selected if int(x.get("importance_score") or 0) >= MIDDAY_HIGH_IMPORTANCE_SCORE]
        if len(hi) >= MIDDAY_MIN_HIGH_IMPORTANCE_ITEMS:
            return selected, None
        return [], "midday skipped (insufficient content)"
    return selected, None


def _warsaw_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Warsaw"))


def _email_subject(slot: str, now_warsaw: datetime) -> str:
    date = now_warsaw.strftime("%Y-%m-%d")
    if slot == "morning":
        label = "תקציר בוקר"
    elif slot == "midday":
        label = "עדכון צהריים"
    elif slot == "evening":
        label = "סיכום ערב"
    else:
        label = slot
    return f"{label} — {date}"


def _build_digest_prompt(slot: str, selected: list[dict]) -> tuple[str, str]:
    cfg = _SLOT_LIMITS[slot]
    min_words = int(cfg["min_words"])
    max_words = int(cfg["max_words"])
    max_items = int(cfg["max_items"])

    section_lines = "\n".join(f"- {k}: {_SECTION_TITLES_HE[k]}" for k in _SECTION_TITLES_HE.keys())

    system = (
        "You write a Hebrew HTML email digest from provided Hebrew summary lines. "
        "Do not invent facts beyond the provided summaries. "
        "Do not add any links not present in the provided items. "
        "Output only valid HTML (no Markdown). "
        "Use these section titles exactly as given.\n\n"
        f"Sections:\n{section_lines}\n\n"
        "Internal categories in items: politics|economy|crime|local|foreign|other. "
        "Group items under the correct Hebrew section title. "
        "If a section has no items, omit it.\n\n"
        "Email structure:\n"
        "1) <h1> title\n"
        "2) <p> short 'תמונת מצב' paragraph summarizing themes\n"
        "3) Sections with <h2> and short paragraphs + bullet items (not just raw list; synthesize).\n"
        "4) Final 'קישורים' section listing each item with clickable link (source + title).\n"
        "Keep the digest between "
        f"{min_words} and {max_words} Hebrew words, max {max_items} items.\n"
    )

    user_items = []
    for it in selected:
        user_items.append(
            "\n".join(
                [
                    f"ID: {it.get('id')}",
                    f"category: {it.get('category')}",
                    f"region: {it.get('region') or ''}",
                    f"importance_score: {it.get('importance_score')}",
                    f"source: {it.get('source')}",
                    f"title: {it.get('title')}",
                    f"url: {it.get('url')}",
                    f"summary_he: {it.get('summary_he')}",
                ]
            )
        )

    user = (
        f"Slot: {slot}\n\n"
        "Items:\n\n"
        + "\n\n---\n\n".join(user_items)
    )
    return system, user


def render_email_digest_html(client: OpenAI, slot: str, selected: list[dict]) -> str:
    system, user = _build_digest_prompt(slot, selected)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL_EMAIL_DIGEST,
        max_completion_tokens=1600,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


def send_email_digest(
    *,
    client: OpenAI,
    slot: str,
    items: list[dict],
) -> tuple[list[int], str | None]:
    if not EMAIL_DIGEST_ENABLED:
        return [], "email digest disabled"

    if EMAIL_TO.strip().lower() != "tshprung@gmail.com":
        return [], "EMAIL_TO must be tshprung@gmail.com"

    if not SMTP_HOST or not SMTP_FROM:
        return [], "SMTP is not configured"

    selected, skip_reason = select_items_for_slot(items, slot)
    if skip_reason:
        return [], skip_reason
    if not selected:
        return [], "no unsent items"

    now_waw = _warsaw_now()
    subject = _email_subject(slot, now_waw)

    html_body = render_email_digest_html(client, slot, selected)
    html_body = _ensure_large_font_html(html_body)
    if not html_body:
        return [], "empty digest html"

    send_email_html(
        smtp_host=SMTP_HOST,
        smtp_port=SMTP_PORT,
        smtp_user=SMTP_USER,
        smtp_password=SMTP_PASSWORD,
        mail_from=SMTP_FROM,
        to_addr=EMAIL_TO,
        subject=subject,
        html_body=html_body,
    )

    sent_ids = [int(x["id"]) for x in selected if x.get("id") is not None]
    return sent_ids, None


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

