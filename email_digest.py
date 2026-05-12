import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from openai import OpenAI

from config import (
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


def score_and_classify_item(title: str, source: str, url: str, summary_he: str) -> tuple[int, str, str | None]:
    blob = f"{title}\n{source}\n{url}\n{summary_he}".lower()
    score = 0

    is_weather = bool(re.search(r"\bm(e|ę)z?g\s*אויר|pogod|prognoz|temperatur|burz|mroz|przymroz", blob))
    is_poll = bool(re.search(r"sonda(?:z|ż|)\b|sond[eę]\b|cbos|ibris|kantar|opinia24|pollster|united", blob))
    is_sport = bool(re.search(r"\bsport\b|ekstraklas|liga|mecz|transfer|uefa|fifa", blob))
    if is_sport:
        score -= 50
    if is_poll:
        score -= 25
    if is_weather:
        score -= 15

    region = None
    if re.search(r"\bwroc[łl]aw\b|\bwroclaw\b", blob) or re.search(r"dolny\s+sl[ąa]sk|dolno[śs]l[ąa]sk", blob):
        region = "Wrocław / Dolny Śląsk"
        score += 25 if re.search(r"\bwroc[łl]aw\b|\bwroclaw\b", blob) else 20

    serious_crime = bool(
        re.search(r"zab[oó]jstw|morderstw|napad|gwa[łl]t|porwan", blob)
    )
    children = bool(re.search(r"\bdzieck|\bniemowl|\bniemowle", blob))
    if serious_crime:
        score += 25
    if children:
        score += 18

    police = bool(re.search(r"\bpolicj|\bprokuratur", blob))
    if police:
        score += 3

    politics = bool(re.search(r"\brz[aą]d\b|\bsejm\b|prezydent|ustaw|podatk|\bzus\b", blob))
    foreign = bool(re.search(r"ukrain|rosj|granica|\bnato\b|\bue\b|unii\s+europej", blob))
    economy = bool(re.search(r"inflac|stopy\s+procent|ceny|mieszk|nieruchom|gospodark", blob))

    if politics:
        score += 12
    if foreign:
        score += 12
    if economy:
        score += 10

    if region and (serious_crime or children or (police and re.search(r"areszt|zatrzym|napad|no[zż]", blob))):
        score += 20
    if serious_crime:
        score += 10

    if region:
        category = "local"
    elif serious_crime or children:
        category = "crime"
    elif politics:
        category = "politics"
    elif economy:
        category = "economy"
    elif foreign:
        category = "foreign"
    else:
        category = "other"

    return int(score), category, region


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
